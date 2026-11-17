"""PDF reports: downloading, reading by page, and what is refused. No external service is contacted."""
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import pdfdocs, sources
from workbench.config import DEFAULT, validate_settings
from workbench.pdfdocs import PdfError, PdfLibrary
from workbench.webtools import WebToolError, WebTools
from pdf_fixture import encrypted, make_pdf
from test_engine import configured, start
from test_web_phase9 import http_server, pin

LONG = 'Annex table A1: unemployment 5.0 percent.\n' + '\n'.join(f'row {index}: filler value {index * 3}' for index in range(400))
PAGES = ['World Outlook', 'Contents', 'Executive summary. Global growth is projected at 3.2 percent in 2026.\nInflation falls to 4.1 percent.',
         'Chapter 1. Trade grew 2.9 percent (see Table 1.1).', '', LONG]
REPORT = make_pdf(PAGES, title='World Outlook (test)', labels_from=(3, 1),
                  outline=[('Executive summary', 3, 0), ('Chapter 1', 4, 0), ('Trade', 4, 1), ('Annex', 6, 0)])


async def read(library, data, **args):
    return await library.read(data, args, source='report.pdf')


async def test_the_first_call_says_how_long_the_document_is_and_what_it_holds():
    result = await read(PdfLibrary(), REPORT)
    assert result['mode'] == 'overview' and result['pages'] == 6 and result['title'] == 'World Outlook (test)'
    assert result['sha256'] == hashlib.sha256(REPORT).hexdigest() and result['untrusted'] is True
    assert [(row['title'], row['level'], row['page']) for row in result['outline']] == [
        ('Executive summary', 0, 3), ('Chapter 1', 0, 4), ('Trade', 1, 4), ('Annex', 0, 6)]
    assert result['counted_pages'] == 6 and len(result['page_chars']) == 6
    assert result['page_chars'][4] == 0 and result['page_chars'][5] == len(LONG)
    # One page of six is a picture: said, with its number, and the rest is readable.
    assert result['text_layer'] == 'partial' and result['pages_without_text'] == [5] and 'no OCR' in result['note']
    assert result['start'] == 'World Outlook' and 'printed_page' in result['printed_pages']
    assert [row.get('printed_page') for row in result['outline']] == ['1', '2', '2', '4']  # beside the position in the file
    assert len(json.dumps(result)) < pdfdocs.DEFAULT_CHARS


async def test_pages_come_back_under_their_numbers_and_a_long_page_continues_where_it_was_cut():
    library = PdfLibrary()
    result = await read(library, REPORT, first_page=3, last_page=6, max_chars=2000)
    assert [row['page'] for row in result['content']] == [3, 4, 5, 6]
    assert result['content'][0]['text'].startswith('Executive summary. Global growth is projected at 3.2 percent')
    # Both numbers on every page: the position in the file, and what the page prints (front matter in roman numerals).
    assert [(row['page'], row['printed_page']) for row in result['content']] == [(3, '1'), (4, '2'), (5, '3'), (6, '4')]
    front = await read(library, REPORT, first_page=1, last_page=2)
    assert [(row['page'], row['printed_page']) for row in front['content']] == [(1, 'i'), (2, 'ii')]
    assert 'printed_page' not in (await read(library, make_pdf(['one', 'two']), first_page=1))['content'][0]  # nothing else printed
    assert result['content'][2]['chars'] == 0 and 'no OCR' in result['content'][2]['note']
    assert result['content'][3]['cut'] is True and result['complete'] is False
    assert result['next_page'] == 6 and result['last_page'] == 6 and len(json.dumps(result, ensure_ascii=False)) <= 2000
    text, offset = result['content'][3]['text'], result['next_offset']
    for _ in range(20):
        more = await read(library, REPORT, first_page=6, offset=offset, max_chars=2000)
        text += more['content'][0]['text']
        if more['complete']:
            break
        offset = more['next_offset']
    assert text == LONG and more['next_page'] is None
    # Without last_page the answer fills up and says where to go on.
    result = await read(library, REPORT, first_page=1)
    assert result['content'][0]['text'] == 'World Outlook' and result['complete'] is True and result['last_page'] == 6


