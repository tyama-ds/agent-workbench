"""Test runner for scripts inside the python_execute sandbox (``import awb_pytest``).

python_runner copies this file, unchanged, into every private workspace as
``.awb_lib/awb_pytest.py``. It must stay standard-library only and must not
import anything from the Workbench. The sandbox forbids subprocesses and, by
default, sockets, so tests run in this process:

    import awb_pytest
    raise SystemExit(awb_pytest.run())

``run`` uses real pytest with a locked-down configuration, cannot outlive its
time budget, and falls back to a small built-in runner when pytest is missing,
breaks or hangs.
"""
import contextlib
import faulthandler
import fnmatch
import importlib.util
import inspect
import os
import pathlib
import shutil
import sys
import threading
import time
import traceback
import unittest

_PREFIX = 'awb_pytest: '
# Written by the python_runner bootstrap: the sandbox time limit in seconds and
# time.monotonic() of this process when the bootstrap started.
_ENV_TIMEOUT, _ENV_STARTED = 'AWB_PYTHON_TIMEOUT', 'AWB_PYTHON_STARTED'
_DEFAULT_BUDGET = 300.0
# pytest must have started its first test within this share of the remaining
# time; otherwise it is treated as stuck and the simple runner takes over.
_PYTEST_START_SHARE = 0.5
_PYTEST_ENV = ('PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'PYTEST_DEBUG', 'PYTEST_DEBUG_TEMPROOT', 'PY_COLORS', 'FORCE_COLOR')
_PATTERNS = ('test_*.py', '*_test.py')
_SKIP_DIRECTORIES = {'__pycache__', 'node_modules', 'venv', 'build', 'dist'}
_MAX_FILES = 200
_NEEDS = 'needs pytest: '
_RUNNER_FILES = (__file__, os.path.dirname(unittest.__file__) + os.sep)


def run(paths=None, *, simple=False, timeout=None):
    """Run tests in the working directory and return an exit code (0 = all passed).

    paths    test files, directories or ``file::name`` ids; default: every
             ``test_*.py`` / ``*_test.py`` below the working directory. Without
             such files, tests defined in the running script itself are run.
    simple   True skips pytest and uses the built-in runner (plain asserts,
             ``tmp_path``, ``monkeypatch``; anything else is reported as not run).
    timeout  seconds this call may take; default: what is left of the sandbox
             time limit.

    Exit codes: 0 all passed, 1 failures, 2 incomplete (time limit, collection
    errors, or tests the simple runner could not run), 4 bad path, 5 no tests.
    """
    out = sys.stdout
    root = os.getcwd()
    selected = [paths] if isinstance(paths, (str, os.PathLike)) else list(paths or [])
    selected = [os.fspath(item) for item in selected]
    deadline = time.monotonic() + _budget(timeout)
    streams = (sys.stdin, sys.stdout, sys.stderr)
    with _sandbox_os():
        try:
            return _run(selected, root, simple, deadline, out)
        finally:
            # A pytest thread that never finished may have left these changed.
            sys.stdin, sys.stdout, sys.stderr = streams
            with contextlib.suppress(OSError):
                os.chdir(root)


def _budget(timeout):
    try:
        total, started = float(os.environ[_ENV_TIMEOUT]), float(os.environ[_ENV_STARTED])
    except (KeyError, ValueError):
        left = _DEFAULT_BUDGET
    else:
        # Keep time for interpreter start-up, the final summary and a clean exit.
        left = total - (time.monotonic() - started) - min(max(3.0, 0.1 * total), 0.5 * total)
    if timeout is not None:
        left = min(left, float(timeout))
    return max(0.5, left)


def _say(out, text, *, interrupts=False):
    """One prefixed line; interrupts=True first ends a line pytest left open."""
    with contextlib.suppress(Exception):
        out.write(('\n' if interrupts else '') + _PREFIX + text + '\n')
        out.flush()


@contextlib.contextmanager
def _sandbox_os(windows=None):
    """Keep pytest and tempfile within what the sandbox workspace allows.

    os.symlink fails: the workspace watchdog stops a run whose workspace holds
    a link, and pytest's tmp_path adds a "<name>current" link where the OS
    permits it (pytest ignores the failure).

    On Windows, 0o700 directories get the default, inherited permissions:
    since Python 3.12.4 os.mkdir(mode=0o700) applies an owner-only ACL, pytest
    (tmp_path, --basetemp) and tempfile.mkdtemp use that mode, and a sandboxed
    process is not expected to be able to enter such a directory afterwards.
    The private workspace needs no extra protection.
    """
    mkdir, symlink = os.mkdir, getattr(os, 'symlink', None)

    def plain_mkdir(path, mode=0o777, *args, **kwargs):
        return mkdir(path, 0o777 if mode == 0o700 else mode, *args, **kwargs)

    def no_symlink(*args, **kwargs):
        raise OSError('symbolic links are not available in the sandbox working directory')

    if (os.name == 'nt') if windows is None else windows:
        os.mkdir = plain_mkdir
    if symlink is not None:
        os.symlink = no_symlink
    try:
        yield
    finally:
        os.mkdir = mkdir
        if symlink is not None:
            os.symlink = symlink


class _Worker:
    """Run function in a daemon thread, so a hang can never outlive the deadline."""

    def __init__(self, function):
        self.box = []

        def target():
            try:
                self.box.append(('done', function()))
            except BaseException as exc:  # SystemExit and pytest outcomes included
                self.box.append(('error', exc))

        self.thread = threading.Thread(target=target, name='awb-pytest-worker', daemon=True)
        self.thread.start()

    def wait(self, seconds):
        """('done', value), ('error', exception) or ('timeout', None)."""
        self.thread.join(max(0.0, seconds))
        return self.box[0] if self.box else ('timeout', None)


def _dump_stacks(reason):
    """The diagnostic for a hang: every thread's Python stack, on stderr."""
    stream = sys.__stderr__ or sys.stderr
    try:
        stream.write(f'{_PREFIX}{reason}; stacks of all threads follow\n')
        stream.flush()
        faulthandler.dump_traceback(file=stream, all_threads=True)
        stream.write(_PREFIX + 'end of thread stacks\n')
        stream.flush()
    except Exception:
        with contextlib.suppress(Exception):
            for ident, frame in sys._current_frames().items():
                stream.write(f'Thread {ident}:\n' + ''.join(traceback.format_stack(frame, limit=40)))
            stream.write(_PREFIX + 'end of thread stacks\n')
            stream.flush()


def _run(selected, root, simple, deadline, out):
    try:
        targets = _targets(selected, root)
    except LookupError as exc:
        _say(out, f'{exc}; 0 passed, 0 failed, 0 not run (exit code 4)')
        return 4
    if not targets:
        _say(out, 'no tests found. Put tests in test_*.py or *_test.py files in the working directory '
                  '(declare them as inputs or write them from the script) and call awb_pytest.run() again; '
                  '0 passed, 0 failed, 0 not run (exit code 5)')
        return 5
    in_script = any(kind == 'main' for kind, _, _ in targets)
    allow_pytest = True
    if in_script and not simple:
        _say(out, 'tests defined in the running script use the built-in simple runner '
                  '(pytest needs them in test_*.py files)')
    elif not simple:
        state = {'stage': 'importing pytest', 'outcomes': {}, 'collection_errors': 0, 'collected': 0}
        limit = (deadline - time.monotonic()) * _PYTEST_START_SHARE
        worker = _Worker(lambda: _pytest_main(selected or [root], root, state))
        status, value = worker.wait(limit)
        if status == 'timeout' and state['stage'].startswith(('running ', 'finishing')):
            # Tests are running: slow, not stuck at start-up. Give them the rest.
            status, value = worker.wait(deadline - time.monotonic())
            if status == 'timeout':
                stage = state['stage']
                _dump_stacks(f'time limit reached at pytest stage: {stage}')
                _stop_pytest(state)
                outcomes = list(state['outcomes'].values())
                outcomes += ['not run'] * max(0, state['collected'] - len(outcomes))
                code = 1 if 'failed' in outcomes else 2
                _say(out, f'{_counts(outcomes)}; time limit reached at stage: {stage}; '
                          f'thread stacks are on stderr (pytest, exit code {code})', interrupts=True)
                return code
        if status == 'done' and value in (0, 1, 2, 5):
            _say(out, _counts(state['outcomes'].values()) + _plural(state['collection_errors'], 'collection error')
                 + f' (pytest, exit code {value})')
            return value
        if status == 'timeout':
            stage = state['stage']
            _dump_stacks(f'pytest started no test within {limit:.1f} s (stage: {stage})')
            _stop_pytest(state)
            # A second import of a module whose import is stuck would block too.
            allow_pytest = stage != 'importing pytest'
            why = f'pytest started no test within {limit:.1f} s (stage: {stage}; thread stacks are on stderr)'
        elif status == 'error' and isinstance(value, ImportError) and state['stage'] == 'importing pytest':
            why = f'pytest is not available ({value})'
        elif status == 'error':
            why = f'pytest could not run ({type(value).__name__}: {str(value)[:300]})'
            with contextlib.suppress(Exception):
                sys.stderr.write(_clip(''.join(traceback.format_exception(type(value), value, value.__traceback__))))
        else:
            why = f'pytest stopped with exit code {value} (internal or usage error)'
        _say(out, why + '; falling back to the built-in simple runner')
    progress = {'results': [], 'current': None, 'stop': False}
    status, value = _Worker(lambda: _simple(targets, root, progress, out, allow_pytest)).wait(
        deadline - time.monotonic())
    incomplete = ''
    if status == 'timeout':
        progress['stop'] = True
        incomplete = f'time limit reached while running {progress["current"] or "the test files"}'
        _dump_stacks(incomplete)
    elif status == 'error':
        incomplete = f'simple runner stopped ({type(value).__name__}: {str(value)[:300]})'
    outcomes = [outcome for _, outcome in progress['results']]
    if incomplete:
        code = 1 if 'failed' in outcomes else 2
    elif 'failed' in outcomes:
        code = 1
    elif 'not run' in outcomes:
        code = 2
    else:
        code = 0 if outcomes else 5
    _say(out, _counts(outcomes) + (f'; {incomplete}' if incomplete else '') + f' (simple runner, exit code {code})',
         interrupts=status == 'timeout')
    return code


def _counts(outcomes):
    outcomes = list(outcomes)
    text = ', '.join(f'{outcomes.count(name)} {name}' for name in ('passed', 'failed', 'not run'))
    return text + _plural(outcomes.count('skipped'), 'skipped', plural='skipped')


def _plural(count, noun, plural=None):
    return f', {count} {noun if count == 1 else plural or noun + "s"}' if count else ''


def _clip(text, limit=4000):
    return text if len(text) <= limit else text[:limit // 3] + '\n...\n' + text[-(2 * limit // 3):]


# --- pytest -----------------------------------------------------------------

class _Recorder:
    """pytest plugin: where the run is and what each test did, for the summary."""

    def __init__(self, state):
        self.state = state

    def pytest_sessionstart(self, session):
        self.state['session'] = session
        self.state['stage'] = 'collecting tests'
        if self.state.get('abandoned'):
            _stop_pytest(self.state)

    def pytest_collectreport(self, report):
        if report.failed:
            self.state['collection_errors'] += 1

    def pytest_collection_finish(self, session):
        self.state['collected'] = len(session.items)
        self.state['stage'] = f'collected {len(session.items)} tests'

    def pytest_runtest_logstart(self, nodeid, location):
        self.state['stage'] = f'running {nodeid}'

    def pytest_runtest_logreport(self, report):
        outcomes = self.state['outcomes']
        if report.failed:
            outcomes[report.nodeid] = 'failed'
        elif report.skipped:
            outcomes.setdefault(report.nodeid, 'skipped')
        elif report.when == 'call':
            outcomes.setdefault(report.nodeid, 'passed')

    def pytest_sessionfinish(self, session, exitstatus):
        self.state['stage'] = 'finishing'


def _stop_pytest(state):
    """Ask an abandoned pytest thread to stop at its next collection or test boundary."""
    state['abandoned'] = True
    with contextlib.suppress(Exception):
        state['session'].shouldstop = 'awb_pytest time limit'


def _pytest_main(arguments, root, state):
    """Call pytest.main with everything that reaches outside the workspace turned off."""
    # Plugins from site-packages are not loaded: some (pytest-asyncio, anyio)
    # import asyncio machinery that opens a socket, which the sandbox refuses.
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    for name in _PYTEST_ENV:
        os.environ.pop(name, None)
    os.environ['NO_COLOR'] = '1'
    os.environ.setdefault('COLUMNS', '100')  # no terminal size probing
    os.environ.setdefault('LINES', '40')
    import pytest
    if state.get('abandoned'):  # the caller gave up while pytest was being imported
        return 2
    state['stage'] = 'starting pytest (configuration)'
    # An explicit empty config file stops the search for one in parent folders.
    config = os.path.join(root, '.awb_pytest.ini')
    with open(config, 'w', encoding='utf-8') as handle:
        handle.write('[pytest]\n')
    return int(pytest.main([
        '-p', 'no:cacheprovider',   # no .pytest_cache writes
        '-p', 'no:faulthandler',    # no duplicated stderr descriptor
        '-p', 'no:pastebin', '-p', 'no:junitxml',
        '--capture=no',             # no descriptor redirection or temporary files
        '--color=no', '--tb=short', '-q', '-ra',
        '--rootdir', root, '--confcutdir', root, '-c', config,
        '--basetemp', os.path.join(root, '.awb_pytest_tmp'),
        '-o', 'console_output_style=classic',
        '-o', 'tmp_path_retention_policy=failed',  # the workspace has an entry limit
        *arguments], plugins=[_Recorder(state)]))


# --- built-in simple runner --------------------------------------------------

def _main_module():
    module = sys.modules.get('__main__')
    return module, getattr(module, '__file__', None)


def _same_file(first, second):
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def _files(directory):
    found = []
    for folder, directories, names in os.walk(directory):
        directories[:] = sorted(name for name in directories
                                if not name.startswith('.') and name not in _SKIP_DIRECTORIES)
        found.extend(os.path.join(folder, name) for name in sorted(names)
                     if any(fnmatch.fnmatch(name, pattern) for pattern in _PATTERNS))
        if len(found) >= _MAX_FILES:
            break
    return found[:_MAX_FILES]


def _targets(selected, root):
    """Resolve paths to [(kind, file or module, selector)]; kind is 'file' or 'main'."""
    main, main_file = _main_module()
    targets = []
    for text in selected:
        name, _, selector = text.partition('::')
        path = os.path.abspath(os.path.join(root, name))
        if main_file and _same_file(path, main_file):
            targets.append(('main', main, selector or None))
        elif os.path.isdir(path):
            targets.extend(('file', item, None) for item in _files(path))
        elif os.path.isfile(path):
            targets.append(('file', path, selector or None))
        else:
            raise LookupError(f'test path not found in the working directory: {name}')
    if not selected:
        targets = [('file', item, None) for item in _files(root)]
        if not targets and main is not None and any(True for _ in _cases(main)):
            targets = [('main', main, None)]
    return targets


class _Context:
    def __init__(self, root, progress, out, pytest):
        self.root, self.progress, self.out, self.pytest = root, progress, out, pytest
        self.temporary = 0

    @property
    def stopped(self):
        return self.progress['stop']

    def begin(self, test_id):
        if self.stopped:
            return
        if self.progress['current'] is not None:
            self.end('failed', 'no outcome reported')
        self.progress['current'] = test_id
        # The name is written first so a hard stop still shows the running test.
        self._write(test_id + ' ')

    def end(self, outcome, detail=''):
        if self.stopped:
            return
        self.progress['results'].append((self.progress['current'], outcome))
        self.progress['current'] = None
        label = outcome.upper()
        detail = str(detail).strip('\n')
        if outcome == 'failed' and detail:
            self._write(label + '\n' + ''.join(f'    {line}\n' for line in detail.split('\n')))
        else:
            self._write(label + (f' ({detail})' if detail else '') + '\n')

    def note(self, test_id, outcome, detail=''):
        self.begin(test_id)
        self.end(outcome, detail)

    def _write(self, text):
        with contextlib.suppress(Exception):
            self.out.write(text)
            self.out.flush()

    def tmp_path(self):
        self.temporary += 1
        path = pathlib.Path(self.root, '.awb_simple_tmp', f't{self.temporary}')
        path.mkdir(parents=True)
        return path


def _simple(targets, root, progress, out, allow_pytest):
    pytest = None
    if allow_pytest:
        # Importing pytest does not load plugins; only pytest.main does.
        os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        try:
            import pytest
        except Exception:
            pytest = None
    context = _Context(root, progress, out, pytest)
    for index, (kind, source, selector) in enumerate(targets):
        if context.stopped:
            return
        if kind == 'main':
            label = os.path.basename(getattr(source, '__file__', '') or '') or '__main__'
            _run_module(source, label, selector, context, None)
            continue
        label = os.path.relpath(source, root).replace(os.sep, '/')
        blocked = 'conftest.py' if _has_conftest(source, root) else None
        try:
            module = _import_file(source, index)
        except BaseException as exc:
            context.note(label, 'failed', 'import error\n' + _describe(exc))
            continue
        _run_module(module, label, selector, context, blocked)


def _has_conftest(path, root):
    folder = os.path.dirname(path)
    while True:
        if os.path.isfile(os.path.join(folder, 'conftest.py')):
            return True
        parent = os.path.dirname(folder)
        if _same_file(folder, root) or parent == folder:
            return False
        folder = parent


def _import_file(path, index):
    folder = os.path.dirname(path)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    name = f'awb_test_{index}_{os.path.splitext(os.path.basename(path))[0]}'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_marker(value):
    return getattr(value, '_fixture_function_marker', None) or getattr(value, '_pytestfixturefunction', None)


def _cases(module):
    """Yield (kind, name, object): 'function', 'class' (pytest style) or 'unittest'."""
    for name, value in list(vars(module).items()):
        if _fixture_marker(value) is not None:
            continue
        if inspect.isclass(value):
            if getattr(value, '__module__', None) != module.__name__:
                continue
            if issubclass(value, unittest.TestCase):
                yield 'unittest', name, value
            elif name.startswith('Test'):
                yield 'class', name, value
        elif name.startswith('test') and inspect.isfunction(value):
            yield 'function', name, value


def _selected(test_id, label, selector):
    target = f'{label}::{selector}'
    return selector is None or test_id == target or test_id.startswith(target + '::')


def _marks(*owners):
    found = []
    for owner in owners:
        value = getattr(owner, 'pytestmark', None)
        found.extend(mark for mark in (value if isinstance(value, (list, tuple)) else [value])
                     if hasattr(mark, 'name') and hasattr(mark, 'args'))
    return found


def _verdict(function, marks, context):
    """('run', fixture names), ('skipped', reason) or ('not run', reason)."""
    for mark in marks:
        if mark.name == 'skip':
            return 'skipped', str(mark.kwargs.get('reason') or (mark.args[0] if mark.args else 'skip mark'))
        if mark.name == 'skipif':
            if not mark.args or not all(isinstance(item, bool) for item in mark.args):
                return 'not run', _NEEDS + 'skipif with a string condition'
            if any(mark.args):
                return 'skipped', str(mark.kwargs.get('reason') or 'skipif mark')
        if mark.name in ('parametrize', 'usefixtures', 'xfail'):
            return 'not run', _NEEDS + mark.name
    if inspect.iscoroutinefunction(function) or inspect.isasyncgenfunction(function):
        return 'not run', _NEEDS + 'async test'
    if inspect.isgeneratorfunction(function):
        return 'not run', _NEEDS + 'generator test'
    try:
        # unittest.mock.patch decorators inject their own positional arguments.
        parameters = inspect.signature(function, follow_wrapped=not hasattr(function, 'patchings')).parameters
    except (TypeError, ValueError):
        parameters = {}
    needed = [item.name for item in parameters.values() if item.default is item.empty
              and item.kind in (item.POSITIONAL_OR_KEYWORD, item.KEYWORD_ONLY)]
    supported = {'tmp_path', 'monkeypatch'} if context.pytest is not None else {'tmp_path'}
    unknown = [name for name in needed if name not in supported]
    if unknown:
        return 'not run', _NEEDS + 'fixture ' + ', '.join(unknown)
    return 'run', needed


def _hook(owner, name, argument):
    """Call an xunit-style setup/teardown function, with or without its optional argument."""
    function = getattr(owner, name, None)
    if not callable(function):
        return
    try:
        wanted = [item for item in inspect.signature(function).parameters.values()
                  if item.default is item.empty and item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)]
    except (TypeError, ValueError):
        wanted = []
    function(argument) if wanted else function()


def _call(function, fixtures, context):
    values, undo = {}, []
    try:
        if 'tmp_path' in fixtures:
            values['tmp_path'] = context.tmp_path()
            undo.append(lambda: shutil.rmtree(values['tmp_path'], ignore_errors=True))
        if 'monkeypatch' in fixtures:
            values['monkeypatch'] = context.pytest.MonkeyPatch()
            undo.append(values['monkeypatch'].undo)
        function(**values)
    finally:
        for step in reversed(undo):
            step()


def _attempt(context, test_id, body, setup=(), teardown=()):
    context.begin(test_id)
    error = None
    try:
        try:
            for step in setup:
                step()
            body()
        finally:
            for step in teardown:
                step()
    except BaseException as exc:
        error = exc
    skips = (unittest.SkipTest,)
    if context.pytest is not None:  # pytest.skip() / pytest.xfail() called inside the test
        skips += (context.pytest.skip.Exception, context.pytest.xfail.Exception)
    if error is None:
        context.end('passed')
    elif isinstance(error, skips):
        context.end('skipped', str(error))
    else:
        context.end('failed', _describe(error))


def _describe(error):
    """Bounded traceback without the runner's leading frames; locals for a bare assert."""
    trace = error.__traceback__
    while trace is not None and trace.tb_frame.f_code.co_filename.startswith(_RUNNER_FILES):
        trace = trace.tb_next
    text = ''.join(traceback.format_exception(type(error), error, trace, limit=-8))
    if isinstance(error, AssertionError) and not str(error) and trace is not None:
        while trace.tb_next is not None:
            trace = trace.tb_next
        shown = []
        for key, value in list(trace.tb_frame.f_locals.items()):
            if key.startswith('__') or inspect.ismodule(value) or inspect.isroutine(value) or inspect.isclass(value):
                continue
            try:
                shown.append(f'{key}={repr(value)[:120]}')
            except Exception:
                shown.append(f'{key}=<unprintable>')
            if len(shown) == 8:
                break
        if shown:
            text += 'locals: ' + ', '.join(shown) + '\n'
    return _clip(text)


def _run_module(module, label, selector, context, blocked):
    cases = []
    for kind, name, value in _cases(module):
        if kind == 'function':
            cases.append((f'{label}::{name}', kind, value, name))
        elif kind == 'unittest':
            cases.extend((f'{label}::{name}::{method}', kind, value, method)
                         for method in unittest.TestLoader().getTestCaseNames(value))
        else:
            methods = dict.fromkeys(key for base in reversed(value.__mro__) for key in vars(base))
            cases.extend((f'{label}::{name}::{method}', kind, value, method) for method in methods
                         if method.startswith('test') and callable(getattr(value, method, None)))
    cases = [case for case in cases if _selected(case[0], label, selector)]
    if not cases:
        return
    if blocked is None and any(getattr(_fixture_marker(value), 'autouse', False) for value in vars(module).values()):
        blocked = 'autouse fixture'
    if blocked is None and '__init__' in {key for _, kind, value, _ in cases if kind == 'class' for key in vars(value)}:
        blocked = 'test class with __init__'
    if blocked is not None:
        for test_id, *_ in cases:
            context.note(test_id, 'not run', _NEEDS + blocked)
        return
    try:
        _hook(module, 'setup_module', module)
    except BaseException as exc:
        for test_id, *_ in cases:
            context.note(test_id, 'failed', 'setup_module failed\n' + _describe(exc))
        return
    try:
        classes = {}
        for test_id, kind, value, name in cases:
            if context.stopped:
                return
            if kind == 'function':
                action, detail = _verdict(value, _marks(module, value), context)
                if action != 'run':
                    context.note(test_id, action, detail)
                    continue
                _attempt(context, test_id, lambda: _call(value, detail, context),
                         [lambda: _hook(module, 'setup_function', value)],
                         [lambda: _hook(module, 'teardown_function', value)])
            else:
                classes.setdefault(value, (kind, []))[1].append((test_id, name))
        for owner, (kind, members) in classes.items():
            if context.stopped:
                return
            (_run_unittest if kind == 'unittest' else _run_class)(module, owner, members, context)
    finally:
        with contextlib.suppress(BaseException):
            _hook(module, 'teardown_module', module)


def _run_class(module, owner, members, context):
    try:
        _hook(owner, 'setup_class', owner)
    except BaseException as exc:
        for test_id, _ in members:
            context.note(test_id, 'failed', 'setup_class failed\n' + _describe(exc))
        return
    try:
        for test_id, name in members:
            if context.stopped:
                return
            plain = inspect.getattr_static(owner, name)
            try:
                instance = owner()
                method = getattr(instance, name)
            except BaseException as exc:
                context.note(test_id, 'failed', _describe(exc))
                continue
            action, detail = _verdict(method, _marks(module, owner, getattr(plain, '__func__', plain)), context)
            if action != 'run':
                context.note(test_id, action, detail)
                continue
            _attempt(context, test_id, lambda: _call(method, detail, context),
                     [lambda: _hook(instance, 'setup_method', method)],
                     [lambda: _hook(instance, 'teardown_method', method)])
    finally:
        with contextlib.suppress(BaseException):
            _hook(owner, 'teardown_class', owner)


class _UnitResult(unittest.TestResult):
    def __init__(self, context, ids):
        super().__init__()
        self.context, self.ids = context, ids

    def _report(self, test, outcome, detail=''):
        if self.context.progress['current'] is None:
            self.context.begin(self.ids.get(getattr(test, '_testMethodName', None), str(test)))
        self.context.end(outcome, detail)

    def startTest(self, test):
        super().startTest(test)
        self.shouldStop = self.context.stopped
        self.context.begin(self.ids.get(test._testMethodName, str(test)))

    def addSuccess(self, test):
        self._report(test, 'passed')

    def addFailure(self, test, err):
        self._report(test, 'failed', _describe(err[1]))

    addError = addFailure

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self._report(test, 'failed', _describe(err[1]))

    def addSkip(self, test, reason):
        self._report(test, 'skipped', reason)

    def addExpectedFailure(self, test, err):
        self._report(test, 'skipped', 'expected failure')

    def addUnexpectedSuccess(self, test):
        self._report(test, 'failed', 'unexpected success')


def _run_unittest(module, owner, members, context):
    ids = {name: test_id for test_id, name in members}
    unittest.TestSuite(owner(name) for name in ids).run(_UnitResult(context, ids))
