"""How the human likes the screen to look is kept by the application, beside the settings."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workbench.preferences import DEFAULT, Preferences, checked
from workbench.server import APP_KEY
from test_cockpit_frontend import check
from test_config_server import bootstrap, serving
from test_frontend import APP


def test_the_choices_are_checked_and_kept_across_starts(tmp_path):
    kept = Preferences(tmp_path)
    assert kept.value == DEFAULT == {'face_style': 'auto', 'face_anime': False}       # anime is not in use until ticked
    assert kept.save({'face_style': 'real', 'face_anime': False}) == {'face_style': 'real', 'face_anime': False}
    assert Preferences(tmp_path).value == {'face_style': 'real', 'face_anime': False}
    assert kept.save({'face_style': 'anime', 'face_anime': True}) == {'face_style': 'anime', 'face_anime': True}
    # A choice of the anime pictures without the tick does not stand.
    assert checked({'face_style': 'anime', 'face_anime': False}) == {'face_style': 'auto', 'face_anime': False}
    for bad in ({}, {'face_style': 'real'}, {'face_style': 'photo', 'face_anime': False}, {'face_style': 'real', 'face_anime': 1},
                {'face_style': 'real', 'face_anime': False, 'more': 1}, [], 'real', None):
        with pytest.raises(ValueError):
            kept.save(bad)
    assert Preferences(tmp_path).value == {'face_style': 'anime', 'face_anime': True}   # a refused value changes nothing
    # A file that is not preferences is not trusted: the defaults.
    (tmp_path / 'ui-preferences.json').write_text('{"face_style": "anime", "face_anime": "yes"}', encoding='utf-8')
    assert Preferences(tmp_path).value == DEFAULT


async def test_the_page_reads_them_with_the_configuration_and_saves_them_at_any_time(tmp_path):
    async with serving(tmp_path / 'http') as (auth, app, client):
        url, headers = auth.origin + '/api/preferences', {'Origin': auth.origin}
        response = await client.put(url, json={'face_style': 'real', 'face_anime': False}, headers=headers)
        assert response.status == 401                                               # not signed in
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        config = await (await client.get(auth.origin + '/api/config')).json()
        assert config['preferences'] == {'face_style': 'auto', 'face_anime': False}
        instance = {**headers, 'X-Workbench-Instance': engine.instance_id}
        response = await client.put(url, json={'face_style': 'anime', 'face_anime': True}, headers=instance)
        assert response.status == 200 and await response.json() == {'ok': True, 'preferences': {'face_style': 'anime', 'face_anime': True}}
        assert (await (await client.get(auth.origin + '/api/config')).json())['preferences'] == {'face_style': 'anime', 'face_anime': True}
        assert json.loads((engine.settings.directory / 'ui-preferences.json').read_text(encoding='utf-8')) == {'face_style': 'anime', 'face_anime': True}
        # Refused: a value that is not preferences, and a request that does not come from this page.
        response = await client.put(url, json={'face_style': 'photo', 'face_anime': True}, headers=instance)
        assert response.status == 400 and engine.preferences.value == {'face_style': 'anime', 'face_anime': True}
        assert (await client.put(url, json={'face_style': 'flat', 'face_anime': False},
                                 headers={**headers, 'X-Workbench-Instance': 'another-start'})).status == 409
        assert (await client.put(url, json={'face_style': 'flat', 'face_anime': False},
                                 headers={**instance, 'Origin': 'https://attacker.invalid'})).status == 403
        # The settings themselves are untouched, and so is their revision.
        assert 'face_style' not in json.dumps(engine.settings.value)


def test_the_page_takes_over_what_was_saved_and_saves_a_change():
    check(r'''
// As saved: the real pictures, anime not in use.
applyFacePreferences({face_style:'real',face_anime:false});
assert.equal(ui.faceStyle,'real');assert.equal(ui.faceAnime,false);assert.equal($('faceStyleSelect').value,'real');assert.equal($('faceAnimeAllow').checked,false);
assert.equal(faceStyle('any-run'),'real');
// Anime ticked and chosen.
applyFacePreferences({face_style:'anime',face_anime:true});
assert.equal(ui.faceStyle,'anime');assert.equal(ui.faceAnime,true);assert.equal($('faceAnimeAllow').checked,true);assert.equal(faceStyle('any-run'),'anime');
// A saved choice of anime without the tick, or anything unknown, does not stand.
applyFacePreferences({face_style:'anime',face_anime:false});assert.equal(ui.faceStyle,'');assert.equal($('faceStyleSelect').value,'auto');
for(const value of [undefined,null,{},{face_style:'photo',face_anime:'yes'}]){applyFacePreferences(value);assert.equal(ui.faceStyle,'');assert.equal(ui.faceAnime,false);}
// A change is sent as it stands on the screen.
const sent=[];
api=async(path,options)=>{sent.push([path,options.method,options.body]);return {ok:true};};
ui.faceAnime=true;ui.faceStyle='real';await saveFacePreferences();
assert.deepEqual(sent,[['/api/preferences','PUT',{face_style:'real',face_anime:true}]]);assert.equal($('facePreferenceStatus').textContent,'');
// A save that fails is said, and the screen keeps what was chosen.
api=async()=>{throw new Error('offline');};await saveFacePreferences();
assert.match($('facePreferenceStatus').textContent,/保存できませんでした/);assert.equal(ui.faceStyle,'real');
''')
    assert APP.count('applyFacePreferences(response.preferences)') == 3
    assert "renderRun();void saveFacePreferences();" in APP
