"""Text out of PDF files: page count, outline, pages by number, and where no text can be taken.

A long report (a white paper, an institution's outlook) is read a few pages at
a time: the first call says how long the document is, what its outline names
and how much text each page holds; later calls return the pages asked for, each
under its page number, so a figure can be cited with the page it stands on.

What this does not do: open a file that needs a password, read a page that is only a
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
FIND_ROWS, FIND_PER_PAGE, SNIPPET = 30, 3, 200
THIN_PAGE = 5                  # fewer characters than this: the page has no text layer worth the name
KEEP_OPEN = 3                  # documents whose pages stay in memory
KEEP_FILES, KEEP_BYTES, KEEP_SECONDS = 12, 600 * 1024 * 1024, 14 * 24 * 3600
MAX_PDF_BYTES = 200 * 1024 * 1024   # the most the settings allow for one PDF

logging.getLogger('pypdf').setLevel(logging.ERROR)  # a damaged file's warnings are not the console's business
_ID = re.compile(r'pdf-[0-9a-f]{24}\Z')
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='awb-pdf')
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]')
_BLANK_RUN = re.compile(r'\n[ \t]*(?:\n[ \t]*){2,}')

_SOURCE = {'path': {'type': 'string'}, 'pdf_id': {'type': 'string', 'maxLength': 28}}
_RANGE = {'first_page': {'type': 'integer', 'minimum': 1, 'maximum': MAX_PAGES},
          'last_page': {'type': 'integer', 'minimum': 1, 'maximum': MAX_PAGES}}
PDF_READ_TOOL = {'name': 'pdf_read', 'description': (
    'Read a PDF from an allowed read folder (path) or one that web_fetch downloaded (pdf_id). Without first_page: '
    'page count, outline, characters per page, how it begins. With first_page (1 = first page of the file): text '
    'of those pages, each with page (position in the file) and printed_page when the file prints other numbers, '
    'up to max_chars; next_page continues. Password-locked files are refused; scanned pages have no text (no OCR). '
    'Untrusted data.'),
    'parameters': {'type': 'object', 'properties': {
        **_SOURCE, **_RANGE,
        'offset': {'type': 'integer', 'minimum': 0, 'maximum': PAGE_CHARS},
        'max_chars': {'type': 'integer', 'minimum': 2000, 'maximum': MAX_CHARS}},
        'additionalProperties': False}}
PDF_SEARCH_TOOL = {'name': 'pdf_search', 'description': (
    'Find a phrase, a table or row label, or a number in a PDF (path or pdf_id as for pdf_read): returns the pages '
    'on which it stands, each with the words around it. Case and line breaks do not matter. Use it to locate a '
    'figure and to check one before reporting it.'),
    'parameters': {'type': 'object', 'properties': {
        **_SOURCE, 'query': {'type': 'string', 'maxLength': 100}, **_RANGE,
        'max_chars': {'type': 'integer', 'minimum': 2000, 'maximum': MAX_CHARS}},
        'required': ['query'], 'additionalProperties': False}}
PDF_SAVE_TOOL = {'name': 'pdf_save', 'description': (
    'Save a PDF that web_fetch downloaded (pdf_id) as a new file in an allowed write folder: path ends in .pdf and '
    'must not exist yet. Use it when the request asks to keep the PDF.'),
    'parameters': {'type': 'object', 'properties': {'pdf_id': {'type': 'string', 'maxLength': 28}, 'path': {'type': 'string'}},
                   'required': ['pdf_id', 'path'], 'additionalProperties': False}}
PDF_TOOLS = {'pdf_read': frozenset(PDF_READ_TOOL['parameters']['properties']),
             'pdf_search': frozenset(PDF_SEARCH_TOOL['parameters']['properties'])}
_ARGS = PDF_TOOLS['pdf_read'] | {'find'}   # what the library itself takes: a search arrives as ``find``

# Added to an agent's instructions once a PDF is part of the work (the request names one, or one was opened or
# downloaded), so that work without PDFs does not carry it.
PDF_POLICY = (
    '\n\nPDF reports: see the page count and outline with pdf_read first. Find what you need with pdf_search (a '
    'phrase, a table name such as "Table 1.1", a row label such as "World Output", or a number) and read only those '
    'pages; never read a long report from cover to cover. Every figure you report carries its page and the words it '
    'comes from (a short quotation or the table row). Cite a page by its position in the file, "p. 26"; where the '
    'result gives printed_page, add it in brackets, "p. 26 (printed 10)", and use this one form everywhere. Before '
    'finishing, look up each headline figure again with pdf_search and compare it with the text: correct what '
    'differs, and write a figure you cannot find as not confirmed, never as another number. Report only pages you '
    'read. A worker reports each figure it confirmed with its value, unit, page and quotation; the coordinator takes '
    'those figures over as they stand and does not mark as unconfirmed what a worker confirmed. A table or chart '
    'holds only figures confirmed on a page: a row nobody confirmed is left out (or its cell says 未確認), never '
    'filled with a number. If you read a PDF that was already in a folder instead of downloading it, say so in the '
    'deliverable and in your report: its path, and that it was not downloaded in this work. If a PDF has no text, say so.')
# Only where pages can be fetched.
PDF_WEB_POLICY = (
    ' A chapter or section you could not obtain or read gets one line, "not obtained; no summary": never write its '
    'points from another part (an executive summary is not chapter 1).'
    ' For "the latest" issue of a report that appears regularly, establish the publication dates first (the '
    'publisher\'s list of issues) and take the newest issue, not the first one found; state its date.'
    ' To get a report, web_fetch its PDF address (the result has a pdf_id); a page that web_fetch returns lists the PDF '
    'files it links to (pdf_links). Where a report comes as several files, fetch the full report first, not its '
    'parts (summary, chapters, tables) one after another. If an institution\'s main site refuses the request, use the same institution\'s '
    'official distribution site (for the IMF, the IMF eLibrary) instead of retrying: search for "<report name> '
    'filetype:pdf" or with site:<the publisher\'s domain> and fetch the PDF directly from where the publisher itself '
    'distributes it (its content network or file storage counts). Where several addresses carry the same file name, '
    'follow these steps in order: (1) web_fetch every candidate with headers_only; (2) read same_name_copies in the '
    'result: the application lists the candidates newest first by last_modified; (3) fetch newest_copy, the one with '
    'the latest date, not the first one found; (4) write the candidates with their dates and sizes, and the one '
    'chosen, in the report. A copy on '
    'a site that is not the publisher\'s (a university repository, a mirror) only when no official one can be had, '
    'and say so. If a part still cannot be '
    'downloaded, ask the human once with ask_user: give its URL and ask them to save the PDF from their browser into '
    'a read folder (recommendation: go on without that part and report it as not obtained). Once it is saved, read it '
    'with pdf_read by path. When the request asks to keep the downloaded PDF (to save it in a folder), save it with '
    'pdf_save (its pdf_id and a path ending in .pdf) before you finish, and name the saved file in the report. Save '
    'the copy you read and quote, once. Before finishing, the application looks up every quotation that stands with a '
    'page number in your files in the PDF; give the page the words stand on, and put only words that are in the PDF '
    'into quotation marks.')
_PDF_WORD = re.compile(r'pdf|ＰＤＦ', re.I)


_NEEDS_PASSWORD = ('This PDF needs a password to open. The application does not open such files and tries no '
                   'password. Say so; a human can save an unprotected copy into a read folder.')


# Only in a piece of work for which the human allowed it.
BROWSER_TRY_POLICY = (
    ' For this work the human allowed one try in a visible browser window: when a site refuses web_fetch, the '
    'application opens that address once by itself and returns what the window showed. Where the site shows a check '
    'meant for a person, the human is asked to pass it in that window. You do not ask for the window and cannot '
    'repeat it; if it also fails, ask the human as described above. When the window read a page, look at its result: '
    'linked_pdf is the full report the same window opened next (read it with pdf_read); if there is none, fetch the '
    'report the page links to (pdf_links) with web_fetch next, and the application opens it from that page. A page or '
    'file a window already brought is returned again when asked for. A refused headers_only question says nothing '
    'about the file; the file itself is then fetched.')


_PUT_LOCK = threading.Lock()  # one writer at a time into the folder of downloaded PDFs


class PdfError(ValueError):
    """A PDF could not be opened or read; the text is safe to show to a model."""


_QUOTE_MARKS = str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"', '–': '-', '—': '-', '‐': '-', '‑': '-', '−': '-'})


def fold_quote(text):
    """Text as it is compared: case, spaces, line breaks and the shapes of quotes and dashes do not count."""
    return ''.join(text.translate(_QUOTE_MARKS).casefold().split()).strip('.,;:。、')


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
        self.sha256, self.bytes, self.lock = sha256, len(data), threading.Lock()
        self.texts, self.flats, self.failed, self.protected = {}, {}, {}, False
        try:
            self.reader = PdfReader(io.BytesIO(data), strict=False)
            if self.reader.is_encrypted:
                # Most public reports of this kind open for anyone: the author set no password to open the
                # file and only restricted changing, printing or copying it. Those are read, as any viewer
                # shows them. A file that needs a password to open is refused; no password is ever tried.
                if not self.reader.decrypt(''):
                    raise PdfError(_NEEDS_PASSWORD)
                self.protected = True
            self.pages = len(self.reader.pages)
        except PdfError:
            raise
        except Exception as exc:  # noqa: BLE001 - the library raises many kinds for a file it cannot open
            name = type(exc).__name__
            if name == 'DependencyError':
                raise PdfError('This PDF is encrypted, and the library that opens such files (cryptography) is not '
                               'installed here. It was not read. Say so; a human can run the application\'s setup '
                               'again, or save an unprotected copy into a read folder.') from None
            if name in {'FileNotDecryptedError', 'WrongPasswordError'}:
                raise PdfError(_NEEDS_PASSWORD) from None
            raise PdfError('This file could not be opened as a PDF (' + name + '). '
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
        if len(labels) != self.pages or all(label == str(index + 1) for index, label in enumerate(labels)):
            return {}
        return {index + 1: label for index, label in enumerate(labels)}

    def text(self, number):
        """One page's text (cached). A page that cannot be parsed is empty and remembered as failed."""
        if number not in self.texts:
            try:
                self.texts[number] = _clean(self.reader.pages[number - 1].extract_text() or '')
            except Exception as exc:  # noqa: BLE001 - the library raises many kinds for a damaged page
                self.texts[number], self.failed[number] = '', type(exc).__name__
        return self.texts[number]

    def flat(self, number):
        """A page's text on one line, for searching across its line breaks."""
        if number not in self.flats:
            self.flats[number] = ' '.join(self.text(number).split())
        return self.flats[number]

    def head(self, number):
        # Both numbers wherever the file prints other numbers than the positions (front matter in roman
        # numerals, a body that starts again at 1): ``page`` is the position, ``printed_page`` what the page shows.
        return {'page': number, **({'printed_page': self.labels[number]} if self.labels else {})}


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
        with _PUT_LOCK:
            for name, content in ((ident + '.pdf', data), (ident + '.json', json.dumps(record).encode('utf-8'))):
                target = self.directory / name
                if name.endswith('.pdf') and self._same(target, data, digest):
                    # Real-machine case: two agents fetched the same report at the same time; replacing the
                    # file the other one had open was refused on Windows ("[WinError 5]") and the fetch failed.
                    # The file is named after its content: the one that is there is this one.
                    continue
                temporary = self.directory / (name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
                try:
                    temporary.write_bytes(content)
                    for attempt in range(6):
                        try:
                            os.replace(temporary, target)
                            break
                        except PermissionError:
                            # Another reader has the old file open for a moment (Windows).
                            if name.endswith('.pdf') and self._same(target, data, digest):
                                break
                            if attempt == 5:
                                if target.is_file():
                                    break  # the record that is there describes the same file; keep it
                                raise PdfError('The downloaded PDF could not be kept (the file is in use); fetch it again') from None
                            time.sleep(.1 * (attempt + 1))
                finally:
                    temporary.unlink(missing_ok=True)
        self._prune(keep=ident)
        return record

    @staticmethod
    def _same(path, data, digest):
        """The file is there and holds exactly this content."""
        try:
            return path.stat().st_size == len(data) and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        except OSError:
            return False

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
        except PdfError:
            raise
        except Exception as exc:  # noqa: BLE001 - whatever a file makes the parser raise is that file's failure
            if not isinstance(exc, asyncio.TimeoutError):
                # Never an unexpected error for the agent: a file that cannot be read is a result, with its reason.
                raise PdfError('This PDF could not be read (' + type(exc).__name__ + '). Say so instead of trying again.') from None
            # The thread cannot be stopped. Its file is closed to further calls, so it holds one of the two
            # parsing places only until that page ends, and nothing new queues behind it.
            if 'sha256' not in marker:
                raise PdfError('The PDF reader is busy with other files; try again later.') from None
            self._stuck.add(marker['sha256'])
            raise PdfError(f'This PDF did not finish within {WAIT_SECONDS} seconds (opening it, or one of its pages). '
                           'The file cannot be read by this application; say so instead of trying again.') from None

    async def locate(self, data, quotes):
        """For each quotation, the pages on which it stands: {quote: [{page, printed_page?}, ...]}.

        None when the file could not be gone through in the time one call has (a long file whose pages were
        not read before): then nothing is known, and nothing is said.
        """
        loop = asyncio.get_running_loop()
        work = loop.run_in_executor(_POOL, self._locate, data, list(quotes))
        try:
            return await asyncio.wait_for(asyncio.shield(work), WAIT_SECONDS)
        except Exception:  # noqa: BLE001 - a check that cannot be made is no finding
            return None

    def _locate(self, data, quotes):
        document = self._document(data, {})
        if not document.lock.acquire(timeout=CALL_SECONDS):
            return None
        try:
            deadline = time.monotonic() + CALL_SECONDS
            wanted = {quote: [part for part in map(fold_quote, re.split(r'…|\.{3,}', quote)) if len(part) >= 4] for quote in quotes}
            found = {quote: [] for quote in quotes}
            for number in range(1, document.pages + 1):
                if time.monotonic() > deadline:
                    return None
                page = fold_quote(document.flat(number))
                for quote, parts in wanted.items():
                    if parts and len(found[quote]) < 8 and all(part in page for part in parts):
                        found[quote].append(document.head(number))
            return found
        finally:
            document.lock.release()

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
        raise PdfError('pdf_read takes path or pdf_id, and optionally first_page, last_page, offset, max_chars')

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
        raise PdfError('query must be words or a number, 1 to 100 characters')
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
              'read_hint': ('Read pages with first_page and last_page (1 is the first page of the file); pdf_search finds '
                            'the pages where a phrase or a number stands. Cite figures as "p. N" with these page numbers.')}
    if document.protected:
        result['protected'] = ('This PDF opens without a password; its author restricted some uses (such as changing, '
                               'printing or copying). It was read as a viewer shows it.')
    if document.labels:
        result['printed_pages'] = ('The numbers printed on the pages differ from the positions in the file: every page returned '
                                   'carries page (the position; first_page and last_page count in it) and printed_page.')
        for row in result['outline']:
            if row.get('page') in document.labels:
                row['printed_page'] = document.labels[row['page']]
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
    """pdf_search: the pages on which the words stand, with what surrounds them (case and line breaks ignored)."""
    wanted = ' '.join(request['find'].split()).casefold()
    first = request['first'] or 1
    if first > document.pages:
        raise PdfError(f'first_page {first} is beyond the last page ({document.pages})')
    last = min(request['last'] or document.pages, document.pages)
    rows, pages, searched, more = [], 0, first - 1, False
    for number in range(first, last + 1):
        if number > first and time.monotonic() > deadline:
            more = True
            break
        text = document.flat(number)
        folded, position, on_page = text.casefold(), 0, 0
        # casefold can change a text's length; positions are only used when it did not.
        same = len(folded) == len(text)
        while on_page < FIND_PER_PAGE:
            position = folded.find(wanted, position)
            if position < 0:
                break
            source = text if same else folded
            context = source[max(0, position - SNIPPET):position + len(wanted) + SNIPPET]
            if not rows or rows[-1]['page'] != number or rows[-1]['context'] != context:
                rows.append({**document.head(number), 'context': context})
            on_page, position = on_page + 1, position + len(wanted)
        pages += bool(on_page)
        searched = number
        if len(rows) >= FIND_ROWS:
            more = number < last
            break
    result = {**base, 'mode': 'search', 'query': request['find'], 'matches': rows[:FIND_ROWS], 'pages_with_matches': pages,
              'searched_pages': [first, searched], 'complete': not more}
    if more:
        result['next_page'] = searched + 1
        result['note'] = 'More pages remain: search again with first_page = next_page.'
    elif not rows:
        result['note'] = ('These words do not stand in the text of these pages. Try fewer words or another wording '
                          '(a number may be printed as "3.1" or "3.1 percent"); text inside images is not searched.')
    else:
        result['note'] = 'Read the page with pdf_read (first_page = page) before quoting more than the words shown.'
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
        web = run['_config']['search']['enabled']
        # The guidance on PDFs joins the instructions once a PDF is part of the work.
        relevant = run.get('_pdf_touched') or bool(_PDF_WORD.search(run.get('task') or ''))
        return ((PDF_POLICY + (PDF_WEB_POLICY if web else '') if relevant else '')
                + (BROWSER_TRY_POLICY if run.get('browser_fetch') else ''))

    def _pdf_mentioned(self, run, text):
        """A later message of the human names a PDF."""
        if isinstance(text, str) and _PDF_WORD.search(text):
            run['_pdf_touched'] = True

    def _pdf_footer(self, run):
        """Under the coordinator's result: which PDFs this work read, and whether each was downloaded in it."""
        rows = list((run.get('_pdf_sources') or {}).items())[:10]
        if not rows:
            return ''
        described = {'downloaded': 'この作業でダウンロード', 'folder': '読み取りフォルダーに既にあったファイル（この作業ではダウンロードしていません）'}
        return ('\n\n【アプリの確認】この作業で読んだ PDF:\n'
                + '\n'.join(f'- {self.redact(source)[:300]} — {described[kind]}' for source, kind in rows))

    async def _pdf_read(self, run, agent, args, tool='pdf_read'):
        if not self._pdf_available(run):
            raise ValueError('PDF を読むには、読み取りを許可したフォルダーか Web 検索の設定が必要です')
        run['_pdf_touched'] = True
        if not isinstance(args, dict) or set(args) - PDF_TOOLS[tool]:
            raise PdfError(f'{tool} takes ' + ', '.join(sorted(PDF_TOOLS[tool])))
        if tool == 'pdf_search':
            if not isinstance(args.get('query'), str):
                raise PdfError('pdf_search needs query: the words or the number to look for')
            args = {**{key: value for key, value in args.items() if key != 'query'}, 'find': args['query']}
        if ('path' in args) == ('pdf_id' in args):
            raise PdfError(f'{tool} needs exactly one of path (a file in an allowed read folder) or pdf_id (from web_fetch)')
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
        run.setdefault('_pdf_sources', {})[record['url']] = 'downloaded'
        if result.get('mode') != 'overview':
            run.setdefault('_pdf_read_ids', {})[args['pdf_id']] = record['url']  # pages or a search: this file was read
        self._pdf_note(run, record['url'], result)
        return result

    async def _pdf_save(self, run, agent, args):
        """Copy a PDF this work downloaded into a write folder, as a new file. The caller holds the file lock."""
        if not isinstance(args, dict) or set(args) != {'pdf_id', 'path'} or not isinstance(args['path'], str):
            raise PdfError('pdf_save takes pdf_id (from web_fetch) and path (a new .pdf file in a write folder)')
        if not args['path'].lower().endswith('.pdf'):
            raise PdfError('path must end in .pdf')
        records = getattr(run.get('_web'), 'pdf_ids', {})
        if args['pdf_id'] not in records:
            raise PdfError('pdf_id must be the id a web_fetch result of this work returned')
        data, record = await asyncio.to_thread(self.pdf_library.get, args['pdf_id'])
        saved, read = run.setdefault('_pdf_saved', {}), run.get('_pdf_read_ids') or {}
        if record['sha256'] in saved:
            # Real-machine case: the same file was saved twice, as "…2025.pdf" and "…2025_latest.pdf".
            raise PdfError(f"This PDF is already saved in this work as {saved[record['sha256']]}. The same file is not saved a "
                           'second time: use that file, and name it in the report.')
        asked = run.setdefault('_pdf_save_asked', set())
        if read and args['pdf_id'] not in read and args['pdf_id'] not in asked:
            # Real-machine case: the report quoted one copy of a document, and an older copy was saved beside it.
            asked.add(args['pdf_id'])
            others = ', '.join(f'{ident} ({url})' for ident, url in list(read.items())[-3:])
            raise PdfError('Not saved. This is not the PDF this work read: its pages were read from ' + others + '. Save the PDF '
                           'the report quotes (that pdf_id), so that the saved file is the one the page numbers refer to. '
                           'If this other file is really the one wanted, call pdf_save again with the same arguments.')
        try:
            result = await asyncio.to_thread(run['_harness'].write_bytes, args['path'], data, 'missing',
                                             limit=run['_config']['limits']['max_pdf_bytes'])
        except ValueError as exc:
            if 'expected_sha256' in str(exc) or 'changed' in str(exc).lower():
                raise PdfError('A file of that name already exists. pdf_save only creates a new file: choose another name') from None
            raise
        self.record_receipt(agent, 'pdf_save', result)
        saved[record['sha256']] = result['path']
        return {**{key: value for key, value in result.items() if key != 'previous_sha256'}, 'source_url': record['url'],
                'note': 'Saved as downloaded. Say in the report where it came from (source_url).'}

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
        source = str(harness.resolve(args['path']))
        result = await self.pdf_library.read(data, {key: value for key, value in args.items() if key != 'path'}, source=source)
        digest = hashlib.sha256(data).hexdigest()
        fetched = next(((ident, record) for ident, record in getattr(run.get('_web'), 'pdf_ids', {}).items()
                        if record.get('sha256') == digest), None)
        if result.get('mode') != 'overview':
            run.setdefault('_pdf_read_paths', {})[source] = digest
        if fetched:
            # Real-machine case: the PDF was downloaded and saved with pdf_save in this work, then read by its
            # path, and the report said it "was not downloaded in this work". It is the downloaded file.
            ident, record = fetched
            result['origin'] = (f"This file is the PDF this work downloaded from {record['url']} (the same content as "
                                f'{ident}). Report it as downloaded in this work, with that address.')
            run.setdefault('_pdf_sources', {})[record['url']] = 'downloaded'
            if result.get('mode') != 'overview':
                run.setdefault('_pdf_read_ids', {})[ident] = record['url']
            return result
        # Where the file came from is the application's knowledge, not the model's: this one was not downloaded
        # by this work's web_fetch.
        result['origin'] = ('A file that was already in a read folder; it was not downloaded in this work. '
                            'Say so (with this path) wherever you report what it contains.')
        run.setdefault('_pdf_sources', {}).setdefault(source, 'folder')
        return result