async def test_search_lists_the_pages_on_which_words_or_a_number_stand_with_what_surrounds_them():
    """Real-machine case: asked for the headline figures of a 124-page report, the model read page after page
    and reported 2.6 % where the text says 3.1 %. The figure is found by its words, on its page."""
    library = PdfLibrary()
    result = await read(library, REPORT, find='PERCENT')
    assert result['mode'] == 'search' and result['query'] == 'PERCENT'
    assert sorted({row['page'] for row in result['matches']}) == [3, 4, 6] and result['pages_with_matches'] == 3
    assert result['complete'] is True and result['searched_pages'] == [1, 6]
    assert any('Trade grew 2.9 percent' in row['context'] for row in result['matches'])
    assert all(row['printed_page'] for row in result['matches']) and 'pdf_read' in result['note']
    # A sentence that the page breaks into lines is found, and so is a number.
    broken = await read(library, REPORT, find='in 2026. inflation   falls')
    assert [(row['page'], row['printed_page']) for row in broken['matches']] == [(3, '1')]
    assert 'Global growth is projected at 3.2 percent in 2026. Inflation falls to 4.1 percent.' in broken['matches'][0]['context']
    assert [row['page'] for row in (await read(library, REPORT, find='4.1 percent'))['matches']] == [3]
    assert [row['page'] for row in (await read(library, REPORT, find='Table A1'))['matches']] == [6]
    assert (await read(library, REPORT, find='percent', first_page=4, last_page=5))['pages_with_matches'] == 1
    nothing = await read(library, REPORT, find='deflation')
    assert nothing['matches'] == [] and 'do not stand in the text' in nothing['note']


@pytest.mark.parametrize('args,message', [
    ({'first_page': 0}, 'first_page must be an integer 1'), ({'first_page': 9}, 'beyond the last page'),
    ({'first_page': 3, 'last_page': 2}, 'must not be before'), ({'last_page': 2}, 'needs first_page'),
    ({'offset': 5}, 'offset continues a page'), ({'find': ' '}, 'query must be'), ({'pages': '1-3'}, 'pdf_read takes'),
    ({'first_page': 1, 'max_chars': 100}, 'max_chars must be an integer'), ({'first_page': '1'}, 'first_page must be an integer'),
])
async def test_wrong_arguments_say_what_is_accepted(args, message):
    with pytest.raises(PdfError, match=message):
        await read(PdfLibrary(), REPORT, **args)


@pytest.mark.parametrize('algorithm', ['AES-256', 'AES-128', 'RC4-128'])
async def test_a_protected_pdf_that_opens_without_a_password_is_read_and_one_that_needs_one_is_refused(algorithm):
    """Real-machine case: four of five Japanese ministry PDFs are encrypted with the author's restrictions
    and no password to open them. Refusing all of them left most public documents unreadable."""
    library = PdfLibrary()
    restricted = encrypted(REPORT, '', algorithm)
    overview = await read(library, restricted)
    assert overview['pages'] == 6 and overview['title'] == 'World Outlook (test)' and overview['text_layer'] == 'partial'
    assert 'opens without a password' in overview['protected'] and 'restricted some uses' in overview['protected']
    page = await read(library, restricted, first_page=3, last_page=3)
    assert page['content'][0]['text'].startswith('Executive summary. Global growth is projected at 3.2 percent')
    assert 'protected' not in await read(library, REPORT)
    with pytest.raises(PdfError, match='needs a password to open') as caught:
        await read(library, encrypted(REPORT, 'secret', algorithm))
    assert 'tries no password' in str(caught.value)


