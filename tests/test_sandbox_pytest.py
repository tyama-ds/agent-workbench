"""awb_pytest, run the way the sandbox runs it but without the Windows LPAC.

Each test stages a workspace with python_runner's own function, then starts
its bootstrap in a subprocess with the sandbox's interpreter flags. Tests may
use a subprocess; scripts inside the sandbox may not, which is why the helper
runs tests in-process.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import python_runner as runner
from workbench import sandbox_pytest

# The folder a human would select as a library path: it holds pytest and, in
# the development environment, pytest-asyncio, whose autoload broke the sandbox.
LIBRARIES = [Path(pytest.__file__).resolve().parent.parent]
RUN = 'import awb_pytest\nraise SystemExit(awb_pytest.run())\n'
CALC = 'def add(a, b):\n    return a + b\n'
PASSING = '''import sys
import pytest
from calc import add

def test_add():
    assert add(1, 2) == 3

@pytest.mark.parametrize('a,b,total', [(1, 1, 2), (2, 3, 5)])
def test_table(a, b, total):
    assert add(a, b) == total

def test_tmp_path_is_inside_the_workspace(tmp_path):
    (tmp_path / 'note.txt').write_text('kept inside')
    assert tmp_path.resolve().is_relative_to(Path.cwd().resolve())

def test_no_site_packages_plugin_was_loaded():
    assert not [name for name in sys.modules if name.startswith(('pytest_asyncio', 'asyncio', 'anyio'))]

from pathlib import Path
'''
FAILING = '''from calc import add

def test_ok():
    assert add(1, 2) == 3

def test_wrong_total():
    total = add(2, 2)
    assert total == 5
'''
SLOW = '''import time

def test_first():
    pass

def test_stuck():
    time.sleep(60)

def test_never_reached():
    pass
'''


def sandbox(tmp_path, code, files=None, *, timeout=60, libraries=LIBRARIES):
    workspace = tmp_path / 'awb-python-test'
    workspace.mkdir()
    for name, text in (files or {}).items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    bootstrap = runner._prepare_workspace(workspace, code, libraries, timeout)
    started = time.monotonic()
    # The sandbox's minimal environment: no PATH, PYTHONPATH, user profile or pytest variables.
    environment = {'TEMP': str(workspace), 'TMP': str(workspace)}
    if 'SystemRoot' in os.environ:
        environment['SystemRoot'] = os.environ['SystemRoot']
    done = subprocess.run([sys.executable, '-I', '-S', '-B', '-u', '-X', 'utf8', str(bootstrap)], cwd=workspace,
                          env=environment, capture_output=True, encoding='utf-8', timeout=120)
    done.seconds = time.monotonic() - started
    done.workspace = workspace
    return done


def summary(done):
    return [line for line in done.stdout.splitlines() if line.startswith('awb_pytest: ')][-1]


def test_passing_tests_run_under_real_pytest_without_leaving_the_workspace(tmp_path):
    done = sandbox(tmp_path, RUN, {'calc.py': CALC, 'test_calc.py': PASSING})
    assert done.returncode == 0, done.stdout + done.stderr
    assert '5 passed' in done.stdout  # parametrize and tmp_path prove this is pytest
    assert summary(done) == 'awb_pytest: 5 passed, 0 failed, 0 not run (pytest, exit code 0)'
    assert done.stderr == ''
    names = {path.relative_to(done.workspace).as_posix() for path in done.workspace.rglob('*')}
    assert '.awb_lib/awb_pytest.py' in names
    # No cache, bytecode, config or link outside the reserved names; passed
    # tests leave no temporary directory behind (the workspace has an entry limit).
    assert names <= {'.awb_bootstrap.py', '.awb_script.py', '.awb_lib', '.awb_lib/awb_pytest.py',
                     '.awb_pytest.ini', '.awb_pytest_tmp', 'calc.py', 'test_calc.py'}
    assert [path.name for path in tmp_path.iterdir()] == ['awb-python-test']


def test_failing_test_returns_non_zero_and_shows_the_assertion(tmp_path):
    done = sandbox(tmp_path, RUN, {'calc.py': CALC, 'test_calc.py': FAILING})
    assert done.returncode == 1
    assert 'assert total == 5' in done.stdout and 'assert 4 == 5' in done.stdout
    assert 'test_calc.py::test_wrong_total' in done.stdout
    assert summary(done) == 'awb_pytest: 1 passed, 1 failed, 0 not run (pytest, exit code 1)'


def test_simple_mode_reports_each_test_and_never_passes_what_it_cannot_run(tmp_path):
    tests = '''import pytest

@pytest.fixture
def database():
    return {}

def test_plain():
    assert 1 + 1 == 2

def test_fixture(database):
    assert database == {}

@pytest.mark.parametrize('value', [1, 2])
def test_table(value):
    assert value

async def test_async():
    assert False

def test_tmp(tmp_path):
    (tmp_path / 'a.txt').write_text('x')
    assert [item.name for item in tmp_path.iterdir()] == ['a.txt']

def test_helpers(monkeypatch):
    monkeypatch.setenv('AWB_SIMPLE', '1')
    with pytest.raises(ZeroDivisionError):
        1 / 0
    assert 0.1 + 0.2 == pytest.approx(0.3)

@pytest.mark.skip(reason='not today')
def test_skipped():
    assert False

class TestGroup:
    def setup_method(self):
        self.value = 2

    def test_value(self):
        assert self.value == 2
'''
    done = sandbox(tmp_path, 'import awb_pytest\nraise SystemExit(awb_pytest.run(simple=True))\n',
                   {'test_simple.py': tests})
    lines = done.stdout.splitlines()
    assert 'test_simple.py::test_plain PASSED' in lines
    assert "test_simple.py::test_fixture NOT RUN (needs pytest: fixture database)" in lines
    assert 'test_simple.py::test_table NOT RUN (needs pytest: parametrize)' in lines
    assert 'test_simple.py::test_async NOT RUN (needs pytest: async test)' in lines
    assert 'test_simple.py::test_tmp PASSED' in lines and 'test_simple.py::test_helpers PASSED' in lines
    assert 'test_simple.py::test_skipped SKIPPED (not today)' in lines
    assert 'test_simple.py::TestGroup::test_value PASSED' in lines
    assert summary(done) == 'awb_pytest: 4 passed, 0 failed, 3 not run, 1 skipped (simple runner, exit code 2)'
    assert done.returncode == 2  # nothing failed, but "all passed" would be untrue
    assert not list((done.workspace / '.awb_simple_tmp').iterdir())


def test_simple_mode_failure_shows_the_line_and_values(tmp_path):
    done = sandbox(tmp_path, 'import awb_pytest\nraise SystemExit(awb_pytest.run(simple=True))\n',
                   {'calc.py': CALC, 'test_calc.py': FAILING})
    assert done.returncode == 1
    assert 'test_calc.py::test_wrong_total FAILED' in done.stdout
    assert 'assert total == 5' in done.stdout and 'locals: total=4' in done.stdout
    assert summary(done) == 'awb_pytest: 1 passed, 1 failed, 0 not run (simple runner, exit code 1)'


def test_simple_mode_runs_unittest_cases_and_xunit_setup(tmp_path):
    tests = '''import unittest
calls = []

def setup_module(module):
    calls.append('module')

def setup_function(function):
    calls.append(function.__name__)

def test_setup_order():
    assert calls == ['module', 'test_setup_order']

class Legacy(unittest.TestCase):
    def setUp(self):
        self.value = 3

    def test_equal(self):
        self.assertEqual(self.value, 3)

    def test_unequal(self):
        self.assertEqual(self.value, 4)

    @unittest.skip('later')
    def test_skipped(self):
        pass
'''
    done = sandbox(tmp_path, 'import awb_pytest\nraise SystemExit(awb_pytest.run(simple=True))\n',
                   {'test_legacy.py': tests}, libraries=[])
    lines = done.stdout.splitlines()
    assert 'test_legacy.py::test_setup_order PASSED' in lines
    assert 'test_legacy.py::Legacy::test_equal PASSED' in lines
    assert 'test_legacy.py::Legacy::test_unequal FAILED' in lines and 'AssertionError: 3 != 4' in done.stdout
    assert 'test_legacy.py::Legacy::test_skipped SKIPPED (later)' in lines
    assert done.returncode == 1


def test_stuck_pytest_dumps_thread_stacks_and_falls_back_within_the_deadline(tmp_path):
    code = '''import time
import awb_pytest

def stuck_before_any_test(*arguments):
    time.sleep(60)

awb_pytest._pytest_main = stuck_before_any_test
raise SystemExit(awb_pytest.run(timeout=3))
'''
    done = sandbox(tmp_path, code, {'calc.py': CALC, 'test_calc.py': FAILING})
    assert done.seconds < 10
    # The diagnostic for the next real-machine run: every thread's stack.
    assert re.search(r'awb_pytest: pytest started no test within 1\.\d s \(stage: importing pytest\); '
                     r'stacks of all threads follow', done.stderr)
    assert 'in stuck_before_any_test' in done.stderr and 'most recent call first' in done.stderr
    assert 'awb_pytest: end of thread stacks' in done.stderr
    assert 'falling back to the built-in simple runner' in done.stdout
    # The fallback is a real result, not a guess.
    assert 'test_calc.py::test_ok PASSED' in done.stdout and 'test_calc.py::test_wrong_total FAILED' in done.stdout
    assert summary(done) == 'awb_pytest: 1 passed, 1 failed, 0 not run (simple runner, exit code 1)'
    assert done.returncode == 1


def test_pytest_that_resumes_after_the_fallback_does_not_run_the_tests_again(tmp_path):
    code = '''import time
import awb_pytest
real = awb_pytest._pytest_main

def late(*arguments):
    time.sleep(2)
    return real(*arguments)

awb_pytest._pytest_main = late
code = awb_pytest.run(timeout=2)
time.sleep(2)  # the abandoned pytest thread wakes up while the script is still alive
raise SystemExit(code)
'''
    done = sandbox(tmp_path, code, {'test_one.py': 'def test_one():\n    print("ran test_one")\n'})
    assert done.returncode == 0
    assert summary(done) == 'awb_pytest: 1 passed, 0 failed, 0 not run (simple runner, exit code 0)'
    assert done.stdout.count('ran test_one') == 1 and ' passed in ' not in done.stdout


def test_deadline_comes_from_the_sandbox_time_limit(tmp_path):
    code = '''import time
import awb_pytest
awb_pytest._pytest_main = lambda *arguments: time.sleep(60)
raise SystemExit(awb_pytest.run())
'''
    done = sandbox(tmp_path, code, {'test_one.py': 'def test_one():\n    pass\n'}, timeout=4)
    assert done.returncode == 0 and done.seconds < 4
    assert summary(done) == 'awb_pytest: 1 passed, 0 failed, 0 not run (simple runner, exit code 0)'
    bootstrap = (done.workspace / '.awb_bootstrap.py').read_text(encoding='utf-8')
    assert 'os.environ["AWB_PYTHON_TIMEOUT"]=\'4\'' in bootstrap


def test_slow_test_under_pytest_reports_partial_results_instead_of_running_twice(tmp_path):
    done = sandbox(tmp_path, 'import awb_pytest\nraise SystemExit(awb_pytest.run(timeout=4))\n', {'test_slow.py': SLOW})
    assert done.seconds < 10 and done.returncode == 2
    assert summary(done) == ('awb_pytest: 1 passed, 0 failed, 2 not run; time limit reached at stage: '
                             'running test_slow.py::test_stuck; thread stacks are on stderr (pytest, exit code 2)')
    assert 'in test_stuck' in done.stderr
    assert 'simple runner' not in done.stdout


def test_stuck_test_in_simple_mode_still_returns_a_summary(tmp_path):
    done = sandbox(tmp_path, 'import awb_pytest\nraise SystemExit(awb_pytest.run(simple=True, timeout=2))\n',
                   {'test_slow.py': SLOW})
    assert done.seconds < 10 and done.returncode == 2
    assert 'test_slow.py::test_first PASSED' in done.stdout
    assert summary(done) == ('awb_pytest: 1 passed, 0 failed, 0 not run; time limit reached while running '
                             'test_slow.py::test_stuck (simple runner, exit code 2)')
    assert 'in test_stuck' in done.stderr


def test_without_pytest_the_simple_runner_is_used(tmp_path):
    done = sandbox(tmp_path, RUN, {'calc.py': CALC, 'test_calc.py': FAILING}, libraries=[])
    assert "awb_pytest: pytest is not available (No module named 'pytest'); falling back" in done.stdout
    assert summary(done) == 'awb_pytest: 1 passed, 1 failed, 0 not run (simple runner, exit code 1)'
    assert done.returncode == 1


def test_broken_pytest_start_falls_back_with_the_reason(tmp_path):
    code = '''import awb_pytest

def refused(*arguments):
    raise PermissionError(13, 'synthetic sandbox refusal')

awb_pytest._pytest_main = refused
raise SystemExit(awb_pytest.run())
'''
    done = sandbox(tmp_path, code, {'test_one.py': 'def test_one():\n    pass\n'})
    assert 'awb_pytest: pytest could not run (PermissionError: [Errno 13] synthetic sandbox refusal); falling back' in done.stdout
    assert 'in refused' in done.stderr
    assert done.returncode == 0


def test_tests_written_in_the_script_itself_are_run(tmp_path):
    code = '''def add(a, b):
    return a + b

def test_add():
    assert add(1, 2) == 3

class TestAdd:
    def test_wrong(self):
        assert add(1, 1) == 3

import awb_pytest
raise SystemExit(awb_pytest.run())
'''
    done = sandbox(tmp_path, code)
    assert '.awb_script.py::test_add PASSED' in done.stdout
    assert '.awb_script.py::TestAdd::test_wrong FAILED' in done.stdout
    assert summary(done) == 'awb_pytest: 1 passed, 1 failed, 0 not run (simple runner, exit code 1)'
    assert done.returncode == 1


def test_no_tests_and_missing_path_are_reported_not_passed(tmp_path):
    done = sandbox(tmp_path, 'import awb_pytest\nprint(awb_pytest.run(), awb_pytest.run("missing_test.py"))\n')
    assert done.stdout.splitlines()[-1] == '5 4'
    assert 'no tests found' in done.stdout and 'test path not found in the working directory: missing_test.py' in done.stdout


def test_selected_test_ids_work_in_both_runners(tmp_path):
    code = ('import awb_pytest\n'
            'print(awb_pytest.run("test_calc.py::test_ok"), awb_pytest.run(["test_calc.py::test_ok"], simple=True))\n')
    done = sandbox(tmp_path, code, {'calc.py': CALC, 'test_calc.py': FAILING})
    assert done.stdout.splitlines()[-1] == '0 0'
    assert 'awb_pytest: 1 passed, 0 failed, 0 not run (pytest, exit code 0)' in done.stdout
    assert 'awb_pytest: 1 passed, 0 failed, 0 not run (simple runner, exit code 0)' in done.stdout
    assert 'test_wrong_total' not in done.stdout


def test_workspace_modules_and_the_helper_are_importable_under_isolated_flags(tmp_path):
    code = ('import sys, calc, awb_pytest\n'
            'print(calc.add(2, 3), awb_pytest.__file__.replace(chr(92), "/").endswith("/.awb_lib/awb_pytest.py"))\n'
            'print(sys.flags.isolated, sys.flags.no_site, sys.dont_write_bytecode)\n')
    done = sandbox(tmp_path, code, {'calc.py': CALC}, libraries=[])
    assert done.stdout.splitlines() == ['5 True', '1 1 True'], done.stderr


def test_helper_keeps_links_and_owner_only_directories_out_of_the_workspace(tmp_path, monkeypatch):
    forwarded = []
    monkeypatch.setattr(os, 'mkdir', lambda path, mode=0o777, **kwargs: forwarded.append(mode))
    plain_mkdir, real_symlink = os.mkdir, os.symlink
    with sandbox_pytest._sandbox_os(windows=True):
        os.mkdir(tmp_path / 'a', 0o700)
        os.mkdir(tmp_path / 'b', 0o750)
        os.mkdir(tmp_path / 'c')
        with pytest.raises(OSError, match='not available in the sandbox'):
            os.symlink(tmp_path, tmp_path / 'link')
    assert forwarded == [0o777, 0o750, 0o777]
    assert os.mkdir is plain_mkdir and os.symlink is real_symlink
    with sandbox_pytest._sandbox_os(windows=False):
        assert os.mkdir is plain_mkdir and os.symlink is not real_symlink
    assert not (tmp_path / 'link').is_symlink()


def test_helper_source_is_standard_library_only_and_ascii():
    import ast
    source = Path(sandbox_pytest.__file__).read_text(encoding='ascii')
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or '.').split('.')[0])
    # pytest is imported lazily inside functions and is optional.
    assert imported - {'pytest'} <= set(sys.stdlib_module_names)


# Real-machine finding (Windows LPAC): the sandboxed process may not stat the
# folder that contains its working directory. pytest asks whether that parent
# "is a file" while collecting, and Python 3.13 lets the PermissionError out.
DENY_PARENT = '''import os
_stat, _parent = os.stat, os.path.dirname(os.getcwd())

def _denied(path, *args, **kwargs):
    if os.path.normcase(os.path.abspath(os.fspath(path))) == os.path.normcase(_parent):
        raise PermissionError(13, 'Access is denied', os.fspath(path))
    return _stat(path, *args, **kwargs)

os.stat = _denied
'''


def test_pytest_collects_when_the_parent_of_the_workspace_cannot_be_read(tmp_path):
    result = sandbox(tmp_path, DENY_PARENT + RUN, {'calc.py': CALC, 'test_calc.py': PASSING})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'passed' in result.stdout and '(pytest, exit code 0)' in result.stdout
    assert 'PermissionError' not in result.stdout + result.stderr


def test_when_pytest_cannot_collect_at_all_the_simple_runner_still_runs_the_tests(tmp_path):
    # The same refusal, but raised as OSError so the helper's own guard does not absorb it:
    # pytest reports "ERROR collecting test session" and no test runs.
    script = DENY_PARENT.replace('PermissionError(13', 'OSError(5') + RUN
    files = {'calc.py': CALC, 'test_calc.py': 'from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n'}
    result = sandbox(tmp_path, script, files)
    assert 'ERROR collecting test session' in result.stdout, result.stdout + result.stderr
    assert 'pytest could not collect any test' in result.stdout and 'falling back to the built-in simple runner' in result.stdout
    assert summary(result) == 'awb_pytest: 1 passed, 0 failed, 0 not run (simple runner, exit code 0)'
    assert result.returncode == 0


def test_a_broken_test_file_is_still_a_failure_after_the_fallback(tmp_path):
    result = sandbox(tmp_path, RUN, {'test_broken.py': 'import module_that_does_not_exist\n\ndef test_x():\n    pass\n'})
    assert result.returncode != 0, result.stdout + result.stderr
