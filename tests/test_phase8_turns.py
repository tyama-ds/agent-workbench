"""Phase 8: mandatory plan and application-run turns (しりとり end to end)."""
import asyncio
import re

import pytest

from workbench.providers import ModelReply, ProviderError
from workbench.turns import TurnGame, tail_kana, to_reading
from test_engine import configured, reply, settled, start

TASK = '５人雇って、みんなでしりとりして。１０回は回して。しりとりの履歴をエクセルにして出力して。'
KANA = 'かきくけこさしすせそたちつてとなにぬねのまみむめも'


def tool_names(tools):
    return {tool['name'] for tool in tools}


class GameClient:
    """A scripted team: the PM plans turns, each participant plays one valid word per turn."""

    def __init__(self, plan, *, moves=None):
        self.plan, self.moves = plan, moves or {}
        self.calls, self.counter, self.systems = [], 0, {}

    def word(self, head):
        self.counter += 1
        return (head or 'あ') + KANA[self.counter % len(KANA)] + KANA[(self.counter // len(KANA)) % len(KANA)] + 'り'

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        names = tool_names(tools)
        agent = conversation_id.rsplit('/', 1)[1]
        self.calls.append((agent, names))
        self.systems[agent] = system
        last = next(row['content'] for row in reversed(messages) if row['role'] in {'user', 'tool'})
        if 'plan_work' in names:
            return reply(calls=[('plan_work', self.plan)])
        if 'submit_turn' in names:
            turn = int(re.search(r'【手番 (\d+)/', next(
                row['content'] for row in reversed(messages) if row['role'] == 'user' and '【手番' in row['content'])).group(1))
            scripted = self.moves.get(turn)
            if scripted:
                move = scripted.pop(0)
                if isinstance(move, Exception):
                    raise move
                if isinstance(move, str):
                    return reply(move)  # plain text instead of the tool
                return reply(calls=[('submit_turn', move)])
            head = re.search(r'「(.)」で始まる語', next(
                row['content'] for row in reversed(messages) if row['role'] == 'user' and '【手番' in row['content']))
            return reply(calls=[('submit_turn', {'word': self.word(head.group(1) if head else '')})])
        if '手番がすべて終わりました' in last or 'finish_work' in names:
            return reply(calls=[('finish_work', {'summary': 'しりとりが終わりました。'})])
        raise AssertionError(f'unexpected request: {names}')


def turns_plan(**extra):
    return {'shape': 'turns', 'reason': '10回＝10周と解釈',
            'turns': {'participants': 5, 'rounds': 10, 'rule': 'shiritori', 'topic': 'しりとり', **extra}}


async def run_game(tmp_path, client, **extra):
    engine, work = configured(tmp_path, client)
    engine.settings.value['limits']['max_workers'] = 5
    run, pm = await start(engine, task=TASK, max_workers=5, **extra)
    for _ in range(600):
        await asyncio.sleep(.01)
        if run['status'] in {'done', 'waiting'} and not any(a.task and not a.task.done() for a in engine.agents.values()):
            break
    return engine, work, run, pm


# --- the acceptance scenario -----------------------------------------------------

@pytest.mark.plan
@pytest.mark.asyncio
async def test_five_participants_play_ten_rounds_and_the_file_matches_the_record(tmp_path):
    client = GameClient(turns_plan(save_as='shiritori.xlsx'))
    engine, work, run, pm = await run_game(tmp_path, client)
    try:
        game = run['_turns']
        assert run['status'] == 'done' and pm.status == 'done', (run['status'], pm.last_error)
        assert game.finished and len(game.accepted()) == 50 and not game.rejected
        players = [engine.agents[row['agent_id']] for row in game.participants]
        assert [player.name for player in players] == [f'参加者{n}' for n in range(1, 6)]
        assert all(player.turns == 10 and player.status == 'done' for player in players)
        # (a) one word per participant per turn, in the declared order
        assert [row['name'] for row in game.history] == [f'参加者{n % 5 + 1}' for n in range(50)]
        # (b) every link, ending and repeat was checked by the application
        readings = [row['reading'] for row in game.history]
        assert all(tail_kana(a) == b[0] for a, b in zip(readings, readings[1:]))
        assert len(set(readings)) == 50 and not any(tail_kana(word) == 'ん' for word in readings)
        # (c) the saved file is the application's record
        import openpyxl
        sheet = openpyxl.load_workbook(work / 'shiritori.xlsx')['手番の履歴']
        rows = list(sheet.iter_rows(values_only=True))
        assert rows[0] == ('手番', '周', '参加者', '語', 'よみ', '判定', '補足')
        assert [(row[0], row[2], row[3]) for row in rows[1:]] == [(row['turn'], row['name'], row['word']) for row in game.history]
        assert pm.output_receipts[-1]['tool'] == 'export_turn_history'
        # the PM used one plan call and one report; every participant call offered only submit_turn
        pm_calls = [names for agent, names in client.calls if agent == pm.id]
        assert len(pm_calls) == 2 and 'spawn_worker' not in pm_calls[0] and pm_calls[1] >= {'finish_work', 'export_turn_history'}
        assert all(names == {'submit_turn'} for agent, names in client.calls if agent != pm.id)
        assert run['model_calls'] == 52
        assert '【アプリの記録】' in pm.results[-1]['text'] and '受理 50 手' in pm.results[-1]['text']
        # participants never see the whole request
        assert all(TASK not in client.systems[player.id] for player in players)
        assert run['turn_work']['done'] == 50 and run['turn_work']['status'] == 'complete'
        assert run['auto_collaborations'] == 0, 'turns do not spend the collaboration budget'
    finally:
        await engine.close()


# --- the referee -----------------------------------------------------------------

@pytest.mark.plan
@pytest.mark.asyncio
async def test_invalid_moves_are_sent_back_and_three_in_a_row_become_a_pass(tmp_path):
    moves = {
        1: [{'word': 'りんご'}],
        2: [{'word': 'ごはん'}, {'word': 'らっぱ'}, {'word': 'りす'}],     # ん ending, wrong head twice -> pass
        3: [{'word': '胡麻'}, {'word': 'ごま めだか'}, {'word': 'ゴリラ'}],  # kanji, two words, then katakana accepted
        4: ['らっぱ'],                                                       # plain text is checked the same way
        5: ['次はパンダにします！', {'word': 'パイナップル'}],               # prose is refused, then the tool
    }
    client = GameClient({'shape': 'turns', 'reason': '', 'turns': {'participants': 5, 'rounds': 1, 'rule': 'shiritori'}}, moves=moves)
    engine, work, run, pm = await run_game(tmp_path, client)
    try:
        game = run['_turns']
        assert [(row['name'], row['status'], row['reading']) for row in game.history] == [
            ('参加者1', 'ok', 'りんご'), ('参加者2', 'pass', ''), ('参加者3', 'ok', 'ごりら'),
            ('参加者4', 'ok', 'らっぱ'), ('参加者5', 'ok', 'ぱいなっぷる')]
        assert [row['code'] for row in game.rejected] == ['n_ending', 'chain', 'chain', 'characters', 'characters', 'characters']
        assert game.history[2]['word'] == 'ゴリラ', 'the written form is kept; the reading is used for the chain'
        assert run['status'] == 'done'
        kinds = [row['kind'] for row in engine.events if row['run_id'] == run['id']]
        assert kinds.count('turn') == 4 and kinds.count('turn_pass') == 1 and kinds.count('turn_rejected') == 5
    finally:
        await engine.close()


@pytest.mark.plan
@pytest.mark.asyncio
async def test_a_failing_participant_is_passed_and_the_game_still_finishes(tmp_path):
    moves = {2: [ProviderError('Provider returned HTTP 400; bad request', status=400)],
             7: [ProviderError('Provider returned HTTP 400; bad request', status=400)]}
    client = GameClient({'shape': 'turns', 'reason': '', 'turns': {'participants': 5, 'rounds': 2, 'rule': 'shiritori'}}, moves=moves)
    engine, work, run, pm = await run_game(tmp_path, client)
    try:
        game = run['_turns']
        assert game.finished and [row['status'] for row in game.history].count('pass') == 2
        assert len(game.accepted()) == 8 and run['status'] == 'done' and pm.status == 'done'
        assert engine.agents[game.participants[1]['agent_id']].status == 'stopped'
    finally:
        await engine.close()


# --- the plan gate -----------------------------------------------------------------

@pytest.mark.plan
@pytest.mark.asyncio
async def test_a_plan_is_required_before_other_tools(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task=TASK, max_workers=3)
        names = tool_names(engine._model_tools(run, pm))
        assert 'plan_work' in names and not names & {'spawn_worker', 'write_text', 'xlsx_write', 'finish_work', 'start_ordered_work'}
        assert 'Plan first' in engine._policy(run, pm)
        with pytest.raises(ValueError, match='plan_work'):
            await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'w', 'task': 'しりとりを全部やって', 'profile_id': 'local'})
        # asking for more participants than the cap is refused with the number, before anything is created
        with pytest.raises(ValueError, match='上限は3人'):
            await engine.execute_tool(run, pm, 'plan_work', turns_plan())
        assert len(run['agent_ids']) == 1 and pm.plan is None
        with pytest.raises(ValueError, match='2〜16人'):
            await engine.execute_tool(run, pm, 'plan_work', {'shape': 'turns', 'reason': '',
                'turns': {'participants': 1, 'rounds': 10, 'rule': 'shiritori'}})
        with pytest.raises(ValueError, match='shape="turns"'):
            await engine.execute_tool(run, pm, 'plan_work', {'shape': 'solo', 'reason': '自分で全部書く'})
        run['task'] = '資料を調べて表にまとめて'
        with pytest.raises(ValueError, match='1人だけ'):
            await engine.execute_tool(run, pm, 'plan_work', {'shape': 'parallel', 'reason': '', 'assignments': [
                {'key': 'a', 'role': 'r', 'goal': 'しりとりを最後までやる担当です', 'deliverable': 'd', 'acceptance': 'ok'}]})
        with pytest.raises(ValueError, match='元の依頼文と同じ'):
            await engine.execute_tool(run, pm, 'plan_work', {'shape': 'parallel', 'reason': '', 'assignments': [
                {'key': 'a', 'role': 'r', 'goal': run['task'], 'deliverable': 'd', 'acceptance': 'ok'},
                {'key': 'b', 'role': 'r', 'goal': '結果を表にまとめて確認する', 'deliverable': 'd', 'acceptance': 'ok'}]})
        accepted = await engine.execute_tool(run, pm, 'plan_work', {'shape': 'sequence', 'reason': '', 'assignments': [
            {'key': 'a', 'role': '調査', 'goal': '対象の資料を読んで要点を出す', 'deliverable': '要点', 'acceptance': '出典つき'},
            {'key': 'b', 'role': '整理', 'goal': '要点を表に整理して確認する', 'deliverable': '表', 'acceptance': '全件', 'depends_on': ['a']}]})
        assert accepted['ok'] and pm.plan['shape'] == 'sequence'
        spawn = next(tool for tool in engine._model_tools(run, pm) if tool['name'] == 'spawn_worker')
        assert not {'participant_key', 'initial_wait'} & set(spawn['parameters']['properties']), 'no clash with depends_on'
        assert 'start_ordered_work' not in tool_names(engine._model_tools(run, pm))
        first = await engine.execute_tool(run, pm, 'spawn_worker', {'role': '調査', 'task': '資料を読む', 'profile_id': 'local'})
        second = await engine.execute_tool(run, pm, 'spawn_worker', {
            'role': '整理', 'task': '表にする', 'profile_id': 'local', 'depends_on': [first['agent_id']]})
        assert second['ok']
        assert pm.public()['plan']['shape'] == 'sequence'
    finally:
        await engine.close()


