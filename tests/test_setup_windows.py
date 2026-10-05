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
        return setup.CONFIG_MARKER if kwargs.get('capture') else ''
    setup.install(options, runner=runner)
    return calls


def installs(calls):
    return [args for args, _ in calls if args[1:3] == ['-m', 'pip'] and 'install' in args]


def test_fresh_install_hashes_binaries_local_build_and_health_checks(project):
    calls = execute(project)
    assert calls[0][0][1:3] == ['-m', 'venv']
    dep, app = installs(calls)
    assert '--require-hashes' in dep and '--only-binary=:all:' in dep
    assert dep[dep.index('-r') + 1] == str(project / 'requirements.lock')
    assert all(item in app for item in ('--no-index', '--no-deps', '--no-build-isolation'))
    assert calls[-2][0][1:4] == ['-m', 'pip', '--python']
    assert calls[-2][0][-1] == 'check'
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
        if args[1:3] == ['-m', 'pip'] and 'install' in args:
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


@pytest.mark.parametrize('key', ['PIP_TARGET', 'PIP_PREFIX', 'PIP_USER', 'PIP_ROOT', 'PIP_PYTHON', 'PIP_TRUSTED_HOST'])
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
    env = dict(os.environ, WORKBENCH_PYTHON=sys.executable,
               PYLAUNCHER_ALLOW_INSTALL="1", PYLAUNCHER_ALWAYS_INSTALL="1",
               PYTHON_MANAGER_AUTOMATIC_INSTALL="true")
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


@pytest.mark.parametrize('config', ["global.target='elsewhere'", "install.user='true'", "global.requirement='https://remote.example/requirements.txt'", "install.editable='https://remote.example/code.git'", "global.python='elsewhere'", "install.root='elsewhere'", "global.trusted-host='internal.example'"])
def test_online_rejects_extra_pip_config(project, config):
    options = setup.parser().parse_args(['--project-root', str(project)])
    calls = []
    def runner(args, **kwargs):
        calls.append(list(map(str, args)))
        return setup.CONFIG_MARKER + '\n' + config if kwargs.get('capture') else ''
    with pytest.raises(setup.SetupStageError, match='pip configuration'):
        setup.install(options, runner=runner)
    assert installs([(args, {}) for args in calls]) == []


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell 5.1 required')
def test_ps51_wrapper_check_with_explicit_python(project):
    # Exercise the wrapper under the runner's existing execution policy.
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                             '-File', str(ROOT / 'scripts/Setup-Windows.ps1'), '-ProjectRoot', str(project),
                             '-PythonExecutable', sys.executable, '-CheckOnly'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Preflight complete' in result.stdout


@pytest.mark.parametrize('option', setup.FORBIDDEN_PIP_OPTIONS)
def test_forbidden_environment_stops_before_any_child_and_omits_value(project, monkeypatch, capsys, option):
    secret = 'secret-user:secret-password@internal.example'
    monkeypatch.setenv('PIP_' + option, secret)
    calls = []
    with pytest.raises(ValueError) as error:
        setup.install(setup.parser().parse_args(['--project-root', str(project)]),
                      runner=lambda *args, **kwargs: calls.append(args))
    assert calls == [] and not (project / '.venv').exists()
    assert secret not in str(error.value) + capsys.readouterr().out
    assert os.environ['PIP_' + option] == secret


def test_every_pip_invocation_is_pinned_and_installs_require_venv(project):
    calls = execute(project)
    for args, _ in calls:
        if args[1:3] == ['-m', 'pip']:
            assert args[3:5] == ['--python', args[0]]
    for args in installs(calls):
        assert '--require-virtualenv' in args


@pytest.mark.parametrize('stage', setup.STAGES)
def test_stage_errors_never_echo_command_config_or_exception(stage, capsys):
    secret = 'secret-password@internal.example'
    def fail(*args, **kwargs):
        raise OSError('blocked ' + secret)
    with pytest.raises(setup.SetupStageError) as error:
        setup.run_stage(stage, fail, [secret])
    assert setup.STAGES[stage][0] in str(error.value)
    assert secret not in str(error.value) + capsys.readouterr().out


