"""Offline synthetic comparisons; no downloads, binary execution or legal clearance."""
import copy
import hashlib
import json
from pathlib import Path
import re

import pytest

from tools import build_portable as builder


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def evidence_case(tmp_path, monkeypatch):
    notices = tmp_path / "notices"
    notices.mkdir()
    bundle = tmp_path / "bundle"
    (bundle / "_internal").mkdir(parents=True)
    # Deliberately no OpenSSL or Microsoft CRT label in this synthetic text.
    text = b"Python Software Foundation\r\nUnlabelled license A\r\nDistributable terms B\r\n"
    (notices / "CPython-LICENSE.txt").write_bytes(text)
    native = {"libssl-3.dll": b"synthetic ssl", "_ssl.pyd": b"synthetic extension",
              "VCRUNTIME140.dll": b"synthetic runtime", "ucrtbase.dll": b"unindexed runtime",
              "api-ms-win-crt-runtime-l1-1-0.dll": b"unindexed forwarder"}
    for name, data in native.items():
        (bundle / "_internal" / name).write_bytes(data)
    identity = {"implementation": "CPython", "version": "3.13.15", "platform": "win32", "architecture": "x64"}
    observations = {"OpenSSL": "synthetic version", "zlib_compiled": "1.3.1", "zlib_runtime": "1.3.1"}
    components = {}
    for name, value in (("OpenSSL", b"Unlabelled license A"), ("Microsoft CRT", b"Distributable terms B"),
                        ("zlib", None), ("liblzma/XZ", None)):
        entry = {"component_version": "synthetic", "source_notice": {"url": "https://example.test/notice", "sha256": "b" * 64},
                 "notice_observation": "not_in_copied_notice", "interpretation": "Observation, not a legal determination."}
        if value is not None:
            entry["notice_span"] = {"byte_start": text.index(value), "byte_length": len(value), "sha256": digest(value)}
        components[name] = entry
    reference = {"schema_version": 1, "identity": identity, "runtime_observations": observations,
                 "scope": "Synthetic reviewed fixture, not clearance.",
                 "archive": {"url": "https://example.test/runtime.zip", "sha256": "a" * 64},
                 "notice": {"sha256": digest(text), "size": len(text)}, "components": components,
                 "native_files": [{"bundle_path": "_internal/" + name.lower(), "archive_path": name.lower(),
                                   "size": len(data), "sha256": digest(data)}
                                  for name, data in native.items() if name not in {
                                      "ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll"}]}
    index = tmp_path / "evidence.json"
    def pin(value):
        data = (json.dumps(value) + "\n").encode()
        index.write_bytes(data)
        monkeypatch.setattr(builder, "CPYTHON_EVIDENCE_SHA256", digest(data))
    pin(reference)
    monkeypatch.setattr(builder, "CPYTHON_EVIDENCE", index)
    inventory = {"evaluation_only": True, "distribution_status": "blocked",
                 "distribution_blockers": list(builder.DISTRIBUTION_BLOCKERS),
                 "cpython": {**identity, "runtime_observations": observations.copy(),
                             "notice": {"path": "CPython-LICENSE.txt", "sha256": digest(text)},
                             "review_status": "unresolved",
                             "component_review": [{"component": name, "status": "unresolved",
                                                   "notice_mentions_name": False, "bundled_files": None}
                                                  for name in builder.NATIVE_COMPONENTS]}}
    builder.record_native_bundle(inventory, bundle)
    return inventory, notices, bundle, reference, index, pin


def run_case(case):
    inventory, notices, *_ = case
    builder.record_reviewed_cpython_evidence(inventory, notices)
    return {x["component"]: x for x in inventory["cpython"]["component_review"]}


