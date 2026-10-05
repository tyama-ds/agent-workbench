import asyncio
import copy
import json
from contextlib import asynccontextmanager

import pytest
from aiohttp import ClientSession, CookieJar, web

from workbench.config import DEFAULT, Settings, validate_settings, url
from workbench.server import BrowserAuth, create_app, APP_KEY


def test_config_bounds_and_secret_free_persistence(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    settings.secrets['local'] = 'fixture-secret'
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-cloud-secret')
    settings.save(copy.deepcopy(DEFAULT))
    public = json.dumps(settings.public())
    assert 'fixture-secret' not in public and 'fixture-cloud-secret' not in public
    assert settings.public()['secret_status']['openai'] is True
    assert 'fixture-' not in settings.path.read_text(encoding='utf-8')
    with pytest.raises(ValueError):
        validate_settings({'limits': {'max_workers': 17}})
    with pytest.raises(ValueError):
        validate_settings({'limits': {'max_workers': True}})
    with pytest.raises(ValueError):
        validate_settings({'local': {'min_interval_seconds': float('nan')}})
    bad = copy.deepcopy(DEFAULT)
    bad['providers'][0]['api_key'] = 'must-not-save'
    with pytest.raises(ValueError):
        validate_settings(bad)
    bad = copy.deepcopy(DEFAULT)
    bad['providers'][0]['proxy_url'] = 'http://127.0.0.1:8080'
    with pytest.raises(ValueError):
        validate_settings(bad)
    with pytest.raises(ValueError):
        validate_settings({'search': {'timeout_seconds': 61}})


def test_old_settings_inherit_24_auto_collaborations_and_custom_value_persists(tmp_path):
    previous = copy.deepcopy(DEFAULT)
    del previous['limits']['max_auto_collaborations']
    (tmp_path / 'settings.json').write_text(json.dumps(previous), encoding='utf-8')
    settings = Settings(tmp_path)
    assert settings.value['limits']['max_auto_collaborations'] == 24
    settings.value['limits']['max_auto_collaborations'] = 7
    settings.save(settings.value)
    assert Settings(tmp_path).value['limits']['max_auto_collaborations'] == 7


@pytest.mark.parametrize('value', [-1, 1001, 2.5, True, '24', None])
def test_auto_collaboration_limit_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_settings({'limits': {'max_auto_collaborations': value}})


@pytest.mark.parametrize('value', [0, 24, 1000])
def test_auto_collaboration_limit_accepts_bounds(value):
    assert validate_settings({'limits': {'max_auto_collaborations': value}})['limits']['max_auto_collaborations'] == value


@pytest.mark.parametrize('host', ['192.168.1.5', '10.0.0.1', '172.16.1.2', '[fd00::1]', '127.0.0.1', 'localhost'])
def test_local_lan_hosts(host):
    assert url('http://' + host + ':8000/v1', local=True)


@pytest.mark.parametrize('host', ['169.254.169.254', 'example.com', '8.8.8.8', '[fe80::1]', '192.0.2.1'])
def test_local_remote_public_metadata_dns_rejected(host):
    with pytest.raises(ValueError):
        url('http://' + host + ':8000/v1', local=True)


def test_remote_gpu_guard_is_not_a_local_measurement():
    settings = copy.deepcopy(DEFAULT)
    settings['providers'][0]['base_url'] = 'http://192.168.1.5:8000/v1'
    settings['local']['gpu_guard_enabled'] = True
    with pytest.raises(ValueError, match='GPU'):
        validate_settings(settings)


@asynccontextmanager
async def serving(tmp_path):
    # Bind first, then give origin validation the actual port.
    import socket
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen()
    sock.setblocking(False)
    auth = BrowserAuth(sock.getsockname()[1])
    app = create_app(tmp_path / 'state', auth)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    try:
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
            yield auth, app, client
    finally:
        await runner.cleanup()
        sock.close()


async def bootstrap(auth, client):
    response = await client.post(auth.origin + '/api/bootstrap', json={}, headers={
        'Origin': auth.origin, 'X-Workbench-Bootstrap': auth.launch_token})
    assert response.status == 200
    assert 'HttpOnly' in response.headers['Set-Cookie'] and 'SameSite=Strict' in response.headers['Set-Cookie']


@pytest.mark.asyncio
async def test_http_auth_origin_host_one_use_bootstrap_and_csp(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        response = await client.get(auth.origin + '/api/state')
        assert response.status == 401
        assert "script-src 'self'" in response.headers['Content-Security-Policy']
        response = await client.get(auth.origin + '/', headers={'Host': 'attacker.invalid'})
        assert response.status == 403
        response = await client.post(auth.origin + '/api/bootstrap', json={}, headers={
            'Origin': 'https://evil.invalid', 'X-Workbench-Bootstrap': auth.launch_token})
        assert response.status == 403 and not auth.bootstrap_used
        await bootstrap(auth, client)
        response = await client.post(auth.origin + '/api/bootstrap', json={}, headers={
            'Origin': auth.origin, 'X-Workbench-Bootstrap': auth.launch_token})
        assert response.status == 401
        response = await client.get(auth.origin + '/api/state')
        assert response.status == 200
        response = await client.put(auth.origin + '/api/config', json={'config_revision': app[APP_KEY].settings.revision, 'config': DEFAULT})
        assert response.status == 403
        response = await client.get(auth.origin + '/workbench/config.py')
        assert response.status == 404
        response = await client.get(auth.origin + '/api/state', headers={'Origin': 'http://attacker.invalid'})
        assert response.status == 403


@pytest.mark.asyncio
async def test_key_not_persisted_invalid_key_and_active_config_lock(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        headers = {'Origin': auth.origin}
        response = await client.post(auth.origin + '/api/secrets', json={'config_revision': app[APP_KEY].settings.revision, 'id': 'local', 'key': 'fixture-memory-secret'}, headers=headers)
        assert response.status == 200
        response = await client.get(auth.origin + '/api/config')
        value = await response.text()
        assert 'fixture-memory-secret' not in value and json.loads(value)['secret_status']['local']
        response = await client.post(auth.origin + '/api/secrets', json={'config_revision': app[APP_KEY].settings.revision, 'id': 'local', 'key': 'bad\r\nheader'}, headers=headers)
        assert response.status == 400
        engine = app[APP_KEY]
        engine.runs['test'] = {'id': 'test', 'status': 'waiting', 'agent_ids': []}
        response = await client.put(auth.origin + '/api/config', json={'config_revision': app[APP_KEY].settings.revision, 'config': DEFAULT}, headers=headers)
        assert response.status == 409
        assert not (tmp_path / 'state' / 'settings.json').exists()


@pytest.mark.asyncio
async def test_model_list_waits_for_chunked_response_without_inference(tmp_path):
    paths = []
    async def models(request):
        paths.append(request.path)
        response = web.StreamResponse(headers={'Content-Type': 'application/json'})
        await response.prepare(request)
        await response.write(b'{"data":[')
        await asyncio.sleep(.03)
        await response.write(b'{"id":"fixture-qwen"}]}')
        await response.write_eof()
        return response
    model_app = web.Application()
    model_app.router.add_get('/v1/models', models)
    runner = web.AppRunner(model_app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    try:
        async with serving(tmp_path) as (auth, app, client):
            await bootstrap(auth, client)
            app[APP_KEY].settings.value['providers'][0]['base_url'] = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/v1'
            response = await client.post(auth.origin + '/api/provider-test', json={'provider_id': 'local'}, headers={'Origin': auth.origin})
            result = await response.json()
            assert result['ok'] and result['models'] == ['fixture-qwen']
            assert result['inference_tested'] is False and result['tools_tested'] is False
            assert result['code'] == 'models_listed' and result['checked_at']
            assert result['selected_model'] == 'unknown' and result['list_incomplete'] is False
            assert paths == ['/v1/models']
    finally:
        await runner.cleanup()


@pytest.mark.parametrize('host', ['192.168.1.5', '[fd00::1]', 'search.example.local'])
def test_searxng_lan_requires_https(host):
    with pytest.raises(ValueError, match='HTTPS'):
        validate_settings({'search': {'provider': 'searxng', 'endpoint': f'http://{host}/search'}})
    result = validate_settings({'search': {'provider': 'searxng', 'endpoint': f'https://{host}/search'}})
    assert result['search']['endpoint'] == f'https://{host}/search'


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '[::1]'])
def test_searxng_loopback_http_exception(host):
    result = validate_settings({'search': {'provider': 'searxng', 'endpoint': f'http://{host}:8888/search'}})
    assert result['search']['endpoint'] == f'http://{host}:8888/search'
