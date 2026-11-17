"""Text out of PDF files: page count, outline, pages by number, and where no text can be taken.

A long report (a white paper, an institution's outlook) is read a few pages at
a time: the first call says how long the document is, what its outline names
and how much text each page holds; later calls return the pages asked for, each
under its page number, so a figure can be cited with the page it stands on.

What this does not do: open an encrypted file, read a page that is only a
scanned image (there is no OCR), run anything a file contains, or follow a
link in it. A PDF is untrusted data. Parsing is pure Python (pypdf) with that
library's own limits on decompressed streams; on top of them a file has a size
limit, a page limit, a time budget per call, and at most two files are parsed
at once. A page that does not finish in time marks its file unreadable, so a
hostile file costs one call, not every later one.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

MAX_PAGES = 5000
PAGE_CHARS = 80_000            # kept of one page's text
DEFAULT_CHARS, MAX_CHARS = 12_000, 24_000   # one answer, as web_read
CALL_SECONDS = 30              # taking text within one call
WAIT_SECONDS = 75              # a call that has not answered by then has met a page that does not end
OUTLINE_ROWS, TITLE_CHARS = 80, 120
FIND_ROWS, FIND_PER_PAGE, SNIPPET = 30, 3, 90
THIN_PAGE = 5                  # fewer characters than this: the page has no text layer worth the name
KEEP_OPEN = 3                  # documents whose pages stay in memory
KEEP_FILES, KEEP_BYTES, KEEP_SECONDS = 12, 600 * 1024 * 1024, 14 * 24 * 3600
MAX_PDF_BYTES = 200 * 1024 * 1024   # the most the settings allow for one PDF

logging.getLogger('pypdf').setLevel(logging.ERROR)  # a damaged file's warnings are not the console's business
_ID = re.compile(r'pdf-[0-9a-f]{24}\Z')
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='awb-pdf')
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]')
_BLANK_RUN = re.compile(r'\n[ \t]*(?:\n[ \t]*){2,}')

PDF_READ_TOOL = {'name': 'pdf_read', 'description': (
    'Read a PDF from an allowed read folder (path) or one that web_fetch downloaded (pdf_id). Without first_page: '
    'page count, outline, characters per page and how it begins. With first_page (1 = first page of the file): the text '
    'of those pages under their page numbers, up to max_chars; next_page continues. find: the pages where a phrase '
    'occurs. Encrypted files are refused; scanned pages have no text (no OCR). Untrusted data.'),
    'parameters': {'type': 'object', 'properties': {
        'path': {'type': 'string'},
        'pdf_id': {'type': 'string', 'maxLength': 28},
        'first_page': {'type': 'integer', 'minimum': 1, 'maximum': MAX_PAGES},
        'last_page': {'type': 'integer', 'minimum': 1, 'maximum': MAX_PAGES},
        'offset': {'type': 'integer', 'minimum': 0, 'maximum': PAGE_CHARS},
        'find': {'type': 'string', 'maxLength': 100},
        'max_chars': {'type': 'integer', 'minimum': 2000, 'maximum': MAX_CHARS}},
        'additionalProperties': False}}
_ARGS = frozenset(PDF_READ_TOOL['parameters']['properties'])

PDF_POLICY = (
    '\n\nPDF reports: use pdf_read. See the page count and outline first; read the executive summary and the first '
    'chapter, then only the chapters the request needs (find locates a term), never cover to cover. Give every figure '
    'with its page ("p. 12", the numbers pdf_read returns) and report only pages you read. If a PDF has no text, say so.')
# Only where pages can be fetched.
PDF_WEB_POLICY = (
    ' To get a report, web_fetch its PDF address (the result has a pdf_id); a page that web_fetch returns lists the PDF '
    'files it links to (pdf_links). If an institution\'s main site refuses the request, use the same institution\'s '
    'official distribution site (for the IMF, the IMF eLibrary) instead of retrying. If no official copy can be '
    'downloaded, say so and ask the human to save the file into a read folder.')


class PdfError(ValueError):
    """A PDF could not be opened or read; the text is safe to show to a model."""


def megabytes(count):
    return f'{count / (1024 * 1024):.1f} MB'


def looks_like_pdf(data):
    """The file header may follow a little leading junk, as readers allow."""
    return b'%PDF-' in bytes(data[:1024])


def _clean(text):
    text = _CONTROL.sub('', text.replace('\r\n', '\n').replace('\r', '\n'))
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    return _BLANK_RUN.sub('\n\n', text).strip()[:PAGE_CHARS]


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


class _Document:
    """One opened file: its reader, what was learnt on opening, and the pages read so far."""

    def __init__(self, data, sha256):
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
        self.sha256, self.bytes, self.lock = sha256, len(data), threading.Lock()
        self.texts, self.failed = {}, {}
        try:
            self.reader = PdfReader(io.BytesIO(data), strict=False)
            if self.reader.is_encrypted:
                raise PdfError('This PDF is encrypted (it needs a password, or its author restricted it). '
                               'The application does not open encrypted PDFs. Say so; a human can save an '
                               'unprotected copy into a read folder.')
            self.pages = len(self.reader.pages)
        except PdfError:
            raise
        except (PyPdfError, ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError, OSError) as exc:
            raise PdfError('This file could not be opened as a PDF (' + type(exc).__name__ + '). '
                           'It may be damaged or not a PDF at all.') from None
        if not 1 <= self.pages <= MAX_PAGES:
            raise PdfError(f'This PDF has {self.pages} pages; the application reads PDFs of 1 to {MAX_PAGES} pages.')
        self.title, self.outline, self.labels = self._title(), self._outline(), self._labels()

    def _title(self):
        try:
            title = (self.reader.metadata or {}).get('/Title')
        except Exception:  # noqa: BLE001 - a damaged information dictionary only loses the title
            title = None
        return ' '.join(_clean(str(title)).split())[:TITLE_CHARS] if isinstance(title, str) else ''

    def _outline(self):
        rows, budget = [], [2000]

        def walk(items, level):
            for item in items:
                budget[0] -= 1
                if budget[0] < 0 or level > 6:
                    return
                if isinstance(item, list):
                    walk(item, level + 1)
                    continue
                try:
                    title = ' '.join(_clean(str(item.title)).split())[:TITLE_CHARS]
                    number = self.reader.get_destination_page_number(item)
                except Exception:  # noqa: BLE001 - one unreadable entry does not lose the others
                    continue
                if title:
                    rows.append({'title': title, 'level': level,
                                 **({'page': number + 1} if isinstance(number, int) and 0 <= number < self.pages else {})})
        try:
            walk(self.reader.outline, 0)
        except Exception:  # noqa: BLE001 - a damaged outline is the same as none
            return []
        # A long outline keeps its upper levels: they are what a reader plans with.
        for deepest in (6, 2, 1, 0):
            kept = [row for row in rows if row['level'] <= deepest]
            if len(kept) <= OUTLINE_ROWS:
                return kept
        return kept[:OUTLINE_ROWS]

    def _labels(self):
        """The numbers printed on the pages ("iv", "23"), when the file states them and they differ."""
        try:
            labels = [str(label)[:12] for label in self.reader.page_labels]
        except Exception:  # noqa: BLE001
            return {}
        if len(labels) != self.pages:
            return {}
        return {index + 1: label for index, label in enumerate(labels) if label and label != str(index + 1)}

    def text(self, number):
        """One page's text (cached). A page that cannot be parsed is empty and remembered as failed."""
        if number not in self.texts:
            try:
                self.texts[number] = _clean(self.reader.pages[number - 1].extract_text() or '')
            except Exception as exc:  # noqa: BLE001 - the library raises many kinds for a damaged page
                self.texts[number], self.failed[number] = '', type(exc).__name__
        return self.texts[number]

    def head(self, number):
        return {'page': number, **({'printed_number': self.labels[number]} if number in self.labels else {})}