def test_unlabelled_content_and_case_insensitive_archive_paths_match_without_clearance(evidence_case):
    inventory, notices, _, reference, _, pin = evidence_case
    before = copy.deepcopy(inventory)
    original_notice = (notices / "CPython-LICENSE.txt").read_bytes()
    reference["distribution_status"] = "cleared"  # Never import a status from an index.
    pin(reference)
    components = run_case(evidence_case)
    for name in ("OpenSSL", "Microsoft CRT"):
        assert components[name]["notice_mentions_name"] is False
        assert components[name]["notice_evidence"]["status"] == "verified_content_match"
        assert components[name]["status"] == "unresolved"
    assert all(x["status"] == "exact_archive_file_match" for x in components["OpenSSL"]["native_provenance"])
    observed = inventory["cpython"]["reviewed_evidence"]["native_files"]
    assert len(observed) == 3
    assert all(x["status"] == "exact_archive_file_match" for x in observed)
    crt = {Path(x["path"]).name: x for x in components["Microsoft CRT"]["native_provenance"]}
    assert crt["VCRUNTIME140.dll"]["status"] == "exact_archive_file_match"
    for name in ("ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll"):
        assert crt[name]["status"] == "not_in_reference_archive"
    for name in ("zlib", "liblzma/XZ"):
        assert components[name]["notice_evidence"]["status"] == "not_in_copied_notice"
        assert "not a legal" in components[name]["notice_evidence"]["interpretation"]
    for key in ("evaluation_only", "distribution_status", "distribution_blockers"):
        assert inventory[key] == before[key]
    assert inventory["cpython"]["review_status"] == before["cpython"]["review_status"]
    assert (notices / "CPython-LICENSE.txt").read_bytes() == original_notice
    assert digest((notices / "CPython-evidence.json").read_bytes()) == builder.CPYTHON_EVIDENCE_SHA256


@pytest.mark.parametrize("key,value", [("implementation", "Other"), ("version", "3.13.16"),
                                       ("platform", "linux"), ("architecture", "ARM64")])
def test_unsupported_runtime_identity_stays_unresolved(evidence_case, key, value):
    evidence_case[0]["cpython"][key] = value
    components = run_case(evidence_case)
    assert not evidence_case[0]["cpython"]["reviewed_evidence"]["runtime_identity_match"]
    assert components["OpenSSL"]["notice_evidence"]["status"] == "unresolved_notice_identity"
    assert all(x["status"] == "unresolved_runtime_identity" for x in components["OpenSSL"]["native_provenance"])


@pytest.mark.parametrize("key", ["OpenSSL", "zlib_compiled", "zlib_runtime"])
def test_changed_or_missing_runtime_observations_do_not_inherit_reference(evidence_case, key):
    del evidence_case[0]["cpython"]["runtime_observations"][key]
    components = run_case(evidence_case)
    assert not evidence_case[0]["cpython"]["reviewed_evidence"]["runtime_observations_match"]
    assert components["OpenSSL"]["notice_evidence"]["status"] == "unresolved_notice_identity"


@pytest.mark.parametrize("change", ["bytes", "manifest_hash", "line_endings", "name_only"])
def test_changed_notice_or_keyword_only_text_never_establishes_content(evidence_case, change):
    inventory, notices, *_ = evidence_case
    path = notices / "CPython-LICENSE.txt"
    data = path.read_bytes()
    if change == "bytes":
        data = data.replace(b"license A", b"license Z")
    elif change == "line_endings":
        data = data.replace(b"\r\n", b"\n")
    elif change == "name_only":
        data = b"OpenSSL; Microsoft CRT; zlib; liblzma/XZ"
        inventory["cpython"]["component_review"][0]["notice_mentions_name"] = True
    else:
        inventory["cpython"]["notice"]["sha256"] = "0" * 64
    path.write_bytes(data)
    if change != "manifest_hash":
        inventory["cpython"]["notice"]["sha256"] = digest(data)
    components = run_case(evidence_case)
    assert components["OpenSSL"]["notice_evidence"]["status"] == "unresolved_notice_identity"
    assert path.read_bytes() == data  # Never normalize or overwrite the notice.