async def test_whatever_the_parser_raises_becomes_a_stated_reason_not_an_unexpected_error(monkeypatch):
    """Real-machine case: without the AES library pypdf raised DependencyError, which is not one of its
    own error classes; it passed through web_fetch as an unexpected error and stopped the PM's turn."""
    import pypdf
    from pypdf.errors import DependencyError

    class NoAes(pypdf.PdfReader):
        def __init__(self, *args, **kwargs):
            raise DependencyError('cryptography>=3.1 is required for AES algorithm')

    protected = encrypted(REPORT)
    monkeypatch.setattr(pypdf, 'PdfReader', NoAes)
    with pytest.raises(PdfError, match='the library that opens such files') as caught:
        await read(PdfLibrary(), protected)
    assert 'It was not read' in str(caught.value)
    monkeypatch.undo()
    # A failure after opening, of a kind nobody listed.
    library = PdfLibrary()
    monkeypatch.setattr(pdfdocs, '_overview', lambda *args: (_ for _ in ()).throw(ZeroDivisionError('boom')))
    with pytest.raises(PdfError, match=r'could not be read \(ZeroDivisionError\)'):
        await read(library, REPORT)


async def test_damaged_scanned_and_oversized_files_are_named_as_such():
    library = PdfLibrary()
    with pytest.raises(PdfError, match='not a PDF'):
        await read(library, b'<html>Access Denied</html>')
    with pytest.raises(PdfError, match='could not be opened as a PDF'):
        await read(library, b'%PDF-1.7\nnothing that follows is a document')
    scan = await read(library, make_pdf(['', '', '']))
    assert scan['text_layer'] == 'none' and scan['pages_without_text'] == [1, 2, 3]
    assert 'no OCR' in scan['note'] and 'do not describe its content' in scan['note']
    pages = await read(library, make_pdf(['', '']), first_page=1)
    assert [row['text'] for row in pages['content']] == ['', ''] and 'no OCR' in pages['content'][0]['note']
    with pytest.raises(PdfError, match=r'This PDF is 0\.0 MB; the limit in the settings is 0\.0 MB'):
        await read(PdfLibrary(max_bytes=1000), REPORT)


async def test_a_page_that_does_not_end_costs_one_call_and_the_file_is_not_tried_again(monkeypatch):
    monkeypatch.setattr(pdfdocs, 'WAIT_SECONDS', .2)
    monkeypatch.setattr(pdfdocs._Document, 'text', lambda self, number: time.sleep(.6) or '')
    library = PdfLibrary()
    started = time.monotonic()
    with pytest.raises(PdfError, match='did not finish within'):
        await read(library, REPORT, first_page=1, last_page=1)
    with pytest.raises(PdfError, match='not tried again'):
        await read(library, REPORT, first_page=2)
    assert time.monotonic() - started < 2
    await asyncio.sleep(.6)  # the abandoned page ends; nothing is left running for the next test


async def test_downloaded_files_are_kept_by_content_and_checked_when_read(tmp_path):
    library = PdfLibrary(tmp_path / 'pdf-cache')
    record = library.put(REPORT, 'https://example.org/report.pdf')
    assert record['pdf_id'] == 'pdf-' + hashlib.sha256(REPORT).hexdigest()[:24] and record['bytes'] == len(REPORT)
    assert library.put(REPORT, 'https://example.org/again.pdf')['pdf_id'] == record['pdf_id']
    data, kept = library.get(record['pdf_id'])
    assert data == REPORT and kept['url'] == 'https://example.org/again.pdf'
    assert sorted(item.name for item in (tmp_path / 'pdf-cache').iterdir()) == [record['pdf_id'] + '.json', record['pdf_id'] + '.pdf']
    for bad in ('pdf-zz', '../' + record['pdf_id'], record['pdf_id'] + '/..', 7, 'pdf-' + '0' * 24):
        with pytest.raises(PdfError):
            library.get(bad)
    (tmp_path / 'pdf-cache' / (record['pdf_id'] + '.pdf')).write_bytes(REPORT + b'changed')
    with pytest.raises(PdfError, match='changed on disk'):
        library.get(record['pdf_id'])
    # Only the newest files are kept.
    monkeypatch_keep = pdfdocs.KEEP_FILES
    try:
        pdfdocs.KEEP_FILES = 2
        ids = [library.put(make_pdf([f'document {index}']), f'https://example.org/{index}.pdf')['pdf_id'] for index in range(4)]
    finally:
        pdfdocs.KEEP_FILES = monkeypatch_keep
    kept = {item.stem for item in (tmp_path / 'pdf-cache').glob('*.pdf')}
    assert ids[-1] in kept and len(kept) <= 3 and not list((tmp_path / 'pdf-cache').glob('*.tmp'))


