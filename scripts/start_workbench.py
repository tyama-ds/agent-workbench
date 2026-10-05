"""Launch without PowerShell, retaining the per-user Windows duplicate-launch guard."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    if FROZEN:
        from workbench import __version__
        parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--project-root', '-ProjectRoot', type=Path, default=ROOT)
    parser.add_argument('--port', '-Port', type=int, default=8818)
    parser.add_argument('--state-dir', '-StateDir', default='')
    parser.add_argument('--no-browser', '-NoBrowser', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('port must be between 0 and 65535')
    root = ROOT if FROZEN else args.project_root.resolve()
    state = str(Path(args.state_dir).resolve()) if args.state_dir else 'default-state-directory'
    identity = f'{root}|{args.port}|{state}|{Path.home()}'.casefold()
    guard = None
    kernel = None
    try:
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            guard = kernel.CreateMutexW(None, False, 'Local\\AgentWorkbenchPython-' + hashlib.sha256(identity.encode()).hexdigest())
            if not guard:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                if args.port:
                    url = f'http://127.0.0.1:{args.port}/'
                    print('Agent Workbench is already starting/running: ' + url)
                    print('Use the existing browser/console. A port alone cannot identify this application safely.')
                else:
                    print('Agent Workbench is already running with a dynamic port. Use its existing console URL.')
                print('If authentication was lost, stop the existing console with Ctrl+C and start again.')
                return 0
        if FROZEN:
            import asyncio
            from workbench.server import serve
            print('Starting Agent Workbench. Keep this console open; Ctrl+C stops the server.', flush=True)
            asyncio.run(serve(args))
            return 0
        command = [sys.executable, '-m', 'workbench.server', '--port', str(args.port)]
        if args.no_browser:
            command.append('--no-browser')
        if args.state_dir:
            command += ['--state-dir', state]
        print('Starting Agent Workbench. Keep this console open; Ctrl+C stops the server.', flush=True)
        return subprocess.call(command, cwd=root)
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if guard and kernel:
            kernel.CloseHandle(guard)


if __name__ == '__main__':
    raise SystemExit(main())
