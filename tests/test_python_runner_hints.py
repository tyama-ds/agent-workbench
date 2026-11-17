"""Model-readable hints for recognisable sandbox failures, and workspace staging.

failure_hint is pure: these samples are the stderr shapes CPython prints on
Windows (some with the Japanese system messages of the machine that found
them), so they run on any platform.
"""
import inspect
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import python_runner as runner
from workbench.harness import HarnessError
from workbench.windows_sandbox import _workspace_size

WORKSPACE = r'C:\Users\tester\AppData\Local\Temp\awb-python-k3j2'
INTERNAL = [WORKSPACE, r'C:\Python313', r'C:\app\.venv\Lib\site-packages']
HOST_OPEN = rf'''Traceback (most recent call last):
  File "{WORKSPACE}\.awb_bootstrap.py", line 9, in <module>
    runpy.run_path('{WORKSPACE.replace(chr(92), chr(92) * 2)}\\.awb_script.py',run_name="__main__")
  File "<frozen runpy>", line 287, in run_path
  File "{WORKSPACE}\.awb_script.py", line 3, in <module>
    with open(r'C:\Users\tester\Documents\sales.csv', encoding='utf-8') as handle:
         ~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
PermissionError: [Errno 13] Permission denied: 'C:\\Users\\tester\\Documents\\sales.csv'
'''


def hint(stderr, exit_code=1, reason=None, **options):
    return runner.failure_hint(exit_code, reason, stderr, internal=INTERNAL, **options)


def test_host_path_failure_names_the_path_and_the_exact_mapping_shape():
    text = hint(HOST_OPEN)
    assert text.startswith('Host files cannot be opened by their host path inside the script.')
    # The same keys _mappings accepts, with the model's own path filled in.
    assert "{'path': <host path>, 'name': <relative name>} to inputs" in text
    assert r"inputs=[{'path': 'C:\Users\tester\Documents\sales.csv', 'name': 'sales.csv'}] then open('sales.csv')" in text
    assert "{'path': <host path>, 'name': <relative name>, 'expected_sha256': 'missing' for a new file" in text
    assert text.endswith(r'Host paths in the error: C:\Users\tester\Documents\sales.csv')
    # Only the model's path: never the workspace, interpreter or library folders.
    assert 'awb-python-' not in text and 'Python313' not in text
    example = {'path': r'C:\Users\tester\Documents\sales.csv', 'name': 'sales.csv'}
    assert runner._mappings([example])[0]['path'] == example['path']
    assert runner._mappings([{**example, 'expected_sha256': 'missing'}], outputs=True)


@pytest.mark.parametrize('stderr,paths', [
    # Localised system message; os.listdir reports WinError 5 with the path.
    ("PermissionError: [WinError 5] アクセスが拒否されました。: 'D:\\\\共有\\\\売上'", ['D:\\共有\\売上']),
    # A path the sandbox cannot even see is reported as missing.
    ("FileNotFoundError: [Errno 2] No such file or directory: 'C:/data/in.xlsx'", ['C:/data/in.xlsx']),
    ("FileNotFoundError: [WinError 3] 指定されたパスが見つかりません。: '\\\\\\\\server\\\\share\\\\a.csv'",
     ['\\\\server\\share\\a.csv']),
    # pandas and friends re-raise with the same message; two files, one repeated.
    ("    df = pd.read_csv(r'C:\\in\\a.csv'); out = open(r'C:\\out\\b.csv', 'w')\n"
     "PermissionError: [Errno 13] Permission denied: 'C:\\\\in\\\\a.csv'", ['C:\\in\\a.csv', 'C:\\out\\b.csv']),
])
def test_host_paths_are_extracted_from_messages_and_source_lines(stderr, paths):
    assert runner._host_paths(stderr, INTERNAL) == paths
    assert hint(stderr).endswith('Host paths in the error: ' + '; '.join(paths))