def fetcher(tmp_path, port, limit=50 * 1024 * 1024):
    tools = WebTools({'search': {'enabled': True, 'provider': 'duckduckgo'}})
    tools.use_pdf_library(PdfLibrary(tmp_path / 'pdf-cache'), limit)
    return tools, f'http://reports.example:{port}'


async def test_web_fetch_keeps_a_pdf_and_returns_what_pdf_read_needs(tmp_path, monkeypatch):
    large = make_pdf(['\n'.join('x' * 60 for _ in range(30))] * 1200)  # well over the 1 MiB limit for ordinary pages

    async def handler(request):
        if request.path == '/report.pdf':
            return web.Response(body=REPORT, content_type='application/pdf')
        if request.path == '/download/outlook.pdf':  # a server that names no kind
            return web.Response(body=REPORT, content_type='application/octet-stream')
        if request.path == '/large.pdf':
            return web.Response(body=large, content_type='application/pdf')
        if request.path == '/denied.pdf':
            return web.Response(body=b'<html>Access Denied</html>', content_type='application/pdf')
        if request.path == '/locked.pdf':
            return web.Response(body=encrypted(REPORT, 'secret'), content_type='application/pdf')
        if request.path == '/restricted.pdf':  # what ministries publish: opens for anyone, changes restricted
            return web.Response(body=encrypted(REPORT), content_type='application/pdf')
        if request.path == '/page':
            return web.Response(text='x' * (2 * 1024 * 1024), content_type='text/plain')
        return web.Response(body=b'PK\x03\x04', content_type='application/zip')

    pin(monkeypatch)
    async with http_server(handler) as port:
        tools, base = fetcher(tmp_path, port)
        assert len(large) > tools.max_bytes
        result = await tools.execute('web_fetch', {'url': base + '/report.pdf'})
        assert result['pdf_id'] == 'pdf-' + hashlib.sha256(REPORT).hexdigest()[:24] and result['pdf_id'] in tools.pdf_ids
        assert result['url'] == base + '/report.pdf' and result['content_type'] == 'application/pdf'
        assert result['pages'] == 6 and result['outline'][0]['title'] == 'Executive summary' and 'pdf_read' in result['read_hint']
        assert 'source' not in result and 'text' not in result
        assert (await tools.execute('web_fetch', {'url': base + '/download/outlook.pdf'}))['pdf_id'] == result['pdf_id']
        assert (await tools.execute('web_fetch', {'url': base + '/large.pdf'}))['pages'] == 1200
        # What is not a readable PDF is refused and nothing of it is kept.
        with pytest.raises(WebToolError, match='not a PDF file'):
            await tools.execute('web_fetch', {'url': base + '/denied.pdf'})
        with pytest.raises(WebToolError, match='needs a password to open'):
            await tools.execute('web_fetch', {'url': base + '/locked.pdf'})
        assert len(tools.pdf_ids) == 2 and len(list((tmp_path / 'pdf-cache').glob('*.pdf'))) == 2
        restricted = await tools.execute('web_fetch', {'url': base + '/restricted.pdf'})
        assert restricted['pages'] == 6 and 'opens without a password' in restricted['protected']
        assert len(tools.pdf_ids) == 3
        # The larger limit is for PDFs only.
        with pytest.raises(WebToolError, match='exceeds the configured size limit'):
            await tools.execute('web_fetch', {'url': base + '/page'})
        with pytest.raises(WebToolError, match=r'and PDF files are supported .*; got application/zip'):
            await tools.execute('web_fetch', {'url': base + '/archive.zip'})
        # The human's limit: said with both sizes, before the file is downloaded.
        small, _ = fetcher(tmp_path, port, limit=1024 * 1024)
        with pytest.raises(WebToolError, match=r'larger than the limit in the settings \(\d+\.\d MB; limit 1\.0 MB\)') as caught:
            await small.execute('web_fetch', {'url': base + '/large.pdf'})
        assert 'It was not downloaded' in str(caught.value) and 'raise the PDF size limit' in str(caught.value)


