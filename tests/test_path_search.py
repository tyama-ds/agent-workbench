"""Bounded name searches use the same read permissions as file tools."""
import json
import os
import subprocess
from pathlib import Path

import pytest

import workbench.harness as harness_module
from workbench.harness import HarnessError, PathHarness, ToolExecutor
from test_engine import ScriptClient, configured, start


def names(result):
    return {item["name"] for item in result["matches"]}


def test_name_search_is_recursive_literal_unicode_and_does_not_read_contents(tmp_path, monkeypatch):
    folder = tmp_path / "資料-REPORT"
    folder.mkdir()
    (folder / "Report-日本語.docx").write_bytes(b"\x00binary")
    (tmp_path / "unrelated.txt").write_text("REPORT", encoding="utf-8")
    harness = PathHarness([str(tmp_path)], [])
    monkeypatch.setattr(harness, "read_bytes", lambda *_: pytest.fail("Name search must not read file contents"))
    result = harness.search_paths(str(tmp_path), "report")
    assert names(result) == {"資料-REPORT", "Report-日本語.docx"}
    assert {item["kind"] for item in result["matches"]} == {"file", "directory"}
    assert not result["truncated"] and result["entries_examined"] == 3
    assert names(harness.search_paths(str(tmp_path), "REPORT", case_sensitive=True)) == {"資料-REPORT"}
    assert names(harness.search_paths(str(tmp_path), "日本語", kind="file")) == {"Report-日本語.docx"}
    assert names(harness.search_paths(str(tmp_path), "report", kind="directory")) == {"資料-REPORT"}
    assert harness.search_paths(str(tmp_path), "*.docx")["matches"] == []


def test_depth_zero_returns_direct_children_and_marks_unsearched_subtrees(tmp_path):
    folder = tmp_path / "match-folder"
    folder.mkdir()
    (folder / "match.txt").write_text("data")
    harness = PathHarness([str(tmp_path)], [])
    result = harness.search_paths(str(tmp_path), "match", max_depth=0)
    assert names(result) == {"match-folder"}
    assert result["truncated"] and result["entries_examined"] == 1
    nested = harness.search_paths(str(tmp_path), "match", max_depth=1)
    assert names(nested) == {"match-folder", "match.txt"} and not nested["truncated"]


def test_result_and_entry_budgets_bound_large_directories(tmp_path):
    for index in range(40):
        (tmp_path / f"match-{index}.txt").write_text("")
    harness = PathHarness([str(tmp_path)], [])
    result = harness.search_paths(str(tmp_path), "match", max_results=3)
    assert len(result["matches"]) == result["entries_examined"] == 3
    assert result["truncated"]
    result = harness.search_paths(str(tmp_path), "absent", max_entries=4)
    assert not result["matches"] and result["entries_examined"] == 4
    assert result["truncated"]


def test_search_response_has_a_utf8_byte_budget(tmp_path, monkeypatch):
    for index in range(20):
        (tmp_path / (f"{index}-" + "資料" * 25 + ".txt")).write_text("")
    monkeypatch.setattr(harness_module, "MAX_OUTPUT", 2000)
    result = PathHarness([str(tmp_path)], []).search_paths(str(tmp_path), "資料", max_results=500)
    assert result["truncated"] and 0 < len(result["matches"]) < 20
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) < 2000


def test_denied_entries_consume_budget_without_exposing_their_names(tmp_path):
    denied = []
    for index in range(12):
        folder = tmp_path / f"private-match-{index}"
        folder.mkdir()
        (folder / "secret-match.txt").write_text("private")
        denied.append(str(folder))
    result = PathHarness([str(tmp_path)], [], denied).search_paths(str(tmp_path), "match", max_entries=3)
    assert result == {"matches": [], "truncated": True, "entries_examined": 3, "skipped": 3}
    assert "private-match" not in json.dumps(result)


def test_search_cannot_use_write_only_or_outside_scope_and_skips_hard_links(tmp_path):
    root, outside = tmp_path / "allowed", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret-match.txt").write_text("private")
    with pytest.raises(HarnessError):
        PathHarness([], [str(root)]).search_paths(str(root), "match")
    harness = PathHarness([str(root)], [])
    with pytest.raises(HarnessError):
        harness.search_paths(str(outside), "match")
    with pytest.raises(HarnessError):
        harness.search_paths("../outside", "match")
    (root / "match.txt").write_text("original")
    os.link(root / "match.txt", root / "match-hardlink.txt")
    result = harness.search_paths(str(root), "match")
    assert result["matches"] == [] and result["skipped"] == 2


