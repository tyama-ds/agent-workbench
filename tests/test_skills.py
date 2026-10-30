"""Skill discovery boundaries and immutable per-run content; no script execution."""
import hashlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.harness import HarnessError, PathHarness
from workbench import skills as module
from workbench.skills import SkillCatalog


def put(root, folder='example', content='# Example\nUse this guide.', layout='skills', filename='SKILL.md'):
    path = root / layout / folder / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
    return path


def catalog(root, **kwargs):
    return SkillCatalog(PathHarness([str(root)], [], **kwargs))


def test_only_fixed_read_root_layouts_are_discovered(tmp_path):
    direct = put(tmp_path, 'direct')
    hidden = put(tmp_path, 'hidden', layout='.agents/skills', filename='skill.md')
    put(tmp_path, 'nested/deep')
    write = tmp_path / 'write'
    put(write, 'write-only')
    result = SkillCatalog(PathHarness([str(tmp_path)], [str(write)])).public()
    assert {item['path'] for item in result['skills']} == {str(direct), str(hidden)}
    assert result['errors'] == []
    assert SkillCatalog(PathHarness([], [str(write)])).public() == {'skills': [], 'errors': []}


def test_absent_locations_are_empty_and_prompt_is_empty(tmp_path):
    result = catalog(tmp_path)
    assert result.public() == {'skills': [], 'errors': []}
    assert result.prompt() == ''


@pytest.mark.parametrize('metadata,expected_name,expected_description', [
    ('name: plain\ndescription: Useful plain text # note', 'plain', 'Useful plain text'),
    ("name: 'Bob''s guide'\ndescription: 'literal # and : text'", "Bob's guide", 'literal # and : text'),
    ('name: "日本語"\ndescription: "line\\nnext"', '日本語', 'line next'),
    ('name: |\n  example\ndescription: >-\n  first line\n  second line', 'example', 'first line second line'),
    ('name: example\ndescription: |+\n  first\n  ---\n  last', 'example', 'first --- last'),
    ('name: example\nextra:\n  nested: [one, two]\ndescription: useful', 'example', 'useful'),
])
def test_supported_frontmatter_subset(tmp_path, metadata, expected_name, expected_description):
    text = '---\n' + metadata + '\n---\n# Body remains intact\n'
    raw = ('\ufeff' + text.replace('\n', '\r\n')).encode('utf-8')
    path = put(tmp_path, content=raw)
    result = catalog(tmp_path)
    public = result.public()
    assert public['errors'] == []
    item, = public['skills']
    assert item['name'] == expected_name
    assert item['description'] == expected_description
    assert item['sha256'] == hashlib.sha256(raw).hexdigest()
    assert item['base_directory'] == str(path.parent)
    assert result.read(item['id'])['content'] == raw.decode('utf-8-sig')


def test_without_frontmatter_uses_folder_and_first_body_line(tmp_path):
    text = '\n## Short description\n\nNever execute this body automatically.'
    put(tmp_path, 'folder-name', text)
    result = catalog(tmp_path)
    item, = result.public()['skills']
    assert (item['name'], item['description']) == ('folder-name', 'Short description')
    assert result.read(item['id'])['content'] == text
    assert 'Never execute this body automatically.' not in result.prompt()
    assert 'read_skill' in result.prompt() and '$name' in result.prompt()
    assert 'permissions or shared budgets' in result.prompt()
    assert 'not automatically executed or loaded' in result.prompt()


@pytest.mark.parametrize('text', [
    '---\nname: a\ndescription: b',
    '---\nname: a\n---\nbody',
    '---\nname: a\nname: b\ndescription: text\n---',
    '---\nname:\n  nested: bad\ndescription: text\n---',
    '---\nname: [a, b]\ndescription: text\n---',
    '---\nname: a\ndescription: {nested: bad}\n---',
    '---\nname: true\ndescription: text\n---',
    '---\nname: 123\ndescription: text\n---',
    '---\nname: *alias\ndescription: text\n---',
    '---\nname: a\ndescription: "unterminated\n---',
    '---\nname: a\ndescription: ""\n---',
    '---\nname: a\ndescription: |2\n  unsupported\n---',
    '---\nname: a\ndescription: "\\ud800"\n---',
    b'\xffbad UTF-8',
    b'# Text\x00binary',
    '',
])
def test_invalid_text_or_metadata_is_reported_and_excluded(tmp_path, text):
    path = put(tmp_path, content=text)
    result = catalog(tmp_path).public()
    assert result['skills'] == []
    assert len(result['errors']) == 1
    assert result['errors'][0]['path'] == str(path)
    assert result['errors'][0]['error']


