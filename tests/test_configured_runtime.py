"""Explicit installed-library launch, without package installation or site hooks."""
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import sysconfig
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/configured_runtime.py'
spec = importlib.util.spec_from_file_location('configured_runtime_tests_subject', SCRIPT)
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


@pytest.fixture
def config_values(tmp_path):
    python = tmp_path / 'Approved Python' / 'python.exe'
    python.parent.mkdir()
    python.write_bytes(b'Not executed by configuration parsing')
    libraries = tmp_path / "会社 libraries & ! % '"
    libraries.mkdir()
    return {'python_executable': str(python), 'library_paths': [str(libraries)]}


def write_config(tmp_path, values, *, encoding='utf-8'):
    path = tmp_path / 'runtime.local.json'
    path.write_text(json.dumps(values, ensure_ascii=False), encoding=encoding)
    return path


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig'])
def test_load_config_accepts_unicode_paths_and_bom(tmp_path, config_values, encoding):
    config = runtime.load_config(write_config(tmp_path, config_values, encoding=encoding))
    assert config.python_executable == Path(config_values['python_executable']).resolve()
    assert config.library_paths == (Path(config_values['library_paths'][0]).resolve(),)
    assert (config.port, config.state_dir, config.open_browser) == (8818, '', True)


def test_load_config_explicit_settings_and_library_order(tmp_path, config_values):
    second = tmp_path / 'second packages'
    second.mkdir()
    config_values['library_paths'] += [str(second), config_values['library_paths'][0]]
    config_values.update(port=0, state_dir=str(tmp_path / 'future state'), open_browser=False)
    config = runtime.load_config(write_config(tmp_path, config_values))
    assert config.library_paths == (Path(config_values['library_paths'][0]).resolve(), second.resolve())
    assert (config.port, config.state_dir, config.open_browser) == (0, str(tmp_path / 'future state'), False)


@pytest.mark.parametrize('field,value', [
    ('python_executable', None), ('python_executable', 42),
    ('python_executable', 'python'), ('python_executable', 'relative/python.exe'),
    ('python_executable', 'C:python.exe'), ('python_executable', 'bad\npython.exe'),
    ('library_paths', None), ('library_paths', 'site-packages'), ('library_paths', []),
    ('library_paths', [None]), ('library_paths', ['relative']),
    ('library_paths', ['bad\x00path']), ('library_paths', ['relative'] * 17),
    ('port', True), ('port', '8818'), ('port', -1), ('port', 65536),
    ('state_dir', None), ('state_dir', 'relative'), ('state_dir', 'bad\rpath'),
    ('open_browser', 1), ('open_browser', 'false'), ('open_browser', None),
    ('library_path', 'misspelled key'),
])
def test_load_config_rejects_invalid_fields(tmp_path, config_values, field, value):
    config_values[field] = value
    with pytest.raises(ValueError):
        runtime.load_config(write_config(tmp_path, config_values))


@pytest.mark.parametrize('field', ['python_executable', 'library_paths'])
def test_load_config_requires_both_paths(tmp_path, config_values, field):
    del config_values[field]
    with pytest.raises(ValueError):
        runtime.load_config(write_config(tmp_path, config_values))


@pytest.mark.parametrize('field', ['python_executable', 'library_paths'])
def test_load_config_rejects_missing_or_wrong_path_kind(tmp_path, config_values, field):
    for value in (tmp_path / 'missing', tmp_path if field == 'python_executable'
                  else Path(config_values['python_executable'])):
        config_values[field] = str(value) if field == 'python_executable' else [str(value)]
        with pytest.raises(ValueError):
            runtime.load_config(write_config(tmp_path, config_values))


@pytest.mark.skipif(os.name != 'nt', reason='Windows network/device path spellings')
@pytest.mark.parametrize('value', [r'\\server\share\python.exe', r'\\?\C:\Python\python.exe'])
def test_load_config_rejects_network_or_device_paths(tmp_path, config_values, value):
    config_values['python_executable'] = value
    with pytest.raises(ValueError, match='absolute local'):
        runtime.load_config(write_config(tmp_path, config_values))


