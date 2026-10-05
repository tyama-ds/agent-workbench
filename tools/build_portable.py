"""Build an experimental, unsigned Windows x64 ONEDIR app in a fresh venv.

Run with official CPython 3.13 x64 on Windows. No cross-compilation, signing,
publishing, or smoke-test claim is performed here. CI must gate artifact upload
on its separate frozen-app acceptance tests. See tools/portable.spec.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "AgentWorkbench"
LABEL = "experimental-unsigned"
NOTICE_PREFIXES = ("license", "licence", "copying", "notice", "copyright", "authors")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def source_version(root: Path = ROOT) -> str:
    tree = ast.parse((root / "workbench" / "__init__.py").read_text(encoding="utf-8"))
    versions = [ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__"
                        for target in node.targets)]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise RuntimeError("Expected exactly one literal source __version__")
    version = versions[0]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.dev\d+)?", version):
        raise RuntimeError(f"Unsupported portable version: {version}")
    declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if declared["project"]["version"] != version:
        raise RuntimeError("pyproject.toml version differs from source __version__")
    return version


def validate_host() -> None:
    if sys.platform != "win32" or platform.python_implementation() != "CPython":
        raise RuntimeError("Portable builds require Windows with official CPython 3.13 x64")
    if sys.version_info[:2] != (3, 13) or struct.calcsize("P") != 8:
        raise RuntimeError("Portable builds require CPython 3.13 x64")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("ARM64 and emulated-architecture builds are not supported")


def lock_versions(path: Path) -> dict[str, str]:
    """Read these reviewed, unconditional, exact-pin lock files, not arbitrary pip syntax."""
    result = {}
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith("#")]
        if not lines:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)\s*\\", lines[0])
        if not match or not all(re.fullmatch(r"\s+--hash=sha256:[0-9a-f]{64}\s*\\?", line)
                                for line in lines[1:]) or len(lines) < 2:
            raise RuntimeError(f"Expected exact pins and SHA256 hashes in {path.name}")
        name = normalize(match[1])
        if name in result:
            raise RuntimeError(f"Duplicate lock entry: {name}")
        result[name] = match[2]
    if not result:
        raise RuntimeError(f"Empty lock: {path.name}")
    return result


def installed_versions() -> dict[str, str]:
    return {normalize(dist.metadata["Name"]): dist.version for dist in metadata.distributions()}


def runtime_distributions(root: Path = ROOT) -> list[str]:
    from packaging.requirements import Requirement

    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pending = list(project["dependencies"])
    found = set()
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        name = normalize(requirement.name)
        if name in found:
            continue
        dist = metadata.distribution(name)
        if not requirement.specifier.contains(dist.version):
            raise RuntimeError(f"Unsatisfied runtime dependency: {requirement}")
        found.add(name)
        pending.extend(dist.requires or ())
    return sorted(found)


def require_notice_terms(text: str, terms: tuple[str, ...], component: str) -> None:
    missing = [term for term in terms if term.lower() not in text.lower()]
    if missing:
        raise RuntimeError(f"Incomplete {component} native notice inventory: {', '.join(missing)}")


def copy_distribution_notices(name: str, destination: Path, role: str) -> dict:
    """Keep actual wheel metadata and notice files, including nested vendor notices."""
    dist = metadata.distribution(name)
    target = destination / normalize(name)
    notices = []
    metadata_files = []
    texts = []
    has_license = False
    has_metadata = False
    for entry in sorted(dist.files or (), key=str):
        relative = PurePosixPath(str(entry).replace("\\", "/"))
        basename = relative.name.lower()
        is_notice = basename.startswith(NOTICE_PREFIXES) and not basename.endswith((".py", ".pyc"))
        is_metadata = basename in {"metadata", "wheel"} and any(
            part.endswith(".dist-info") for part in relative.parts)
        if not (is_notice or is_metadata):
            continue
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe dependency notice path: {name}: {relative}")
        source = Path(dist.locate_file(entry))
        if not source.is_file() or source.is_symlink() or source.stat().st_size == 0:
            raise RuntimeError(f"Missing dependency notice/metadata: {name}: {relative}")
        copied = target.joinpath(*relative.parts)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, copied)
        item = {"path": copied.relative_to(destination).as_posix(), "sha256": sha256(copied)}
        (notices if is_notice else metadata_files).append(item)
        if is_notice:
            texts.append(source.read_text(encoding="utf-8", errors="replace"))
            has_license |= basename.startswith(("license", "licence", "copying"))
        has_metadata |= basename == "metadata"
    if not has_license or not has_metadata:
        raise RuntimeError(f"Missing license or distribution METADATA for {name}")
    text = "\n".join(texts)
    if normalize(name) == "lxml":
        require_notice_terms(text, ("libxml2", "libxslt", "libexslt", "zlib", "iconv"), "lxml")
    if normalize(name) == "pillow":
        # Upstream Windows wheels append the bundled codecs' actual license texts.
        require_notice_terms(text, ("LIBJPEG", "LIBPNG", "LIBTIFF", "LIBWEBP", "OPENJPEG",
                                   "FREETYPE", "LCMS", "ZLIB"), "Pillow")
    if normalize(name) == "pyinstaller":
        require_notice_terms(text, ("bootloader", "exception"), "PyInstaller")
    return {"name": dist.metadata["Name"], "version": dist.version, "role": role,
            "license_expression": dist.metadata.get("License-Expression"),
            "project_urls": dist.metadata.get_all("Project-URL") or [],
            "notices": notices, "metadata": metadata_files}


def collect_notices(destination: Path, runtime: list[str], build: list[str],
                    python_home: Path | None = None) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    inventory = {"schema_version": 1, "distributions": []}
    for name in sorted(set(runtime) | set(build)):
        inventory["distributions"].append(copy_distribution_notices(
            name, destination, "runtime" if name in runtime else "build-tool/bootloader"))
    if "lxml" in runtime:
        supplement = copy_supplementary_notices(ROOT / "tools" / "portable-notices" / "lxml",
                                              destination / "lxml-supplementary", "lxml")
        inventory["supplementary_native_notices"] = supplement
    python_license = (python_home or Path(sys.base_prefix)) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Missing CPython Windows LICENSE.txt; use the official Windows distribution")
    text = python_license.read_text(encoding="utf-8", errors="replace")
    require_notice_terms(text, ("Python Software Foundation", "OpenSSL", "libffi", "zlib"), "CPython")
    copied = destination / "CPython-LICENSE.txt"
    shutil.copyfile(python_license, copied)
    inventory["cpython"] = {"version": platform.python_version(),
                             "notice": {"path": copied.name, "sha256": sha256(copied)}}
    (destination / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return inventory


def copy_supplementary_notices(source: Path, destination: Path, distribution: str) -> dict:
    """Fail closed if reviewed upstream supplements change or do not match the wheel."""
    inventory = json.loads((source / "sources.json").read_text(encoding="utf-8"))
    if (inventory["distribution"] != distribution
            or inventory["version"] != metadata.version(distribution)):
        raise RuntimeError(f"Native notice supplements do not match installed {distribution}")
    if {entry["path"] for entry in inventory["files"]} != {"elementtree.txt", "LGPL-2.1.txt", "zlib.txt"}:
        raise RuntimeError("Missing reviewed lxml native notice supplements")
    for entry in inventory["files"]:
        path = source / entry["path"]
        if not path.is_file() or path.is_symlink() or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"Missing or changed native notice supplement: {entry['path']}")
    shutil.copytree(source, destination)
    return {"distribution": distribution, "version": inventory["version"],
            "sources": (destination.name + "/sources.json"),
            "files": [{**entry, "path": destination.name + "/" + entry["path"]}
                      for entry in inventory["files"]],
            "review": "License texts and provenance, not a legal-compliance or source-obligation determination."}


def write_version_resource(path: Path, version: str) -> None:
    parts = [int(value) for value in re.findall(r"\d+", version)]
    numeric = tuple((parts + [0])[:4])
    strings = {"FileDescription": "Agent Workbench (experimental, unsigned)",
               "FileVersion": version, "InternalName": APP_NAME,
               "OriginalFilename": APP_NAME + ".exe", "ProductName": "Agent Workbench",
               "ProductVersion": version}
    entries = ",\n".join(f"StringStruct({key!r}, {value!r})" for key, value in strings.items())
    path.write_text(
        "VSVersionInfo(ffi=FixedFileInfo("
        f"filevers={numeric!r}, prodvers={numeric!r}, mask=0x3f, flags=0x2, "
        "OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)), "
        "kids=[StringFileInfo([StringTable('040904B0', [" + entries + "])]), "
        "VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n", encoding="utf-8")


def file_inventory(directory: Path, exclude: tuple[str, ...] = ()) -> list[dict]:
    result = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Symlink in portable bundle: {path}")
        relative = path.relative_to(directory).as_posix()
        if path.is_file() and relative not in exclude:
            result.append({"path": relative, "size": path.stat().st_size, "sha256": sha256(path)})
    return result


def write_manifest(bundle: Path, version: str, source_sha: str, runtime: list[str],
                   build: list[str], root: Path = ROOT) -> dict:
    manifest = {"schema_version": 1, "product": APP_NAME, "version": version,
                "label": LABEL, "source_sha": source_sha,
                "built_at_utc": datetime.now(timezone.utc).isoformat(),
                "platform": "windows", "architecture": "x64", "bundle_mode": "onedir",
                "console": True, "upx": False, "signed": False,
                "python": {"implementation": platform.python_implementation(),
                           "version": platform.python_version()},
                "tools": {name: metadata.version(name) for name in sorted(set(build) | {"pip"})},
                "runtime_dependencies": {name: metadata.version(name) for name in runtime},
                "locks": {name: sha256(root / name) for name in ("requirements.lock", "requirements-build.lock")},
                "verification": "Not performed by builder; separate frozen acceptance tests required.",
                "file_hash_scope": "All bundle files except build-manifest.json itself.",
                "files": file_inventory(bundle, ("build-manifest.json",))}
    (bundle / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def archive_bundle(bundle: Path, output: Path, version: str) -> Path:
    archive = output / f"{APP_NAME}-{version}-windows-x64-experimental.zip"
    checksum = archive.with_suffix(".zip.sha256")
    if archive.exists() or checksum.exists():
        raise RuntimeError(f"Refusing to overwrite an existing artifact: {archive}")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for entry in file_inventory(bundle):
            source = bundle / entry["path"]
            zipped.write(source, f"{APP_NAME}/{entry['path']}")
    checksum.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="ascii")
    return archive


def assemble(output: Path, work: Path, source_sha: str) -> Path:
    validate_host()
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Internal assembly requires the fresh build virtual environment")
    version = source_version()
    runtime_lock = lock_versions(ROOT / "requirements.lock")
    build_lock = lock_versions(ROOT / "requirements-build.lock")
    installed = installed_versions()
    for name, expected in {**runtime_lock, **build_lock}.items():
        if installed.get(name) != expected:
            raise RuntimeError(f"Build environment differs from lock: {name}")
    unexpected = set(installed) - set(runtime_lock) - set(build_lock) - {"pip", "agent-workbench"}
    if unexpected:
        raise RuntimeError(f"Unexpected build environment packages: {sorted(unexpected)}")
    runtime = runtime_distributions()
    build = sorted(set(build_lock) | {"packaging", "setuptools"})
    notices = work / "THIRD-PARTY-NOTICES"
    collect_notices(notices, runtime, build)
    version_file = work / "version-resource.txt"
    write_version_resource(version_file, version)
    context = work / "context.json"
    context.write_text(json.dumps({"root": str(ROOT), "runtime_distributions": runtime,
                                   "version_resource": str(version_file)}), encoding="utf-8")
    env = os.environ.copy()
    env["WORKBENCH_BUILD_CONTEXT"] = str(context)
    env["PYTHONHASHSEED"] = "0"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                    "--distpath", str(output), "--workpath", str(work / "pyinstaller"),
                    str(ROOT / "tools" / "portable.spec")], check=True, cwd=ROOT, env=env)
    bundle = output / APP_NAME
    if not (bundle / f"{APP_NAME}.exe").is_file():
        raise RuntimeError("PyInstaller did not create the expected executable")
    for required in ("static/index.html", "static/app.js", "static/styles.css", "docs/interface.json",
                     "docx/templates/default.docx", "pptx/templates/default.pptx"):
        if not (bundle / "_internal" / required).is_file():
            raise RuntimeError(f"Missing bundled application resource: {required}")
    shutil.copytree(notices, bundle / notices.name)
    shutil.copyfile(ROOT / "LICENSE", bundle / "LICENSE")
    shutil.copyfile(ROOT / "README.md", bundle / "README.md")
    shutil.copytree(ROOT / "docs", bundle / "docs")
    (bundle / "EXPERIMENTAL.txt").write_text(
        "EXPERIMENTAL, UNSIGNED WINDOWS X64 BUILD\n"
        "Extract the entire folder. Keep _internal beside AgentWorkbench.exe.\n"
        "This build has no installer, updater, tray integration, or code signature.\n"
        "Build success does not establish acceptance-test success.\n"
        "Do not bypass Windows security warnings.\n", encoding="utf-8")
    write_manifest(bundle, version, source_sha, runtime, build)
    return archive_bundle(bundle, output, version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build" / "portable")
    parser.add_argument("--_assemble", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_source-sha", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        validate_host()
        version = source_version()
        output = args.output_dir.resolve()
        work_root = args.work_dir.resolve()
        if args._assemble:
            if not args._source_sha or not re.fullmatch(r"[0-9a-f]{40,64}", args._source_sha):
                raise RuntimeError("Missing verified Git source SHA")
            archive = assemble(output, work_root, args._source_sha)
            print(f"Built unsigned experimental artifact: {archive}")
            return 0
        source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        status = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"],
                                         cwd=ROOT, text=True).strip()
        if status:
            raise RuntimeError("Build requires a clean Git checkout so source_sha identifies the source")
        if (output / APP_NAME).exists() or list(output.glob(f"{APP_NAME}-{version}-windows-x64-experimental.zip*")):
            raise RuntimeError("Output already contains this bundle; choose an empty --output-dir")
        output.mkdir(parents=True, exist_ok=True)
        work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="build-", dir=work_root) as temporary:
            work = Path(temporary)
            environment = work / "venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / "Scripts" / "python.exe"
            for filename in ("requirements.lock", "requirements-build.lock"):
                subprocess.run([str(python), "-m", "pip", "--isolated", "install", "--require-hashes",
                                "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
                                "-r", str(ROOT / filename)], check=True, cwd=ROOT)
            subprocess.run([str(python), "-m", "pip", "--isolated", "install", "--no-deps",
                            "--no-build-isolation", str(ROOT)], check=True, cwd=ROOT)
            subprocess.run([str(python), "-m", "pip", "check"], check=True, cwd=ROOT)
            subprocess.run([str(python), str(Path(__file__).resolve()), "--_assemble",
                            "--_source-sha", source_sha, "--output-dir", str(output),
                            "--work-dir", str(work)], check=True, cwd=ROOT)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Portable build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
