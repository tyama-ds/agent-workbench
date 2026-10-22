"""Directory creation stays inside the same folder harness as file writes."""
import asyncio
import contextlib
import os
import subprocess
from pathlib import Path

import pytest

from workbench.harness import HarnessError, PathHarness, ToolExecutor


def execute(tools, name, **args):
    return asyncio.run(tools.execute(name, args))


def test_nested_creation_is_write_only_idempotent_and_planned(tmp_path):
    harness = PathHarness([], [str(tmp_path)])
    tools = ToolExecutor(harness)
    target = tmp_path / 'reports' / '日本語'
    assert harness.directory_creation_paths(str(target)) == [target.parent, target]
    result = execute(tools, 'create_directory', path='reports/日本語')
    assert result == {'path': str(target), 'kind': 'directory', 'operation': 'created'}
    assert target.is_dir()
    assert harness.directory_creation_paths(str(target)) == [target]
    assert execute(tools, 'create_directory', path=str(target))['operation'] == 'existing'
    execute(tools, 'write_text', path=str(target / 'report.txt'), text='保存できました', expected_sha256='missing')
    assert (target / 'report.txt').read_text(encoding='utf-8') == '保存できました'
    with pytest.raises(HarnessError):
        execute(tools, 'list_directory', path=str(target))
    specification = next(item for item in tools.schemas() if item['name'] == 'create_directory')
    assert specification['parameters']['required'] == ['path']
    with pytest.raises(HarnessError, match='Unsupported'):
        execute(tools, 'create_directory', path=str(target), parents=True)


def test_existing_parent_is_not_in_creation_plan(tmp_path):
    parent = tmp_path / 'existing'
    parent.mkdir()
    harness = PathHarness([], [str(tmp_path)])
    target = parent / 'one' / 'two'
    assert harness.directory_creation_paths(str(target)) == [parent / 'one', target]
    assert harness.directory_creation_paths(str(tmp_path)) == [tmp_path]
    assert harness.create_directory(str(tmp_path))['operation'] == 'existing'


@pytest.mark.parametrize('mode', ['outside', 'read_only', 'denied'])
def test_scope_rejection_does_not_create_any_parent(tmp_path, mode):
    root, other = tmp_path / 'write', tmp_path / 'other'
    root.mkdir()
    other.mkdir()
    target = (root if mode == 'denied' else other) / 'new' / 'blocked' / 'child'
    denied = [str(root / 'new' / 'blocked')] if mode == 'denied' else []
    harness = PathHarness([str(other)] if mode == 'read_only' else [], [str(root)], denied)
    with pytest.raises(HarnessError):
        harness.create_directory(str(target))
    assert not target.parents[1].exists()


@pytest.mark.parametrize('path', ['../outside', 'new/../outside', 'new/NUL', 'new/COM1.txt',
    'new/trailing.', 'new/trailing ', 'new/file:stream', 'new/*', r'\\server\share\new'])
