"""Looking at the screen (desktop, first stage): view only, chosen per piece of work, approved per look.

- off unless ticked at the start of that work; every look waits for the human, also where no other approval is asked;
- the picture goes to the model beside the tool result, and is never part of the conversation, the log or the history;
- a model connection that cannot take a picture is told so, and the work goes on without it.
"""
import asyncio
import base64
import json
import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import screen
from workbench.context import request_size
from workbench.engine import AdmissionError, Engine, SCREEN_REFUSED_NOTE, SCREEN_VIEW_LIMIT
from workbench.providers import (PICTURE_TEXT, ProviderError, _anthropic_messages, _local_messages, _openai_messages,
                                 _request_payload)
from test_engine import ScriptClient, configured, reply, settled, start


def decoded(png):
    """(width, height, rows of RGB bytes) of a PNG as this application writes it."""
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    at, chunks = 8, {}
    while at < len(png):
        size, kind = struct.unpack('>I', png[at:at + 4])[0], png[at + 4:at + 8]
        data = png[at + 8:at + 8 + size]
        assert struct.unpack('>I', png[at + 8 + size:at + 12 + size])[0] == zlib.crc32(kind + data) & 0xffffffff
        chunks[kind] = data
        at += 12 + size
    width, height, depth, colour = struct.unpack('>IIBB', chunks[b'IHDR'][:10])
    assert (depth, colour) == (8, 2) and b'IEND' in chunks
    raw = zlib.decompress(chunks[b'IDAT'])
    stride = width * 3 + 1
    assert len(raw) == stride * height and all(raw[row * stride] == 0 for row in range(height))
    return width, height, [raw[row * stride + 1:(row + 1) * stride] for row in range(height)]


def test_the_picture_is_a_png_of_the_pixels_it_was_given():
    # Two rows of three pixels, as Windows gives them: blue, green, red, unused.
    bgra = bytes([255, 0, 0, 0,  0, 255, 0, 0,  0, 0, 255, 0,
                  10, 20, 30, 0,  40, 50, 60, 0,  70, 80, 90, 0])
    width, height, rows = decoded(screen.png_from_bgra(bgra, 3, 2))
    assert (width, height) == (3, 2)
    assert rows[0] == bytes([0, 0, 255,  0, 255, 0,  255, 0, 0])      # blue, green, red: each in RGB order
    assert rows[1] == bytes([30, 20, 10,  60, 50, 40,  90, 80, 70])
    with pytest.raises(screen.ScreenError):
        screen.png_from_bgra(bgra, 3, 3)                              # not the size it claims
    # The picture keeps the screen's shape; only a large screen is made smaller.
    assert screen.scaled(1280, 720) == (1280, 720)
    assert screen.scaled(3840, 2160) == (1568, 882) and screen.scaled(1080, 1920) == (882, 1568)


@pytest.mark.skipif(os.name == 'nt', reason='elsewhere than Windows there is no screen to picture')
def test_elsewhere_than_windows_the_screen_cannot_be_pictured():
    assert screen.available() is False
    with pytest.raises(screen.ScreenError, match='Windows only'):
        screen.capture()


@pytest.mark.skipif(os.name != 'nt', reason='the screen is pictured through Windows')
def test_on_windows_the_primary_screen_is_pictured():
    shot = screen.capture()
    width, height, rows = decoded(shot['png'])
    assert (width, height) == (shot['width'], shot['height']) == screen.scaled(shot['screen_width'], shot['screen_height'])
    assert max(width, height) <= screen.MAX_EDGE and len(rows) == height


PICTURE = {'media_type': 'image/png', 'data': base64.b64encode(b'not really a picture').decode('ascii')}
TALK = [{'role': 'user', 'content': 'Look at the screen.'},
        {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c0', 'name': 'screen_view', 'arguments': {}},
                                                           {'id': 'c1', 'name': 'list_team', 'arguments': {}}]},
        {'role': 'tool', 'tool_call_id': 'c0', 'name': 'screen_view', 'content': '{"ok": true}'},
        {'role': 'tool', 'tool_call_id': 'c1', 'name': 'list_team', 'content': '{"agents": []}'}]