async def test_a_page_lists_the_pdf_files_it_links_to_and_they_can_be_fetched(tmp_path, monkeypatch):
    """Real-machine case: the IMF eLibrary page of a report links to its chapters' PDF files; the address
    carries a query with colons, and the words of every link are the same."""
    state = '?t:state:client=AbC-dEf_123/456=='
    page = ('<html><body><h1>World Economic Outlook, October 2026</h1><p>Summary of the report.</p>'
            f'<a href="/supplemental/book/9798229055079/9798229055079.xml/WEOEA2026002-S001_UNIVERSAL_PDF.pdf{state}" '
            'title="Executive Summary">Download PDF</a>'
            f'<a href="/supplemental/book/9798229055079/9798229055079.xml/WEOEA2026002-S002_UNIVERSAL_PDF.pdf{state}#page=2">Download PDF</a>'
            '<a href="/display/book/9798229055079/CH001.xml">Chapter 1</a>'
            '<a href="https://other.example/files/annex.PDF">Annex</a>'
            '<a href="javascript:openPdf()">Open pdf viewer</a><a href="mailto:pdf@example.org">pdf by mail</a>'
            '<a href="https://user:secret@files.example/a.pdf">with credentials</a>'
            f'<a href="/supplemental/book/9798229055079/9798229055079.xml/WEOEA2026002-S001_UNIVERSAL_PDF.pdf{state}">again</a>'
            '<script>var a = "<a href=\\"/hidden.pdf\\">x</a>";</script>'
            + ''.join(f'<a href="/archive/{index}.pdf">Issue {index}</a>' for index in range(60)) + '</body></html>')

    async def handler(request):
        if request.path.endswith('S001_UNIVERSAL_PDF.pdf'):
            assert request.query_string == state[1:]
            return web.Response(body=REPORT, content_type='application/pdf')
        return web.Response(text=page, content_type='text/html')

    pin(monkeypatch)
    async with http_server(handler) as port:
        tools, base = fetcher(tmp_path, port)
        result = await tools.execute('web_fetch', {'url': base + '/display/book/9798229055079/9798229055079.xml'})
        assert 'World Economic Outlook, October 2026' in result['text'] and 'Download PDF' in result['text']
        links = result['pdf_links']
        first = f'{base}/supplemental/book/9798229055079/9798229055079.xml/WEOEA2026002-S001_UNIVERSAL_PDF.pdf{state}'
        assert links[0] == {'url': first, 'text': 'Executive Summary Download PDF'}
        assert links[1] == {'url': first.replace('S001', 'S002'), 'text': 'Download PDF'}  # the fragment is not part of an address
        assert links[2] == {'url': 'https://other.example/files/annex.PDF', 'text': 'Annex'}
        urls = [row['url'] for row in links]
        assert len(urls) == len(set(urls)) == 40 and not any('CH001' in url or 'secret' in url or 'hidden' in url for url in urls)
        assert '(23 more not listed)' in result['pdf_links_note'] and 'pdf_read' in result['pdf_links_note']
        assert len(json.dumps(result, ensure_ascii=False)) < 18000
        fetched = await tools.execute('web_fetch', {'url': links[0]['url']})
        assert fetched['pages'] == 6 and fetched['pdf_id'] in tools.pdf_ids
        # A page without such links says nothing about them.
        page = '<html><body><p>No files here.</p><a href="/about">About</a></body></html>'
        assert 'pdf_links' not in await tools.execute('web_fetch', {'url': base + '/plain'})


