"""Retired-builder rejection and historical helpers; no executable is built."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("portable_builder", ROOT / "tools" / "build_portable.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_source_version_matches_runtime_and_metadata():
    from workbench import __version__
    assert builder.source_version() == __version__


def test_source_version_rejects_mismatch_without_importing(tmp_path):
    (tmp_path / "workbench").mkdir()
    (tmp_path / "workbench" / "__init__.py").write_text(
        "raise Exception('must not execute')\n__version__ = '0.1.1.dev5'\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.1.dev4"\n')
    with pytest.raises(RuntimeError, match="differs"):
        builder.source_version(tmp_path)


def test_historical_build_lock_is_separate_from_source_dependencies():
    runtime = builder.lock_versions(ROOT / "requirements.lock")
    build = builder.lock_versions(ROOT / "requirements-build.lock")
    assert not (set(runtime) & set(build))
    assert set(build) == {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes"}
    assert {"setuptools", "packaging"} <= set(runtime)


@pytest.mark.parametrize("text", ["anything>=1", "anything==1 \\\n", "anything==1 \\\n    --hash=sha256:BAD", ""])
def test_lock_parser_fails_closed(tmp_path, text):
    lock = tmp_path / "bad.lock"
    lock.write_text(text)
    with pytest.raises(RuntimeError):
        builder.lock_versions(lock)


def test_non_windows_build_is_explicitly_rejected(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows"):
        builder.validate_host()
    assert builder.main(["--evaluation-only"]) == 1


@pytest.mark.parametrize("arguments", [[], ["--help"], ["--evaluation-only"],
    ["--evaluation-only", "--_assemble", "--_source-sha", "a" * 40], ["--unknown-option"]])
def test_every_former_cli_mode_rejected_without_build_side_effects(tmp_path, monkeypatch, capsys, arguments):
    import subprocess
    import venv
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled builder must not invoke processes, install packages or create a venv")
    monkeypatch.setattr(builder, "validate_host", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(venv.EnvBuilder, "create", forbidden)
    assert builder.main([*arguments, "--output-dir", str(tmp_path / "output"),
                         "--work-dir", str(tmp_path / "work")]) == 1
    assert "Python bundling is disabled" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("evaluation_only", [False, True])
def test_direct_assembly_always_rejected_before_host_probe(tmp_path, monkeypatch, evaluation_only):
    monkeypatch.setattr(builder, "validate_host", lambda: pytest.fail("Must reject before host probe"))
    with pytest.raises(RuntimeError, match="Python bundling is disabled"):
        builder.assemble(tmp_path / "out", tmp_path / "work", "a" * 40, evaluation_only=evaluation_only)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("version,bits,machine", [((3, 12), 8, "AMD64"), ((3, 13), 4, "AMD64"),
                                                 ((3, 13), 8, "ARM64")])
def test_wrong_windows_interpreter_rejected(monkeypatch, version, bits, machine):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "version_info", version)
    monkeypatch.setattr(builder.struct, "calcsize", lambda _: bits)
    monkeypatch.setattr(builder.platform, "machine", lambda: machine)
    with pytest.raises(RuntimeError):
        builder.validate_host()


class FakeMetadata(dict):
    def get_all(self, name):
        value = self.get(name)
        return [value] if value else None


def fake_distribution(root, name="example", license_text="Example license", include_metadata=True):
    files = []
    for filename, content in {f"{name}.dist-info/licenses/LICENSE": license_text,
                              f"{name}.dist-info/METADATA": f"Name: {name}\nVersion: 1.0\n"}.items():
        if not include_metadata and filename.endswith("METADATA"):
            continue
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        files.append(Path(filename))
    return SimpleNamespace(metadata=FakeMetadata(Name=name), version="1.0", files=files,
                           locate_file=lambda path: root / path)


def test_notice_inventory_preserves_actual_files_and_hashes(tmp_path, monkeypatch):
    dist = fake_distribution(tmp_path / "wheel")
    monkeypatch.setattr(builder.metadata, "distribution", lambda _: dist)
    notices = tmp_path / "notices"
    result = builder.copy_distribution_notices("example", notices, "runtime")
    assert result["name"] == "example" and result["version"] == "1.0"
    assert result["role"] == "runtime"
    for entry in result["metadata"] + result["notices"]:
        assert builder.sha256(notices / entry["path"]) == entry["sha256"]
    assert (notices / result["notices"][0]["path"]).read_text() == "Example license"


def test_british_spelling_licence_and_authors_are_collected(tmp_path, monkeypatch):
    dist = fake_distribution(tmp_path / "wheel")
    old = next(path for path in dist.files if path.name == "LICENSE")
    renamed = old.with_name("LICENCE.rst")
    dist.locate_file(old).rename(dist.locate_file(renamed))
    dist.files = [renamed if path == old else path for path in dist.files]
    author = renamed.with_name("AUTHORS.txt")
    dist.locate_file(author).write_text("Contributors")
    dist.files.append(author)
    monkeypatch.setattr(builder.metadata, "distribution", lambda _: dist)
    result = builder.copy_distribution_notices("example", tmp_path / "notices", "runtime")
    assert len(result["notices"]) == 2


@pytest.mark.parametrize("missing", ["license", "metadata"])
def test_missing_distribution_notices_or_metadata_fail(tmp_path, monkeypatch, missing):
    dist = fake_distribution(tmp_path / "wheel", include_metadata=missing != "metadata")
    if missing == "license":
        dist.files = [p for p in dist.files if p.name != "LICENSE"]
    monkeypatch.setattr(builder.metadata, "distribution", lambda _: dist)
    with pytest.raises(RuntimeError, match="Missing license or distribution METADATA"):
        builder.copy_distribution_notices("example", tmp_path / "notices", "runtime")


@pytest.mark.parametrize("name", ["lxml", "pillow", "pyinstaller"])
def test_native_notices_cannot_be_replaced_with_top_level_license(tmp_path, monkeypatch, name):
    dist = fake_distribution(tmp_path / "wheel", name=name)
    monkeypatch.setattr(builder.metadata, "distribution", lambda _: dist)
    with pytest.raises(RuntimeError, match="native notice inventory"):
        builder.copy_distribution_notices(name, tmp_path / "notices", "runtime")


def test_dependency_notice_path_traversal_rejected(tmp_path, monkeypatch):
    dist = fake_distribution(tmp_path / "wheel")
    dist.files.append(Path("../LICENSE-secret"))
    monkeypatch.setattr(builder.metadata, "distribution", lambda _: dist)
    with pytest.raises(RuntimeError, match="Unsafe"):
        builder.copy_distribution_notices("example", tmp_path / "notices", "runtime")


def test_cpython_native_notices_are_required(tmp_path):
    with pytest.raises(RuntimeError, match="Missing CPython"):
        builder.collect_notices(tmp_path / "notices", [], [], tmp_path / "python")
    python = tmp_path / "python"
    python.mkdir()
    (python / "LICENSE.txt").write_text("Not an interpreter license")
    with pytest.raises(RuntimeError, match="CPython native notice"):
        builder.collect_notices(tmp_path / "incomplete", [], [], python)


def test_cpython_license_is_in_inventory(tmp_path):
    python = tmp_path / "python"
    python.mkdir()
    (python / "LICENSE.txt").write_text("Python Software Foundation; OpenSSL; libffi; zlib")
    destination = tmp_path / "notices"
    inventory = builder.collect_notices(destination, [], [], python)
    assert inventory["cpython"]["notice"]["sha256"] == builder.sha256(destination / "CPython-LICENSE.txt")
    assert json.loads((destination / "inventory.json").read_text()) == inventory


def test_evaluation_preserves_actual_license_and_records_unresolved_components(tmp_path):
    python = tmp_path / "python"
    python.mkdir()
    # Real installations need not mention every native component in this file.
    text = "Python Software Foundation; libffi notice only in this synthetic fixture"
    (python / "LICENSE.txt").write_text(text)
    destination = tmp_path / "notices"
    inventory = builder.collect_notices(destination, [], [], python)
    assert (destination / "CPython-LICENSE.txt").read_text() == text
    assert inventory["evaluation_only"] is True
    assert inventory["distribution_status"] == "blocked"
    assert inventory["distribution_blockers"]
    assert inventory["cpython"]["runtime_observations"]["OpenSSL"]
    assert inventory["cpython"]["runtime_observations"]["zlib_runtime"]
    components = {item["component"]: item for item in inventory["cpython"]["component_review"]}
    assert set(components) == set(builder.NATIVE_COMPONENTS)
    assert all(item["status"] == "unresolved" for item in components.values())
    assert not components["OpenSSL"]["notice_mentions_name"]
    assert components["libffi"]["notice_mentions_name"]
    assert components["SQLite"]["bundled_files"] is None


def test_native_inventory_identifies_only_actual_bundled_files(tmp_path):
    (tmp_path / "_internal").mkdir()
    for filename in ("python313.dll", "libssl-3.dll", "_ssl.pyd", "vcruntime140.dll"):
        (tmp_path / "_internal" / filename).write_bytes(b"Synthetic file, not a binary")
    inventory = {"cpython": {"component_review": [
        {"component": name, "status": "unresolved"} for name in builder.NATIVE_COMPONENTS]}}
    builder.record_native_bundle(inventory, tmp_path)
    components = {item["component"]: item for item in inventory["cpython"]["component_review"]}
    assert len(components["OpenSSL"]["bundled_files"]) == 2
    assert components["OpenSSL"]["status"] == "unresolved"
    assert components["SQLite"]["bundled_files"] == []
    assert components["SQLite"]["status"].startswith("not_observed_in_bundle")
    for item in inventory["native_files"]:
        assert item["sha256"] == builder.sha256(tmp_path / item["path"])


def test_supplementary_notices_are_versioned_and_hash_verified(tmp_path, monkeypatch):
    source = tmp_path / "supplements"
    source.mkdir()
    files = []
    for name in ("elementtree.txt", "LGPL-2.1.txt", "zlib.txt"):
        path = source / name
        path.write_text("Example notice fixture")
        files.append({"path": name, "sha256": builder.sha256(path), "source": "https://example.test"})
    (source / "sources.json").write_text(json.dumps({"distribution": "lxml", "version": "6.1.3", "files": files}))
    monkeypatch.setattr(builder.metadata, "version", lambda _: "6.1.3")
    result = builder.copy_supplementary_notices(source, tmp_path / "notices", "lxml")
    assert result["version"] == "6.1.3" and len(result["files"]) == 3
    (source / "zlib.txt").write_text("Changed")
    with pytest.raises(RuntimeError, match="changed native notice"):
        builder.copy_supplementary_notices(source, tmp_path / "changed", "lxml")
    monkeypatch.setattr(builder.metadata, "version", lambda _: "7.0.0")
    with pytest.raises(RuntimeError, match="do not match"):
        builder.copy_supplementary_notices(source, tmp_path / "version", "lxml")


def test_version_resource_is_derived_from_source(tmp_path):
    path = tmp_path / "version.txt"
    builder.write_version_resource(path, "0.1.1.dev5")
    resource = path.read_text()
    ast.parse(resource)
    assert "filevers=(0, 1, 1, 5)" in resource
    assert "'ProductVersion', '0.1.1.dev5'" in resource
    assert "flags=0x2" in resource
    assert "experimental, unsigned" in resource


def test_manifest_covers_every_bundle_file_except_itself(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    for filename in ("requirements.lock", "requirements-build.lock"):
        (root / filename).write_text(filename)
    bundle = tmp_path / builder.APP_NAME
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "AgentWorkbench.exe").write_bytes(b"test fixture, not executable")
    (bundle / "_internal" / "resource.txt").write_text("Japanese: 日本語", encoding="utf-8")
    monkeypatch.setattr(builder.metadata, "version", lambda _: "1.2.3")
    result = builder.write_manifest(bundle, "0.1.1.dev5", "a" * 40, ["example"], ["pyinstaller"], root)
    assert result["source_sha"] == "a" * 40
    assert result["architecture"] == "x64" and result["bundle_mode"] == "onedir"
    assert result["console"] and not result["upx"] and not result["signed"]
    assert result["label"] == "experimental-unsigned"
    assert result["evaluation_only"] is True and result["distribution_status"] == "blocked"
    assert result["distribution_blockers"]
    assert {item["path"] for item in result["files"]} == {"AgentWorkbench.exe", "_internal/resource.txt"}
    for item in result["files"]:
        assert item["sha256"] == builder.sha256(bundle / item["path"])
    assert result["locks"]["requirements.lock"] == builder.sha256(root / "requirements.lock")


def test_zip_keeps_onedir_and_checksum(tmp_path):
    bundle = tmp_path / builder.APP_NAME
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "AgentWorkbench.exe").write_bytes(b"fixture")
    (bundle / "_internal" / "default.docx").write_bytes(b"fixture template")
    archive = builder.archive_bundle(bundle, tmp_path, "0.1.1.dev5")
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == {"AgentWorkbench/AgentWorkbench.exe",
                                          "AgentWorkbench/_internal/default.docx"}
    assert archive.with_suffix(".zip.sha256").read_text() == f"{builder.sha256(archive)}  {archive.name}\n"
    with pytest.raises(RuntimeError, match="Refusing to overwrite"):
        builder.archive_bundle(bundle, tmp_path, "0.1.1.dev5")


def test_direct_spec_fails_before_import_or_build():
    spec = (ROOT / "tools" / "portable.spec").read_text()
    tree = ast.parse(spec)
    assert len(tree.body) == 1 and isinstance(tree.body[0], ast.Raise)
    with pytest.raises(SystemExit, match="Python bundling is disabled"):
        exec(compile(tree, "portable.spec", "exec"), {})
    source = ast.parse((ROOT / "tools" / "build_portable.py").read_text())
    imports = {alias.name for node in ast.walk(source) if isinstance(node, ast.Import)
               for alias in node.names}
    assert not imports & {"subprocess", "venv", "PyInstaller"}


def test_checksum_pinned_notices_disable_checkout_line_ending_conversion():
    attributes = (Path(__file__).resolve().parents[1] / '.gitattributes').read_text(encoding='utf-8')
    assert 'tools/portable-notices/** -text' in attributes.splitlines()