def test_approved_transport_configuration_is_preserved(project, monkeypatch):
    monkeypatch.setenv('PIP_INDEX_URL', 'https://mirror.example/simple')
    monkeypatch.setenv('PIP_CERT', 'approved.pem')
    calls = []
    def runner(args, **kwargs):
        calls.append((list(map(str, args)), kwargs))
        return setup.CONFIG_MARKER + "\nglobal.index-url='https://mirror.example/simple'\nglobal.proxy='http://proxy.example:8080'\nglobal.cert='approved.pem'" if kwargs.get('capture') else ''
    setup.install(setup.parser().parse_args(['--project-root', str(project)]), runner=runner)
    assert len(installs(calls)) == 2
    assert all(kw['env']['PIP_INDEX_URL'] == 'https://mirror.example/simple' for _, kw in calls)
    assert all(kw['env']['PIP_CERT'] == 'approved.pem' for _, kw in calls)


def test_old_pip_fails_closed_without_installing_or_upgrading(project):
    calls = []
    def runner(args, **kwargs):
        args = list(map(str, args)); calls.append((args, kwargs))
        if '--version' in args:
            raise RuntimeError('no such option: --python')
    with pytest.raises(setup.SetupStageError, match='pip 22.3 or newer'):
        setup.install(setup.parser().parse_args(['--project-root', str(project)]), runner=runner)
    assert installs(calls) == []
    assert not any('--upgrade' in args for args, _ in calls)


