"""Interactive setup planning; no subprocess, pip or network is executed."""
import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('interactive_setup', ROOT / 'scripts/setup_windows.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / '会社 project & spaces !'
    root.mkdir()
    for relative in ('requirements.lock', 'pyproject.toml', 'workbench/server.py',
                     'static/index.html', 'docs/interface.json'):
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text('fixture', encoding='ascii')
    return root


def run_main(monkeypatch, project, answers, *arguments):
    prompts, calls = [], []
    values = iter(answers)

    def read(prompt):
        prompts.append(prompt)
        value = next(values)
        if isinstance(value, BaseException):
            raise value
        return value

    def runner(args, **kwargs):
        calls.append((list(map(str, args)), kwargs))
        return setup.CONFIG_MARKER if kwargs.get('capture') else ''

    monkeypatch.setattr('builtins.input', read)
    original_install = setup.install
    monkeypatch.setattr(setup, 'install', lambda options: original_install(options, runner=runner))
    code = setup.main(['--project-root', str(project), *arguments])
    return code, prompts, calls


def dependency(calls):
    return next(args for args, _ in calls if '--require-hashes' in args)


@pytest.mark.parametrize('quoted', [False, True])
def test_interactive_proxy_and_unicode_ca_are_arguments_only(project, monkeypatch, capsys, quoted):
    certificate = project / '会社 CA & ! %name% ^ (trusted).pem'
    certificate.write_text('fixture', encoding='ascii')
    value = '"' + str(certificate) + '"' if quoted else str(certificate)
    code, prompts, calls = run_main(monkeypatch, project,
                                    ['http://proxy.example:8080/', value], '--interactive')
    assert code == 0 and len(prompts) == 2
    dep = dependency(calls)
    assert dep[dep.index('--proxy') + 1] == 'http://proxy.example:8080'
    assert dep[dep.index('--cert') + 1] == str(certificate)
    assert '--trusted-host' not in dep and '--require-hashes' in dep
    assert all('shell' not in kwargs for _, kwargs in calls)
    assert not (project / '.venv').exists()
    output = capsys.readouterr()
    assert str(certificate) not in output.out + output.err


def test_blank_network_entries_preserve_environment_without_saving(project, monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY', 'http://existing.example:8080')
    monkeypatch.setenv('PIP_PROXY', 'http://pip.example:3128')
    monkeypatch.setenv('PIP_CERT', 'approved-existing.pem')
    monkeypatch.setenv('PIP_CONFIG_FILE', 'existing-pip.ini')
    before_env = dict(os.environ)
    before_files = {str(path): path.read_bytes() for path in project.rglob('*') if path.is_file()}
    code, prompts, calls = run_main(monkeypatch, project, ['', '   '], '--interactive')
    assert code == 0 and len(prompts) == 2
    assert '--proxy' not in dependency(calls) and '--cert' not in dependency(calls)
    for _, kwargs in calls:
        assert all(kwargs['env'][key] == before_env[key] for key in
                   ('HTTPS_PROXY', 'PIP_PROXY', 'PIP_CERT', 'PIP_CONFIG_FILE'))
    assert dict(os.environ) == before_env
    assert {str(path): path.read_bytes() for path in project.rglob('*') if path.is_file()} == before_files


@pytest.mark.parametrize('arguments', [[], ['--check'], ['--proxy', 'http://explicit.example:8080']])
def test_cli_without_interactive_never_reads_input(project, monkeypatch, arguments):
    code, prompts, calls = run_main(monkeypatch, project, [], *arguments)
    assert code == 0 and prompts == []
    if '--check' in arguments:
        assert calls == []


@pytest.mark.parametrize('supplied', ['proxy', 'certificate', 'both'])
def test_interactive_does_not_overwrite_explicit_values(project, monkeypatch, supplied):
    certificate = project / 'approved.pem'
    certificate.write_text('fixture', encoding='ascii')
    arguments = ['--interactive']
    if supplied in ('proxy', 'both'):
        arguments += ['--proxy', 'http://explicit.example:8080']
    if supplied in ('certificate', 'both'):
        arguments += ['--certificate', str(certificate)]
    code, prompts, calls = run_main(monkeypatch, project,
                                    [] if supplied == 'both' else [''], *arguments)
    assert code == 0 and len(prompts) == (0 if supplied == 'both' else 1)
    dep = dependency(calls)
    if supplied in ('proxy', 'both'):
        assert dep[dep.index('--proxy') + 1] == 'http://explicit.example:8080'
    if supplied in ('certificate', 'both'):
        assert dep[dep.index('--cert') + 1] == str(certificate)


def test_interactive_offline_skips_network_prompts(project, monkeypatch):
    wheels = project / 'wheels'
    wheels.mkdir()
    (wheels / 'approved.whl').write_bytes(b'fixture')
    code, prompts, calls = run_main(monkeypatch, project, [], '--interactive', '--wheelhouse', str(wheels))
    assert code == 0 and prompts == []
    dep = dependency(calls)
    assert '--no-index' in dep and '--proxy' not in dep and '--cert' not in dep


@pytest.mark.parametrize('error', [EOFError(), KeyboardInterrupt()])
@pytest.mark.parametrize('stage', ['proxy', 'certificate'])
def test_cancel_at_either_prompt_runs_no_commands(project, monkeypatch, capsys, stage, error):
    answers = [error] if stage == 'proxy' else ['http://proxy.example:8080', error]
    code, prompts, calls = run_main(monkeypatch, project, answers, '--interactive')
    assert code == 1 and calls == []
    assert len(prompts) == (1 if stage == 'proxy' else 2)
    output = capsys.readouterr()
    assert output.err.strip() == 'Setup cancelled before installation. No installation commands were run.'
    assert not (project / '.venv').exists()


@pytest.mark.parametrize('proxy', ['proxy-secret:8080', 'http://secret-user:secret-pass@proxy',
                                  'http://proxy/secret.pac', 'http://proxy?secret=x',
                                  'http://proxy#secret', 'http://proxy:99999',
                                  'http://proxy\\secret', 'http://proxy secret'])
def test_invalid_interactive_proxy_never_runs_pip_or_echoes_input(project, monkeypatch, capsys, proxy):
    code, prompts, calls = run_main(monkeypatch, project, [proxy], '--interactive')
    assert code == 1 and calls == [] and len(prompts) == 1
    output = capsys.readouterr()
    assert 'Proxy must be an HTTP(S) origin' in output.err
    assert 'secret' not in output.out + output.err
    assert not (project / '.venv').exists()


@pytest.mark.parametrize('path', ['missing-secret-ca.pem', '"missing-secret CA.pem"', 'bad\0secret.pem'])
def test_invalid_interactive_ca_never_runs_pip_or_echoes_input(project, monkeypatch, capsys, path):
    code, prompts, calls = run_main(monkeypatch, project, ['', path], '--interactive')
    assert code == 1 and calls == [] and len(prompts) == 2
    output = capsys.readouterr()
    assert 'Certificate must be an existing organization-approved PEM CA bundle.' in output.err
    assert 'secret' not in output.out + output.err
    assert not (project / '.venv').exists()


def test_interactive_check_can_validate_input_without_installing(project, monkeypatch):
    code, prompts, calls = run_main(monkeypatch, project,
                                    ['http://proxy.example:8080', ''], '--interactive', '--check')
    assert code == 0 and len(prompts) == 2 and calls == []