def test_extracted_paths_are_bounded_and_internal_folders_are_ignored():
    many = ''.join(f"PermissionError: [Errno 13] Permission denied: 'C:\\\\data\\\\file{index}.csv'\n" for index in range(9))
    assert len(runner._host_paths(many)) == 3
    long_path = "PermissionError: [Errno 13] Permission denied: 'C:\\\\" + 'x' * 250 + "'"
    assert runner._host_paths(long_path) == []
    private = (f"PermissionError: [Errno 13] Permission denied: '{WORKSPACE}\\out'\n"
               "    import_module('C:\\\\app\\\\.venv\\\\Lib\\\\site-packages\\\\pandas\\\\io.py')\n"
               "    requests.get(base + '/api/items')\n")
    assert runner._host_paths(private, INTERNAL) == []
    # Denied inside the workspace (a directory opened as a file) is not a host-path problem.
    assert hint(private) is None
    assert len(hint(many + HOST_OPEN * 20, reason='timeout', timeout=60)) <= 1800


def test_missing_relative_file_points_to_inputs_without_claiming_a_host_path():
    text = hint("FileNotFoundError: [Errno 2] No such file or directory: 'sales.csv'")
    assert text.startswith('The script runs in a private working directory that holds only the declared inputs')
    assert "to inputs and open it by that name" in text and 'Host paths in the error' not in text


def test_refused_subprocess_is_explained_without_a_file_hint():
    stderr = r'''  File "C:\Python313\Lib\subprocess.py", line 1554, in _execute_child
    hp, ht, pid, tid = _winapi.CreateProcess(executable, args,
PermissionError: [WinError 5] アクセスが拒否されました。
'''
    text = hint(stderr)
    assert text.startswith('Starting other programs is blocked in the sandbox')
    assert 'import awb_pytest; raise SystemExit(awb_pytest.run())' in text
    assert 'inputs' not in text


@pytest.mark.parametrize('network_enabled,expected', [
    (False, 'Network access is disabled for this run'),
    (True, 'WinError 10013 with network access enabled'),
])
def test_refused_socket_hint_depends_on_the_network_setting(network_enabled, expected):
    stderr = 'PermissionError: [WinError 10013] アクセス許可で禁じられた方法でソケットにアクセスしようとしました。'
    text = hint(stderr, network_enabled=network_enabled)
    assert text.startswith(expected) and 'inputs' not in text


def test_name_resolution_failure_is_a_network_hint_only_while_network_is_disabled():
    stderr = 'urllib.error.URLError: <urlopen error [Errno 11001] getaddrinfo failed>'
    assert hint(stderr).startswith('Network access is disabled for this run')
    assert hint(stderr, network_enabled=True) is None


@pytest.mark.parametrize('reason,options,expected', [
    ('timeout', {'timeout': 60}, 'The script was stopped at the 60 s time limit; nothing was published.'),
    ('output_limit', {'output_limit': 65536}, 'stdout+stderr exceeded the 65536-byte limit'),
    ('workspace_limit', {}, 'The working directory exceeded its limit (64 MiB, 2048 entries'),
])
def test_termination_reasons_have_hints(reason, options, expected):
    assert hint('', exit_code=1, reason=reason, **options).startswith(expected)
    # The entry count quoted to the model is the watchdog's own default.
    assert inspect.signature(_workspace_size).parameters['max_entries'].default == 2048


def test_missing_module_hint_mentions_the_fallback_for_pytest():
    text = hint("ModuleNotFoundError: No module named 'pytest'")
    assert text.startswith("No module named 'pytest': only the standard library and the library folders")
    assert text.endswith('awb_pytest.run() also works without pytest (built-in simple runner).')
    assert 'awb_pytest.run()' not in hint("ModuleNotFoundError: No module named 'pandas'")