def test_unsafe_spellings_rejected_before_creating_parents(tmp_path, path):
    harness = PathHarness([], [str(tmp_path)])
    with pytest.raises(HarnessError):
        harness.create_directory(path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('nested', [False, True])
def test_file_collision_is_not_overwritten(tmp_path, nested):
    path = tmp_path / 'file.txt'
    path.write_text('original', encoding='utf-8')
    harness = PathHarness([], [str(tmp_path)])
    with pytest.raises(HarnessError):
        harness.create_directory(str(path / 'child' if nested else path))
    assert path.read_text(encoding='utf-8') == 'original'


def test_missing_configured_root_is_not_created(tmp_path):
    root = tmp_path / 'missing'
    with pytest.raises(HarnessError):
        PathHarness([], [str(root)])
    root.mkdir()
    harness = PathHarness([], [str(root)])
    root.rmdir()
    with pytest.raises(HarnessError):
        harness.create_directory(str(root / 'child'))
    assert not root.exists()


def test_relative_paths_require_one_write_root(tmp_path):
    other = tmp_path / 'other'
    other.mkdir()
    for roots in ([], [str(tmp_path), str(other)]):
        with pytest.raises(HarnessError, match='absolute path'):
            PathHarness([], roots).create_directory('new')
    assert not (tmp_path / 'new').exists()


def test_directory_creation_is_bounded_before_mutation(tmp_path):
    harness = PathHarness([], [str(tmp_path)])
    too_deep = tmp_path.joinpath(*(['d'] * 33))
    with pytest.raises(HarnessError, match='32'):
        harness.create_directory(str(too_deep))
    assert list(tmp_path.iterdir()) == []
    target = too_deep.parent
    assert len(harness.directory_creation_paths(str(target))) == 32
    harness.create_directory(str(target))
    assert target.is_dir()


def _directory_link(path, target, kind):
    if kind == 'junction':
        subprocess.run([os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe'), '/d', '/c',
                        'mklink', '/J', str(path), str(target)], check=True, capture_output=True,
                       creationflags=0x08000000)
    else:
        try:
            path.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip('Host does not permit directory symlinks')


LINK_KINDS = ['symlink'] + (['junction'] if os.name == 'nt' else [])


@pytest.mark.parametrize('kind', LINK_KINDS)
@pytest.mark.parametrize('nested', [False, True])
def test_links_cannot_be_used_as_target_or_parent(tmp_path, kind, nested):
    root, outside = tmp_path / 'root', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    link = root / 'link'
    _directory_link(link, outside, kind)
    try:
        harness = PathHarness([], [str(root)])
        with pytest.raises(HarnessError, match='reparse'):
            harness.create_directory(str(link / 'child' if nested else link))
        assert list(outside.iterdir()) == []
    finally:
        if kind == 'junction':
            os.rmdir(link)
        else:
            link.unlink()


@pytest.mark.parametrize('kind', LINK_KINDS)
def test_rechecks_parent_replaced_after_creation_plan(tmp_path, monkeypatch, kind):
    root, outside = tmp_path / 'root', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    parent = root / 'parent'
    parent.mkdir()
    harness = PathHarness([], [str(root)])
    original_hold = harness._parents_held
    replaced = False

    @contextlib.contextmanager
    def replace_before_hold(path, **kwargs):
        nonlocal replaced
        if not replaced:
            parent.rename(root / 'original')
            _directory_link(parent, outside, kind)
            replaced = True
        with original_hold(path, **kwargs):
            yield

    monkeypatch.setattr(harness, '_parents_held', replace_before_hold)
    try:
        with pytest.raises(HarnessError, match='reparse'):
            harness.create_directory(str(parent / 'child'))
        assert not (outside / 'child').exists()
    finally:
        if replaced:
            if kind == 'junction':
                os.rmdir(parent)
            else:
                parent.unlink()


@pytest.mark.parametrize('collision', ['file', 'directory'])
def test_concurrent_target_creation_is_revalidated(tmp_path, monkeypatch, collision):
    harness = PathHarness([], [str(tmp_path)])
    target = tmp_path / 'new'
    original_hold = harness._parents_held

    @contextlib.contextmanager
    def create_before_hold(path, **kwargs):
        if collision == 'file':
            target.write_text('other writer', encoding='utf-8')
        else:
            target.mkdir()
        with original_hold(path, **kwargs):
            yield

    monkeypatch.setattr(harness, '_parents_held', create_before_hold)
    if collision == 'file':
        with pytest.raises(HarnessError, match='not a directory'):
            harness.create_directory(str(target))
        assert target.read_text(encoding='utf-8') == 'other writer'
    else:
        assert harness.create_directory(str(target))['operation'] == 'existing'


def test_failed_creation_keeps_already_created_parents(tmp_path, monkeypatch):
    harness = PathHarness([], [str(tmp_path)])
    target = tmp_path / 'created' / 'blocked'
    original_mkdir = Path.mkdir

    def fail_leaf(path, *args, **kwargs):
        if path == target:
            raise PermissionError('synthetic permission failure')
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', fail_leaf)
    with pytest.raises(HarnessError, match='parents may remain'):
        harness.create_directory(str(target))
    assert target.parent.is_dir() and not target.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows parent handle regression')
def test_windows_creation_holds_parent_against_rename(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    harness = PathHarness([], [str(root)])
    target = root / 'new'
    original_mkdir = Path.mkdir

    def try_rename_parent(path, *args, **kwargs):
        if path == target:
            with pytest.raises(PermissionError):
                root.rename(tmp_path / 'moved')
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', try_rename_parent)
    harness.create_directory(str(target))
    assert target.is_dir() and not (tmp_path / 'moved').exists()


@pytest.mark.parametrize('tool,name,fields', [
    ('docx_write', 'report.docx', {'paragraphs': ['Saved report']}),
    ('xlsx_write', 'report.xlsx', {'cells': [{'sheet': 'Sheet', 'cell': 'A1', 'value': 'Saved report'}]}),
    ('pptx_write', 'report.pptx', {'slides': [{'title': 'Saved report', 'body': ['Saved content']}]}),
])
def test_office_files_can_be_saved_in_created_directories(tmp_path, tool, name, fields):
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    target = tmp_path / 'reports' / 'nested'
    execute(tools, 'create_directory', path=str(target))
    result = execute(tools, tool, path=str(target / name), expected_sha256='missing', **fields)
    assert result['operation'] == 'created' and result['bytes'] > 0
    assert (target / name).is_file()
    output = execute(tools, tool.replace('_write', '_read'), path=str(target / name))
    assert output['sha256'] == result['sha256']
