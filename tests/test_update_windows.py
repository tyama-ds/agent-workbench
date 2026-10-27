"""Update ownership and locked install flow, without network/package mutations."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_windows_tested', ROOT / 'scripts/update_workbench.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'AWB 日本語 & space'
    environment = root / '.venv'
    python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    python.parent.mkdir(parents=True)
    python.write_bytes(b'fixture-not-an-executable')
    (environment / 'pyvenv.cfg').write_text('home = approved-python\n', encoding='utf-8')
    library = environment / 'Lib/site-packages'
    record = library / 'agent_workbench-0.1.1.dev32.dist-info/direct_url.json'
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'url': root.as_uri(), 'dir_info': {'editable': True}}), encoding='utf-8')
    return root, environment, python, library, record


def test_same_location_environment_and_editable_source_are_accepted(project, tmp_path):
    root, env, python, library, _ = project
    assert update.existing_environment(root, prefix=env, base_prefix=tmp_path/'approved', executable=python) == root
    update.installed_source(root, purelib=library)


@pytest.mark.parametrize('fault', ['base-python', 'other-prefix', 'other-executable', 'incomplete'])
def test_existing_environment_rejects_wrong_interpreter_before_setup(project, tmp_path, fault):
    root, env, python, _, _ = project
    prefix, base, executable = env, tmp_path/'approved', python
    if fault == 'base-python': base = env
    if fault == 'other-prefix': prefix = tmp_path/'other'
    if fault == 'other-executable': executable = tmp_path/'python.exe'
    if fault == 'incomplete': (env/'pyvenv.cfg').unlink()
    with pytest.raises(ValueError, match='same folder'):
        update.existing_environment(root, prefix=prefix, base_prefix=base, executable=executable)
    assert python.read_bytes() == b'fixture-not-an-executable'


@pytest.mark.parametrize('value', [None, [], {'url': 5}, {'url': 'https://example.com/source'},
    {'url': 'file://host/source', 'dir_info': {'editable': True}},
    {'url': 'file:///wrong-folder', 'dir_info': {'editable': True}}])
def test_invalid_or_moved_editable_source_is_preserved(project, value):
    root, _, _, library, record = project
    record.write_text(json.dumps(value), encoding='utf-8')
    before = record.read_bytes()
    with pytest.raises(ValueError): update.installed_source(root, purelib=library)
    assert record.read_bytes() == before


@pytest.mark.parametrize('fault', ['not-editable', 'query', 'fragment', 'large', 'duplicate', 'missing'])
def test_ambiguous_source_metadata_is_preserved(project, fault):
    root, _, _, library, record = project
    value = {'url': root.as_uri(), 'dir_info': {'editable': True}}
    if fault == 'not-editable': value['dir_info'] = {'editable': False}
    if fault == 'query': value['url'] += '?other=1'
    if fault == 'fragment': value['url'] += '#other'
    if fault == 'large': value['padding'] = 'x' * 9000
    record.write_text(json.dumps(value), encoding='utf-8')
    if fault == 'duplicate':
        other = library/'agent_workbench-0.1.1.dev31.dist-info/direct_url.json'
        other.parent.mkdir(); other.write_bytes(record.read_bytes())
    if fault == 'missing': record.unlink()
    before = {str(p): p.read_bytes() for p in library.rglob('*') if p.is_file()}
    with pytest.raises(ValueError): update.installed_source(root, purelib=library)
    assert {str(p): p.read_bytes() for p in library.rglob('*') if p.is_file()} == before


def test_package_directory_must_belong_to_this_environment(project, tmp_path):
    with pytest.raises(ValueError, match='outside'):
        update.installed_source(project[0], purelib=tmp_path/'unrelated')


def test_invalid_owner_never_imports_installer(monkeypatch):
    def reject(root): raise ValueError('invalid owner')
    monkeypatch.setattr(update, 'existing_environment', reject)
    monkeypatch.setattr(update, 'load_setup', lambda root: pytest.fail('must not import setup'))
    assert update.main([]) == 1


def prepared_main(monkeypatch, project):
    root = project[0]
    setup = update.load_setup(ROOT)
    monkeypatch.setattr(update, 'ROOT', root)
    monkeypatch.setattr(update, 'existing_environment', lambda selected: selected)
    monkeypatch.setattr(update, 'installed_source', lambda selected: None)
    monkeypatch.setattr(update, 'load_setup', lambda selected: setup)
    monkeypatch.setattr(setup, 'ROOT', root)
    return setup


def test_update_reuses_real_locked_install_flow_without_environment_creation(monkeypatch, project, capsys):
    root, _, python, _, _ = project
    setup = prepared_main(monkeypatch, project)
    for relative in ('requirements.lock', 'pyproject.toml', 'workbench/server.py', 'static/index.html', 'docs/interface.json'):
        p = root/relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('fixture', encoding='utf-8')
    calls = []
    def runner(args, **kwargs):
        calls.append([str(a) for a in args])
        return setup.CONFIG_MARKER + '\n' if 'config' in args else ''
    install = setup.install
    monkeypatch.setattr(setup, 'install', lambda options: install(options, runner=runner))
    assert update.main([]) == 0
    assert not any(command[1:3] == ['-m', 'venv'] for command in calls)
    dependencies = next(command for command in calls if '--require-hashes' in command)
    assert dependencies[0] == str(python) and '--require-virtualenv' in dependencies and '--only-binary=:all:' in dependencies
    assert dependencies[-1] == str(root/'requirements.lock')
    application = next(command for command in calls if '-e' in command)
    assert '--no-index' in application and '--no-deps' in application and application[-1] == str(root)
    assert any(command[-1] == 'check' for command in calls)
    assert 'Update complete' in capsys.readouterr().out
    assert python.read_bytes() == b'fixture-not-an-executable'


def test_update_cannot_retarget_another_install(monkeypatch, project, tmp_path):
    setup = prepared_main(monkeypatch, project)
    monkeypatch.setattr(setup, 'install', lambda options: pytest.fail('must not install'))
    assert update.main(['--project-root', str(tmp_path/'other')]) == 1


def test_cancel_before_install_is_not_success(monkeypatch, project, capsys):
    setup = prepared_main(monkeypatch, project)
    def cancel(options): raise setup.SetupCancelled()
    monkeypatch.setattr(setup, 'interactive_options', cancel)
    monkeypatch.setattr(setup, 'install', lambda options: pytest.fail('must not install'))
    assert update.main(['--interactive']) == 1
    assert 'Update complete' not in capsys.readouterr().out


@pytest.mark.skipif(os.name != 'nt', reason='native Windows batch help')
@pytest.mark.parametrize('argument', ['--help', '-h', '/?'])
def test_batch_help_does_not_need_or_start_python(tmp_path, argument):
    project = tmp_path/'会社 AWB & ! (update)'; project.mkdir()
    batch = project/'Update.bat'; batch.write_bytes((ROOT/'Update.bat').read_bytes())
    # cmd has its own quoting grammar; use its native entrypoint argument rather
    # than placing a CRT-escaped quoted path inside a CALL command string.
    result = subprocess.run(['cmd.exe', '/d', '/v:off', '/c', 'Update.bat', argument],
        cwd=project, input='', capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and 'same folder' not in result.stderr
    assert 'Application source is not downloaded' in result.stdout
    assert not (project/'.venv').exists()
