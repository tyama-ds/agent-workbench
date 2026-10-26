"""Real BAT entrypoints, with only local stdlib fixture scripts behind Python.

No setup implementation, package installer, workbench server, or browser is
executed. Captured cmd output remains bytes, including localized pause output.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[1]
MARKERS = ('Lib/os.py', 'Lib/venv/__init__.py', 'Lib/ensurepip/__init__.py')
CONSOLES = [0, getattr(subprocess, 'CREATE_NO_WINDOW', 0)]
WINDOWS = pytest.mark.skipif(os.name != 'nt', reason='Windows cmd.exe required')
HOSTILE = 'C:\\not-installed" & echo injected>shell-side-effect.txt & rem "'


def test_bat_entrypoints_are_direct_and_do_not_use_aliases_or_policy_bypass():
    for name, script in [('Setup.bat', 'setup_windows.py'),
                         ('Launch.bat', 'start_workbench.py')]:
        text = (ROOT / name).read_text(encoding='utf-8')
        assert 'DisableDelayedExpansion' in text
        assert script in text
        assert not re.search(r'(?im)^\s*(?:call\s+)?(?:py|python|pymanager)(?:\s|$)', text)
        assert 'powershell' not in text.lower()
        assert 'executionpolicy' not in text.lower()
        assert 'Setup.cmd' not in text and 'Launch.cmd' not in text
        assert 'curl' not in text.lower() and 'bitsadmin' not in text.lower()
    setup = (ROOT / 'Setup.bat').read_text(encoding='utf-8')
    assert all(marker.replace('/', '\\') in setup for marker in MARKERS)
    assert 'set /p ' in setup.lower()
    assert '.venv\\Scripts\\python.exe' in (ROOT / 'Launch.bat').read_text()


@pytest.fixture(scope='module')
def standard_python():
    executable = Path(getattr(sys, '_base_executable', None) or sys.executable)
    if (os.name != 'nt' or not executable.is_absolute()
            or executable.name.lower() != 'python.exe' or not executable.is_file()
            or not all((executable.parent / name).is_file() for name in MARKERS)):
        pytest.skip('A separately installed standard Windows CPython is required')
    return executable


def _runtime_copy(destination, executable):
    """Temporary executable fixture, not a distributable Python installation.

    Child tests point PYTHONHOME at the already installed standard library. The
    copied real exe/DLLs exercise Windows path handling without running setup.
    """
    destination.mkdir(parents=True)
    shutil.copy2(executable, destination / 'python.exe')
    for source in executable.parent.glob('*.dll'):
        shutil.copy2(source, destination / source.name)
    for name in MARKERS:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'# local entrypoint fixture only\n')
    return destination / 'python.exe'


@pytest.fixture(scope='module')
def special_python(tmp_path_factory, standard_python):
    base = tmp_path_factory.mktemp('bat-runtime')
    return _runtime_copy(base / 'approved Python & ! %AWB_BAT_EXPAND% ^ (local)', standard_python)


@pytest.fixture(scope='module')
def unicode_python(tmp_path_factory, standard_python):
    base = tmp_path_factory.mktemp('bat-unicode-runtime')
    return _runtime_copy(base / '会社 Python & ! %AWB_BAT_EXPAND% ^ (local)', standard_python)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / '会社 source & ! %AWB_BAT_EXPAND% ^ (fixture)'
    root.mkdir()
    for name in ('Setup.bat', 'Launch.bat'):
        shutil.copy2(ROOT / name, root / name)
    scripts = root / 'scripts'
    scripts.mkdir()
    body = (
        'import json, os, sys\nfrom pathlib import Path\n'
        'record = {"args": sys.argv[1:], "executable": sys.executable, '
        '"script": Path(__file__).name, "cwd": os.getcwd()}\n'
        'with Path("python-receipt.json").open("x", encoding="ascii") as stream:\n'
        '    json.dump(record, stream, ensure_ascii=True)\n'
        'print("\\nBAT_FIXTURE:" + json.dumps(record, ensure_ascii=True))\n'
        'raise SystemExit(int(os.environ.get("AWB_BAT_FIXTURE_EXIT", "17")))\n'
    )
    for name in ('setup_windows.py', 'start_workbench.py'):
        (scripts / name).write_text(body, encoding='ascii')
    # Any delegation or PATH alias would leave evidence; no real installer is
    # reachable through these fixture entrypoints.
    for name in ('Setup.cmd', 'Launch.cmd', 'python.cmd', 'py.cmd', 'pymanager.cmd'):
        (root / name).write_text('@echo unexpected>alias-invoked.txt\n@exit /b 91\n', encoding='ascii')
    return root


def _environment(project, standard_python=None, selection=None):
    env = dict(os.environ)
    for key in ('WORKBENCH_PYTHON', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP'):
        env.pop(key, None)
    env.update(PATH=str(project), PYLAUNCHER_ALLOW_INSTALL='1',
               PYLAUNCHER_ALWAYS_INSTALL='1', PYTHON_MANAGER_AUTOMATIC_INSTALL='true',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', AWB_BAT_EXPAND='MUST_NOT_EXPAND',
               HTTPS_PROXY='http://private-proxy-secret.invalid:8080',
               PIP_CERT='private-ca-secret.pem')
    if standard_python is not None:
        env['PYTHONHOME'] = str(standard_python.parent)
    if selection is not None:
        env['WORKBENCH_PYTHON'] = str(selection)
    return env


def _run(project, entry, arguments=(), *, env, data=b'\r\n', creationflags=0):
    cmd = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/cmd.exe'
    return subprocess.run([str(cmd), '/d', '/v:off', '/c', entry, *arguments],
                          cwd=project, env=env, input=data, capture_output=True,
                          creationflags=creationflags, timeout=20)


def _snapshot(project):
    return {str(path.relative_to(project)): path.read_bytes()
            for path in project.rglob('*') if path.is_file()}


def _assert_not_invoked(project):
    assert not (project / 'python-receipt.json').exists()
    assert not (project / 'shell-side-effect.txt').exists()
    assert not (project / 'alias-invoked.txt').exists()
    assert not (project / '.venv').exists()


def _receipt(project, result, arguments, executable, script, exit_code=17):
    assert result.returncode == exit_code, (result.stdout, result.stderr)
    saved = json.loads((project / 'python-receipt.json').read_text(encoding='ascii'))
    rows = [line.removeprefix(b'BAT_FIXTURE:') for line in result.stdout.splitlines()
            if line.startswith(b'BAT_FIXTURE:')]
    assert len(rows) == 1, (result.stdout, result.stderr)
    assert json.loads(rows[0].decode('ascii')) == saved
    assert saved['args'] == list(arguments)
    assert Path(saved['executable']) == executable
    assert saved['script'] == script
    assert Path(saved['cwd']) == project
    assert not (project / 'alias-invoked.txt').exists()
    assert not (project / 'shell-side-effect.txt').exists()


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
@pytest.mark.parametrize('help_arg', ['--help', '-h', '/?'])
@pytest.mark.parametrize('selection', [None, HOSTILE])
def test_help_precedes_prompt_validation_and_hostile_environment(project, help_arg, selection, creationflags):
    env = _environment(project, selection=selection)
    before = _snapshot(project)
    result = _run(project, 'Setup.bat', [help_arg], env=env, data=b'', creationflags=creationflags)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert b'Agent Workbench source setup' in result.stdout
    assert b'Setup.bat' in result.stdout and b'Launch.bat' in result.stdout
    assert b'Python path: ' not in result.stdout
    assert b'private-proxy-secret' not in result.stdout + result.stderr
    assert b'private-ca-secret' not in result.stdout + result.stderr
    assert all(option in result.stdout for option in
               (b'--check', b'--proxy', b'--certificate', b'--wheelhouse', b'--timeout', b'--retries'))
    assert result.stderr == b''
    assert _snapshot(project) == before


@WINDOWS
@pytest.mark.parametrize('help_arg', ['--help', '-h', '/?'])
@pytest.mark.parametrize('extra', [['--check'], [''], ['two words & ! ^']])
def test_help_requires_first_and_only_argument(project, help_arg, extra):
    result = _run(project, 'Setup.bat', [help_arg, *extra],
                  env=_environment(project, selection=HOSTILE), data=b'')
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert b'Python path: ' not in result.stdout
    _assert_not_invoked(project)


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
@pytest.mark.parametrize('data', [b'', b'\r\n'])
def test_prompt_blank_or_eof_cancels_without_execution(project, data, creationflags):
    result = _run(project, 'Setup.bat', ['--check'], env=_environment(project),
                  data=data, creationflags=creationflags)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert b'Python path: ' in result.stdout
    _assert_not_invoked(project)


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
@pytest.mark.parametrize('quoted', [False, True], ids=['bare', 'copy-as-path'])
def test_prompt_accepts_real_python_and_preserves_metacharacters(project, standard_python,
                                                               special_python, quoted, creationflags):
    selection = str(special_python)
    if quoted:
        selection = '"' + selection + '"'
    result = _run(project, 'Setup.bat', ['--check'], env=_environment(project, standard_python),
                  data=selection.encode('ascii') + b'\r\n\r\n', creationflags=creationflags)
    assert b'Python path: ' in result.stdout
    _receipt(project, result, ['--check'], special_python, 'setup_windows.py')


def _verified_prompt_bytes(project, standard_python, value, creationflags):
    # Redirected set /p input can differ from chcp's reported output encoding,
    # and CREATE_NO_WINDOW changes which console is inherited. Calibrate the
    # test transport in a standalone cmd stub, before testing the real BAT.
    # No codepage is changed and this probe cannot invoke setup or the app.
    probe = project / 'input-encoding-probe'
    probe.mkdir()
    (probe / 'capture.py').write_text(
        'import json, os\nprint("\\nINPUT_JSON:" + '
        'json.dumps(os.environ.get("AWB_BAT_INPUT"), ensure_ascii=True))\n', encoding='ascii')
    (probe / 'probe.bat').write_bytes(
        b'@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
        b'set /p "AWB_BAT_INPUT=Input: "\r\n'
        b'"%AWB_INPUT_PYTHON%" "%~dp0capture.py"\r\n')
    env = _environment(project, standard_python)
    env.pop('AWB_BAT_INPUT', None)
    env['AWB_INPUT_PYTHON'] = str(standard_python)
    chcp = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/chcp.com'
    reported = _run(probe, str(chcp), env=env, data=b'', creationflags=creationflags)
    assert reported.returncode == 0, (reported.stdout, reported.stderr)
    codepages = re.findall(rb'\d+', reported.stdout)
    assert len(codepages) == 1, reported.stdout
    encodings = dict.fromkeys(['cp' + codepages[0].decode('ascii'), 'utf-8'])
    observations = []
    for encoding in encodings:
        try:
            data = (value + '\r\n').encode(encoding)
        except UnicodeEncodeError:
            continue
        result = _run(probe, 'probe.bat', env=env, data=data, creationflags=creationflags)
        assert result.returncode == 0, (result.stdout, result.stderr)
        lines = [line.removeprefix(b'INPUT_JSON:') for line in result.stdout.splitlines()
                 if line.startswith(b'INPUT_JSON:')]
        assert len(lines) == 1, (result.stdout, result.stderr)
        observed = json.loads(lines[0].decode('ascii'))
        observations.append({'encoding': encoding, 'observed': observed})
        if observed == value:
            (probe / 'transport.json').write_text(json.dumps({
                'method': 'independent set/p stub; real Setup.bat not invoked during calibration',
                'creationflags': creationflags,
                'reported_codepage': codepages[0].decode('ascii'),
                'expected': value, 'observations': observations,
                'selected_encoding': encoding, 'exact_roundtrip': True,
            }, ensure_ascii=True, indent=2), encoding='ascii')
            return data
    pytest.skip('Existing redirected cmd input cannot represent the Unicode fixture; environment route still tested')


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
@pytest.mark.parametrize('quoted', [False, True])
def test_prompt_unicode_has_verified_input_encoding(project, standard_python, unicode_python, quoted, creationflags):
    selection = str(unicode_python)
    if quoted:
        selection = '"' + selection + '"'
    data = _verified_prompt_bytes(project, standard_python, selection, creationflags)
    result = _run(project, 'Setup.bat', env=_environment(project, standard_python),
                  data=data + b'\r\n', creationflags=creationflags)
    _receipt(project, result, ['--interactive'], unicode_python, 'setup_windows.py')


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
@pytest.mark.parametrize('quoted', [False, True])
def test_environment_python_skips_prompt_and_preserves_unicode_path(project, standard_python,
                                                                  unicode_python, quoted, creationflags):
    selection = str(unicode_python)
    if quoted:
        selection = '"' + selection + '"'
    result = _run(project, 'Setup.bat', ['--check'],
                  env=_environment(project, standard_python, selection), data=b'', creationflags=creationflags)
    assert b'Python path: ' not in result.stdout
    _receipt(project, result, ['--check'], unicode_python, 'setup_windows.py')


@WINDOWS
@pytest.mark.parametrize('route', ['prompt', 'environment'])
@pytest.mark.parametrize('selection', ['python', 'py', 'relative\\python.exe',
                                      '\\root-relative\\python.exe', 'C:python.exe',
                                      '\\\\server\\share\\python.exe',
                                      'C:\\missing\\python.exe', HOSTILE,
                                      '"C:\\bad"quote\\python.exe"',
                                      '""C:\\bad\\python.exe""'])
def test_invalid_or_embedded_quote_selection_does_not_execute(project, route, selection):
    env = _environment(project, selection=selection if route == 'environment' else None)
    data = (selection + '\r\n\r\n').encode('ascii') if route == 'prompt' else b''
    result = _run(project, 'Setup.bat', ['--check'], env=env, data=data)
    assert result.returncode != 0, (result.stdout, result.stderr)
    if route == 'environment':
        assert b'Python path: ' not in result.stdout
    _assert_not_invoked(project)


@WINDOWS
@pytest.mark.parametrize('missing', MARKERS)
def test_every_standard_library_marker_is_required_before_execution(project, missing):
    runtime = project / 'alias-like'
    runtime.mkdir()
    executable = runtime / 'python.exe'
    executable.write_bytes(b'not an executable; validation must reject it')
    for marker in MARKERS:
        if marker != missing:
            path = runtime / marker
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
    result = _run(project, 'Setup.bat', env=_environment(project, selection=executable))
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert b'Python path: ' not in result.stdout
    _assert_not_invoked(project)


@WINDOWS
def test_executable_name_must_be_python_exe(project):
    executable = project / 'pythonw.exe'
    executable.write_bytes(b'not an executable')
    for marker in MARKERS:
        path = project / marker
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    result = _run(project, 'Setup.bat', env=_environment(project, selection=executable))
    assert result.returncode != 0, (result.stdout, result.stderr)
    _assert_not_invoked(project)


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
@pytest.mark.parametrize('arguments', [
    ['--check', '--certificate', r'C:\会社 CA & ! 50% ^\証明書.pem', '--timeout', '120', '--retries', '2'],
    ['--wheelhouse', r'C:\Approved Packages & ! 50% ^\wheelhouse'],
    ['--unknown'], ['--check', '/?'], ['--project-root', ''], ['--interactive', '--check'],
    [''], ['unknown words & ! (value) ^'],
])
def test_setup_forwards_all_arguments_and_exit_status(project, standard_python, arguments, creationflags):
    result = _run(project, 'Setup.bat', arguments,
                  env=_environment(project, standard_python, standard_python), creationflags=creationflags)
    _receipt(project, result, arguments, standard_python, 'setup_windows.py')


def _interactive_installer_fixture(project):
    """Use the actual Python prompts/validation/planner; stub every child command.

    No pip, environment creation, application or network can run behind this
    fixture. Only the outer BAT and approved installed Python execute natively.
    """
    implementation = project / 'scripts/setup_implementation.py'
    shutil.copy2(ROOT / 'scripts/setup_windows.py', implementation)
    for relative in ('requirements.lock', 'pyproject.toml', 'workbench/server.py',
                     'static/index.html', 'docs/interface.json'):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture', encoding='ascii')
    (project / 'scripts/setup_windows.py').write_text(
        'import importlib.util, json, os, sys\nfrom pathlib import Path\n'
        'spec = importlib.util.spec_from_file_location("installer", '
        'Path(__file__).with_name("setup_implementation.py"))\n'
        'setup = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(setup)\n'
        'calls = []\n'
        'def runner(args, **kwargs):\n'
        '    calls.append(list(map(str, args)))\n'
        '    return setup.CONFIG_MARKER if kwargs.get("capture") else ""\n'
        'original_install = setup.install\n'
        'setup.install = lambda options: original_install(options, runner=runner)\n'
        'code = setup.main()\n'
        'record = {"args": sys.argv[1:], "executable": sys.executable, '
        '"script": Path(__file__).name, "cwd": os.getcwd(), "calls": calls}\n'
        'with Path("python-receipt.json").open("x", encoding="ascii") as stream:\n'
        '    json.dump(record, stream, ensure_ascii=True)\n'
        'print("\\nBAT_FIXTURE:" + json.dumps(record, ensure_ascii=True))\n'
        'raise SystemExit(code)\n', encoding='ascii')


def _run_prompted_interactive(project, executable, env, data, creationflags):
    # cmd's set /p can read ahead and discard later lines from redirected
    # input. Send the Python path alone, then wait for Python's actual prompt
    # before supplying network answers, as a person using the console would.
    cmd = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/cmd.exe'
    args = [str(cmd), '/d', '/v:off', '/c', 'Setup.bat']
    process = subprocess.Popen(args, cwd=project, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=creationflags, bufsize=0)
    prefix = bytearray()

    def read_until_prompt():
        while not prefix.endswith(b'Proxy URL '):
            value = process.stdout.read(1)
            if not value:
                return
            prefix.extend(value)

    reader = threading.Thread(target=read_until_prompt, daemon=True)
    reader.start()
    try:
        process.stdin.write((str(executable) + '\r\n').encode('ascii'))
        process.stdin.flush()
        reader.join(timeout=20)
        if reader.is_alive():
            process.kill()
            reader.join(timeout=5)
            pytest.fail('Interactive Python prompt was not reached: ' + repr(bytes(prefix)))
        assert prefix.endswith(b'Proxy URL '), bytes(prefix)
        out, err = process.communicate(data, timeout=20)
        return subprocess.CompletedProcess(args, process.returncode, bytes(prefix) + out, err)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
@pytest.mark.parametrize('route', ['environment', 'prompt'])
@pytest.mark.parametrize('network', ['proxy-ca', 'blank', 'invalid-proxy', 'invalid-ca', 'eof-first', 'eof-second'])
def test_real_bat_to_interactive_python_keeps_network_input_out_of_cmd(
        project, standard_python, route, network, creationflags):
    _interactive_installer_fixture(project)
    certificate = project / '会社 CA & ! 50% ^ (trusted).pem'
    certificate.write_text('local fixture; no TLS operation is performed', encoding='ascii')
    lines = {
        'proxy-ca': 'http://approved.example:8080\n"' + str(certificate) + '"\n',
        'blank': '\n\n',
        'invalid-proxy': 'http://secret-user:secret-pass@proxy.example:8080\n\n',
        'invalid-ca': '\nmissing-secret-ca.pem\n',
        'eof-first': '',
        'eof-second': 'http://approved.example:8080\n',
    }[network]
    env = _environment(project, standard_python,
                       standard_python if route == 'environment' else None)
    # This is the declared pipe transport. Real Windows console input is
    # Unicode; cmd's Python-path prompt is ASCII for this integration fixture.
    env['PYTHONIOENCODING'] = 'utf-8'
    data = lines.replace('\n', '\r\n').encode('utf-8')
    if route == 'prompt':
        assert str(standard_python).isascii()
        result = _run_prompted_interactive(project, standard_python, env, data, creationflags)
    else:
        result = _run(project, 'Setup.bat', env=env, data=data, creationflags=creationflags)
    success = network in ('proxy-ca', 'blank')
    _receipt(project, result, ['--interactive'], standard_python, 'setup_windows.py',
             exit_code=0 if success else 1)
    saved = json.loads((project / 'python-receipt.json').read_text(encoding='ascii'))
    assert b'Proxy URL ' in result.stdout
    assert not (project / '.venv').exists()
    if success:
        dep, app = [args for args in saved['calls'] if 'install' in args]
        if network == 'proxy-ca':
            assert dep[dep.index('--proxy') + 1] == 'http://approved.example:8080'
            assert dep[dep.index('--cert') + 1] == str(certificate)
        else:
            assert '--proxy' not in dep and '--cert' not in dep
        assert '--no-index' in app and '--proxy' not in app and '--cert' not in app
    else:
        assert saved['calls'] == []
        if network.startswith('eof-'):
            assert b'Setup cancelled before installation' in result.stderr
        elif network == 'invalid-proxy':
            assert b'Proxy must be an HTTP(S) origin' in result.stderr
        elif network == 'invalid-ca':
            assert b'Certificate must be an existing organization-approved PEM CA bundle.' in result.stderr
        assert b'secret-user' not in result.stdout + result.stderr
        assert b'secret-pass' not in result.stdout + result.stderr
        assert b'missing-secret-ca' not in result.stdout + result.stderr


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
def test_launch_without_private_environment_points_to_setup_bat(project, creationflags):
    result = _run(project, 'Launch.bat', env=_environment(project, selection=HOSTILE),
                  creationflags=creationflags)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert b'Setup.bat' in result.stdout
    assert b'Setup.cmd' not in result.stdout
    _assert_not_invoked(project)


@WINDOWS
@pytest.mark.parametrize('creationflags', CONSOLES, ids=['console', 'no-console'])
@pytest.mark.parametrize('exit_code', [0, 17])
def test_launch_uses_private_python_and_forwards_arguments_and_status(project, standard_python,
                                                                   creationflags, exit_code):
    executable = _runtime_copy(project / '.venv/Scripts', standard_python)
    arguments = ['--fixture-option', '会社 path & ! 50% ^', '--empty', '']
    env = _environment(project, standard_python, HOSTILE)
    env['AWB_BAT_FIXTURE_EXIT'] = str(exit_code)
    result = _run(project, 'Launch.bat', arguments, env=env, creationflags=creationflags)
    _receipt(project, result, arguments, executable, 'start_workbench.py', exit_code)