@pytest.mark.parametrize('raw', [b'{', b'[]', b'null', b'\xff', b' ' * 65537],
                         ids=['syntax', 'array', 'null', 'invalid-utf8', 'oversized'])
def test_load_config_rejects_invalid_documents(tmp_path, raw):
    path = tmp_path / 'runtime.local.json'
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        runtime.load_config(path)


def test_load_config_rejects_duplicate_keys(tmp_path, config_values):
    path = write_config(tmp_path, {**config_values, 'port': 8818})
    path.write_text(path.read_text(encoding='utf-8')[:-1] + ', "port": 8820}', encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate JSON key'):
        runtime.load_config(path)


@pytest.fixture
def installed_runtime():
    python = Path(getattr(sys, '_base_executable', None) or sys.executable).resolve()
    libraries = Path(sysconfig.get_path('purelib')).resolve()
    assert python.is_file() and libraries.is_dir()
    return python, libraries


def configured_command(python, config):
    return [str(python), '-I', '-S', '-B', str(SCRIPT), '--config', str(config)]


def run_check(python, config, **kwargs):
    return subprocess.run(configured_command(python, config) + ['--check'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=30, **kwargs)


def test_isolated_check_uses_installed_libraries_without_site_hooks(tmp_path, installed_runtime):
    python, libraries = installed_runtime
    extra = tmp_path / "会社 packages & ! % '"
    extra.mkdir()
    marker = tmp_path / 'site-hook-executed'
    code = f'from pathlib import Path; Path({str(marker)!r}).write_text("unexpected")\n'
    (extra / 'injected.pth').write_text(
        f'import pathlib; pathlib.Path({str(marker)!r}).write_text("unexpected")\n', encoding='utf-8')
    (extra / 'sitecustomize.py').write_text(code, encoding='utf-8')
    (extra / 'usercustomize.py').write_text(code, encoding='utf-8')
    # An unrelated regular package must not replace the source launcher.
    scripts = extra / 'scripts'
    scripts.mkdir()
    (scripts / '__init__.py').write_text(code, encoding='utf-8')
    (scripts / 'start_workbench.py').write_text(code, encoding='utf-8')
    state = tmp_path / 'not-created-state'
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        config = write_config(tmp_path, {'python_executable': str(python),
            'library_paths': [str(extra), str(libraries)], 'state_dir': str(state),
            'port': occupied.getsockname()[1], 'open_browser': False})
        result = run_check(python, config, cwd=tmp_path, env=dict(os.environ,
            PYTHONPATH=str(extra), PYTHONHOME=str(tmp_path / 'invalid-python-home'),
            PYTHONUSERBASE=str(extra)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Runtime packages: 17 checked' in result.stdout
    assert 'No server started; no packages installed' in result.stdout
    assert not marker.exists() and not state.exists()
    assert not (extra / '__pycache__').exists() and not (tmp_path / '.venv').exists()


def test_runtime_lock_preserves_exact_full_lock_versions_and_hashes():
    def requirement_blocks(filename):
        result = {}
        for block in (ROOT / filename).read_text(encoding='utf-8').strip().split('\n\n'):
            match = re.match(r'([A-Za-z0-9_.-]+)==', block)
            if match:
                result[match.group(1)] = block
        return result

    runtime_blocks = requirement_blocks('requirements-runtime.lock')
    full_blocks = requirement_blocks('requirements.lock')
    assert len(runtime_blocks) == 17
    assert runtime_blocks == {name: full_blocks[name] for name in runtime_blocks}
    assert {'aiohttp', 'python-docx', 'openpyxl', 'python-pptx'} <= runtime_blocks.keys()
    assert not {'pip', 'setuptools', 'pytest', 'pytest-asyncio', 'packaging'} & runtime_blocks.keys()


def test_check_lists_missing_packages_without_installing(tmp_path, installed_runtime):
    python, _ = installed_runtime
    empty = tmp_path / 'empty-packages'
    empty.mkdir()
    config = write_config(tmp_path, {'python_executable': str(python), 'library_paths': [str(empty)]})
    result = run_check(python, config, cwd=tmp_path)
    assert result.returncode == 1
    assert 'aiohttp: missing' in result.stderr and 'python-docx: missing' in result.stderr
    assert 'No packages were installed' in result.stderr
    assert not list(empty.iterdir()) and not (tmp_path / '.venv').exists()


def test_check_reports_version_mismatch_before_loading_package(tmp_path, installed_runtime):
    python, libraries = installed_runtime
    extra = tmp_path / 'version-mismatch'
    metadata = extra / 'aiohttp-0.0.0.dist-info'
    metadata.mkdir(parents=True)
    (metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: aiohttp\nVersion: 0.0.0\n')
    (extra / 'aiohttp.py').write_text('raise AssertionError("must not import incompatible package")\n')
    config = write_config(tmp_path, {'python_executable': str(python),
                                    'library_paths': [str(extra), str(libraries)]})
    result = run_check(python, config, cwd=tmp_path)
    assert result.returncode == 1
    assert 'aiohttp: found 0.0.0, requires 3.14.3' in result.stderr
    assert 'must not import incompatible package' not in result.stderr


def test_check_requires_selected_interpreter_and_isolation_flags(tmp_path, installed_runtime):
    python, libraries = installed_runtime
    config = write_config(tmp_path, {'python_executable': str(python), 'library_paths': [str(libraries)]})
    result = subprocess.run([str(python), str(SCRIPT), '--config', str(config), '--check'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and '-I -S -B' in result.stderr
    other = tmp_path / 'python.exe'
    other.write_bytes(b'Not executed')
    config = write_config(tmp_path, {'python_executable': str(other), 'library_paths': [str(libraries)]})
    result = run_check(python, config, cwd=tmp_path)
    assert result.returncode == 1 and 'does not match python_executable' in result.stderr


def test_configured_libraries_are_denied_even_inside_allowed_parent(tmp_path, config_values, monkeypatch):
    from workbench import runtime_paths
    from workbench.harness import HarnessError, PathHarness

    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(runtime_paths, 'PROTECTED_ROOTS', runtime_paths.PROTECTED_ROOTS)
    config = runtime.load_config(write_config(tmp_path, config_values))
    runtime.prepare_imports(config)
    assert Path(sys.base_prefix).resolve() in runtime_paths.PROTECTED_ROOTS
    dependency = config.library_paths[0] / 'dependency.py'
    dependency.write_text('trusted dependency')
    harness = PathHarness([str(tmp_path)], [str(tmp_path)],
                          [str(path) for path in runtime_paths.PROTECTED_ROOTS])
    for write in (False, True):
        with pytest.raises(HarnessError, match='denied folder'):
            harness.resolve(str(dependency), write=write)


@pytest.mark.skipif(os.name != 'nt', reason='Windows mutex and console process groups required')
def test_configured_server_and_duplicate_launch(tmp_path, installed_runtime):
    python, libraries = installed_runtime
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    state = tmp_path / "会社 state & ! % '"
    config = write_config(tmp_path, {'python_executable': str(python), 'library_paths': [str(libraries)],
                                    'port': port, 'state_dir': str(state), 'open_browser': False})
    command = configured_command(python, config)
    output = tmp_path / 'configured-launch.log'
    with output.open('w', encoding='utf-8') as log:
        first = subprocess.Popen(command, cwd=tmp_path, stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if first.poll() is not None:
                    pytest.fail(output.read_text(encoding='utf-8', errors='replace'))
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                pytest.fail('Configured server did not start')
            second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=20)
            assert second.returncode == 0, second.stdout + second.stderr
            assert 'already starting/running' in second.stdout
            assert first.poll() is None and state.is_dir()
        finally:
            if first.poll() is None:
                first.send_signal(signal.CTRL_BREAK_EVENT)
                try:
                    first.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    first.kill()
                    first.wait(timeout=10)