def test_deny_roots_and_reparse_candidates_are_not_read(tmp_path, monkeypatch):
    denied = put(tmp_path, 'denied')
    blocked = put(tmp_path, 'reparse')
    allowed = put(tmp_path, 'allowed')
    original = PathHarness.resolve
    reads = []
    original_read = PathHarness.read_bytes

    def resolve(self, value, **kwargs):
        if Path(value) == blocked:
            raise HarnessError('Symlinks, junctions and reparse points are forbidden')
        return original(self, value, **kwargs)

    def read(self, value):
        reads.append(value)
        return original_read(self, value)

    monkeypatch.setattr(PathHarness, 'resolve', resolve)
    monkeypatch.setattr(PathHarness, 'read_bytes', read)
    public = catalog(tmp_path, deny_roots=[str(denied.parent)]).public()
    assert [item['path'] for item in public['skills']] == [str(allowed)]
    assert reads == [str(allowed)]
    assert any('denied' in item['error'] for item in public['errors'])
    assert any('reparse' in item['error'] for item in public['errors'])


def test_hardlinked_skill_is_rejected(tmp_path):
    path = put(tmp_path)
    os.link(path, tmp_path / 'other.md')
    public = catalog(tmp_path).public()
    assert public['skills'] == []
    assert any('hard link' in item['error'] for item in public['errors'])


class Entries:
    def __init__(self, paths):
        self.items = iter(SimpleNamespace(path=str(path)) for path in paths)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def __next__(self):
        return next(self.items)


@pytest.mark.parametrize('blocked_second', [False, True])
def test_case_ambiguity_is_rejected_even_when_one_spelling_is_blocked(tmp_path, monkeypatch, blocked_second):
    path = put(tmp_path)
    lower = path.with_name('skill.md')
    if not lower.exists():
        lower.write_bytes(path.read_bytes())
    original_scan, original_resolve = os.scandir, PathHarness.resolve

    def scan(directory):
        return Entries([path, lower]) if Path(directory) == path.parent else original_scan(directory)

    def resolve(self, value, **kwargs):
        if blocked_second and str(value) == str(lower):
            raise HarnessError('Blocked alternate casing')
        return original_resolve(self, value, **kwargs)

    monkeypatch.setattr(module.os, 'scandir', scan)
    monkeypatch.setattr(PathHarness, 'resolve', resolve)
    public = catalog(tmp_path).public()
    assert public['skills'] == []
    assert any('Ambiguous' in item['error'] for item in public['errors'])


def test_snapshots_keep_body_and_id_but_recheck_current_authority(tmp_path):
    path = put(tmp_path, content='# First\nOld body')
    harness = PathHarness([str(tmp_path)], [])
    original = SkillCatalog(harness)
    before, = original.public()['skills']
    path.write_text('# Second\nNew body', encoding='utf-8')
    fresh = SkillCatalog(harness)
    after, = fresh.public()['skills']
    assert after['id'] == before['id'] and after['sha256'] != before['sha256']
    assert original.read(before['id'])['content'] == '# First\nOld body'
    returned = original.read(before['id'])
    returned['content'] = 'mutated'
    assert original.read(before['id'])['content'] == '# First\nOld body'
    path.unlink()
    assert original.read(before['id'])['sha256'] == before['sha256']
    harness.deny_roots = (path.parent,)
    with pytest.raises(HarnessError, match='denied'):
        original.read(before['id'])
    for unknown in ('missing', '', None, {}):
        with pytest.raises(ValueError, match='Unknown'):
            original.read(unknown)