async def test_size_and_date_alone_tell_several_copies_of_a_report_apart(tmp_path, monkeypatch):
    """Real-machine case: the IEA's storage holds five files named WorldEnergyOutlook2025.pdf; the newest
    by Last-Modified is the current edition. Comparing them must not need five downloads of 15 MB."""
    copies = {'/assets/1438d3a5/WorldEnergyOutlook2025.pdf': ('Fri, 27 Nov 2025 09:12:00 GMT', REPORT),
              '/assets/0a1b2c3d/WorldEnergyOutlook2025.pdf': ('Wed, 12 Nov 2025 08:00:00 GMT', REPORT + b'%old')}
    asked = []

    async def handler(request):
        asked.append((request.method, request.path))
        if request.path not in copies:
            return web.Response(status=404)
        date, data = copies[request.path]
        return web.Response(body=b'' if request.method == 'HEAD' else data, content_type='application/pdf',
                            headers={'Last-Modified': date, 'Content-Length': str(len(data)), 'ETag': '"0x8DE2"'})

    pin(monkeypatch)
    async with http_server(handler) as port:
        tools, base = fetcher(tmp_path, port)
        facts = [await tools.execute('web_fetch', {'url': base + path, 'headers_only': True}) for path in copies]
        assert [(row['last_modified'], row['bytes']) for row in facts] == [(date, len(data)) for date, data in copies.values()]
        assert all(row['headers_only'] is True and row['content_type'] == 'application/pdf' and 'Nothing was downloaded' in row['note']
                   for row in facts)
        assert [method for method, _ in asked] == ['HEAD', 'HEAD'] and not tools.pdf_ids and not (tmp_path / 'pdf-cache').exists()
        # The one chosen is then downloaded, and its date stays with it.
        newest = await tools.execute('web_fetch', {'url': base + '/assets/1438d3a5/WorldEnergyOutlook2025.pdf'})
        assert newest['pages'] == 6 and newest['last_modified'] == 'Fri, 27 Nov 2025 09:12:00 GMT'
        with pytest.raises(WebToolError, match='HTTP 404'):
            await tools.execute('web_fetch', {'url': base + '/assets/none.pdf', 'headers_only': True})
        with pytest.raises(WebToolError, match='headers_only must be true or false'):
            await tools.execute('web_fetch', {'url': base + '/x.pdf', 'headers_only': 'yes'})


async def test_a_pdf_without_a_declared_length_stops_at_the_limit(tmp_path, monkeypatch):
    async def handler(request):
        response = web.StreamResponse(headers={'Content-Type': 'application/pdf'})
        await response.prepare(request)
        for _ in range(40):
            await response.write(b'%PDF-1.4\n' + b'0' * 65536)
        return response

    pin(monkeypatch)
    async with http_server(handler) as port:
        tools, base = fetcher(tmp_path, port, limit=1024 * 1024)
        with pytest.raises(WebToolError, match=r'larger than the limit in the settings \(limit 1\.0 MB\)'):
            await tools.execute('web_fetch', {'url': base + '/stream.pdf'})
    assert not (tmp_path / 'pdf-cache').exists()


