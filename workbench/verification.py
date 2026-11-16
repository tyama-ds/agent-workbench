"""Running tests for the team, and telling the human when they were not run (phase 9).

``run_tests`` lets any agent that may run Python hand the application a folder
and get test results back: the application copies the files into the sandbox
and runs them, so the agent needs no script, inputs or outputs. Every test run
(this tool, or ``python_execute`` output that carries an ``awb_pytest:``
summary) is recorded by the application. When the human asked for the tests to
be run, the root PM's completion is checked against that record: a missing or
failed run is sent back once, and whatever the PM then reports, the
application states the recorded outcome under the result.
"""
from __future__ import annotations

import re
import time

from .python_runner import MAX_TEST_PATHS, execute_tests

STRING = {'type': 'string'}
RUN_TESTS_TOOL = {'name': 'run_tests', 'description': (
    'Run Python tests with pytest and get the pass/fail counts and output. The application copies the files into the '
    'sandbox and runs them for you: no script, inputs or outputs, and nothing is written back. '
    'paths: the folder that holds both the code and its tests (or each such file or folder; a src/ folder is importable). '
    'Use this whenever the task asks to run, pass or verify tests; a test that was only written is not verified.'),
    'parameters': {'type': 'object', 'properties': {
        'paths': {'type': 'array', 'minItems': 1, 'maxItems': MAX_TEST_PATHS, 'items': STRING}},
        'required': ['paths'], 'additionalProperties': False}}
TESTS_POLICY = ('\n\nTests: when the request asks to run or pass tests, run them with run_tests (give the folder that holds '
                'the code and the tests) and report the counts it returns. Never report tests as passing without a run; '
                'if they cannot be run, say so plainly.')
TESTS_UNAVAILABLE_POLICY = ('\n\nTests: this run cannot execute code, so tests cannot be run here. '
                            'Say plainly that they were not run; never report them as passing.')

_TEST_REQUEST = re.compile(
    r'テスト[^。．\n]{0,24}(?:実行|走ら|回し|回す|通し|通す|通る|通ること|パス|合格|成功|確認)'
    r'|(?:pytest|unittest)[^。．\n]{0,24}(?:実行|走ら|回し|回す|通し|通す|通る|パス|確認)'
    r'|\b(?:run|execute|pass)(?:es|ing)?\b[^.\n]{0,40}\b(?:tests?|pytest|unittest)\b'
    r'|\b(?:tests?|pytest)\b[^.\n]{0,40}\b(?:pass(?:es|ing)?|are run|is run|be run|executed)\b', re.I)
_SUMMARY = re.compile(r'^awb_pytest: (.*(\d+) passed, (\d+) failed, (\d+) not run.*)$', re.M)
_STATE_LABELS = {'passed': '成功', 'failed': '失敗あり', 'missing': '未実行'}


def tests_requested(text):
    """True when the human's wording asks for tests to be executed, not only written."""
    return bool(isinstance(text, str) and _TEST_REQUEST.search(text))


def test_outcome(stdout, exit_code):
    """The last ``awb_pytest:`` summary in a script's output, or None.

    ok needs a clean exit, at least one passed test and none failed or not run.
    """
    found = _SUMMARY.findall(stdout if isinstance(stdout, str) else '')
    if not found:
        return None
    line, passed, failed, not_run = found[-1]
    passed, failed, not_run = int(passed), int(failed), int(not_run)
    return {'ok': exit_code == 0 and passed > 0 and failed == 0 and not_run == 0,
            'passed': passed, 'failed': failed, 'not_run': not_run, 'summary': line.strip()[:300]}


def _tail(value, limit):
    value = value if isinstance(value, str) else ''
    return value if len(value) <= limit else '...\n' + value[-limit:]