@pytest.mark.plan
@pytest.mark.asyncio
async def test_solo_plan_unlocks_the_pm_own_tools_only(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=2)
        await engine.execute_tool(run, pm, 'plan_work', {'shape': 'solo', 'reason': '1回で済む'})
        names = tool_names(engine._model_tools(run, pm))
        assert {'write_text', 'finish_work'} <= names and not names & {'plan_work', 'spawn_worker', 'wait_for_workers'}
        with pytest.raises(ValueError, match='solo'):
            await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'w', 'task': 't', 'profile_id': 'local'})
        again = await engine.execute_tool(run, pm, 'plan_work', {'shape': 'solo', 'reason': '変更なし'})
        assert again['ok'], 'a plan may be replaced until workers exist'
    finally:
        await engine.close()


@pytest.mark.plan
@pytest.mark.asyncio
async def test_turns_pm_cannot_write_its_own_history_and_export_uses_the_record(tmp_path):
    client = GameClient({'shape': 'turns', 'reason': '', 'turns': {'participants': 2, 'rounds': 2, 'rule': 'shiritori', 'first_word': 'しりとり'}})
    engine, work, run, pm = await run_game(tmp_path, client)
    try:
        game = run['_turns']
        assert game.history[0]['reading'][0] == 'り', 'the first move continues the first word'
        with pytest.raises(ValueError, match='手番制の作業中'):
            await engine.execute_tool(run, pm, 'xlsx_write', {'path': str(work / 'mine.xlsx'), 'cells': [], 'expected_sha256': 'missing'})
        saved = await engine.execute_tool(run, pm, 'export_turn_history', {'filename': 'history.csv'})
        text = (work / 'history.csv').read_text(encoding='utf-8-sig')
        assert saved['ok'] and all(row['word'] in text for row in game.history) and 'しりとり' in text
        again = await engine.execute_tool(run, pm, 'export_turn_history', {'filename': 'history.csv'})
        assert again['path'].endswith('history-2.csv'), 'an existing file is never overwritten'
        outside = await engine.execute_tool(run, pm, 'export_turn_history', {'filename': '../x.xlsx'})
        assert outside['path'] == str(work / 'x.xlsx'), 'only the file name is used, inside the write folder'
        with pytest.raises(ValueError, match='ファイル名'):
            await engine.execute_tool(run, pm, 'export_turn_history', {'filename': 'history.exe'})
        assert 'ask_user' not in tool_names(engine._model_tools(run, pm)), 'no further human questions once turns run'
    finally:
        await engine.close()