def test_each_kind_of_model_connection_is_given_the_picture_beside_the_result():
    images = {'c0': PICTURE}
    # Anthropic: inside the tool result itself.
    blocks = _anthropic_messages(TALK, images)[-1]['content']
    assert blocks[0] == {'type': 'tool_result', 'tool_use_id': 'c0', 'content': [
        {'type': 'text', 'text': '{"ok": true}'},
        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': PICTURE['data']}}]}
    assert blocks[1] == {'type': 'tool_result', 'tool_use_id': 'c1', 'content': '{"agents": []}'}
    # OpenAI: a result is text, so the picture follows the whole batch of results as one user item.
    items = _openai_messages(TALK, images)
    assert [item.get('type') for item in items[-3:-1]] == ['function_call_output', 'function_call_output']
    assert items[-1] == {'role': 'user', 'content': [{'type': 'input_text', 'text': PICTURE_TEXT},
                                                     {'type': 'input_image', 'image_url': 'data:image/png;base64,' + PICTURE['data']}]}
    # A local server: the same, in the chat format.
    chat = _local_messages(TALK, 'system text', images)
    assert [row['role'] for row in chat] == ['system', 'user', 'assistant', 'tool', 'tool', 'user']
    assert chat[-1]['content'] == [{'type': 'text', 'text': PICTURE_TEXT},
                                   {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + PICTURE['data']}}]
    # A later message comes after the picture, not between the results and it.
    later = [*TALK, {'role': 'user', 'content': 'And now?'}]
    assert [row['role'] for row in _local_messages(later, '', images)][-3:] == ['tool', 'user', 'user']
    assert _openai_messages(later, images)[-1] == {'role': 'user', 'content': 'And now?'}
    # A server that numbers its calls anew in every turn: the picture belongs to the latest result with that id.
    again = [*TALK, {'role': 'user', 'content': 'Once more.'},
             {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c0', 'name': 'screen_view', 'arguments': {}}]},
             {'role': 'tool', 'tool_call_id': 'c0', 'name': 'screen_view', 'content': '{"ok": true}'}]
    for text in (json.dumps(_anthropic_messages(again, images)), json.dumps(_openai_messages(again, images)),
                 json.dumps(_local_messages(again, '', images))):
        assert text.count(PICTURE['data']) == 1 and text.rindex(PICTURE['data']) > text.index('Once more.')
    # Without a picture every format is what it was.
    for build in (_anthropic_messages, _openai_messages):
        assert build(TALK) == build(TALK, {}) == build(TALK, {'other': PICTURE})
    assert _local_messages(TALK, '') == _local_messages(TALK, '', None)
    with pytest.raises(ProviderError, match='Invalid picture'):
        _anthropic_messages(TALK, {'c0': {'media_type': 'text/html', 'data': 'x'}})


def test_the_picture_travels_with_one_request_and_is_not_counted_as_conversation():
    for kind in ('anthropic', 'openai', 'local'):
        profile = {'id': 'p', 'kind': kind, 'model': 'm', '_images': {'c0': PICTURE}, '_live_note': 'NOTE'}
        payload = json.dumps(_request_payload(kind, 'm', profile, TALK, [], 'system text', 1000))
        assert payload.count(PICTURE['data']) == 1 and 'NOTE' in payload
        plain = json.dumps(_request_payload(kind, 'm', {**profile, '_images': None}, TALK, [], 'system text', 1000))
        assert PICTURE['data'] not in plain
        # The size of the context is that of the text: the picture is not part of the conversation.
        assert request_size(profile, TALK, [], 'system text') == request_size({**profile, '_images': None}, TALK, [], 'system text')
    # A local server's chat template takes one user turn after the results: the note joins the picture's message.
    local = _request_payload('local', 'm', {'id': 'p', 'kind': 'local', '_images': {'c0': PICTURE}, '_live_note': 'NOTE'},
                             TALK, [], '', 1000)['messages']
    assert [row['role'] for row in local][-2:] == ['tool', 'user'] and local[-1]['content'][-1] == {'type': 'text', 'text': 'NOTE'}


def shots(monkeypatch, *, available=True):
    """The screen, replaced: every look is counted and gives a small picture."""
    taken = []

    def capture():
        taken.append(len(taken) + 1)
        return {'png': b'PNG%d' % len(taken), 'width': 1568, 'height': 882, 'screen_width': 1920, 'screen_height': 1080}
    monkeypatch.setattr(Engine, 'screen_capture', staticmethod(capture))
    monkeypatch.setattr(Engine, 'screen_available', staticmethod(lambda: available))
    return taken


async def answered(engine, agent, call, decision):
    for _ in range(300):
        await asyncio.sleep(.005)
        if agent.approval:
            break
    asked = dict(agent.approval)
    engine.resolve_approval(agent.id, {'approval_id': asked['id'], 'decision': decision})
    return asked, call


async def test_the_screen_is_looked_at_only_where_the_human_ticked_it_and_approved_the_look(tmp_path, monkeypatch):
    taken = shots(monkeypatch)
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        # Not ticked (the default): the tool is not offered, and a call is refused before the human is asked.
        run, pm = await start(engine, max_workers=0)
        assert run['screen_view'] is False and 'screen_view' not in {tool['name'] for tool in engine._model_tools(run, pm)}
        with pytest.raises(ValueError, match='この作業では許可されていない'):
            await engine.execute_tool(run, pm, 'screen_view', {})
        assert pm.approval is None and taken == []
        with pytest.raises(AdmissionError, match='真偽値'):
            await start(engine, max_workers=0, screen_view=1)

        # Ticked, in a piece of work that asks for no other approval: every look still waits for the human.
        run, pm = await start(engine, max_workers=0, screen_view=True, approval_mode='always_allow')
        assert run['screen_view'] is True and run['approval_mode'] == 'always_allow'
        assert 'screen_view' in {tool['name'] for tool in engine._model_tools(run, pm)}
        asked, call = await answered(engine, pm, asyncio.create_task(engine.execute_tool(run, pm, 'screen_view', {})), 'approve')
        assert asked['tool'] == 'screen_view' and asked['expires_at'] > 0
        assert '画面に映っているものは、すべて送られます' in asked['summary'] and 'アプリは画面を操作しません' in asked['summary']
        result = await call
        assert taken == [1] and result['ok'] is True and (result['width'], result['height']) == (1568, 882)
        # The picture is beside the conversation: the result is text, and so are the event and the saved history.
        data = base64.b64encode(b'PNG1').decode('ascii')
        assert pm._screen == {'call_id': None, 'media_type': 'image/png', 'data': data} and data not in json.dumps(result)
        events = [row['text'] for row in engine.events if row['kind'] == 'screen']
        assert events == [f'{pm.name}: 画面を 1 枚撮影し、モデルに渡しました（1568×882、この作業で 1 回目）']
        assert data not in json.dumps(engine.history.load(run['id']) if hasattr(engine.history, 'load') else {}, default=str)

        # Said no: nothing is pictured, and the model is told.
        asked, call = await answered(engine, pm, asyncio.create_task(engine.execute_tool(run, pm, 'screen_view', {})), 'reject')
        with pytest.raises(ValueError, match='人がこの操作を承認しませんでした'):
            await call
        assert taken == [1]
        # Arguments are not taken, a read-only agent has no such tool, and one piece of work has a limit of looks.
        with pytest.raises(ValueError, match='no arguments'):
            await engine.execute_tool(run, pm, 'screen_view', {'window': 'x'})
        pm.read_only = True
        assert 'screen_view' not in {tool['name'] for tool in engine._model_tools(run, pm)}
        with pytest.raises(ValueError, match='読み取り専用'):
            await engine.execute_tool(run, pm, 'screen_view', {})
        pm.read_only = False
        run['_screen_views'] = SCREEN_VIEW_LIMIT
        with pytest.raises(ValueError, match=f'{SCREEN_VIEW_LIMIT} 回まで'):
            await engine.execute_tool(run, pm, 'screen_view', {})
        assert pm.approval is None and taken == [1]
    finally:
        await asyncio.wait_for(engine.close(), 20)


async def test_where_the_screen_cannot_be_pictured_the_choice_is_refused_at_the_start(tmp_path, monkeypatch):
    shots(monkeypatch, available=False)
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        with pytest.raises(AdmissionError, match='Windows だけ'):
            await start(engine, max_workers=0, screen_view=True)
        run, pm = await start(engine, max_workers=0)
        assert run['screen_view'] is False
    finally:
        await asyncio.wait_for(engine.close(), 20)


async def approving(engine):
    """The human at the screen: approves every look that is asked for."""
    while True:
        await asyncio.sleep(.005)
        for agent in list(engine.agents.values()):
            if agent.approval and agent.approval['tool'] == 'screen_view':
                engine.resolve_approval(agent.id, {'approval_id': agent.approval['id'], 'decision': 'approve'})


async def test_the_model_sees_the_latest_picture_with_its_next_requests(tmp_path, monkeypatch):
    taken, seen = shots(monkeypatch), []

    def step(answer):
        async def respond(profile, messages):
            seen.append((dict(profile.get('_images') or {}), json.dumps(messages, default=str)))
            return answer
        return respond
    client = ScriptClient([step(reply(calls=[('screen_view', {})])), step(reply(text='A spreadsheet is open.')),
                           step(reply(calls=[('screen_view', {})])), step(reply(calls=[('finish_work', {'summary': '画面を確認しました。'})]))])
    engine, _ = configured(tmp_path, client)
    human = asyncio.create_task(approving(engine))
    try:
        run, pm = await asyncio.wait_for(start(engine, max_workers=0, screen_view=True, task='画面を見て、開いているものを教えて'), 20)
        await asyncio.wait_for(settled(engine), 20)
        engine.enqueue(pm, 'もう一度見てください')
        await asyncio.wait_for(settled(engine), 20)
        assert taken == [1, 2] and len(seen) == 4
        first, second = (base64.b64encode(b'PNG%d' % n).decode('ascii') for n in (1, 2))
        # Before the look there is no picture; after it, the picture goes with each request that holds its result.
        assert seen[0][0] == {}
        assert list(seen[1][0].values()) == [{'media_type': 'image/png', 'data': first}]
        assert list(seen[2][0].values()) == [{'media_type': 'image/png', 'data': first}]
        # After the second look only that one is sent: the earlier picture is gone.
        assert list(seen[3][0].values()) == [{'media_type': 'image/png', 'data': second}]
        # The conversation itself holds text only.
        assert all(first not in text and second not in text for _, text in seen)
        assert first not in json.dumps(pm.conversation, default=str) and second not in json.dumps(pm.logs, default=str)
    finally:
        human.cancel()
        await asyncio.wait_for(engine.close(), 20)


async def test_a_model_connection_that_cannot_take_a_picture_is_told_and_the_work_goes_on(tmp_path, monkeypatch):
    taken, seen = shots(monkeypatch), []

    async def looks(profile, messages):
        return reply(calls=[('screen_view', {})])

    async def answers(profile, messages):
        seen.append((bool(profile.get('_images')), profile.get('_live_note') or ''))
        if profile.get('_images'):
            raise ProviderError('Provider returned HTTP 400; response body withheld', status=400)
        return reply(calls=[('finish_work', {'summary': '画面は見られませんでした。'})])
    client = ScriptClient([looks, answers, answers])
    engine, _ = configured(tmp_path, client)
    human = asyncio.create_task(approving(engine))
    try:
        run, pm = await asyncio.wait_for(start(engine, max_workers=0, screen_view=True, task='画面を見て'), 20)
        await asyncio.wait_for(settled(engine), 20)
        # The request with the picture was turned away; the same request went again without it, with a note
        # that the screen was not seen.
        assert taken == [1] and [with_picture for with_picture, _ in seen] == [True, False]
        assert SCREEN_REFUSED_NOTE not in seen[0][1] and SCREEN_REFUSED_NOTE in seen[1][1]
        assert pm._screen is None and pm._screen_refused == 'HTTP 400' and pm.status == 'done'
        assert any('画面の画像を受け取れませんでした（HTTP 400）' in row['text'] for row in engine.events if row['kind'] == 'screen')
        # This agent is not given another look, and the human is not asked for one.
        with pytest.raises(ValueError, match='画像を受け取れませんでした'):
            await engine.execute_tool(run, pm, 'screen_view', {})
        assert pm.approval is None and taken == [1]
    finally:
        human.cancel()
        await asyncio.wait_for(engine.close(), 20)
