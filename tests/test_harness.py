"""Folder policy and Office round trips; no Office app or shell tool is invoked."""
import asyncio
import hashlib
import io
import os
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.harness import HarnessError, PathHarness, ToolExecutor, _check_package


@pytest.fixture
def folders(tmp_path):
    read, write, secret, outside = (tmp_path / name for name in ("read", "write", "secret", "outside"))
    for path in (read, write, secret, outside):
        path.mkdir()
    return read, write, secret, outside


def execute(executor, name, **args):
    return asyncio.run(executor.execute(name, args))


def test_read_write_and_deny_are_independent_with_optimistic_hash(folders):
    read, write, secret, outside = folders
    (read / "input.txt").write_text("hello", encoding="utf-8")
    (secret / "private.txt").write_text("secret", encoding="utf-8")
    harness = PathHarness([str(read), str(secret)], [str(write)], [str(secret)])
    tools = ToolExecutor(harness)
    assert execute(tools, "read_text", path=str(read / "input.txt"))["text"] == "hello"
    for path in (secret / "private.txt", outside / "unknown", write / "output.txt"):
        with pytest.raises(HarnessError):
            execute(tools, "read_text", path=str(path))
    with pytest.raises(HarnessError):
        execute(tools, "write_text", path=str(read / "input.txt"), text="changed", expected_sha256=hashlib.sha256(b"hello").hexdigest())
    result = execute(tools, "write_text", path=str(write / "output.txt"), text="日本語", expected_sha256="missing")
    assert (write / "output.txt").read_text(encoding="utf-8") == "日本語"
    assert (write / "output.txt").stat().st_nlink == 1
    with pytest.raises(HarnessError, match="changed"):
        execute(tools, "write_text", path=str(write / "output.txt"), text="oops", expected_sha256="missing")
    execute(tools, "write_text", path=str(write / "output.txt"), text="next", expected_sha256=result["sha256"])
    assert not list(write.glob(".workbench-*"))


@pytest.mark.parametrize("path", ["../escape", "folder/../escape", "C:relative", "file.txt:stream", "NUL", "COM1.txt", "trailing.", "trailing ", "\\\\server\\share\\file", "//server/share", "\\\\?\\C:\\file", "file*", "x\x00y"])
def test_unsafe_path_spellings_are_rejected(tmp_path, path):
    harness = PathHarness([str(tmp_path)], [str(tmp_path)])
    with pytest.raises(HarnessError):
        harness.resolve(path, write=True, must_exist=False)


def test_hardlinks_are_rejected_and_not_listed(tmp_path):
    source = tmp_path / "first.txt"
    source.write_text("private", encoding="utf-8")
    os.link(source, tmp_path / "second.txt")
    harness = PathHarness([str(tmp_path)], [str(tmp_path)])
    for name in ("first.txt", "second.txt"):
        with pytest.raises(HarnessError, match="hard link"):
            harness.read_bytes(name)
    assert harness.list_directory(str(tmp_path))["entries"] == []


def test_symlinks_cannot_escape_or_be_configured_as_roots(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("private", encoding="utf-8")
    try:
        (root / "shortcut").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symlink creation")
    harness = PathHarness([str(root)], [str(root)])
    with pytest.raises(HarnessError, match="reparse"):
        harness.read_bytes(str(root / "shortcut" / "secret.txt"))
    with pytest.raises(HarnessError):
        PathHarness([str(root / "shortcut")], [])


@pytest.mark.skipif(os.name != "nt", reason="Native Windows junction regression")
def test_windows_junction_is_rejected(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "junction"
    subprocess.run([os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"), "/d", "/c", "mklink", "/J", str(link), str(outside)],
                   check=True, capture_output=True, creationflags=0x08000000)
    try:
        harness = PathHarness([str(root)], [str(root)])
        with pytest.raises(HarnessError, match="reparse"):
            harness.resolve(str(link / "new.txt"), write=True, must_exist=False)
    finally:
        os.rmdir(link)  # Removes this verified junction itself, not its target.


def test_patch_unique_match_hash_bounds_and_search(tmp_path):
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)], max_file_bytes=100))
    path = str(tmp_path / "input.txt")
    result = execute(tools, "write_text", path=path, text="one\ntwo\nthree", expected_sha256="missing")
    changed = execute(tools, "patch_text", path=path, find="two", replace="日本語", expected_sha256=result["sha256"])
    assert execute(tools, "search_text", path=str(tmp_path), query="日本語")["matches"][0]["line"] == 2
    with pytest.raises(HarnessError):
        execute(tools, "patch_text", path=path, find="absent", replace="x", expected_sha256=changed["sha256"])
    with pytest.raises(HarnessError):
        execute(tools, "write_text", path=path, text="a" * 101, expected_sha256=changed["sha256"])
    assert "日本語" in Path(path).read_text(encoding="utf-8")
    assert all("shell" not in item["name"] and "command" not in item["name"] for item in tools.schemas())
    with pytest.raises(HarnessError):
        execute(tools, "read_text", path=path, unexpected=True)


