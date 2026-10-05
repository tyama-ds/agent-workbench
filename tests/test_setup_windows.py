"""Installer command planning is testable without Windows, network or package installation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup_windows', ROOT / 'scripts/setup_windows.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / '会社 project & spaces !'
    root.mkdir()
    for relative in ('requirements.lock', 'pyproject.toml', 'workbench/server.py', 'static/index.html', 'docs/interface.json'):
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text('fixture', encoding='utf-8')
    return root


def execute(project, *arguments, fail=None):
    options = setup.parser().parse_args(['--project-root', str(project), *map(str, arguments)])
    calls = []
    def runner(args, **kwargs):
        args = list(map(str, args))
        calls.append((args, kwargs))
        if fail and fail(args):
            raise RuntimeError('simulated failure')
    setup.install(options, runner=runner)
    return calls


def installs(calls):
    return [args for args, _ in calls if args[1:4] == ['-m', 'pip', 'install']]


def test_fresh_install_hashes_binaries_local_build_and_health_checks(project):
    calls = execute(project)
    assert calls[0][0][1:3] == ['-m', 'venv']
    dep, app = installs(calls)
    assert '--require-hashes' in dep and '--only-binary=:all:' in dep
    assert dep[dep.index('-r') + 1] == str(project / 'requirements.lock')
    assert all(item in app for item in ('--no-index', '--no-deps', '--no-build-isolation'))
    assert calls[-2][0][1:] == ['-m', 'pip', 'check']
    assert 'import workbench.server' in calls[-1][0][-1]
    assert all(kwargs['cwd'] == project for _, kwargs in calls)


def test_reinstall_reuses_environment(project):
    python = project / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    python.parent.mkdir(parents=True)
    python.write_bytes(b'fixture')
    calls = execute(project)
    assert not any(args[1:3] == ['-m', 'venv'] for args, _ in calls)
    assert python.read_bytes() == b'fixture'


def test_incomplete_venv_is_preserved(project):
    (project / '.venv').mkdir()
    with pytest.raises(ValueError, match='incomplete'):
        execute(project)
    assert (project / '.venv').is_dir()


def test_check_only_does_not_run_commands_or_create_venv(project, capsys):
    assert execute(project, '--check') == []
    assert not (project / '.venv').exists()
    assert 'No packages installed' in capsys.readouterr().out


def test_proxy_certificate_and_inherited_config(project, monkeypatch):
    certificate = project / 'company CA.pem'
    certificate.write_text('fixture')
    monkeypatch.setenv('HTTPS_PROXY', 'http://inherited.example:8080')
    calls = execute(project, '--proxy', 'http://proxy.example:3128', '--certificate', certificate)
    dep, app = installs(calls)
    assert dep[dep.index('--proxy') + 1] == 'http://proxy.example:3128'
    assert dep[dep.index('--cert') + 1] == str(certificate)
    assert '--proxy' not in app  # local-only build
    assert calls[-1][1]['env']['HTTPS_PROXY'] == 'http://inherited.example:8080'
    assert '--trusted-host' not in dep


def test_offline_ignores_external_find_links_and_config(project, monkeypatch):
    wheels = project / 'wheel house'
    wheels.mkdir()
    (wheels / 'fixture.whl').write_bytes(b'fixture')
    monkeypatch.setenv('PIP_FIND_LINKS', 'https://remote.example/wheels')
    calls = execute(project, '--wheelhouse', wheels)
    dep, app = installs(calls)
    assert '--no-index' in dep and '--no-index' in app
    assert dep[dep.index('--find-links') + 1] == str(wheels)
    for args, kwargs in calls:
        if args[1:4] == ['-m', 'pip', 'install']:
            assert 'PIP_FIND_LINKS' not in kwargs['env']
            assert kwargs['env']['PIP_CONFIG_FILE'] == os.devnull
    assert os.environ['PIP_FIND_LINKS'].startswith('https://')


@pytest.mark.parametrize('proxy', ['proxy:8080', 'http://user:password@proxy', 'socks5://proxy:1234',
                                  'http://proxy/proxy.pac', 'http://proxy?x=secret', 'http://proxy#secret',
                                  'http://proxy:0', 'http://proxy:99999', 'http://proxy\\path'])
def test_invalid_proxy(proxy):
    with pytest.raises(ValueError):
        setup.validate_proxy(proxy)


@pytest.mark.parametrize('version,bits,implementation', [((3, 10), 64, 'CPython'), ((3, 14), 64, 'CPython'),
                                                       ((3, 13), 32, 'CPython'), ((3, 13), 64, 'PyPy')])
def test_unsupported_python(version, bits, implementation):
    assert not setup.python_supported(version, bits, implementation)


def test_missing_files_and_readonly_folder(project, monkeypatch):
    def denied(**kwargs):
        raise PermissionError
    monkeypatch.setattr(setup.tempfile, 'TemporaryFile', denied)
    with pytest.raises(ValueError, match='not writable'):
        execute(project)
    (project / 'static/index.html').unlink()
    with pytest.raises(ValueError, match='entire ZIP'):
        execute(project)


@pytest.mark.parametrize('option,value', [('--timeout', '4'), ('--retries', '11'), ('--certificate', 'missing'), ('--wheelhouse', 'missing')])
def test_invalid_options(project, option, value):
    with pytest.raises((ValueError, SystemExit)):
        execute(project, option, value)


@pytest.mark.parametrize('stage', ['venv', 'pip', 'install', 'check', '-c'])
def test_failure_propagates_without_success_message(project, capsys, stage):
    with pytest.raises(RuntimeError):
        execute(project, fail=lambda args: stage in args)
    assert 'Setup complete' not in capsys.readouterr().out


def test_diagnostics_omit_proxy_values(project, monkeypatch, capsys):
    monkeypatch.setenv('HTTPS_PROXY', 'http://secret-user:secret-password@internal.example:8080')
    execute(project, '--check')
    output = capsys.readouterr().out
    assert 'secret' not in output and 'internal.example' not in output
    assert '"proxy_configured": true' in output


@pytest.mark.parametrize('key', ['PIP_TARGET', 'PIP_PREFIX', 'PIP_USER'])
def test_redirected_pip_install_refused(project, monkeypatch, key):
    monkeypatch.setenv(key, '1')
    with pytest.raises(ValueError, match=key):
        execute(project)


def test_cmd_entrypoints_do_not_bypass_policy():
    for name in ('Setup.cmd', 'Launch.cmd'):
        content = (ROOT / name).read_text()
        assert 'ExecutionPolicy' not in content and 'powershell' not in content.lower()
        assert 'DisableDelayedExpansion' in content


@pytest.mark.skipif(os.name != 'nt', reason='Windows cmd.exe required')
def test_real_cmd_check_with_unicode_and_spaces(tmp_path):
    import shutil
    project = tmp_path / '会社 project & spaces !'
    shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns('.git', '.venv', '__pycache__', 'runtime'))
    env = dict(os.environ, WORKBENCH_PYTHON=sys.executable)
    # Launch as a user would from the extracted project directory. Passing a
    # quoted batch path as a subprocess argument invokes cmd's special /c
    # quote stripping, before the batch file itself can protect its paths.
    result = subprocess.run(['cmd.exe', '/d', '/c', 'Setup.cmd', '--check'],
                            cwd=project, input='\n', text=True, capture_output=True,
                            env=env, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Preflight complete' in result.stdout


def test_free_threaded_python_refused():
    assert not setup.python_supported((3, 13), 64, 'CPython', True)


def test_offline_rejects_network_options(project):
    wheelhouse = project / 'wheels'
    wheelhouse.mkdir()
    (wheelhouse / 'fixture.whl').write_bytes(b'fixture')
    with pytest.raises(ValueError, match='Offline'):
        execute(project, '--wheelhouse', wheelhouse, '--proxy', 'http://proxy:8080')


@pytest.mark.parametrize('key', ['PIP_REQUIREMENT', 'PIP_CONSTRAINT', 'PIP_EDITABLE', 'PIP_BUILD_CONSTRAINT', 'PIP_TARGET'])
def test_offline_removes_all_injected_pip_inputs(project, monkeypatch, key):
    wheelhouse = project / 'wheels'
    wheelhouse.mkdir()
    (wheelhouse / 'fixture.whl').write_bytes(b'fixture')
    monkeypatch.setenv(key, 'https://remote.example/input')
    calls = execute(project, '--wheelhouse', wheelhouse)
    for _, kwargs in calls:
        assert key not in kwargs['env']


@pytest.mark.parametrize('config', ["global.target='elsewhere'", "install.user='true'", "global.requirement='https://remote.example/requirements.txt'", "install.editable='https://remote.example/code.git'"])
def test_online_rejects_extra_pip_config(project, config):
    options = setup.parser().parse_args(['--project-root', str(project)])
    calls = []
    def runner(args, **kwargs):
        calls.append(list(map(str, args)))
        return config if kwargs.get('capture') else ''
    with pytest.raises(ValueError, match='pip configuration'):
        setup.install(options, runner=runner)
    assert installs([(args, {}) for args in calls]) == []


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell 5.1 required')
def test_ps51_wrapper_check_with_explicit_python(project):
    # CI only: process-local Bypass lets the test exercise the compatibility wrapper.
    # Shipping entrypoints never change execution policy.
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(ROOT / 'scripts/Setup-Windows.ps1'), '-ProjectRoot', str(project),
                             '-PythonExecutable', sys.executable, '-CheckOnly'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Preflight complete' in result.stdout