def test_real_pip_config_probe_cannot_run_alternate_interpreter(tmp_path, monkeypatch):
    # No packages or network: a hostile config targets a script that would leave
    # evidence if executed. The explicit CLI target must win before config reads.
    import importlib.util
    if importlib.util.find_spec('pip') is None:
        pytest.skip('pip required for read-only config probe')
    config = tmp_path / 'pip.ini'
    marker = tmp_path / 'unexpected-execution'
    alternate = tmp_path / ('alternate.cmd' if os.name == 'nt' else 'alternate-python')
    if os.name == 'nt':
        alternate.write_text('@echo off\necho unexpected > "' + str(marker) + '"\nexit /b 91\n', encoding='utf-8')
    else:
        alternate.write_text('#!/bin/sh\nprintf unexpected > "' + str(marker) + '"\nexit 91\n', encoding='utf-8')
        alternate.chmod(0o700)
    config.write_text('[global]\npython = ' + str(alternate) + '\n', encoding='utf-8')
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('PIP_')}
    env.update(PIP_CONFIG_FILE=str(config), PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1')
    result = subprocess.run([sys.executable, '-m', 'pip', '--python', sys.executable, 'config', 'list'],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'global.python=' in result.stdout
    assert not marker.exists()


def test_interpreter_probe_rejects_supported_python_outside_expected_venv(project):
    calls = execute(project)
    args = next(args for args, _ in calls if '-c' in args)
    # Execute only the fixed stdlib validation code with a mismatched expected prefix.
    result = subprocess.run([sys.executable, '-c', args[args.index('-c') + 1], str(project / '.venv')],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0


@pytest.mark.parametrize('hidden_output', ['', 'Usage: pip config [options]', "global.index-url='https://mirror.example'"])
def test_unverified_config_output_fails_closed(project, hidden_output):
    calls = []
    def runner(args, **kwargs):
        calls.append((list(map(str, args)), kwargs))
        return hidden_output if kwargs.get('capture') else ''
    with pytest.raises(setup.SetupStageError, match='Complete configuration output'):
        setup.install(setup.parser().parse_args(['--project-root', str(project)]), runner=runner)
    assert installs(calls) == []


@pytest.mark.parametrize('selector', ['quiet', 'global', 'site', 'user', 'isolated'])
def test_real_config_inspection_resists_selectors_quiet_and_logging(tmp_path, selector):
    import importlib.util
    if importlib.util.find_spec('pip') is None:
        pytest.skip('pip required for read-only config probe')
    secret = 'secret-user:secret-password@internal.example'
    leak_log = tmp_path / 'unsafe-pip.log'
    config = tmp_path / 'pip.ini'
    config.write_text('[global]\nroot = ' + secret + '\nlog = ' + str(leak_log) +
                      '\nquiet = 50\n[config]\n' + selector + ' = 1\n', encoding='utf-8')
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('PIP_')}
    env.update(PIP_CONFIG_FILE=str(config), PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1')
    env.update({'PIP_' + key: '0' for key in setup.INSPECTION_OPTIONS})
    result = subprocess.run([sys.executable, '-m', 'pip', '--python', sys.executable,
                             '--log', os.devnull, 'config', 'list'], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert setup.CONFIG_MARKER in result.stdout.splitlines()
    assert 'global.root=' in result.stdout
    assert not leak_log.exists()


def test_inspection_controls_do_not_mutate_install_environment(project, monkeypatch):
    monkeypatch.setenv('PIP_QUIET', '3')
    monkeypatch.setenv('PIP_SITE', '1')
    calls = execute(project)
    inspection = next((args, kw) for args, kw in calls if args[-2:] == ['config', 'list'])
    assert inspection[1]['env']['PIP_QUIET'] == '0'
    assert inspection[1]['env']['PIP_SITE'] == '0'
    assert inspection[0][inspection[0].index('--log') + 1] == os.devnull
    for args in installs(calls):
        kw = next(kw for call, kw in calls if call == args)
        assert kw['env']['PIP_QUIET'] == '3' and kw['env']['PIP_SITE'] == '1'
    assert os.environ['PIP_QUIET'] == '3' and os.environ['PIP_SITE'] == '1'



def test_redirected_venv_folder_is_preserved_and_rejected(project, tmp_path):
    outside = tmp_path / 'separate environment'
    outside.mkdir()
    marker = outside / 'existing.txt'
    marker.write_text('preserve', encoding='utf-8')
    try:
        (project / '.venv').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('directory symlinks unavailable')
    calls = []
    with pytest.raises(ValueError, match='redirects'):
        setup.install(setup.parser().parse_args(['--project-root', str(project)]),
                      runner=lambda *args, **kwargs: calls.append(args))
    assert not calls
    assert marker.read_text(encoding='utf-8') == 'preserve'
    assert (project / '.venv').is_symlink()



def test_real_setup_rejects_hidden_redirect_before_dependency_install(project, monkeypatch, capsys):
    secret = 'secret-password@internal.example'
    config = project / 'approved-pip.ini'
    leak_log = project / 'must-not-exist.log'
    config.write_text('[global]\nroot = ' + secret + '\nquiet = 50\nlog = ' + str(leak_log) +
                      '\n[config]\nsite = true\n', encoding='utf-8')
    monkeypatch.setenv('PIP_CONFIG_FILE', str(config))
    monkeypatch.setenv('PIP_QUIET', '1')
    monkeypatch.setenv('PIP_SITE', '1')
    calls = []
    def runner(args, **kwargs):
        args = list(map(str, args)); calls.append((args, kwargs))
        assert not (args[1:3] == ['-m', 'pip'] and 'install' in args), 'must reject before dependency installation'
        return setup.invoke(args, **kwargs)
    with pytest.raises(setup.SetupStageError, match='pip setting redirects') as error:
        setup.install(setup.parser().parse_args(['--project-root', str(project)]), runner=runner)
    assert installs(calls) == []
    assert secret not in str(error.value) + capsys.readouterr().out
    assert not leak_log.exists()
    assert config.read_text(encoding='utf-8').startswith('[global]\nroot = ' + secret)



def test_captured_python_output_uses_private_utf8_contract(tmp_path):
    env = dict(os.environ, PYTHONIOENCODING='cp1252')
    text = setup.invoke([sys.executable, '-c', "print('\\u4f1a\\u793e path')"], cwd=tmp_path, env=env, capture=True)
    assert text.strip() == '\u4f1a\u793e path'
    assert env['PYTHONIOENCODING'] == 'cp1252'


def test_setup_entrypoints_use_only_explicit_standard_interpreter():
    cmd = (ROOT / 'Setup.cmd').read_text()
    ps = (ROOT / 'scripts/Setup-Windows.ps1').read_text()
    assert 'if not defined WORKBENCH_PYTHON goto python_required' in cmd
    assert '"%WORKBENCH_PYTHON%" "%~dp0scripts\\setup_windows.py"' in cmd
    assert 'Get-Command' not in ps
    assert '& $PythonExecutable @arguments' in ps
    assert '$env:WORKBENCH_PYTHON' in ps
    import re
    assert not re.search(r'(?m)^\s*(?:call\s+)?(?:py|python)(?:\s|$)', cmd, re.I)
    for relative in ('Lib\\os.py', 'Lib\\venv\\__init__.py', 'Lib\\ensurepip\\__init__.py'):
        assert relative in cmd and relative in ps
    for text in (cmd, ps):
        assert 'PYTHON_MANAGER_' not in text  # no overrideable install-on-demand workaround
        assert 'PYLAUNCHER_' not in text


@pytest.mark.skipif(os.name != 'nt', reason='Windows cmd.exe required')
@pytest.mark.parametrize('selection', ['', 'python', 'relative\\python.exe', 'missing', 'alias'])
def test_real_cmd_rejects_missing_or_alias_runtime_without_invocation(tmp_path, selection):
    import shutil
    project = tmp_path / 'source & spaces !'
    project.mkdir()
    shutil.copy2(ROOT / 'Setup.cmd', project / 'Setup.cmd')
    # An alias-like executable path without a standard runtime layout is rejected
    # before Windows can attempt to execute it. No executable fixture is built.
    alias = project / 'python.exe'
    alias.write_text('not an executable')
    selected = str(alias) if selection == 'alias' else str(project / 'missing' / 'python.exe') if selection == 'missing' else selection
    env = dict(os.environ, WORKBENCH_PYTHON=selected,
               PYLAUNCHER_ALLOW_INSTALL='1', PYLAUNCHER_ALWAYS_INSTALL='1',
               PYTHON_MANAGER_AUTOMATIC_INSTALL='true')
    result = subprocess.run(['cmd.exe', '/d', '/c', 'Setup.cmd', '--check'],
                            cwd=project, input='\n', text=True, capture_output=True, env=env, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Python must be approved and installed separately' in result.stdout
    assert 'not a valid Win32' not in result.stderr
    assert not (project / '.venv').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell 5.1 required')
@pytest.mark.parametrize('selection', ['', 'python', 'alias'])
def test_real_ps_rejects_missing_or_alias_runtime_without_invocation(project, selection):
    alias = project / 'python.exe'
    alias.write_text('not an executable')
    selected = str(alias) if selection == 'alias' else selection
    env = dict(os.environ, WORKBENCH_PYTHON=selected,
               PYLAUNCHER_ALLOW_INSTALL='1', PYLAUNCHER_ALWAYS_INSTALL='1',
               PYTHON_MANAGER_AUTOMATIC_INSTALL='true')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                             '-File', str(ROOT / 'scripts/Setup-Windows.ps1'), '-ProjectRoot', str(project),
                             '-CheckOnly'], capture_output=True, text=True, env=env, timeout=30)
    assert result.returncode != 0
    expected = 'actual standard CPython installation' if selection == 'alias' else 'Python must be approved and installed separately'
    assert expected in result.stderr
    assert not (project / '.venv').exists()