def test_docx_paragraph_and_table_edits_retain_run_format(tmp_path):
    from docx import Document
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    path = str(tmp_path / "report.docx")
    created = execute(tools, "docx_write", path=path, expected_sha256="missing", paragraphs=["Title", "Before"], tables=[[["A", "B"], ["C", "D"]]])
    doc = Document(path)
    doc.paragraphs[1].runs[0].bold = True
    doc.save(path)
    expected = execute(tools, "file_hash", path=path)["sha256"]
    execute(tools, "docx_edit", path=path, expected_sha256=expected, operations=[
        {"type": "replace_paragraph", "index": 1, "text": "After"},
        {"type": "replace_cell", "table": 0, "row": 1, "column": 0, "text": "変更"},
        {"type": "append_paragraph", "text": "End"}])
    read = execute(tools, "docx_read", path=path)
    assert [row["text"] for row in read["paragraphs"]] == ["Title", "After", "End"]
    assert read["tables"][0][1][0] == "変更"
    assert Document(path).paragraphs[1].runs[0].bold
    with pytest.raises(HarnessError):
        execute(tools, "docx_edit", path=path, expected_sha256=created["sha256"], operations=[{"type": "append_paragraph", "text": "stale"}])


def test_xlsx_cells_formulas_and_external_formula_guard(tmp_path):
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    path = str(tmp_path / "data.xlsx")
    created = execute(tools, "xlsx_write", path=path, expected_sha256="missing", cells=[{"sheet": "Sheet", "cell": "A1", "value": "Name"}, {"sheet": "Sheet", "cell": "B2", "value": -7}])
    read = execute(tools, "xlsx_read", path=path, range="A1:B2")
    assert read["cells"][-1]["value"] == -7
    for bad in ("=1+2", "+SUM(A1)", " @test"):
        with pytest.raises(HarnessError, match="Formula"):
            execute(tools, "xlsx_write", path=path, expected_sha256=created["sha256"], cells=[{"sheet": "Sheet", "cell": "A2", "value": bad}])
    allowed = execute(tools, "xlsx_write", path=path, expected_sha256=created["sha256"], allow_formulas=True, cells=[{"sheet": "Sheet", "cell": "A2", "value": "=SUM(B2,2)"}])
    assert any(row["formula"] for row in execute(tools, "xlsx_read", path=path, range="A1:B2")["cells"])
    with pytest.raises(HarnessError, match="External"):
        execute(tools, "xlsx_write", path=path, expected_sha256=allowed["sha256"], allow_formulas=True, cells=[{"sheet": "Sheet", "cell": "A2", "value": '=WEBSERVICE("https://example.com")'}])


def test_pptx_create_read_replace(tmp_path):
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    path = str(tmp_path / "slides.pptx")
    created = execute(tools, "pptx_write", path=path, expected_sha256="missing", slides=[{"title": "First", "body": ["One", "Two"]}])
    read = execute(tools, "pptx_read", path=path)
    assert read["slides"][0]["shapes"][0]["paragraphs"] == ["First"]
    execute(tools, "pptx_edit", path=path, expected_sha256=created["sha256"], operations=[{"slide": 0, "shape": 0, "paragraph": 0, "text": "Updated"}])
    assert execute(tools, "pptx_read", path=path)["slides"][0]["shapes"][0]["paragraphs"] == ["Updated"]