@pytest.mark.parametrize("option,value", [
    ("max_results", 0), ("max_results", 501), ("max_results", True),
    ("max_entries", 0), ("max_entries", 20001), ("max_depth", -1), ("max_depth", 33),
    ("case_sensitive", "false"), ("kind", "all"), ("kind", []),
])
def test_search_rejects_invalid_limits_and_modes(tmp_path, option, value):
    with pytest.raises(HarnessError):
        PathHarness([str(tmp_path)], []).search_paths(str(tmp_path), "match", **{option: value})


@pytest.mark.parametrize("query", ["", "x" * 501, "\0", "\ud800", None])
def test_search_rejects_invalid_queries(tmp_path, query):
    with pytest.raises(HarnessError):
        PathHarness([str(tmp_path)], []).search_paths(str(tmp_path), query)


def test_search_rechecks_queued_directory_after_it_disappears(tmp_path, monkeypatch):
    folder = tmp_path / "match-folder"
    folder.mkdir()
    harness = PathHarness([str(tmp_path)], [])
    original = os.scandir

    class RemovingIterator:
        def __enter__(self):
            self.iterator = original(tmp_path)
            return self.iterator

        def __exit__(self, *args):
            self.iterator.close()
            folder.rmdir()

    monkeypatch.setattr(harness_module.os, "scandir", lambda path: RemovingIterator() if Path(path) == tmp_path else original(path))
    result = harness.search_paths(str(tmp_path), "absent")
    assert not result["matches"] and result["skipped"] == 1


def test_search_skips_symlink_directory_without_following_it(tmp_path):
    root, outside = tmp_path / "allowed", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret-match.txt").write_text("private")
    try:
        (root / "match-shortcut").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symlink creation")
    result = PathHarness([str(root)], []).search_paths(str(root), "match")
    assert result["matches"] == [] and result["skipped"] == 1


@pytest.mark.skipif(os.name != "nt", reason="Native Windows junction regression")
def test_search_skips_windows_junction(tmp_path):
    root, outside = tmp_path / "allowed", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret-match.txt").write_text("private")
    link = root / "match-junction"
    subprocess.run([os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"), "/d", "/c", "mklink", "/J", str(link), str(outside)],
                   check=True, capture_output=True, creationflags=0x08000000)
    try:
        result = PathHarness([str(root)], []).search_paths(str(root), "match")
        assert result["matches"] == [] and result["skipped"] == 1
    finally:
        os.rmdir(link)  # Remove this known junction itself, never its target.


async def test_engine_name_and_content_search_preserve_private_state_deny(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.settings.value["paths"]["read_roots"] = [str(tmp_path)]
    engine.kick = lambda agent: None
    (engine.settings.directory / "private-match.txt").write_text("needle")
    (work / "public-match.txt").write_text("needle\n本文", encoding="utf-8")
    try:
        run, agent = await start(engine)
        paths = await engine.execute_tool(run, agent, "search_paths", {"path": str(tmp_path), "query": "match"})
        assert names(paths) == {"public-match.txt"}
        text = await engine.execute_tool(run, agent, "search_text", {"path": str(work), "query": "本文"})
        assert text["matches"][0]["line"] == 2
        assert not agent.output_receipts
    finally:
        await engine.close()


async def test_search_tool_dispatch_and_schema(tmp_path):
    (tmp_path / "Report.txt").write_text("unread")
    tools = ToolExecutor(PathHarness([str(tmp_path)], []))
    spec = next(tool for tool in tools.schemas() if tool["name"] == "search_paths")
    assert spec["parameters"]["required"] == ["path", "query"]
    result = await tools.execute("search_paths", {"path": str(tmp_path), "query": "REPORT", "kind": "file", "max_depth": 0})
    assert names(result) == {"Report.txt"} and not result["truncated"]
    with pytest.raises(HarnessError):
        await tools.execute("search_paths", {"path": str(tmp_path), "query": "report", "shell": True})
