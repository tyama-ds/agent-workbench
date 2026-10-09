"""Policy-respecting, per-user source installer. Uses only the Python standard library."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import sysconfig
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

# Preserve transport settings but never redirect this install or weaken TLS checks.
FORBIDDEN_PIP_OPTIONS = ('TARGET', 'PREFIX', 'ROOT', 'PYTHON', 'USER', 'REQUIREMENT',
                         'CONSTRAINT', 'BUILD_CONSTRAINT', 'EDITABLE', 'TRUSTED_HOST')
CONFIG_MARKER = ":env:.disable-pip-version-check='1'"
INSPECTION_OPTIONS = ('QUIET', 'VERBOSE', 'GLOBAL', 'SITE', 'USER', 'HELP', 'VERSION', 'ISOLATED')
STAGES = {
    'environment': ('Create private environment', 'Ask IT to check the approved Python installation and folder permissions. If a partial .venv remains, use a newly extracted source folder.'),
    'interpreter': ('Validate private interpreter', 'The existing .venv is incomplete, moved, or unsupported. Use a newly extracted source folder and approved standard 64-bit CPython 3.11-3.13.'),
    'pip': ('Check private pip', 'This environment needs working pip with --python support (pip 22.3 or newer). Ask IT to repair the approved Python installation or use a newly extracted source folder; setup will not upgrade pip automatically.'),
    'configuration': ('Check pip configuration', 'Ask IT to review pip configuration. No dependency packages were installed.'),
    'dependencies': ('Install locked dependencies', 'Check the preceding pip error: proxy/407 needs IT-approved connectivity/authentication; certificate errors need an approved CA bundle; missing wheels need the matching Python version and architecture. Retry with the same source or an approved offline wheelhouse.'),
    'application': ('Install local application', 'The local-only application install failed. Ask IT to check the source folder and locked build tools; no online fallback is used.'),
    'consistency': ('Check package consistency', 'The private environment has inconsistent dependencies. Retry Setup.cmd using the same lock and approved package source.'),
    'imports': ('Check application imports', 'A required module could not load. Ask IT to review the preceding error and any application-control block; do not disable protection.'),
}


class SetupStageError(RuntimeError):
    """Only fixed stage/recovery text is exposed; never child arguments or config."""


def run_stage(stage, runner, arguments, **kwargs):
    label, recovery = STAGES[stage]
    print('Setup step: ' + label + '.', flush=True)
    try:
        return runner(arguments, **kwargs)
    except (RuntimeError, OSError, UnicodeError, subprocess.SubprocessError):
        raise SetupStageError(f'{label} failed. {recovery}') from None


def installation_environment(options):
    child_env = dict(os.environ)
    if options.wheelhouse:
        # Offline mode never accepts injected pip options, URLs or destinations.
        child_env = {key: value for key, value in child_env.items() if not key.upper().startswith('PIP_')}
        child_env['PIP_CONFIG_FILE'] = os.devnull
    else:
        for key in FORBIDDEN_PIP_OPTIONS:
            if child_env.get('PIP_' + key):
                raise ValueError(f'PIP_{key} is set. Ask IT to review it: setup requires its private .venv, fixed inputs and verified TLS. The setting was not changed.')
    child_env.update(PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1')
    return child_env


def validate_proxy(value):
    try:
        url = urlsplit(value)
        if (any(ord(char) <= 32 or ord(char) == 127 or char == '\\' for char in value)
                or url.scheme not in ('http', 'https') or not url.hostname
                or url.username is not None or url.password is not None
                or url.path not in ('', '/') or url.query or url.fragment
                or (url.port is not None and url.port < 1)):
            raise ValueError
    except ValueError:
        raise ValueError('Proxy must be an HTTP(S) origin without credentials or a PAC path.') from None
    return value.rstrip('/')


def python_supported(version=None, bits=None, implementation=None, free_threaded=None):
    version = sys.version_info[:2] if version is None else version
    bits = struct.calcsize('P') * 8 if bits is None else bits
    implementation = platform.python_implementation() if implementation is None else implementation
    free_threaded = sysconfig.get_config_var('Py_GIL_DISABLED') if free_threaded is None else free_threaded
    return (3, 11) <= tuple(version) <= (3, 13) and bits == 64 and implementation == 'CPython' and not free_threaded


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--project-root', type=Path, default=ROOT)
    result.add_argument('--proxy', type=validate_proxy)
    result.add_argument('--certificate', type=Path)
    result.add_argument('--wheelhouse', type=Path, help='Offline wheel folder; disables package indexes')
    result.add_argument('--timeout', type=int, choices=range(5, 601), default=60, metavar='5..600')
    result.add_argument('--retries', type=int, choices=range(0, 11), default=3, metavar='0..10')
    result.add_argument('--check', action='store_true', help='Report prerequisites without installing or using network')
    return result


def preflight(options):
    root = options.project_root.resolve()
    if not python_supported():
        raise ValueError('Use standard 64-bit CPython 3.11, 3.12 or 3.13 (3.13 recommended). Ask IT for an approved per-user installation.')
    if os.name == 'nt' and (str(root).startswith('\\\\') or root.drive.startswith('\\\\')):
        raise ValueError('Extract the entire ZIP to a local user-writable folder, not a network share.')
    for relative in ('requirements.lock', 'pyproject.toml', 'workbench/server.py', 'static/index.html', 'docs/interface.json'):
        if not (root / relative).is_file():
            raise ValueError('Project files are missing. Extract the entire ZIP before running Setup.cmd.')
    if options.certificate:
        options.certificate = options.certificate.resolve()
        if not options.certificate.is_file():
            raise ValueError('Certificate must be an existing organization-approved PEM CA bundle.')
    if options.wheelhouse:
        options.wheelhouse = options.wheelhouse.resolve()
        if not options.wheelhouse.is_dir() or not any(options.wheelhouse.glob('*.whl')):
            raise ValueError('Wheelhouse must be a folder containing approved .whl files for this Python version and Windows architecture.')
    if options.wheelhouse and (options.proxy or options.certificate):
        raise ValueError('Offline installation does not use --proxy or --certificate. Specify only --wheelhouse.')
    # A temporary probe is removed immediately; no existing user files are changed.
    try:
        with tempfile.TemporaryFile(dir=root):
            pass
    except OSError:
        raise ValueError('Project folder is not writable. Extract to a local folder you own (for example under %LOCALAPPDATA%). Do not run as administrator.') from None
    return root


def invoke(arguments, *, cwd, env, capture=False):
    # Windows pipes otherwise use the ANSI code page, which cannot represent
    # every approved extraction path. Only captured reads use this private UTF-8
    # contract; preserve the caller's environment and normal console behavior.
    child_env = dict(env, PYTHONIOENCODING='utf-8') if capture else env
    result = subprocess.run([str(value) for value in arguments], cwd=cwd, env=child_env, check=False,
                            capture_output=capture, text=capture, encoding='utf-8' if capture else None)
    if result.returncode:
        raise RuntimeError(f'Command failed (exit {result.returncode}).')
    return result.stdout if capture else ''


def install(options, *, runner=invoke):
    root = preflight(options)
    environment = root / '.venv'
    if environment.resolve() != environment:
        raise ValueError('The .venv folder redirects outside its expected location. It was not changed. Use a newly extracted local source folder or ask IT to inspect it.')
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    status = {'python': platform.python_version(), 'bits': struct.calcsize('P') * 8,
              'implementation': platform.python_implementation(), 'mode': 'offline' if options.wheelhouse else 'online',
              'environment_exists': environment.exists(), 'environment_python_exists': python.is_file(),
              'proxy_configured': bool(options.proxy or os.environ.get('PIP_PROXY') or os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')),
              'certificate_supplied': bool(options.certificate), 'folder_writable': True}
    print(json.dumps(status, indent=2), flush=True)
    child_env = installation_environment(options)
    if options.check:
        print('Preflight complete. No packages installed; network, company policy and existing environment health are not tested.')
        return
    if not python.is_file():
        if environment.exists():
            raise ValueError('An incomplete .venv exists. It was not deleted. Ask IT to inspect or use a newly extracted project folder.')
        run_stage('environment', runner, [sys.executable, '-m', 'venv', str(environment)], cwd=root, env=child_env)
    # Prove the executable belongs to this venv, not merely a supported Python.
    probe = "import sys,struct,platform,sysconfig; from pathlib import Path; raise SystemExit(0 if (3,11)<=sys.version_info[:2]<=(3,13) and struct.calcsize('P')==8 and platform.python_implementation()=='CPython' and not sysconfig.get_config_var('Py_GIL_DISABLED') and sys.prefix!=sys.base_prefix and Path(sys.prefix).resolve()==Path(sys.argv[1]).resolve() else 1)"
    run_stage('interpreter', runner, [python, '-c', probe, str(environment)], cwd=root, env=child_env)
    # Pin before reading configuration: global.python can otherwise redirect even
    # `pip config list` into another interpreter. Older pip must fail closed.
    pip = [python, '-m', 'pip', '--python', str(python)]
    run_stage('pip', runner, pip + ['--version'], cwd=root, env=child_env, capture=True)
    if not options.wheelhouse:
        # config's selectors/quiet flags must not hide install-relevant settings.
        # Override only this read; do not alter the user's files or install env.
        inspection_env = dict(child_env)
        inspection_env.update({'PIP_' + key: '0' for key in INSPECTION_OPTIONS})
        config = run_stage('configuration', runner, pip + ['--log', os.devnull, 'config', 'list'],
                           cwd=root, env=inspection_env, capture=True) or ''
        if CONFIG_MARKER not in config.splitlines():
            raise SetupStageError('Check pip configuration failed. Complete configuration output could not be verified. Ask IT to inspect the approved pip installation; no dependency packages were installed.')
        forbidden_config = {key.lower().replace('_', '-') for key in FORBIDDEN_PIP_OPTIONS}
        for line in config.splitlines():
            full_key = line.split('=', 1)[0].strip()
            if full_key in {':env:.' + key.lower() for key in INSPECTION_OPTIONS}:
                continue
            key = full_key.rsplit('.', 1)[-1]
            if key in forbidden_config:
                raise SetupStageError('Check pip configuration failed. A pip setting redirects the private environment, adds package inputs or disables TLS verification. Ask IT to review it or use an approved offline wheelhouse. The setting was not changed; no dependency packages were installed.')
    network = ['--timeout', str(options.timeout), '--retries', str(options.retries)]
    if options.wheelhouse:
        network += ['--no-index', '--find-links', str(options.wheelhouse)]
    else:
        if options.proxy:
            network += ['--proxy', options.proxy]
        if options.certificate:
            network += ['--cert', str(options.certificate)]
    base = pip + ['install', '--disable-pip-version-check', '--require-virtualenv']
    run_stage('dependencies', runner, base + network + ['--only-binary=:all:', '--require-hashes', '-r', root / 'requirements.lock'], cwd=root, env=child_env)
    # Build tools are in the hash-locked wheel set; this stage must never fetch anything.
    run_stage('application', runner, base + ['--no-index', '--no-deps', '--no-build-isolation', '-e', str(root)], cwd=root, env=child_env)
    run_stage('consistency', runner, pip + ['check'], cwd=root, env=child_env)
    run_stage('imports', runner, [python, '-c', 'import workbench.server, docx, openpyxl, pptx'], cwd=root, env=child_env)
    print('Setup complete. Double-click Launch.cmd. Keep this folder in place.')


def main(argv=None):
    try:
        install(parser().parse_args(argv))
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f'Setup stopped: {error}', file=sys.stderr)
        print('The existing .venv is retained. See the failed setup step and docs/WINDOWS_SETUP.md. '
              'Do not disable TLS checks, execution policy or endpoint protection. '
              'Review terminal output for credentials/internal addresses before sharing it.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
