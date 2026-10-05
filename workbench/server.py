"""Loopback-only application server; secrets and live transcripts stay local."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

from .config import Settings, ROOT, text
from .engine import Engine
from .redaction import RedactionCapacityError, REDACTION_CAPACITY_MESSAGE
from .runtime_paths import FROZEN

APP_KEY = web.AppKey('engine', Engine)
STATIC = ROOT / 'static'


def private_directory(path):
    path = Path(path).absolute()
    for item in [path, *path.parents]:
        if item.exists() and (item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('状態フォルダーに symlink / junction は使用できません')
    path.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt' and FROZEN:
        from .windows_runtime import harden_directory
        harden_directory(path)
    elif os.name == 'nt':
        system = Path(os.environ['SystemRoot']) / 'System32'
        result = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'], capture_output=True,
                                text=True, timeout=10, creationflags=0x08000000, check=True)
        match = re.search(r'S-1-5-[0-9-]+', result.stdout)
        if not match:
            raise RuntimeError('Windows user SID を取得できません')
        subprocess.run([str(system / 'icacls.exe'), str(path), '/inheritance:r', '/grant:r',
                        f'*{match[0]}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], check=True,
                       capture_output=True, timeout=10, creationflags=0x08000000)
    else:
        path.chmod(0o700)
    return path


class BrowserAuth:
    def __init__(self, port):
        self.origin = f'http://127.0.0.1:{port}'
        self.host = f'127.0.0.1:{port}'
        self.cookie_name = f'workbench_{port}'
        self.session = secrets.token_urlsafe(32)
        self.launch_token = secrets.token_urlsafe(32)
        self.expires = time.monotonic() + 180
        self.bootstrap_used = False

    @property
    def launch_url(self):
        return self.origin + '/#token=' + self.launch_token

    @web.middleware
    async def middleware(self, request, handler):
        try:
            if request.remote not in {'127.0.0.1', '::1'} or request.headers.get('Host') != self.host:
                raise web.HTTPForbidden(text='Invalid host')
            if request.headers.get('Origin') not in {None, self.origin} or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise web.HTTPForbidden(text='Invalid origin')
            if request.method not in {'GET', 'HEAD'}:
                if request.headers.get('Origin') != self.origin:
                    raise web.HTTPForbidden(text='Same-origin request required')
                if request.content_type != 'application/json':
                    raise web.HTTPUnsupportedMediaType(text='JSON required')
            public = request.path in {'/', '/index.html', '/app.js', '/styles.css', '/api/bootstrap'}
            if not public and not hmac.compare_digest(request.cookies.get(self.cookie_name, '').encode(), self.session.encode()):
                raise web.HTTPUnauthorized(text='起動ショートカットから認証してください')
            response = await handler(request)
        except web.HTTPException as exc:
            response = web.json_response({'ok': False, 'error': exc.text}, status=exc.status)
        except RedactionCapacityError:
            response = web.json_response({'ok': False, 'error': REDACTION_CAPACITY_MESSAGE,
                                          'code': 'redaction_capacity'}, status=409)
        except (ValueError, KeyError, TypeError) as exc:
            try:
                message = request.app[APP_KEY].redact(str(exc))[:1000]
                response = web.json_response({'ok': False, 'error': message}, status=400)
            except RedactionCapacityError:
                response = web.json_response({'ok': False, 'error': REDACTION_CAPACITY_MESSAGE,
                                              'code': 'redaction_capacity'}, status=409)
        except OSError:
            response = web.json_response({'ok': False, 'error': 'ファイルまたはネットワーク操作に失敗しました'}, status=503)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'",
            'Cross-Origin-Resource-Policy': 'same-origin'})
        return response

    async def bootstrap(self, request):
        token = request.headers.get('X-Workbench-Bootstrap', '')
        if self.bootstrap_used or time.monotonic() >= self.expires or not hmac.compare_digest(token.encode(), self.launch_token.encode()):
            raise web.HTTPUnauthorized(text='起動リンクが無効または期限切れです')
        self.bootstrap_used = True
        response = web.json_response({'ok': True})
        response.set_cookie(self.cookie_name, self.session, httponly=True, samesite='Strict', path='/')
        return response


async def body(request):
    value = await request.json()
    if not isinstance(value, dict):
        raise ValueError('JSON object が必要です')
    return value


def create_app(directory: Path, auth: BrowserAuth, *, client=None):
    settings = Settings(private_directory(directory))
    engine = Engine(settings, client)
    app = web.Application(middlewares=[auth.middleware], client_max_size=1024 * 1024)
    app[APP_KEY] = engine

    async def clean(_app):
        yield
        await engine.close()
        settings.secrets.clear()
    app.cleanup_ctx.append(clean)

    async def static(request):
        name = request.match_info.get('name', 'index.html')
        if name not in {'index.html', 'app.js', 'styles.css'}:
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC / name)

    async def config(request):
        if request.method == 'PUT':
            value = await body(request)
            revision = value.get('config_revision')
            if type(revision) is not int or revision != settings.revision:
                return web.json_response({'ok': False, 'code': 'settings_changed',
                    'error': '保存済み設定が変わったか、設定の確認情報がありません。保存済み設定を読み直してから編集してください。'}, status=409)
            if engine.active():
                raise web.HTTPConflict(text='設定変更は実行中のチームを停止してから行ってください')
            # Recheck ownership after the body arrives; do not await between
            # this revision/active-run check and the atomic settings transition.
            return web.json_response(engine.save_settings(value.get('config')))
        return web.json_response(settings.public())

    async def secret(request):
        value = await body(request)
        revision = value.get('config_revision')
        if type(revision) is not int or revision != settings.revision:
            return web.json_response({'ok': False, 'code': 'settings_changed',
                'error': '保存済み設定が変わったか、設定の確認情報がありません。保存済み設定を読み直してからキーを入力してください。'}, status=409)
        ident = value.get('id')
        if not isinstance(ident, str) or ident not in {p['id'] for p in settings.value['providers']} | {'search'}:
            raise ValueError('未知のプロファイル ID です')
        key = text(value.get('key'), 'key', 4096)
        if any(ord(c) < 32 or ord(c) == 127 for c in key):
            raise ValueError('API キーに制御文字は使用できません')
        if key and ident == 'search' and (settings.value['search']['provider'] != 'brave' or not settings.value['search']['endpoint']):
            raise ValueError('検索キーは保存済みの接続先を持つ Brave Search だけで使用できます。SearXNG とページ取得では使用しません。')
        # No await between saved-target validation and the atomic mutation.
        # Clearing an old value also requires the same revision precondition.
        engine.set_secret(ident, key)
        return web.json_response({'ok': True, 'id': ident, 'config_revision': settings.revision,
                                  'configured': settings.public()['secret_status'][ident]})

    async def state(request):
        view = request.query.get('view')
        if view is None:
            return web.json_response(engine.snapshot())
        if view != 'selected' or any(len(request.query.getall(key, [])) > 1
                                     for key in ('view', 'run_id', 'agent_id')):
            raise ValueError('状態表示の選択が不正です')
        return web.json_response(engine.selected_snapshot(run_id=request.query.get('run_id'),
                                                          agent_id=request.query.get('agent_id')))

    async def start(request):
        return web.json_response(await engine.start_run(await body(request)))

    async def stop(request):
        await body(request)
        return web.json_response(await engine.stop_run(request.match_info['id']))

    async def message(request):
        value = await body(request)
        return web.json_response(await engine.human_message(request.match_info['id'], value.get('text')))

    async def provider_test(request):
        value = await body(request)
        profile = next((p for p in settings.value['providers'] if p['id'] == value.get('provider_id')), None)
        if profile is None:
            raise ValueError('未知のプロファイルです')
        from .diagnostics import diagnose_provider
        key = settings.key(profile)
        engine._redaction.remember([*engine._secret_values(), key])
        return web.json_response(engine._redact_tree(await diagnose_provider(profile, key)))

    async def preflight(request):
        return web.json_response(engine.preflight(await body(request)))

    app.router.add_get('/', static)
    app.router.add_post('/api/bootstrap', auth.bootstrap)
    app.router.add_get('/api/config', config)
    app.router.add_put('/api/config', config)
    app.router.add_post('/api/secrets', secret)
    app.router.add_get('/api/state', state)
    app.router.add_post('/api/runs', start)
    app.router.add_post('/api/run-preflight', preflight)
    app.router.add_post('/api/runs/{id}/stop', stop)
    app.router.add_post('/api/agents/{id}/message', message)
    app.router.add_post('/api/provider-test', provider_test)
    app.router.add_get('/{name}', static)
    return app


async def serve(args):
    directory = Path(args.state_dir) if args.state_dir else Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'AgentWorkbench'
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind(('127.0.0.1', args.port))
    except OSError:
        listener.close()
        raise RuntimeError(f'ポート {args.port} は使用中です。既存の Agent Workbench を利用するか --port で別の番号を指定してください') from None
    listener.listen()
    listener.setblocking(False)
    auth = BrowserAuth(listener.getsockname()[1])
    app = create_app(directory, auth)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        await web.SockSite(runner, listener).start()
        print('Agent Workbench started. Ctrl+C to stop.', flush=True)
        if args.no_browser:
            print(auth.launch_url, flush=True)
        else:
            if FROZEN and os.name == "nt":
                from .windows_runtime import capture_helper
                await capture_helper("browser", auth.launch_url, timeout=15)
            else:
                await asyncio.to_thread(webbrowser.open, auth.launch_url)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        listener.close()


def main():
    parser = argparse.ArgumentParser(description='Local-first multi-provider agent workbench')
    parser.add_argument('--port', type=int, default=8818)
    parser.add_argument('--state-dir')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('port must be between 0 and 65535')
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