async def test_an_agent_reads_a_saved_pdf_and_a_downloaded_one_and_the_run_remembers_the_pages(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.settings.value['search']['enabled'] = True
    engine.settings.value['limits']['max_file_bytes'] = 2048  # a PDF has its own limit
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='WEO の PDF を読んで要約を summary.md に書いて', max_workers=0)
        names = [tool['name'] for tool in engine._model_tools(run, pm)]
        policy = engine._policy(run, pm)
        assert {'pdf_read', 'pdf_search'} <= set(names) and 'PDF reports:' in policy and 'never read a long report from cover to cover' in policy
        assert 'official distribution site (for the IMF, the IMF eLibrary)' in policy and 'pdf_links' in policy
        # A refused report page: the publisher's own file is searched for, the newest of several copies chosen and said.
        assert 'filetype:pdf' in policy and "site:<the publisher's domain>" in policy and 'its content network or file storage counts' in policy
        assert 'web_fetch headers_only' in policy and 'newest by last_modified and size' in policy
        assert 'only when no official one can be had, and say so' in policy
        # Figures: found by search, cited with one form of page number and the words they come from, and looked up again.
        assert 'Find what you need with pdf_search' in policy and '"p. 26 (printed 10)"' in policy
        assert 'carries its page and the words it comes from' in policy
        assert 'look up each headline figure again with pdf_search' in policy and 'never as another number' in policy
        (work / 'weo.pdf').write_bytes(REPORT)
        assert len(REPORT) > 2048
        overview = await engine.execute_tool(run, pm, 'pdf_read', {'path': str(work / 'weo.pdf')})
        assert overview['pages'] == 6 and overview['source'] == str(work / 'weo.pdf')
        # Real-machine case: asked to download the report, a worker read a copy left in the folder by an earlier
        # test and nothing said so. Where a file came from is the application's knowledge.
        assert 'already in a read folder; it was not downloaded in this work' in overview['origin']
        assert 'If you read a PDF that was already in a folder instead of downloading it, say so' in policy
        # Figures a worker confirmed are taken over; a table holds no figure that nobody confirmed.
        assert 'does not mark as unconfirmed what a worker confirmed' in policy
        assert 'a row nobody confirmed is left out (or its cell says 未確認), never filled with a number' in policy
        page = await engine.execute_tool(run, pm, 'pdf_read', {'path': 'weo.pdf', 'first_page': 3, 'last_page': 3})
        assert 'Global growth is projected at 3.2 percent' in page['content'][0]['text']
        # The usual file rules apply: outside the read folders nothing is read.
        outside = tmp_path / 'elsewhere.pdf'
        outside.write_bytes(REPORT)
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'pdf_read', {'path': str(outside)})
        with pytest.raises(ValueError, match='exactly one of path'):
            await engine.execute_tool(run, pm, 'pdf_read', {'path': 'weo.pdf', 'pdf_id': 'pdf-' + '0' * 24})
        run['_config']['limits']['max_pdf_bytes'] = 1024 * 1024
        (work / 'huge.pdf').write_bytes(b'%PDF-1.4\n' + b'0' * (1024 * 1024))
        with pytest.raises(ValueError, match=r'a PDF may be up to 1\.0 MB \(the PDF size limit in the settings\)'):
            await engine.execute_tool(run, pm, 'pdf_read', {'path': 'huge.pdf'})
        # A downloaded PDF: only an id this work's web_fetch returned is accepted.
        url = 'https://www.example.org/pubs/outlook-2026.pdf'
        record = engine.pdf_library.put(REPORT, url)
        with pytest.raises(ValueError, match='fetch the PDF'):
            await engine.execute_tool(run, pm, 'pdf_read', {'pdf_id': record['pdf_id']})
        run['_web'].pdf_ids[record['pdf_id']] = record
        fetched = {'pdf_id': record['pdf_id'], 'url': url, **{key: value for key, value in overview.items() if key not in ('source', 'origin')}}
        engine._pages_note(run, 'web_fetch', {'url': url}, engine._urls_seen(run, fetched))
        assert run['_pages'][sources.normalize(url)] == ('pdf', '6 pages; no page read yet; title «World Outlook (test)»')
        result = await engine.execute_tool(run, pm, 'pdf_read', {'pdf_id': record['pdf_id'], 'first_page': 3, 'last_page': 5})
        assert result['url'] == url and [row['page'] for row in result['content']] == [3, 4, 5]
        await engine.execute_tool(run, pm, 'pdf_read', {'pdf_id': record['pdf_id'], 'first_page': 6, 'max_chars': 2000})
        found = await engine.execute_tool(run, pm, 'pdf_search', {'pdf_id': record['pdf_id'], 'query': 'percent'})  # finding is not reading
        assert found['mode'] == 'search' and found['pages_with_matches'] == 3 and found['url'] == url
        assert (await engine.execute_tool(run, pm, 'pdf_search', {'path': 'weo.pdf', 'query': 'Global growth'}))['matches'][0]['page'] == 3
        for bad in ({'pdf_id': record['pdf_id']}, {'pdf_id': record['pdf_id'], 'query': 'x', 'offset': 3},
                    {'pdf_id': record['pdf_id'], 'find': 'x'}):
            with pytest.raises(ValueError):
                await engine.execute_tool(run, pm, 'pdf_search', bad)
        with pytest.raises(ValueError, match='pdf_read takes'):
            await engine.execute_tool(run, pm, 'pdf_read', {'path': 'weo.pdf', 'find': 'percent'})
        # Page 5 holds no text, so it does not count as read.
        assert run['_pages'][sources.normalize(url)][1].startswith('6 pages; pages read: 3-4, 6; title')
        text = f'# 要約\n世界の成長率は 3.2%（p. 3）。\n出典: {url}\n'
        await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'summary.md'), 'text': text, 'expected_sha256': 'missing'})
        pm.pending.clear()
        review = await engine.execute_tool(run, pm, 'finish_work', {'summary': '要約を保存しました。'})
        assert review['ok'] is False and review['code'] == 'sources_review'
        assert f'{url} - downloaded PDF, 6 pages; pages read: 3-4, 6' in review['error']
        assert 'only pages listed as read can be cited' in review['error']
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '要約を保存しました。'})
        assert f'{url} — 取得した PDF（6 pages; pages read: 3-4, 6' in done['summary']
        # Under the report: which PDFs were read, and which of them this work downloaded.
        assert '【アプリの確認】この作業で読んだ PDF:' in done['summary']
        assert f"- {work / 'weo.pdf'} — 読み取りフォルダーに既にあったファイル（この作業ではダウンロードしていません）" in done['summary']
        assert f'- {url} — この作業でダウンロード' in done['summary']
    finally:
        await engine.close()


