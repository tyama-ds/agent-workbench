"""Native configured launcher checks without application imports or installations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def standard_python():
    executable = Path(getattr(sys, '_base_executable', None) or sys.executable)
    required = ('Lib/os.py', 'Lib/venv/__init__.py', 'Lib/ensurepip/__init__.py')
    if (not executable.is_absolute() or executable.name.lower() != 'python.exe'
            or not executable.is_file()
            or not all((executable.parent / relative).is_file() for relative in required)):
        pytest.skip('A separately installed standard Windows CPython is required')
    return str(executable)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "会社 configured & spaces ! % apostrophe ' (source)"
    root.mkdir()
    shutil.copy2(ROOT / 'Launch-Configured.cmd', root / 'Launch-Configured.cmd')
    (root / 'scripts').mkdir()
    (root / 'scripts/configured_runtime.py').write_text(
        "import json, pathlib, sys\n"
        "root = pathlib.Path(__file__).resolve().parents[1]\n"
        "config_path = pathlib.Path(sys.argv[sys.argv.index('--config') + 1])\n"
        "config = json.loads(config_path.read_text(encoding='utf-8-sig'))\n"
        "result = {'argv': sys.argv[1:], 'config': config, 'isolated': sys.flags.isolated, "
        "'no_site': sys.flags.no_site, 'no_bytecode': sys.flags.dont_write_bytecode}\n"
        "(root / 'invoked.json').write_text(json.dumps(result), encoding='utf-8')\n"
        "print('CONFIGURED_PROBE')\n"
        "raise SystemExit(config.get('probe_exit', 0))\n",
        encoding='utf-8')
    return root


def run_cmd(project, *arguments, env=None):
    return subprocess.run(
        [shutil.which('cmd.exe'), '/d', '/c', 'Launch-Configured.cmd', *arguments],
        cwd=project, env=env, input='', text=True, errors='replace',
        capture_output=True, timeout=30)


def write_config(project, value, *, encoding='utf-8'):
    (project / 'runtime.local.json').write_text(json.dumps(value, ensure_ascii=False), encoding=encoding)


def test_bootstrap_uses_fixed_code_without_policy_or_runtime_installation():
    command = (ROOT / 'Launch-Configured.cmd').read_text(encoding='ascii')
    assert 'setlocal DisableDelayedExpansion' in command
    assert '-NoProfile -NonInteractive -Command' in command
    assert "@('-I','-S','-B'" in command
    assert '& $python @arguments' in command
    for forbidden in ('Invoke-Expression', '-ExecutionPolicy', 'Set-ExecutionPolicy',
                      'for /f', 'PYTHON_MANAGER_', 'PYLAUNCHER_', 'pip install'):
        assert forbidden.lower() not in command.lower()


@pytest.mark.skipif(os.name != 'nt', reason='Windows CMD and built-in PowerShell required')
@pytest.mark.parametrize('arguments', [(), ('--check',)])
@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig'])
def test_real_configured_bootstrap_preserves_json_and_isolates_python(project, standard_python, arguments, encoding):
    # A real interpreter reached through this existing, awkwardly named directory
    # exercises literal path handling without copying or modifying Python itself.
    try:
        selected_python = project / os.path.relpath(standard_python, project)
    except ValueError:  # CI may keep Python and temporary files on different drives.
        selected_python = Path(standard_python)
    payload = {
        'python_executable': str(selected_python).replace('\\', '/'),
        'library_paths': [str(project / "libraries & ! % ' 日本語")],
        'state_dir': "C:/state & ! % ' $(Set-Content injected.txt bad)",
        'arbitrary_data': '"; Set-Content injected.txt bad; #',
    }
    write_config(project, payload, encoding=encoding)
    poison = project / 'poison'
    poison.mkdir()
    (poison / 'sitecustomize.py').write_text('raise RuntimeError("must not run")\n', encoding='ascii')
    (poison / 'json.py').write_text('raise RuntimeError("must not load")\n', encoding='ascii')
    env = dict(os.environ, PATH=str(project), PYTHONPATH=str(poison), PYTHONHOME=str(poison))
    result = run_cmd(project, *arguments, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'CONFIGURED_PROBE'
    assert result.stderr == ''
    observed = json.loads((project / 'invoked.json').read_text(encoding='utf-8'))
    assert observed['argv'] == ['--config', str(project / 'runtime.local.json'), *arguments]
    assert observed['config'] == payload
    assert observed['isolated'] == observed['no_site'] == observed['no_bytecode'] == 1
    assert not (project / 'injected.txt').exists()
    assert not (project / '.venv').exists()
    assert not list(project.rglob('__pycache__'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows CMD required')
@pytest.mark.parametrize('config', ['absent', 'invalid'])
def test_real_configured_help_does_not_require_python_json_or_powershell(project, config):
    if config == 'invalid':
        (project / 'runtime.local.json').write_text('invalid JSON', encoding='utf-8')
    env = dict(os.environ, SystemRoot=str(project / 'missing-system'), PATH=str(project))
    result = run_cmd(project, '--help', env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ''
    assert 'Agent Workbench configured launch' in result.stdout
    assert not (project / 'invoked.json').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows CMD required')
@pytest.mark.parametrize('arguments', [
    ('--unknown',), ('--port', '8818'), ('',), ('--help', '--check'),
    ('--check', '--help'), ('--check', ''), ('--help', '', '--check'),
    ('--check', "two words & marks ! % apostrophe '"),
])
def test_real_configured_bootstrap_rejects_arguments_before_start(project, arguments):
    result = run_cmd(project, *arguments)
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr == ''
    assert 'Nothing was started' in result.stdout
    assert not (project / 'invoked.json').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows CMD and built-in PowerShell required')
@pytest.mark.parametrize('selection', [
    'missing-config', 'invalid-json', 'missing-key', 'null', 'number',
    'relative', 'missing-python', 'alias', 'injected-path',
])
def test_real_configured_bootstrap_rejects_unusable_interpreter_without_invoking_it(project, selection):
    alias = project / 'python.exe'
    alias.write_bytes(b'not an executable')
    payload = {
        'missing-key': {}, 'null': {'python_executable': None},
        'number': {'python_executable': 42},
        'relative': {'python_executable': 'python.exe'},
        'missing-python': {'python_executable': str(project / 'missing/python.exe')},
        'alias': {'python_executable': str(alias)},
        'injected-path': {'python_executable': 'C:/bad"; Set-Content injected.txt bad; #/python.exe'},
    }
    if selection == 'invalid-json':
        (project / 'runtime.local.json').write_text('not json', encoding='utf-8')
    elif selection != 'missing-config':
        write_config(project, payload[selection])
    result = run_cmd(project, '--check')
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Configured launch stopped:' in result.stderr
    assert result.stdout == ''  # --check errors must not pause or start Python.
    assert not (project / 'invoked.json').exists()
    assert not (project / 'injected.txt').exists()
    assert 'not a valid Win32' not in result.stderr


@pytest.mark.skipif(os.name != 'nt', reason='Windows CMD and built-in PowerShell required')
def test_real_configured_check_preserves_python_exit_status_without_pause(project, standard_python):
    write_config(project, {'python_executable': standard_python, 'probe_exit': 17})
    result = run_cmd(project, '--check')
    assert result.returncode == 17, result.stdout + result.stderr
    assert result.stdout.strip() == 'CONFIGURED_PROBE'
    assert result.stderr == ''