@pytest.mark.parametrize('exit_code,reason,stderr', [
    (0, None, HOST_OPEN),                       # success: warnings on stderr are not failures
    (1, 'cancelled', HOST_OPEN),                # the human stopped it
    (1, None, 'ZeroDivisionError: division by zero'),
    (1, None, "ValueError: could not parse 'C:\\\\data\\\\x.csv'"),  # a path alone is not an access failure
    (1, None, None),
])
def test_no_hint_without_a_recognised_sandbox_failure(exit_code, reason, stderr):
    assert runner.failure_hint(exit_code, reason, stderr, internal=INTERNAL) is None


@pytest.mark.parametrize('name', ['awb_pytest.py', 'AWB_PyTest.py', 'awb_pytest', 'awb_pytest/data.csv',
                                  'awb_pytest.cp313-win_amd64.pyd', '.awb_lib/awb_pytest.py', '.AWB_LIB/x.py'])
def test_helper_names_cannot_be_declared(name):
    for outputs in (False, True):
        item = {'path': 'ignored', 'name': name, **({'expected_sha256': 'missing'} if outputs else {})}
        with pytest.raises(HarnessError, match='reserved'):
            runner._mappings([item], outputs=outputs)


def test_similar_names_are_still_allowed():
    names = ['awb_pytest_report.txt', 'tests/awb_pytest.py', 'test_awb.py', 'pytest.ini', 'conftest.py']
    assert [str(item['name']).replace('\\', '/') for item in
            runner._mappings([{'path': 'ignored', 'name': name} for name in names])] == names


def test_prepare_workspace_stages_script_helper_and_bootstrap(tmp_path):
    workspace = tmp_path / 'awb-python-stage'
    workspace.mkdir()
    (workspace / 'input.csv').write_text('a,b\n')
    bootstrap = runner._prepare_workspace(workspace, 'print(1)', [Path('/libs/site-packages')], 45)
    assert bootstrap == workspace / '.awb_bootstrap.py'
    assert (workspace / '.awb_script.py').read_text(encoding='utf-8') == 'print(1)'
    helper = workspace / '.awb_lib' / 'awb_pytest.py'
    assert helper.read_bytes() == Path(runner.__file__).with_name('sandbox_pytest.py').read_bytes()
    # Everything the runner adds uses the reserved prefix, so no declared input
    # or output can collide with it and none of it can be published.
    assert sorted(path.name for path in workspace.iterdir()) == ['.awb_bootstrap.py', '.awb_lib', '.awb_script.py', 'input.csv']
    lines = bootstrap.read_text(encoding='utf-8').splitlines()
    assert lines[1] == 'os.environ["AWB_PYTHON_TIMEOUT"]=\'45\''
    # Helper first (a workspace file cannot shadow it), then the working
    # directory, then the standard library, then the selected libraries.
    assert lines[3] == f'sys.path[:0]={[str(workspace / ".awb_lib"), str(workspace)]!r}'
    assert lines[4] == f'sys.path.extend({[str(Path("/libs/site-packages"))]!r})'
    # The helper stays far below the workspace watchdog's limits.
    assert _workspace_size(workspace, runner._WORKSPACE_LIMIT) and helper.stat().st_size < 64 * 1024


def test_missing_helper_source_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, '_HELPER_SOURCE', tmp_path / 'absent.py')
    with pytest.raises(HarnessError, match='test helper'):
        runner._prepare_workspace(tmp_path, 'pass', [], 10)


