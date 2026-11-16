"""Phase 9: run_tests (the application copies the files and runs the tests),
the record of test runs, and telling the human when requested tests did not run."""
import asyncio

import pytest

from workbench import python_runner, verification
from workbench.engine import Engine
from workbench.harness import HarnessError, PathHarness, ToolExecutor
from test_engine import configured, reply, start
from test_phase9_completion import quiet


# --- what is copied into the sandbox -------------------------------------------------

def project(root):
    (root / 'src').mkdir(parents=True)
    (root / 'tests').mkdir()
    (root / 'src' / 'calc.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
    (root / 'tests' / 'test_calc.py').write_text('from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n', encoding='utf-8')
    (root / 'tests' / 'cases.json').write_text('[]', encoding='utf-8')
    (root / '__pycache__').mkdir()
    (root / '__pycache__' / 'calc.cpython-313.pyc').write_bytes(b'\0')
    (root / '.venv').mkdir()
    (root / '.venv' / 'big.py').write_text('x = 1', encoding='utf-8')
    (root / 'report.xlsx').write_bytes(b'PK')
    return root


def test_a_folder_is_copied_with_its_layout_and_without_caches(tmp_path):
    root = project(tmp_path / 'proj')
    harness = PathHarness([str(tmp_path)], [])
    inputs, skipped = python_runner.collect_test_inputs(harness, [str(root)])
    assert [item['name'] for item in inputs] == ['src/calc.py', 'tests/cases.json', 'tests/test_calc.py']
    assert skipped == 1  # report.xlsx; cache and virtual-environment folders are not entered
    # Two folders keep their place below the folder they share.
    inputs, _ = python_runner.collect_test_inputs(harness, [str(root / 'tests'), str(root / 'src')])
    assert [item['name'] for item in inputs] == ['src/calc.py', 'tests/cases.json', 'tests/test_calc.py']
    # Single files of one folder land side by side.
    inputs, _ = python_runner.collect_test_inputs(harness, [str(root / 'src' / 'calc.py')])
    assert [item['name'] for item in inputs] == ['calc.py']


def test_paths_outside_the_permitted_folders_or_without_python_are_refused(tmp_path):
    inside, outside = tmp_path / 'in', tmp_path / 'out'
    inside.mkdir(), outside.mkdir()
    (outside / 'test_x.py').write_text('def test_x(): pass', encoding='utf-8')
    (inside / 'notes.txt').write_text('memo', encoding='utf-8')
    harness = PathHarness([str(inside)], [])
    with pytest.raises(HarnessError, match='outside the permitted'):
        python_runner.collect_test_inputs(harness, [str(outside)])
    with pytest.raises(HarnessError, match='No Python files'):
        python_runner.collect_test_inputs(harness, [str(inside)])
    with pytest.raises(HarnessError, match='1 to 16'):
        python_runner.collect_test_inputs(harness, [])
    for index in range(python_runner.MAX_TEST_FILES + 1):
        (inside / f'test_{index}.py').write_text('', encoding='utf-8')
    with pytest.raises(HarnessError, match='More than 200 files'):
        python_runner.collect_test_inputs(harness, [str(inside)])


def test_the_sandbox_script_runs_awb_pytest_with_src_importable():
    compile(python_runner.TEST_CODE, 'run_tests', 'exec')
    assert 'awb_pytest.run()' in python_runner.TEST_CODE and '"src"' in python_runner.TEST_CODE


# --- wording and summaries -----------------------------------------------------------

@pytest.mark.parametrize('text,expected', [
    ('計算モジュールを作り、テストも実行して', True),
    ('pytest を書いて、通ることを確認してください', True),
    ('テストがすべてパスする状態にして', True),
    ('Write the function and run the tests', True),
    ('Make sure all tests pass', True),
    ('テストコードも書いてください', False),
    ('統計のテスト結果を表にまとめて', False),
    ('しりとりを10回して', False),
])
def test_only_a_request_to_execute_tests_counts(text, expected):
    assert verification.tests_requested(text) is expected


def test_the_summary_line_decides_the_outcome():
    passed = verification.test_outcome('collected 2 items\nawb_pytest: 2 passed, 0 failed, 0 not run (exit code 0)\n', 0)
    assert passed['ok'] and passed['passed'] == 2
    failed = verification.test_outcome('awb_pytest: 1 passed, 1 failed, 0 not run (exit code 1)\n', 1)
    assert not failed['ok'] and failed['failed'] == 1
    assert not verification.test_outcome('awb_pytest: 0 passed, 0 failed, 0 not run (exit code 5)\n', 5)['ok']
    assert not verification.test_outcome('awb_pytest: 2 passed, 0 failed, 1 not run (simple runner, exit code 2)\n', 2)['ok']
    assert verification.test_outcome('2 passed in 0.1s', 0) is None  # not the application's runner


# --- the engine ----------------------------------------------------------------------

def sandbox(monkeypatch, outputs):
    """Stand-in for the Windows sandbox: each call returns the next prepared output."""
    calls = []

    async def fake(config, harness, paths):
        calls.append(list(paths))
        stdout, code = outputs[min(len(calls), len(outputs)) - 1]
        return {'exit_code': code, 'termination_reason': None, 'stdout': stdout, 'stderr': '', 'outputs': [],
                'files': ['calc.py', 'test_calc.py'], 'files_skipped': 0}
    monkeypatch.setattr(verification, 'execute_tests', fake)
    monkeypatch.setattr(Engine, '_python_ready', lambda self, run: bool(run['_config']['python']['enabled']))
    return calls


PASS = ('awb_pytest: 2 passed, 0 failed, 0 not run (exit code 0)\n', 0)
FAIL = ("E   ModuleNotFoundError: No module named 'calc'\nawb_pytest: 0 passed, 1 failed, 0 not run (exit code 1)\n", 1)


@pytest.mark.asyncio
async def test_run_tests_is_offered_with_python_and_records_the_result(tmp_path, monkeypatch):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    calls = sandbox(monkeypatch, [FAIL, PASS])
    try:
        run, pm = await start(engine, task='計算モジュールを作ってテストも実行して', max_workers=0)
        assert 'run_tests' not in {tool['name'] for tool in engine._model_tools(run, pm)}
        assert 'cannot execute code' in engine._policy(run, pm)
        run['_config']['python']['enabled'] = True
        names = {tool['name'] for tool in engine._model_tools(run, pm)}
        assert {'run_tests', 'python_execute'} <= names
        pm.read_only = True  # a read-only verifier keeps run_tests, not its own code
        limited = {tool['name'] for tool in engine._model_tools(run, pm)}
        assert 'run_tests' in limited and 'python_execute' not in limited
        pm.read_only = False
        assert 'run them with run_tests' in engine._policy(run, pm)
        assert run['test_check'] == {'requested': True, 'state': 'missing', 'summary': '', 'runs': 0}

        first = await engine.execute_tool(run, pm, 'run_tests', {'paths': [str(work)]})
        assert first['ok'] is False and first['failed'] == 1 and 'folder that holds the code under test' in first['note']
        assert run['test_check']['state'] == 'failed'
        second = await engine.execute_tool(run, pm, 'run_tests', {'paths': [str(work)]})
        assert second['ok'] is True and second['passed'] == 2 and second['files_copied'] == 2
        assert calls == [[str(work)], [str(work)]]
        assert run['test_check']['state'] == 'passed' and run['test_check']['runs'] == 2
        assert [row['kind'] for row in engine.events].count('tests_run') == 2
        pm.pending.clear()
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '実装とテストを終えました。'})
        assert done['ok'] and 'テストの実行記録: 成功（2 passed, 0 failed, 0 not run' in done['summary']
        with pytest.raises(ValueError, match='paths だけ'):
            await engine.execute_tool(run, pm, 'run_tests', {'paths': [str(work)], 'code': 'x'})
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_finishing_without_the_requested_test_run_is_sent_back_once_then_reported(tmp_path, monkeypatch):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    sandbox(monkeypatch, [PASS])
    try:
        run, pm = await start(engine, task='関数を実装し、テストも実行してください', max_workers=0)
        run['_config']['python']['enabled'] = True
        pm.pending.clear()
        refused = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'テストは全て合格しました。'})
        assert refused['ok'] is False and refused['code'] == 'tests_not_passed' and 'run_tests' in refused['error']
        assert pm.status != 'done'
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'テストは全て合格しました。'})
        assert done['ok'] and '一度も実行されていません' in done['summary'] and '未検証' in done['summary']
        assert run['test_check'] == {'requested': True, 'state': 'missing', 'summary': '', 'runs': 0}
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_a_task_that_never_asked_for_tests_gets_no_check(tmp_path, monkeypatch):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    sandbox(monkeypatch, [PASS])
    try:
        run, pm = await start(engine, task='売上を集計して表にして', max_workers=0)
        run['_config']['python']['enabled'] = True
        assert 'Tests:' not in engine._policy(run, pm) and 'test_check' not in run
        pm.pending.clear()
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '集計しました。'})
        assert done['ok'] and 'テスト' not in done['summary']
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_without_python_the_missing_run_is_reported_without_a_pointless_retry(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='実装してテストも実行して', max_workers=0)
        pm.pending.clear()
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '実装しました。テストは未実行です。'})
        assert done['ok'] and '一度も実行されていません' in done['summary'] and 'アプリからは実行できません' in done['summary']
        with pytest.raises(ValueError, match='テストは実行できません'):
            await engine.execute_tool(run, pm, 'run_tests', {'paths': [str(work)]})
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_a_plain_text_completion_is_also_sent_back_and_a_worker_run_counts(tmp_path, monkeypatch):
    """Real-machine case: the PM delegated the coding task, the 実行・検証担当 never
    ran anything, and the PM reported completion."""
    sandbox(monkeypatch, [PASS])

    class Team:
        pm_calls = 0
        worker_calls = 0

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            names = {tool['name'] for tool in tools}
            if '"assigned_role": "検証"' in system:
                self.worker_calls += 1
                assert 'run_tests' in names
                if self.worker_calls == 1:
                    return reply(calls=[('run_tests', {'paths': ['.']})])
                return reply(calls=[('finish_work', {'summary': 'テストを実行し、2 件合格しました。'})])
            self.pm_calls += 1
            if self.pm_calls == 1:
                return reply('実装が完了しました。テストも問題ありません。')  # nothing was run
            if self.pm_calls == 2:
                assert any('no record of a test run' in str(message.get('content')) for message in messages)
                return reply(calls=[('spawn_worker', {'role': '検証', 'task': 'テストを実行する', 'profile_id': 'local'})])
            return reply('検証担当がテストを実行し、合格しました。')

    engine, work = configured(tmp_path, Team())
    engine.settings.value['python']['enabled'] = True
    try:
        run, pm = await start(engine, task='計算モジュールを実装し、テストも実行して')
        await quiet(engine)
        assert run['status'] == 'done', (run['status'], pm.status, pm.last_error)
        assert run['test_check']['state'] == 'passed'
        assert 'テストの実行記録: 成功' in pm.results[-1]['text']
        assert [row['kind'] for row in engine.events].count('tests_run') == 1
    finally:
        await engine.close()