def test_duplicate_names_keep_distinct_ids_and_overlapping_roots_do_not_duplicate(tmp_path):
    text = '---\nname: same\ndescription: example\n---\nbody'
    put(tmp_path, 'first', text)
    put(tmp_path, 'second', text, layout='.agents/skills')
    result = SkillCatalog(PathHarness([str(tmp_path), str(tmp_path / '.agents')], []))
    items = result.public()['skills']
    assert len(items) == 2 and {item['name'] for item in items} == {'same'}
    assert len({item['id'] for item in items}) == 2
    assert all(len(item['id']) == 64 for item in items)
    assert 'If names are ambiguous, do not guess' in result.prompt()


@pytest.mark.parametrize('configured,expected', [(10 * 1024 * 1024, 32768), (64, 64)])
def test_reads_use_narrow_harness_cap_without_mutating_shared_limit(tmp_path, monkeypatch, configured, expected):
    put(tmp_path, content=b'# Oversized\n' + b'x' * expected)
    harness = PathHarness([str(tmp_path)], [], max_file_bytes=configured)
    original_read = PathHarness.read_bytes
    caps = []

    def read(self, path):
        caps.append(self.max_file_bytes)
        return original_read(self, path)

    monkeypatch.setattr(PathHarness, 'read_bytes', read)
    public = SkillCatalog(harness).public()
    assert public['skills'] == [] and public['errors']
    assert caps == [expected]
    assert harness.max_file_bytes == configured


def test_invalid_returned_bytes_consume_total_snapshot_budget(tmp_path, monkeypatch):
    for index in range(4):
        put(tmp_path, str(index), b'\xff' * 16)
    monkeypatch.setattr(module, 'MAX_TOTAL_BYTES', 32)
    original_read = PathHarness.read_bytes
    read_bytes = []

    def read(self, path):
        result = original_read(self, path)
        read_bytes.append(result)
        return result

    monkeypatch.setattr(PathHarness, 'read_bytes', read)
    public = catalog(tmp_path).public()
    assert public['skills'] == []
    assert sum(map(len, read_bytes)) == 32
    assert any('32 bytes' in item['error'] for item in public['errors'])


def test_skill_count_is_bounded_and_extra_candidates_are_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'MAX_SKILLS', 2)
    for index in range(3):
        put(tmp_path, str(index))
    result = catalog(tmp_path)
    assert len(result.public()['skills']) == 2
    assert any('exceeds 2' in item['error'] for item in result.public()['errors'])
    assert len(result.prompt()) <= module.MAX_PROMPT_CHARS


def test_failed_bounded_reads_cannot_reset_the_total_budget(tmp_path, monkeypatch):
    for index in range(4):
        put(tmp_path, str(index))
    monkeypatch.setattr(module, 'MAX_FILE_BYTES', 16)
    monkeypatch.setattr(module, 'MAX_TOTAL_BYTES', 32)
    attempts = []

    def changed_during_read(self, path):
        attempts.append(self.max_file_bytes)
        raise HarnessError('File exceeds the size limit')

    monkeypatch.setattr(PathHarness, 'read_bytes', changed_during_read)
    value = catalog(tmp_path).public()
    assert attempts == [16, 16]
    assert not value['skills']
    assert any('32 bytes' in item['error'] for item in value['errors'])


def test_scan_cap_counts_rejected_entries_and_does_not_accept_partial_folder(tmp_path, monkeypatch):
    path = put(tmp_path)
    rejected = path.parent / 'denied.txt'
    rejected.write_text('x', encoding='utf-8')
    original_scan = os.scandir
    monkeypatch.setattr(module, 'MAX_VISITS', 3)

    def scan(directory):
        if Path(directory) == path.parent:
            return Entries([path, rejected, path.with_name('skill.md')])
        return original_scan(directory)

    monkeypatch.setattr(module.os, 'scandir', scan)
    public = catalog(tmp_path, deny_roots=[str(rejected)]).public()
    assert public['skills'] == []
    assert any('denied' in item['error'] for item in public['errors'])
    assert any('3-entry visit limit' in item['error'] for item in public['errors'])
