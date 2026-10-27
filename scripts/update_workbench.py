"""Refresh an existing in-place environment without selecting Python again."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import sysconfig
from urllib.parse import urlsplit
from urllib.request import url2pathname

ROOT = Path(__file__).resolve().parents[1]


def existing_environment(root, *, prefix=None, base_prefix=None, executable=None):
    root = Path(root).resolve()
    environment = root / '.venv'
    if environment.resolve() != environment:
        raise ValueError('The private environment redirects to another folder. It was not changed.')
    interpreter = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    current_prefix = Path(sys.prefix if prefix is None else prefix).resolve()
    base = Path(sys.base_prefix if base_prefix is None else base_prefix).resolve()
    current_executable = Path(sys.executable if executable is None else executable)
    # Executable paths may be symlinks on POSIX. The prefix proves ownership;
    # lexical parentage additionally prevents selecting another environment.
    if (current_prefix != environment or current_prefix == base
            or current_executable.absolute() != interpreter.absolute()
            or not interpreter.is_file() or not (environment / 'pyvenv.cfg').is_file()):
        raise ValueError('Use Update.bat from the same folder where Setup.bat completed. '
                         'Do not copy or move .venv; a new location needs Setup.bat once.')
    return root


def installed_source(root, *, purelib=None):
    """Reject a copied environment still bound to another editable checkout."""
    root = Path(root).resolve()
    library = Path(sysconfig.get_path('purelib') if purelib is None else purelib)
    if not library.resolve().is_relative_to(root / '.venv'):
        raise ValueError('The private package directory is outside this application environment.')
    records = list(library.glob('agent_workbench-*.dist-info/direct_url.json'))
    if len(records) != 1:
        raise ValueError('A completed local application install was not found. Run Setup.bat once in this folder.')
    record = records[0]
    if any(p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & 0x400
           for p in (record, record.parent, library)) or record.stat().st_size > 8192:
        raise ValueError('The installed application reference is invalid. It was not changed.')
    value = json.loads(record.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not isinstance(value.get('url'), str):
        raise ValueError('The installed application reference is invalid.')
    location = urlsplit(value['url'])
    if (location.scheme != 'file' or location.netloc or location.query or location.fragment
            or value.get('dir_info') != {'editable': True}
            or Path(url2pathname(location.path)).resolve() != root):
        raise ValueError('This environment belongs to another source folder. Run Setup.bat in the new folder; do not copy .venv.')


def load_setup(root):
    spec = importlib.util.spec_from_file_location('workbench_in_place_setup', root / 'scripts/setup_windows.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    return setup


def main(argv=None):
    try:
        root = existing_environment(ROOT)
        installed_source(root)
        setup = load_setup(root)
        options = setup.parser().parse_args(argv)
        if options.project_root.resolve() != root:
            raise ValueError('Update only supports this application folder; --project-root cannot select another folder.')
        try:
            setup.install(setup.interactive_options(options))
        except setup.SetupCancelled:
            print('Update cancelled before installation.', file=sys.stderr)
            return 1
        if not options.check:
            print('Update complete. Open the existing Launch.bat or shortcut. Saved settings and history are retained.')
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'Update stopped: {exc}', file=sys.stderr)
        print('Saved settings and history were not reset. '
              'If network settings are needed, use Update.bat --interactive. '
              'Keep the existing folder and inspect the failed setup step before retrying.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