@pytest.mark.parametrize("entry,payload", [("word/vbaProject.bin", b"x"), ("xl/externalLinks/externalLink1.xml", b"<x/>"),
    ("word/_rels/document.xml.rels", b'<Relationships><Relationship TargetMode="External" Target="https://example.com"/></Relationships>'),
    ("word/document.xml", b'<!DOCTYPE x [<!ENTITY e "bad">]><x/>'), ("../escape", b"x")])
def test_unsafe_office_packages_rejected(entry, payload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry, payload)
    with pytest.raises(HarnessError):
        _check_package(buffer.getvalue(), 10 * 1024 * 1024)


def test_zip_bomb_and_old_office_extensions_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"a" * 1000000)
    with pytest.raises(HarnessError, match="expansion"):
        _check_package(buffer.getvalue(), 10 * 1024 * 1024)
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    for suffix, name in ((".doc", "docx_read"), (".docm", "docx_read"), (".xls", "xlsx_read"), (".xlsm", "xlsx_read"), (".ppt", "pptx_read")):
        with pytest.raises(HarnessError, match="Only"):
            execute(tools, name, path=str(tmp_path / ("old" + suffix)))


def test_cancelled_file_operation_drains_thread_before_releasing_caller_lock(tmp_path, monkeypatch):
    async def run():
        tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
        entered, release = threading.Event(), threading.Event()
        original = tools._execute
        def delayed(name, args):
            entered.set()
            assert release.wait(5)
            return original(name, args)
        monkeypatch.setattr(tools, "_execute", delayed)
        lock = asyncio.Lock()
        async def locked_write():
            async with lock:
                await tools.execute("write_text", {"path": str(tmp_path / "delayed.txt"), "text": "settled", "expected_sha256": "missing"})
        operation = asyncio.create_task(locked_write())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            operation.cancel()
            await asyncio.sleep(.02)
            assert lock.locked() and not operation.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
            assert not lock.locked() and (tmp_path / "delayed.txt").read_text() == "settled"
        finally:
            release.set()
            await asyncio.gather(operation, return_exceptions=True)
    asyncio.run(run())


def test_office_read_hash_describes_same_snapshot_even_if_file_changes(tmp_path, monkeypatch):
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    path = tmp_path / "snapshot.docx"
    created = execute(tools, "docx_write", path=str(path), paragraphs=["Original snapshot"], expected_sha256="missing")
    original = tools.harness.read_bytes
    def changed_after_read(value):
        data = original(value)
        path.write_bytes(b"Changed after snapshot was read")
        return data
    monkeypatch.setattr(tools.harness, "read_bytes", changed_after_read)
    result = execute(tools, "docx_read", path=str(path))
    assert result["paragraphs"][0]["text"] == "Original snapshot"
    assert result["sha256"] == created["sha256"]


@pytest.mark.parametrize("formula", ['=WEBSERVICE("https://example.com")', '=HYPERLINK("file:///secret")', "='cmd'|' /C calc'!A0", '=INDIRECT("[remote.xlsx]Sheet1!A1")', '=REGISTER.ID("module","function")'])
def test_existing_and_new_active_formulas_are_rejected_even_with_explicit_formula_flag(tmp_path, formula):
    import openpyxl
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    path = tmp_path / "active.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = formula
    workbook.save(path)
    workbook.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for name, args in (("xlsx_read", {}), ("xlsx_write", {"expected_sha256": digest, "allow_formulas": True, "cells": [{"sheet": "Sheet", "cell": "B1", "value": 1}]})):
        with pytest.raises(HarnessError, match="External"):
            execute(tools, name, path=str(path), **args)
    with pytest.raises(HarnessError, match="External"):
        execute(tools, "xlsx_write", path=str(tmp_path / "new.xlsx"), expected_sha256="missing", allow_formulas=True,
                cells=[{"sheet": "Sheet", "cell": "A1", "value": formula}])