@pytest.mark.approvals
@pytest.mark.asyncio
async def test_run_tests_waits_for_approval_like_python(tmp_path, monkeypatch):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    sandbox(monkeypatch, [PASS])
    try:
        run, pm = await start(engine, task='テストを実行して', max_workers=0)
        run['_config']['python']['enabled'] = True
        assert engine._approval_needed(run, 'run_tests', {'paths': [str(work)]}) == run['_config']['approvals']['python']
        assert str(work) in engine._approval_summary(run, 'run_tests', {'paths': [str(work)]})
        task = asyncio.ensure_future(engine.execute_tool(run, pm, 'run_tests', {'paths': [str(work)]}))
        for _ in range(100):
            await asyncio.sleep(.01)
            if pm.approval:
                break
        assert pm.approval and pm.approval['tool'] == 'run_tests'
        engine.resolve_approval(pm.id, {'approval_id': pm.approval['id'], 'decision': 'approve'})
        assert (await task)['ok'] is True
    finally:
        await engine.close()


# --- P3: numbers written as text -----------------------------------------------------

@pytest.mark.asyncio
async def test_numeric_strings_become_numbers_in_xlsx(tmp_path):
    import io
    import openpyxl
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    target = str(tmp_path / 'stats.xlsx')
    values = ['123,366,734', '1,234.50', '12.5%', '42', '-1,000', '００１２', '0123', "'2024", '1234567890123456', '東京都', 3.5, None,
              # Real-machine case: one column held both; the second stayed text because its "0." was counted as a digit.
              '1.19311288444599%', '0.239578342117881%', '0.0023957834211788123', '123456789012345.678']
    cells = [{'sheet': 'Sheet', 'cell': f'A{index}', 'value': value} for index, value in enumerate(values, 1)]
    result = await tools.execute('xlsx_write', {'path': target, 'cells': cells, 'expected_sha256': 'missing'})
    assert result['numeric_strings_converted'] == 9
    sheet = openpyxl.load_workbook(io.BytesIO((tmp_path / 'stats.xlsx').read_bytes()))['Sheet']
    got = [sheet[f'A{index}'].value for index in range(1, len(values) + 1)]
    assert got[:12] == [123366734, 1234.5, 0.125, 42, -1000, '００１２', '0123', '2024', '1234567890123456', '東京都', 3.5, None]
    assert got[12] == pytest.approx(0.0119311288444599) and got[13] == pytest.approx(0.00239578342117881)
    assert got[14] == pytest.approx(0.0023957834211788123) and got[15] == pytest.approx(123456789012345.678)
    assert all(isinstance(value, float) for value in got[12:])
    assert sheet['A13'].number_format == sheet['A14'].number_format  # the whole column is one type and format
    assert sheet['A1'].number_format == '#,##0' and sheet['A2'].number_format == '#,##0.00' and sheet['A3'].number_format == '0.0%'
    assert sheet['A4'].number_format == 'General'
    # Other formula-like text is still refused.
    with pytest.raises(HarnessError, match='Formula-like'):
        await tools.execute('xlsx_write', {'path': str(tmp_path / 'other.xlsx'), 'expected_sha256': 'missing',
                                           'cells': [{'sheet': 'Sheet', 'cell': 'A1', 'value': '-SUM(A1)'}]})