class VerificationMixin:
    # Engine._python_ready(run) says whether Python can run in this run.

    def _tests_note_request(self, run, text):
        """The human's request or a later message asks for a test run; checked at the next completion."""
        if tests_requested(text):
            run['_tests_requested'], run['_tests_gated'] = True, False
            self._tests_publish(run)

    def _tests_policy(self, run):
        if not run.get('_tests_requested'):
            return ''
        return TESTS_POLICY if self._python_ready(run) else TESTS_UNAVAILABLE_POLICY

    def _tests_record(self, run, agent, tool, result):
        """Remember a test run found in a tool result; returns its outcome or None."""
        if not isinstance(result, dict):
            return None
        outcome = test_outcome(result.get('stdout'), result.get('exit_code'))
        if outcome is None:
            return None
        record = {**outcome, 'agent_id': agent.id, 'tool': tool, 'at': time.time()}
        runs = run.setdefault('_test_runs', [])
        runs.append(record)
        del runs[:-50]
        self.event(run['id'], agent.id, 'tests_run',
                   f'{agent.name} がテストを実行しました: {outcome["summary"]}'
                   + ('' if outcome['ok'] else '（成功していません）'))
        self._tests_publish(run)
        return record

    def _tests_state(self, run):
        runs = run.get('_test_runs') or []
        if not runs:
            return 'missing', ''
        last = runs[-1]
        return ('passed' if last['ok'] else 'failed'), last['summary']

    def _tests_publish(self, run):
        """What the human sees next to the run: asked for, and how the last run ended."""
        if not run.get('_tests_requested') and not run.get('_test_runs'):
            return
        state, summary = self._tests_state(run)
        run['test_check'] = {'requested': bool(run.get('_tests_requested')), 'state': state,
                             'summary': self.redact(summary), 'runs': len(run.get('_test_runs') or [])}

    async def _run_tests(self, run, agent, args):
        if not self._python_ready(run):
            raise ValueError('Python実行は無効、またはWindowsの隔離実行に未対応です。テストは実行できません')
        if set(args) != {'paths'}:
            raise ValueError('run_tests の引数は paths だけです')
        result = await execute_tests(run['_config']['python'], run['_harness'], args['paths'])
        outcome = self._tests_record(run, agent, 'run_tests', result)
        files = result.get('files') or []
        response = {'ok': bool(outcome and outcome['ok']),
                    'summary': outcome['summary'] if outcome else 'no test summary was produced',
                    **({key: outcome[key] for key in ('passed', 'failed', 'not_run')} if outcome else {}),
                    'exit_code': result.get('exit_code'), 'files_copied': len(files), 'files': files[:40],
                    'stdout': _tail(result.get('stdout'), 6000), 'stderr': _tail(result.get('stderr'), 3000)}
        for key in ('termination_reason', 'hint'):
            if result.get(key):
                response[key] = result[key]
        if not response['ok'] and 'ModuleNotFoundError' in (result.get('stdout') or '') + (result.get('stderr') or ''):
            response['note'] = ('A module was not found. paths must include the folder that holds the code under test, '
                                'not only the tests; only the selected libraries are installed.')
        return response

    def _tests_gate(self, run, agent):
        """Once per run: text sending the root PM back when requested tests did not pass or run."""
        if agent.parent_id is not None or not run.get('_tests_requested') or run.get('_tests_gated'):
            return None
        state, summary = self._tests_state(run)
        if state == 'passed' or not self._python_ready(run):
            return None
        if any(self.agents[ident].status in {'working', 'queued'} or self.agents[ident].pending
               for ident in run['agent_ids'] if ident != agent.id):
            return None
        run['_tests_gated'] = True
        if state == 'missing':
            return ('[application notice] The human asked for the tests to be run, but the application has no record of a '
                    'test run in this work. Call run_tests now with the folder that holds the code and its tests, read '
                    'the result, fix any failure and run again. Finish only after that; if the tests cannot be run, '
                    'say so plainly in your result instead of reporting success.')
        return ('[application notice] The last test run recorded by the application did not pass: ' + summary + '. '
                'Fix the cause and call run_tests again, or state plainly in your result that the tests fail. '
                'Do not report success.')

    def _tests_footer(self, run):
        """The application's own record, appended to the root PM's result."""
        if not run.get('_tests_requested') and not run.get('_test_runs'):
            return ''
        self._tests_publish(run)
        state, summary = self._tests_state(run)
        if state == 'passed':
            return f'\n\n【アプリの確認】テストの実行記録: 成功（{self.redact(summary)}）'
        if state == 'failed':
            return ('\n\n【アプリの確認】テストは実行されましたが、最後の実行は成功していません（'
                    f'{self.redact(summary)}）。成果物は、テストに合格した状態ではありません。')
        reason = '' if self._python_ready(run) else '（この作業では Python の実行が許可されていない、または Windows 以外のため、アプリからは実行できません）'
        return ('\n\n【アプリの確認】テストの実行が依頼されていますが、この作業ではテストが一度も実行されていません' + reason
                + '。成果物は未検証です。上の報告に「合格」「成功」とあっても、アプリの実行記録はありません。')