@pytest.mark.parametrize("payload", [
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:instrText>DDEAUTO cmd /c calc</w:instrText></w:document>',
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:fldSimple w:instr="INCLUDETEXT secret.txt"/></w:document>',
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:instrText>DD</w:instrText><w:instrText>EAUTO cmd /c calc</w:instrText></w:document>',
    '<!DOCTYPE x [<!ENTITY e "bad">]><x/>'.encode("utf-16"),
])
def test_active_word_fields_and_utf16_entities_are_rejected(payload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", payload)
    with pytest.raises(HarnessError):
        _check_package(buffer.getvalue(), 10 * 1024 * 1024)


@pytest.mark.parametrize('payload', [b'find\xff\xfe', b'find\x00tail', b'PK\x03\x04\x00find', b'\xff\xfeF\x00i\x00n\x00d\x00'])
@pytest.mark.parametrize('tool', ['write_text', 'patch_text'])
def test_text_mutations_reject_binary_original_without_changes(tmp_path, payload, tool):
    path = tmp_path / 'ordinary.txt'  # Content, not a misleading extension, decides.
    path.write_bytes(payload)
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    args = {'text': 'replacement'} if tool == 'write_text' else {'find': 'find', 'replace': 'replacement'}
    with pytest.raises(HarnessError, match='UTF-8|Binary'):
        execute(tools, tool, path=str(path), expected_sha256=hashlib.sha256(payload).hexdigest(), **args)
    assert path.read_bytes() == payload
    assert not list(tmp_path.glob('.workbench-*'))


@pytest.mark.parametrize('payload', [b'', b'find\r\nnext', 'find 日本語 😀'.encode(), b'\xef\xbb\xbffind\r\nnext'])
def test_write_text_validates_write_only_targets_without_granting_read(tmp_path, payload):
    path = tmp_path / 'text.data'
    path.write_bytes(payload)
    tools = ToolExecutor(PathHarness([], [str(tmp_path)]))
    with pytest.raises(HarnessError, match='read folders'):
        execute(tools, 'read_text', path=str(path))
    result = execute(tools, 'write_text', path=str(path), text='更新 😀', expected_sha256=hashlib.sha256(payload).hexdigest())
    assert path.read_bytes() == '更新 😀'.encode()
    assert result['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not list(tmp_path.glob('.workbench-*'))


def test_write_only_binary_target_is_still_rejected(tmp_path):
    path = tmp_path / 'data.bin'
    original = b'\x00binary'
    path.write_bytes(original)
    tools = ToolExecutor(PathHarness([], [str(tmp_path)]))
    with pytest.raises(HarnessError, match='Binary'):
        execute(tools, 'write_text', path=str(path), text='', expected_sha256=hashlib.sha256(original).hexdigest())
    assert path.read_bytes() == original


def test_patch_preserves_bom_and_crlf(tmp_path):
    path = tmp_path / 'bom.txt'
    original = b'\xef\xbb\xbffind\r\nnext\r\n'
    path.write_bytes(original)
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    execute(tools, 'patch_text', path=str(path), find='find', replace='日本語', expected_sha256=hashlib.sha256(original).hexdigest())
    assert path.read_bytes() == b'\xef\xbb\xbf' + '日本語\r\nnext\r\n'.encode()
    assert execute(tools, 'read_text', path=str(path))['text'] == '日本語\r\nnext\r\n'


@pytest.mark.parametrize('payload', [b'\xff', b'new\x00text'])
def test_text_write_boundary_checks_output_before_creation(tmp_path, payload):
    harness = PathHarness([], [str(tmp_path)])
    with pytest.raises(HarnessError, match='UTF-8|Binary'):
        harness.write_bytes('new.txt', payload, 'missing', text_only=True)
    assert list(tmp_path.iterdir()) == []


def test_text_write_rechecks_hash_after_temporary_write(tmp_path, monkeypatch):
    path = tmp_path / 'file.txt'
    path.write_bytes(b'original')
    harness = PathHarness([], [str(tmp_path)])
    fsync = os.fsync
    def external_edit(fd):
        fsync(fd)
        path.write_bytes(b'\x00changed by external editor')
    monkeypatch.setattr(os, 'fsync', external_edit)
    with pytest.raises(HarnessError, match='changed before replacement'):
        harness.write_bytes(str(path), b'replacement', hashlib.sha256(b'original').hexdigest(), text_only=True)
    assert path.read_bytes() == b'\x00changed by external editor'
    assert not list(tmp_path.glob('.workbench-*'))


def test_text_atomic_replace_failure_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / 'file.txt'
    path.write_bytes(b'original')
    def failed_replace(*args):
        raise OSError('simulated replace failure')
    monkeypatch.setattr(os, 'replace', failed_replace)
    tools = ToolExecutor(PathHarness([], [str(tmp_path)]))
    with pytest.raises(OSError, match='simulated'):
        execute(tools, 'write_text', path=str(path), text='replacement', expected_sha256=hashlib.sha256(b'original').hexdigest())
    assert path.read_bytes() == b'original'
    assert not list(tmp_path.glob('.workbench-*'))


@pytest.mark.parametrize('payload', [b'%PDF-1.4\nfind\n%%EOF\n', b'\xef\xbb\xbf \n%PDF-1.4\nfind', b'GIF89afind', b'find\x01tail', b'find\x7ftail', 'find\u0085tail'.encode(), b'BZhfind', b'RIFFfind'])
@pytest.mark.parametrize('tool', ['write_text', 'patch_text'])
def test_text_mutations_reject_disguised_formats_and_controls(tmp_path, payload, tool):
    path = tmp_path / 'renamed.txt'
    path.write_bytes(payload)
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    args = {'text': 'safe'} if tool == 'write_text' else {'find': 'find', 'replace': 'safe'}
    with pytest.raises(HarnessError, match='binary|Binary'):
        execute(tools, tool, path=str(path), expected_sha256=hashlib.sha256(payload).hexdigest(), **args)
    assert path.read_bytes() == payload
    assert not list(tmp_path.glob('.workbench-*'))


@pytest.mark.parametrize('name', ['empty.docx', 'empty.PDF', 'empty.XLSX', 'empty.pptx', 'empty.GIF', 'empty.zip'])
@pytest.mark.parametrize('exists', [False, True])
def test_text_mutation_cannot_create_or_replace_known_format(tmp_path, name, exists):
    path = tmp_path / name
    if exists:
        path.write_bytes(b'')
    tools = ToolExecutor(PathHarness([], [str(tmp_path)]))
    with pytest.raises(HarnessError, match='extension'):
        execute(tools, 'write_text', path=str(path), text='safe', expected_sha256=hashlib.sha256(b'').hexdigest() if exists else 'missing')
    assert path.exists() == exists
    if exists:
        assert path.read_bytes() == b''
    assert not list(tmp_path.glob('.workbench-*'))


@pytest.mark.parametrize('payload', ['%PDF-1.4\n%%EOF', 'GIF89a', 'text\x01', 'text\u0085'])
def test_text_mutation_rejects_known_format_or_controls_in_new_output(tmp_path, payload):
    tools = ToolExecutor(PathHarness([], [str(tmp_path)]))
    with pytest.raises(HarnessError, match='binary|Binary'):
        execute(tools, 'write_text', path='new.txt', text=payload, expected_sha256='missing')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('name,text', [('data.csv', 'a,b\r\n1,2'), ('data.json', '{"a":1}'), ('drawing.svg', '<svg></svg>'), ('script', '#!/bin/sh\necho hello'), ('empty.txt', '')])
def test_text_mutation_keeps_ordinary_text_formats(tmp_path, name, text):
    tools = ToolExecutor(PathHarness([], [str(tmp_path)]))
    execute(tools, 'write_text', path=name, text=text, expected_sha256='missing')
    assert (tmp_path / name).read_bytes() == text.encode()


def test_patch_cannot_erase_signature_to_bypass_original_validation(tmp_path):
    original = b'%PDF-1.4\nfind\n%%EOF\n'
    path = tmp_path / 'renamed.txt'
    path.write_bytes(original)
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    with pytest.raises(HarnessError, match='binary'):
        execute(tools, 'patch_text', path=str(path), find=original.decode(), replace='safe text', expected_sha256=hashlib.sha256(original).hexdigest())
    assert path.read_bytes() == original
    assert not list(tmp_path.glob('.workbench-*'))


def test_patch_cannot_edit_known_document_extension(tmp_path):
    path = tmp_path / 'damaged.PDF'
    path.write_bytes(b'find')
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    with pytest.raises(HarnessError, match='extension'):
        execute(tools, 'patch_text', path=str(path), find='find', replace='safe', expected_sha256=hashlib.sha256(b'find').hexdigest())
    assert path.read_bytes() == b'find'