# --- pure rules ----------------------------------------------------------------------

def test_shiritori_rules_for_long_marks_small_kana_and_katakana():
    assert to_reading(' 「カレー」 ') == 'かれー' and tail_kana('かれー') == 'れ'
    assert tail_kana('きしゃ') == 'や' and tail_kana('らっぱ') == 'ぱ'
    game = TurnGame(rule='shiritori', participants=[{'key': 'a', 'agent_id': '1', 'name': 'A'},
                                                    {'key': 'b', 'agent_id': '2', 'name': 'B'}], rounds=2)
    assert game.submit('1', 'カレー')['outcome'] == 'accepted'
    assert game.submit('1', 'れもん')['outcome'] == 'not_your_turn'
    assert game.submit('2', 'れもん')['code'] == 'n_ending'
    assert game.submit('2', 'れいぞうこ')['outcome'] == 'accepted'
    assert game.submit('1', 'こ')['code'] == 'length'
    assert game.submit('1', 'こま')['outcome'] == 'accepted'
    assert game.submit('2', 'まり')['outcome'] == 'accepted' and game.finished
    assert game.submit('1', 'りす')['outcome'] == 'finished'
    repeat = TurnGame(rule='shiritori', participants=[{'key': 'a', 'agent_id': '1', 'name': 'A'},
                                                      {'key': 'b', 'agent_id': '2', 'name': 'B'}], rounds=1)
    assert repeat.submit('1', 'ああ')['outcome'] == 'accepted'
    assert repeat.submit('2', 'アア')['code'] == 'duplicate', 'katakana and hiragana are the same word'


def test_a_whole_round_of_passes_ends_the_game_early():
    game = TurnGame(rule='free', participants=[{'key': 'a', 'agent_id': '1', 'name': 'A'},
                                               {'key': 'b', 'agent_id': '2', 'name': 'B'}], rounds=5, topic='t')
    assert game.submit('1', '意見です')['outcome'] == 'accepted'
    game.pass_current('x')
    game.pass_current('x')
    assert game.finished and game.ended_early and len(game.history) == 3