async def test_pdf_read_is_offered_only_where_a_pdf_can_come_from(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.settings.value['paths'] = {'read_roots': [], 'write_roots': [], 'deny_roots': []}
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0)
        assert not {'pdf_read', 'pdf_search'} & {tool['name'] for tool in engine._model_tools(run, pm)}
        assert 'PDF reports:' not in engine._policy(run, pm)
        with pytest.raises(ValueError, match='読み取りを許可したフォルダー'):
            await engine.execute_tool(run, pm, 'pdf_read', {'path': 'x.pdf'})
    finally:
        await engine.close()
    # With a read folder and no web: the tool and how to read, without the part about fetching.
    (tmp_path / 'second').mkdir()
    engine, work = configured(tmp_path / 'second', None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0)
        assert 'pdf_read' in [tool['name'] for tool in engine._model_tools(run, pm)]
        # Work that has nothing to do with a PDF does not carry the guidance; it joins once a PDF is opened.
        assert 'PDF reports:' not in engine._policy(run, pm)
        (work / 'report.pdf').write_bytes(REPORT)
        await engine.execute_tool(run, pm, 'pdf_read', {'path': 'report.pdf'})
        policy = engine._policy(run, pm)
        assert 'PDF reports:' in policy and 'eLibrary' not in policy and 'web_fetch its PDF address' not in policy
        # Or once the human names one, at the start or later.
        named, lead = await start(engine, task='報告書.PDF を要約して', max_workers=0)
        assert 'PDF reports:' in engine._policy(named, lead)
        later, lead = await start(engine, max_workers=0)
        engine._pdf_mentioned(later, 'さっきの pdf も見てください')
        assert 'PDF reports:' in engine._policy(later, lead)
    finally:
        await engine.close()


def test_the_pdf_size_limit_is_a_setting_with_bounds():
    assert DEFAULT['limits']['max_pdf_bytes'] == 50 * 1024 * 1024
    raw = json.loads(json.dumps(DEFAULT))
    del raw['limits']['max_pdf_bytes']  # settings saved before this version
    assert validate_settings(raw, check_paths=False)['limits']['max_pdf_bytes'] == 50 * 1024 * 1024
    for bad in (1000, 201 * 1024 * 1024, '50MB'):
        raw['limits']['max_pdf_bytes'] = bad
        with pytest.raises(ValueError):
            validate_settings(raw, check_paths=False)
