"""Agents speak in the manner of the character the screen shows them as.

- the server deals the same characters as the screen, so the manner matches the face the human sees;
- it is wording only, a choice per piece of work (on unless unticked), and left out where wording is fixed.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workbench import personas
from workbench.engine import AdmissionError, Engine
from test_cockpit_frontend import check
from test_engine import configured, start
from test_frontend import APP, HTML
from test_task_guidance import Elements

RUNS = ['run-a', 'run-b', 'r-3e21983ed0285f4d', 'r-96249bac2abddce2', 'r-0000000000000001', '日本語の作業', '']


def test_the_server_deals_the_same_characters_as_the_screen():
    expected = {run: personas.order(run) for run in RUNS}
    check('const expected=' + json.dumps(expected, ensure_ascii=False) + ',characters=' + json.dumps(
        [[ident, name] for ident, name, _ in personas.CHARACTERS], ensure_ascii=False) + r''';
assert.deepEqual(FACES.map(face=>[face.id,face.name]),characters);          // the same characters, in the same order
for(const [run,order] of Object.entries(expected))assert.deepEqual(faceOrder(run),order,run);   // and the same shuffle
''')
    assert len(personas.CHARACTERS) == 26 and len({row[0] for row in personas.CHARACTERS}) == 26
    for run in RUNS:
        assert sorted(personas.order(run)) == list(range(26))
        assert personas.character(run, 0) == personas.CHARACTERS[personas.order(run)[0]]
        assert personas.character(run, 26) == personas.character(run, 0)   # more agents than characters: the cast starts again
    assert all(manner.strip() and '口調' in manner for _, _, manner in personas.CHARACTERS)


def test_the_manner_is_wording_only_and_says_where_it_does_not_apply():
    text = personas.policy('run-a', 0)
    _, name, manner = personas.character('run-a', 0)
    assert f'"{name}"' in text and manner in text
    for phrase in ('This changes the wording only', 'Facts, numbers, names, quotations and page references stay exact',
                   'It does NOT apply to the contents of files', 'a line beginning "VERDICT:"', 'Do not mention the character'):
        assert phrase in text
    assert personas.policy('run-a', 1) != text and personas.policy('run-b', 0) != text


@pytest.mark.persona
async def test_agents_are_told_their_manner_unless_the_human_unticked_it(tmp_path):
    assert Engine.persona_default is True
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=2)
        worker = engine._new_agent(run, 'local', 'writer', pm.id, assignment='Write the report')
        assert run['persona'] is True
        for place, agent in enumerate((pm, worker)):
            text = engine._policy(run, agent)
            assert text.endswith(personas.policy(run['id'], place)) and personas.character(run['id'], place)[2] in text
        assert engine._policy(run, pm) != engine._policy(run, worker)
        # A reviewer's verdict is parsed: it keeps its plain wording.
        reviewer = engine._new_agent(run, 'local', 'reviewer', pm.id, assignment='Read the files')
        reviewer.read_only = reviewer._reviewer = True
        assert 'Manner of speaking' not in engine._policy(run, reviewer)
        # Unticked at the start: nobody in that piece of work is told a manner.
        plain, plain_pm = await start(engine, max_workers=0, persona=False)
        assert plain['persona'] is False and 'Manner of speaking' not in engine._policy(plain, plain_pm)
        with pytest.raises(AdmissionError, match='真偽値'):
            await start(engine, max_workers=0, persona='yes')
        # The choice is kept with the run.
        assert engine.snapshot()['runs'][0]['persona'] is True
    finally:
        await engine.close()


async def test_tests_and_scripted_fixtures_run_without_it(tmp_path):
    assert Engine.persona_default is False
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0)
        assert run['persona'] is False and 'Manner of speaking' not in engine._policy(run, pm)
        chosen, chosen_pm = await start(engine, max_workers=0, persona=True)
        assert chosen['persona'] is True and 'Manner of speaking' in engine._policy(chosen, chosen_pm)
    finally:
        await engine.close()
    for name in ('tools/browser_fixture.py', 'tools/adaptive_browser_fixture.py', 'tools/benchmark_state.py'):
        assert 'persona_default = False' in (Path(__file__).resolve().parents[1] / name).read_text(encoding='utf-8')


def test_the_start_screen_offers_the_choice_ticked():
    attrs = Elements().ids['personaAllow']['attrs']
    assert attrs.get('type') == 'checkbox' and 'checked' in attrs and attrs.get('aria-describedby') == 'personaAllowHelp'
    assert HTML.index('id="reviewAllow"') < HTML.index('id="personaAllow"') < HTML.index('id="adaptiveTeam"')
    assert "if($('personaAllow')&&$('personaAllow').checked!==true)payload.persona=false;" in APP