@pytest.mark.parametrize("change", ["hash", "size", "path", "duplicate_case"])
def test_native_mismatch_is_separate_from_notice_content(evidence_case, change):
    inventory, _, bundle, *_ = evidence_case
    path = bundle / "_internal" / "libssl-3.dll"
    if change in {"hash", "size"}:
        data = b"synthetic SSL" if change == "hash" else b"longer synthetic SSL"
        path.write_bytes(data)
    elif change == "path":
        other = bundle / "other"
        other.mkdir()
        path.rename(other / path.name)
    builder.record_native_bundle(inventory, bundle)
    if change == "duplicate_case":
        duplicate = dict(next(x for x in inventory["native_files"] if x["path"].endswith("libssl-3.dll")))
        duplicate["path"] = duplicate["path"].upper()
        inventory["native_files"].append(duplicate)
    components = run_case(evidence_case)
    assert components["OpenSSL"]["notice_evidence"]["status"] == "verified_content_match"
    ssl = next(x for x in components["OpenSSL"]["native_provenance"] if x["path"].endswith("libssl-3.dll"))
    expected = "not_in_reference_archive" if change == "path" else "unresolved_file_mismatch"
    assert ssl["status"] == expected
    assert components["OpenSSL"]["status"] == "unresolved"


@pytest.mark.parametrize("change", ["archive", "notice", "native", "span", "invalid_json"])
def test_changed_review_index_is_rejected_before_comparison(evidence_case, change):
    reference, index = evidence_case[3:5]
    if change == "archive": reference["archive"]["sha256"] = "0" * 64
    if change == "notice": reference["notice"]["sha256"] = "0" * 64
    if change == "native": reference["native_files"][0]["sha256"] = "0" * 64
    if change == "span": reference["components"]["OpenSSL"]["notice_span"]["sha256"] = "0" * 64
    index.write_text("not JSON" if change == "invalid_json" else json.dumps(reference))
    with pytest.raises(RuntimeError, match="Changed reviewed CPython evidence index"):
        run_case(evidence_case)
    assert evidence_case[0]["distribution_status"] == "blocked"


@pytest.mark.parametrize("field,value", [("byte_start", -1), ("byte_start", 99999),
                                       ("byte_length", 99999), ("byte_length", 0), ("sha256", "0" * 64)])
def test_invalid_reviewed_span_stays_unresolved(evidence_case, field, value):
    reference = evidence_case[3]
    reference["components"]["OpenSSL"]["notice_span"][field] = value
    evidence_case[5](reference)
    assert run_case(evidence_case)["OpenSSL"]["notice_evidence"]["status"] == "unresolved_content_mismatch"


def test_checked_in_reference_has_exact_archive_identity_and_pinned_original_bytes():
    data = builder.CPYTHON_EVIDENCE.read_bytes()
    assert digest(data) == builder.CPYTHON_EVIDENCE_SHA256
    reference = json.loads(data)
    assert reference["identity"] == {"implementation": "CPython", "version": "3.13.15", "platform": "win32", "architecture": "x64"}
    assert reference["archive"]["sha256"] == "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"
    assert reference["notice"]["sha256"] == "62bec384df47b0328307db41455ff6ea2559e5546b394ac69148561b21703120"
    assert reference["notice"]["size"] == 33861
    for name in ("OpenSSL", "Microsoft CRT"):
        span = reference["components"][name]["notice_span"]
        assert 0 < span["byte_start"] < span["byte_start"] + span["byte_length"] <= 33861
        assert re.fullmatch("[0-9a-f]{64}", span["sha256"])
    paths = [x["bundle_path"].casefold() for x in reference["native_files"]]
    assert len(paths) == len(set(paths))
    assert "_internal/ucrtbase.dll" not in paths


def test_workflow_uploads_remain_exact_nonbinary_evidence_allowlist():
    workflow = (builder.ROOT / ".github/workflows/tests.yml").read_text()
    paths = []
    for match in re.finditer(r"(?m)^          path: \|\n((?:            [^\n]+\n)+)", workflow):
        paths.extend(x.strip() for x in match[1].splitlines())
    assert set(paths) == {
        "runtime/verification/workbench-*.png", "runtime/verification/browser-smoke.json",
        "runtime/verification/state-benchmark.json", "runtime/verification/portable-smoke.json",
        "runtime/verification/portable-console.json", "runtime/verification/portable-workbench.png",
        "runtime/verification/portable-workbench-failure.png", "dist/AgentWorkbench/build-manifest.json",
        "dist/AgentWorkbench/THIRD-PARTY-NOTICES/inventory.json"}
    assert workflow.count("uses: actions/upload-artifact@") == 2