def test_a_rejected_file_mapping_names_the_argument_and_the_value():
    """Real-machine case: three saves failed with "Path contains traversal..." and
    "Path does not exist", and nothing said which argument was wrong."""
    from workbench import python_runner
    from workbench.harness import HarnessError
    good = {'path': 'out/report.docx', 'name': 'report.docx', 'expected_sha256': 'missing'}
    assert python_runner._mappings([good], outputs=True)[0]['path'] == 'out/report.docx'
    with pytest.raises(HarnessError) as absolute:
        python_runner._mappings([{**good, 'name': 'C:\\Users\\me\\out\\report.docx'}], outputs=True)
    message = str(absolute.value)
    assert message.startswith("outputs[0].name 'C:\\\\Users") and 'relative file name inside the sandbox' in message
    with pytest.raises(HarnessError, match=r"inputs\[1\]\.name '\.\./secret\.txt'"):
        python_runner._mappings([{'path': 'a.csv', 'name': 'a.csv'}, {'path': 'b.csv', 'name': '../secret.txt'}])
    with pytest.raises(HarnessError, match=r'outputs\[0\] needs exactly expected_sha256, name, path'):
        python_runner._mappings([{'path': 'out/report.docx', 'name': 'report.docx'}], outputs=True)
    with pytest.raises(HarnessError, match=r"inputs\[0\]\.path 'missing\.csv': .* \(path is the existing host file"):
        python_runner._located("inputs[0].path", 'missing.csv', lambda: (_ for _ in ()).throw(HarnessError('Path does not exist')),
                               'path is the existing host file to copy in')


def test_a_scan_that_meets_a_file_being_saved_is_made_again_before_the_run_is_ended(tmp_path, monkeypatch):
    """CI case (real Windows sandbox): a script saved a .docx, an .xlsx and a .pptx; one scan of the
    workspace met a file in the moment it was written and the run ended as 'workspace_changed'."""
    import contextlib
    import os
    from workbench import windows_sandbox
    from workbench.windows_sandbox import SandboxError, _live_scan
    pauses = []
    monkeypatch.setattr(windows_sandbox.time, 'sleep', pauses.append)

    # A real scan over a folder in which a file vanishes between being listed and being looked at.
    (tmp_path / 'kept.txt').write_text('x' * 10)
    (tmp_path / 'sample.docx.tmp').write_text('y')
    real_scandir, vanished = os.scandir, []

    def scandir(path):
        entries = list(real_scandir(path))
        if not vanished:
            vanished.append(True)
            (tmp_path / 'sample.docx.tmp').unlink()        # listed, then gone
        return contextlib.nullcontext(iter(entries))
    monkeypatch.setattr(windows_sandbox.os, 'scandir', scandir)

    def streams(path):
        # As the real check does for a file that is gone (FindFirstStreamW fails): an error, not "no streams".
        if not os.path.lexists(path):
            raise SandboxError('Cannot inspect private storage streams')
        return False
    # One scan alone does fail. Where the listing keeps each entry's details (Windows) it is the
    # stream check that fails; elsewhere looking at the vanished entry already does.
    with pytest.raises((OSError, SandboxError)):
        _workspace_size(tmp_path, 1000, named_stream=streams)
    vanished.clear()
    (tmp_path / 'sample.docx.tmp').write_text('y')
    assert _live_scan(lambda: _workspace_size(tmp_path, 1000, named_stream=streams)) is True and pauses == [.005]
    assert _live_scan(lambda: _workspace_size(tmp_path, 5, named_stream=streams)) is False   # over the limit is an answer, not a failure

    # Transient failures of either kind are retried; a failure that stays is still reported.
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 4:
            raise (PermissionError('sharing violation') if len(attempts) % 2 else SandboxError('Cannot inspect private storage streams'))
        return True
    pauses.clear()
    assert _live_scan(flaky) is True and len(attempts) == 4 and pauses == [.005, .01, .02]

    def broken():
        attempts.append(1)
        raise SandboxError('Private sandbox root was replaced')
    attempts.clear()
    pauses.clear()
    with pytest.raises(SandboxError, match='root was replaced'):
        _live_scan(broken)
    assert len(attempts) == len(windows_sandbox._LIVE_SCAN_PAUSES) == 6 and sum(pauses) == pytest.approx(.155)
    with pytest.raises(ValueError):                         # anything else is not a storage race
        _live_scan(lambda: (_ for _ in ()).throw(ValueError('bug')))
    # The loop that watches a running script uses it; the scan after the script has ended does not.
    source = inspect.getsource(windows_sandbox)
    assert source.count('_live_scan(lambda:') == 1 and source.count('_workspace_size(workspace, workspace_limit') == 2
