"""Run with an explicitly selected interpreter and installed library directories."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import importlib
import importlib.util
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import struct
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEYS = {'python_executable', 'library_paths', 'port', 'state_dir', 'open_browser'}
IMPORT_NAMES = {
    'aiohappyeyeballs': 'aiohappyeyeballs', 'aiohttp': 'aiohttp', 'aiosignal': 'aiosignal',
    'attrs': 'attrs', 'et_xmlfile': 'et_xmlfile', 'frozenlist': 'frozenlist', 'idna': 'idna',
    'lxml': 'lxml.etree', 'multidict': 'multidict', 'openpyxl': 'openpyxl', 'pillow': 'PIL.Image',
    'propcache': 'propcache', 'python-docx': 'docx', 'python-pptx': 'pptx',
    'typing_extensions': 'typing_extensions', 'xlsxwriter': 'xlsxwriter', 'yarl': 'yarl',
}


@dataclass(frozen=True)
class RuntimeConfig:
    python_executable: Path
    library_paths: tuple[Path, ...]
    port: int = 8818
    state_dir: str = ''
    open_browser: bool = True


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _local_path(value, field):
    if not isinstance(value, str) or not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(field + ' must be a non-empty path without control characters.')
    path = Path(value)
    if not path.is_absolute() or (os.name == 'nt' and not re.match(r'^[A-Za-z]:[\\/]', value)):
        raise ValueError(field + ' must be an absolute local path, not an alias or network share.')
    resolved = path.resolve()
    if os.name == 'nt' and not re.match(r'^[A-Za-z]:[\\/]', str(resolved)):
        raise ValueError(field + ' must resolve to a local path.')
    return resolved


def load_config(path: Path) -> RuntimeConfig:
    with Path(path).open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('Runtime JSON must be at most 64 KiB.')
    try:
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Runtime config must be valid UTF-8 JSON. See runtime.example.json.') from exc
    if not isinstance(data, dict):
        raise ValueError('Runtime JSON must contain an object.')
    unknown = set(data) - CONFIG_KEYS
    if unknown:
        raise ValueError('Unknown runtime JSON keys: ' + ', '.join(sorted(unknown)))
    python = _local_path(data.get('python_executable'), 'python_executable')
    if not python.is_file() or (os.name == 'nt' and python.name.lower() != 'python.exe'):
        raise ValueError('python_executable must point to an existing python.exe.')
    libraries = data.get('library_paths')
    if not isinstance(libraries, list) or not 1 <= len(libraries) <= 16:
        raise ValueError('library_paths must contain 1 to 16 installed package directories.')
    paths = tuple(dict.fromkeys(_local_path(value, 'library_paths') for value in libraries))
    if any(not path.is_dir() for path in paths):
        raise ValueError('Every library_paths entry must be an existing directory, not a wheel file.')
    port = data.get('port', 8818)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('port must be an integer between 0 and 65535.')
    state = data.get('state_dir', '')
    if not isinstance(state, str):
        raise ValueError('state_dir must be an absolute local path or an empty string.')
    if state:
        state = str(_local_path(state, 'state_dir'))
    browser = data.get('open_browser', True)
    if not isinstance(browser, bool):
        raise ValueError('open_browser must be true or false.')
    return RuntimeConfig(python, paths, port, state, browser)


def validate_interpreter(config: RuntimeConfig):
    if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
        raise ValueError('Use Launch-Configured.cmd or run the configured python.exe with -I -S -B.')
    if Path(sys.executable).resolve() != config.python_executable:
        raise ValueError('The running Python does not match python_executable in the runtime JSON.')
    if not ((3, 11) <= sys.version_info[:2] <= (3, 13) and struct.calcsize('P') == 8
            and platform.python_implementation() == 'CPython' and not sysconfig.get_config_var('Py_GIL_DISABLED')):
        raise ValueError('Use standard 64-bit CPython 3.11, 3.12 or 3.13 with matching library files.')
    if os.name == 'nt':
        for relative in ('Lib/os.py', 'Lib/venv/__init__.py', 'Lib/ensurepip/__init__.py'):
            if not (config.python_executable.parent / relative).is_file():
                raise ValueError('Use a standard installed Python, not a launcher alias or copied virtual environment.')


def prepare_imports(config: RuntimeConfig):
    # -I -S keeps ambient PYTHONPATH, user sites, sitecustomize and .pth code out.
    # Append after the interpreter's standard library; do not run site.addsitedir.
    sys.path.extend(str(path) for path in (ROOT, *config.library_paths) if str(path) not in sys.path)
    importlib.invalidate_caches()
    from workbench import runtime_paths
    runtime_paths.PROTECTED_ROOTS = tuple(dict.fromkeys((
        *runtime_paths.PROTECTED_ROOTS, Path(sys.base_prefix).resolve(), *config.library_paths,
    )))


def check_packages():
    required = dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^\s]+)',
                              (ROOT / 'requirements-runtime.lock').read_text(encoding='utf-8'), re.M))
    if set(required) != set(IMPORT_NAMES):
        raise ValueError('Runtime dependency list is incomplete. Restore requirements-runtime.lock from this source version.')
    errors = []
    for package, expected in required.items():
        try:
            found = metadata.version(package)
        except metadata.PackageNotFoundError:
            errors.append(f'{package}: missing (requires {expected})')
            continue
        if found != expected:
            errors.append(f'{package}: found {found}, requires {expected}')
    if errors:
        raise ValueError('Installed package check failed:\n  ' + '\n  '.join(errors)
                         + '\nSee docs/DEPENDENCIES.md and requirements-runtime.lock. No packages were installed.')
    for package, module in IMPORT_NAMES.items():
        try:
            importlib.import_module(module)
        except (ImportError, OSError, ValueError) as exc:
            raise ValueError(f'{package} could not load ({type(exc).__name__}). '
                             'Check the package files and Python version/architecture.') from exc
    print(f'Runtime packages: {len(required)} checked (versions and imports).', flush=True)


def run_server(args):
    os.chdir(args.project_root)
    from workbench.server import serve
    asyncio.run(serve(args))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'runtime.local.json')
    parser.add_argument('--check', action='store_true', help='Check installed packages without starting a server or installing anything')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        validate_interpreter(config)
        prepare_imports(config)
        check_packages()
        importlib.import_module('workbench.server')  # Check application imports before reporting success.
        # A shared site-packages may contain an unrelated regular `scripts`
        # package, which would override this source tree's namespace directory.
        spec = importlib.util.spec_from_file_location('_workbench_launcher', ROOT / 'scripts/start_workbench.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        print('Python: ' + str(config.python_executable), flush=True)
        for path in config.library_paths:
            print('Library path: ' + str(path), flush=True)
        if args.check:
            print('Runtime check complete. No server started; no packages installed.', flush=True)
            return 0
        launch_args = ['--project-root', str(ROOT), '--port', str(config.port)]
        if config.state_dir:
            launch_args += ['--state-dir', config.state_dir]
        if not config.open_browser:
            launch_args.append('--no-browser')
        return launcher.main(launch_args, server_runner=run_server)
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print('Configured launch stopped: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