class PdfLibrary:
    """Downloaded PDFs on disk (the application's own folder, not a work folder) and opened documents in memory."""

    def __init__(self, directory=None, max_bytes=MAX_PDF_BYTES):
        self.directory, self.max_bytes = (Path(directory) if directory else None), max_bytes
        self._open, self._guard, self._stuck = OrderedDict(), threading.Lock(), set()

    # --- files that web_fetch downloaded ------------------------------------------------
    def put(self, data, url):
        """Keep a downloaded PDF; the same content gets the same id."""
        if self.directory is None:
            raise PdfError('This installation has no place to keep downloaded PDFs')
        digest = hashlib.sha256(data).hexdigest()
        ident = 'pdf-' + digest[:24]
        record = {'pdf_id': ident, 'sha256': digest, 'bytes': len(data), 'url': url,
                  'fetched_at': datetime.now(timezone.utc).isoformat()}
        self.directory.mkdir(parents=True, exist_ok=True)
        for name, content in ((ident + '.pdf', data), (ident + '.json', json.dumps(record).encode('utf-8'))):
            temporary = self.directory / (name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
            try:
                temporary.write_bytes(content)
                os.replace(temporary, self.directory / name)
            finally:
                temporary.unlink(missing_ok=True)
        self._prune(keep=ident)
        return record

    def get(self, ident):
        if not isinstance(ident, str) or not _ID.fullmatch(ident) or self.directory is None:
            raise PdfError('pdf_id must be the id a web_fetch result of this work returned, such as "pdf-0123..."')
        try:
            data = (self.directory / (ident + '.pdf')).read_bytes()
            record = json.loads((self.directory / (ident + '.json')).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise PdfError('That downloaded PDF is no longer kept; fetch its URL again with web_fetch') from None
        if hashlib.sha256(data).hexdigest()[:24] != ident[4:] or not isinstance(record, dict):
            raise PdfError('That downloaded PDF changed on disk; fetch its URL again with web_fetch')
        return data, record

    def _prune(self, keep):
        try:
            files = sorted((item for item in self.directory.glob('pdf-*.pdf')), key=lambda item: item.stat().st_mtime, reverse=True)
        except OSError:
            return
        total, now = 0, time.time()
        for index, item in enumerate(files):
            try:
                info = item.stat()
            except OSError:
                continue
            total += info.st_size
            if item.stem != keep and (index >= KEEP_FILES or total > KEEP_BYTES or now - info.st_mtime > KEEP_SECONDS):
                for path in (item, item.with_suffix('.json')):
                    path.unlink(missing_ok=True)

    # --- reading ------------------------------------------------------------------------
    def _document(self, data, marker):
        if len(data) > self.max_bytes:
            raise PdfError(f'This PDF is {megabytes(len(data))}; the limit in the settings is {megabytes(self.max_bytes)}.')
        if not looks_like_pdf(data):
            raise PdfError('This file is not a PDF (it does not begin with the PDF header).')
        digest = marker['sha256'] = hashlib.sha256(data).hexdigest()
        if digest in self._stuck:
            raise PdfError('This PDF could not be read earlier (a page did not finish in time); it is not tried again.')
        with self._guard:
            document = self._open.get(digest)
            if document is not None:
                self._open.move_to_end(digest)
                return document
        document = _Document(data, digest)
        with self._guard:
            self._open[digest] = document
            while len(self._open) > KEEP_OPEN:
                self._open.popitem(last=False)
        return document

    async def read(self, data, args, *, source):
        """Answer one pdf_read call for the given file bytes. ``source`` is the path or URL to show."""
        request = _request(args)
        loop = asyncio.get_running_loop()
        marker = {}
        work = loop.run_in_executor(_POOL, self._read, data, request, source, marker)
        try:
            return await asyncio.wait_for(asyncio.shield(work), WAIT_SECONDS)
        except asyncio.TimeoutError:
            # The thread cannot be stopped. Its file is closed to further calls, so it holds one of the two
            # parsing places only until that page ends, and nothing new queues behind it.
            if 'sha256' not in marker:
                raise PdfError('The PDF reader is busy with other files; try again later.') from None
            self._stuck.add(marker['sha256'])
            raise PdfError(f'This PDF did not finish within {WAIT_SECONDS} seconds (opening it, or one of its pages). '
                           'The file cannot be read by this application; say so instead of trying again.') from None

    def _read(self, data, request, source, marker):
        document = self._document(data, marker)
        if not document.lock.acquire(timeout=CALL_SECONDS):
            raise PdfError('This PDF is being read by another call; try again in a moment.')
        try:
            deadline = time.monotonic() + CALL_SECONDS
            base = {'source': source, 'pages': document.pages, 'sha256': document.sha256, 'untrusted': True}
            if request['find'] is not None:
                return _find(document, base, request, deadline)
            if request['first'] is None:
                return _overview(document, base, deadline)
            return _pages(document, base, request, deadline)
        finally:
            document.lock.release()


def _request(args):
    if not isinstance(args, dict) or set(args) - _ARGS:
        raise PdfError('pdf_read takes path or pdf_id, and optionally first_page, last_page, offset, find, max_chars')

    def integer(name, low, high, default=None):
        value = args.get(name, default)
        if value is None:
            return None
        if type(value) is not int or not low <= value <= high:
            raise PdfError(f'{name} must be an integer {low}..{high}')
        return value
    first, last = integer('first_page', 1, MAX_PAGES), integer('last_page', 1, MAX_PAGES)
    offset = integer('offset', 0, PAGE_CHARS, 0)
    find = args.get('find')
    if find is not None and (not isinstance(find, str) or not find.strip() or len(find) > 100):
        raise PdfError('find must be a word or phrase of 1 to 100 characters')
    if last is not None and first is None and find is None:
        raise PdfError('last_page needs first_page')
    if first is not None and last is not None and last < first:
        raise PdfError('last_page must not be before first_page')
    if offset and (first is None or find is not None):
        raise PdfError('offset continues a page that was cut: give it together with first_page')
    return {'first': first, 'last': last, 'offset': offset, 'find': find.strip() if find else None,
            'max_chars': integer('max_chars', 2000, MAX_CHARS, DEFAULT_CHARS)}


def _text_state(document, counted):
    """What to say about pages without text, from the pages counted so far."""
    thin = [number for number in range(1, counted + 1) if len(document.texts.get(number, '')) < THIN_PAGE]
    result = {}
    if thin:
        result['pages_without_text'] = thin[:40]
        if len(thin) > 40:
            result['pages_without_text_more'] = len(thin) - 40
    if counted and len(thin) == counted:
        result['text_layer'] = 'none'
        result['note'] = ('No text could be taken from this PDF' + ('' if counted == document.pages else f' (first {counted} pages)')
                          + ': its pages are images (a scan) or use fonts without a text mapping. The application has no OCR. '
                            'Say that the document could not be read; do not describe its content.')
    elif thin:
        result['text_layer'] = 'partial'
        result['note'] = (f'{len(thin)} of the {counted} pages counted hold no text (images, charts or scans; no OCR). '
                          'What stands only on those pages was not read.')
    else:
        result['text_layer'] = 'present'
    if document.failed:
        result['pages_not_parsed'] = sorted(document.failed)[:40]
    return result


def _overview(document, base, deadline):
    counted = 0
    for number in range(1, document.pages + 1):
        if number > 3 and time.monotonic() > deadline:
            break
        document.text(number)
        counted = number
    chars = [len(document.texts[number]) for number in range(1, counted + 1)]
    start = next((document.texts[number] for number in range(1, counted + 1) if len(document.texts[number]) >= THIN_PAGE), '')
    result = {**base, 'mode': 'overview', 'bytes': document.bytes,
              **({'title': document.title} if document.title else {}),
              'outline': document.outline, 'counted_pages': counted, 'total_chars': sum(chars),
              **_text_state(document, counted),
              'start': ' '.join(start.split())[:500],
              'read_hint': ('Read pages with first_page and last_page (1 is the first page of the file); find lists the pages '
                            'where a term occurs. Cite figures as "p. N" with these page numbers.')}
    if document.labels:
        result['printed_numbers'] = ('The numbers printed on the pages differ from the file\'s page numbers; each page returned '
                                     'carries printed_number. first_page and last_page always count from the first page of the file.')
    if counted < document.pages:
        result['counted_note'] = (f'Pages {counted + 1}..{document.pages} were not counted within the time for one call; '
                                  'they are counted when they are read.')
    # Per-page counts for a document of ordinary length; sums over ten pages for a longer one.
    if counted <= 400:
        result['page_chars'] = chars
    else:
        result['page_chars_by_ten'] = [sum(chars[index:index + 10]) for index in range(0, counted, 10)]
    while _size(result) > DEFAULT_CHARS and result['outline']:
        result['outline'] = result['outline'][:len(result['outline']) * 2 // 3]
        result['outline_truncated'] = True
    return result


def _pages(document, base, request, deadline):
    first, offset, maximum = request['first'], request['offset'], request['max_chars']
    if first > document.pages:
        raise PdfError(f'first_page {first} is beyond the last page ({document.pages})')
    last = min(request['last'] or document.pages, document.pages)
    result = {**base, 'mode': 'pages', 'first_page': first, 'content': [], 'next_page': None, 'next_offset': None,
              'complete': True}
    for number in range(first, last + 1):
        if result['content'] and time.monotonic() > deadline:
            result.update(next_page=number, complete=False, stopped='time for one call was used; go on from next_page')
            break
        text = document.text(number)
        skip = offset if number == first else 0
        if skip > len(text):
            raise PdfError(f'offset {skip} is beyond the text of page {number} ({len(text)} characters)')
        row = {**document.head(number), 'chars': len(text), 'text': text[skip:]}
        if skip:
            row['offset'] = skip
        if len(text) < THIN_PAGE:
            row['note'] = ('this page could not be parsed' if number in document.failed
                           else 'no text on this page (an image, a chart or a scan; no OCR)')
        result['content'].append(row)
        if _size(result) <= maximum:
            continue
        # Over the answer's size: cut this page's text to what fits, or leave the page for the next call.
        result['content'].pop()
        low, high = 0, len(row['text'])
        while low < high:
            middle = (low + high + 1) // 2
            result['content'].append({**row, 'text': row['text'][:middle], 'cut': True})
            fits = _size(result) <= maximum - 200
            result['content'].pop()
            low, high = (middle, high) if fits else (low, middle - 1)
        if low >= 400 or not result['content']:
            if not low:
                raise PdfError('max_chars is too small for one page; ask for a larger answer')
            result['content'].append({**row, 'text': row['text'][:low], 'cut': True})
            result.update(next_page=number, next_offset=skip + low, complete=False)
        else:
            result.update(next_page=number, complete=False)
        break
    else:
        if last < document.pages:
            result['next_page'] = last + 1
    result['last_page'] = result['content'][-1]['page'] if result['content'] else first
    if result['next_offset'] is None:
        del result['next_offset']
    return result


def _find(document, base, request, deadline):
    wanted = request['find'].casefold()
    first = request['first'] or 1
    if first > document.pages:
        raise PdfError(f'first_page {first} is beyond the last page ({document.pages})')
    last = min(request['last'] or document.pages, document.pages)
    rows, pages, searched, more = [], 0, first - 1, False
    for number in range(first, last + 1):
        if number > first and time.monotonic() > deadline:
            more = True
            break
        text = document.text(number)
        folded, position, on_page = text.casefold(), 0, 0
        # casefold can change a text's length; positions are only used when it did not.
        same = len(folded) == len(text)
        while on_page < FIND_PER_PAGE:
            position = folded.find(wanted, position)
            if position < 0:
                break
            source = text if same else folded
            snippet = ' '.join(source[max(0, position - SNIPPET):position + len(wanted) + SNIPPET].split())
            if not rows or rows[-1]['page'] != number or rows[-1]['snippet'] != snippet:
                rows.append({**document.head(number), 'snippet': snippet})
            on_page, position = on_page + 1, position + len(wanted)
        pages += bool(on_page)
        searched = number
        if len(rows) >= FIND_ROWS:
            more = number < last
            break
    result = {**base, 'mode': 'find', 'find': request['find'], 'matches': rows[:FIND_ROWS], 'pages_with_matches': pages,
              'searched_pages': [first, searched], 'complete': not more}
    if more:
        result['next_page'] = searched + 1
        result['note'] = 'More pages remain: call again with find and first_page = next_page.'
    elif not rows:
        result['note'] = ('The phrase does not occur in the text of these pages. Try a shorter or different wording; '
                          'text inside images is not searched.')
    while _size(result) > request['max_chars'] and result['matches']:
        result['matches'].pop()
        result['complete'] = False
        result['next_page'] = result['matches'][-1]['page'] + 1 if result['matches'] else first
    return result


class PdfToolMixin:
    """The engine's side of pdf_read: who may read which file, and what the run remembers of it."""

    def _pdf_available(self, run):
        config = run['_config']
        return bool(config['paths']['read_roots'] or config['search']['enabled'])

    def _pdf_policy(self, run):
        if not self._pdf_available(run):
            return ''
        return PDF_POLICY + (PDF_WEB_POLICY if run['_config']['search']['enabled'] else '')

    async def _pdf_read(self, run, agent, args):
        if not self._pdf_available(run):
            raise ValueError('PDF を読むには、読み取りを許可したフォルダーか Web 検索の設定が必要です')
        if not isinstance(args, dict) or set(args) - _ARGS:
            raise PdfError('pdf_read takes path or pdf_id, and optionally first_page, last_page, offset, find, max_chars')
        if ('path' in args) == ('pdf_id' in args):
            raise PdfError('pdf_read needs exactly one of path (a file in an allowed read folder) or pdf_id (from web_fetch)')
        if 'path' in args:
            if not isinstance(args['path'], str):
                raise PdfError('path must be a string')
            return await self._execute_read_tool(run, agent, 'pdf_read', args)
        records = getattr(run.get('_web'), 'pdf_ids', {})
        if args['pdf_id'] not in records:
            raise PdfError('pdf_id must be the id a web_fetch result of this work returned; fetch the PDF\'s URL with web_fetch first')
        data, record = await asyncio.to_thread(self.pdf_library.get, args['pdf_id'])
        async with self._run_deadline(run):
            result = await self.pdf_library.read(data, {key: value for key, value in args.items() if key != 'pdf_id'},
                                                 source=record['url'])
        result = {'pdf_id': args['pdf_id'], 'url': record['url'], **{key: value for key, value in result.items() if key != 'source'}}
        self._pdf_note(run, record['url'], result)
        return result

    async def _pdf_from_file(self, run, args):
        """A PDF in a folder the human allowed for reading; the usual path checks, the PDF size limit."""
        limit = run['_config']['limits']['max_pdf_bytes']
        harness = run['_harness']
        try:
            data = await asyncio.to_thread(harness.read_bytes, args['path'], limit)
        except ValueError as exc:
            if 'size limit' in str(exc):
                raise PdfError(f'{exc}: a PDF may be up to {megabytes(limit)} (the PDF size limit in the settings)') from None
            raise
        return await self.pdf_library.read(data, {key: value for key, value in args.items() if key != 'path'},
                                           source=str(harness.resolve(args['path'])))
