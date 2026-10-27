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

from .config import Settings, ROOT, COPILOT_PROFILE_ID, SEARCH_KEY_UNSUPPORTED, preview_settings_import, text
from .engine import Engine, WorkBoardError
from .redaction import RedactionCapacityError, REDACTION_CAPACITY_MESSAGE
from .history import HistoryError, ArchivedReadOnly
from .securestore import CredentialStorageError, SavedCredentialIdentityChange
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


class InstanceChanged(ValueError):
    pass


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
            public = request.path in {'/', '/index.html', '/app.js', '/styles.css', '/agent-workbench.ico', '/api/bootstrap'}
            if not public and not hmac.compare_digest(request.cookies.get(self.cookie_name, '').encode(), self.session.encode()):
                raise web.HTTPUnauthorized(text='起動ショートカットから認証してください')
            if request.path.startswith('/api/') and request.path != '/api/bootstrap' and request.method not in {'GET', 'HEAD'}:
                expected = request.app[APP_KEY].instance_id
                if not hmac.compare_digest(request.headers.get('X-Workbench-Instance', '').encode(), expected.encode()):
                    raise InstanceChanged()
            response = await handler(request)
        except web.HTTPException as exc:
            response = web.json_response({'ok': False, 'error': exc.text}, status=exc.status)
        except InstanceChanged:
            response = web.json_response({'ok': False, 'code': 'instance_changed',
                'instance_id': request.app[APP_KEY].instance_id,
                'error': 'サーバーが再起動したか、起動識別子が不足しています。最新の設定・状態を読み込み、内容を確認してから操作してください。'}, status=409)
        except RedactionCapacityError:
            response = web.json_response({'ok': False, 'error': REDACTION_CAPACITY_MESSAGE,
                                          'code': 'redaction_capacity'}, status=409)
        except SavedCredentialIdentityChange as exc:
            response = web.json_response({'ok': False, 'code': exc.code, 'error': str(exc),
                'affected_ids': exc.affected_ids}, status=409)
        except CredentialStorageError as exc:
            response = web.json_response({'ok': False, 'code': exc.code, 'error': str(exc)}, status=409)
        except (HistoryError, ArchivedReadOnly) as exc:
            response = web.json_response({'ok': False, 'code': exc.code, 'error': str(exc)}, status=409)
        except WorkBoardError as exc:
            response = web.json_response({'ok': False, 'code': exc.code, 'error': str(exc)}, status=409)
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
        response = web.json_response({'ok': True, 'instance_id': request.app[APP_KEY].instance_id})
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
        engine.schedule_copilot_sync()
        try:
            yield
        finally:
            try:
                await engine.close()
            finally:
                settings.secrets.clear()
    app.cleanup_ctx.append(clean)

    async def static(request):
        name = request.match_info.get('name', 'index.html')
        if name not in {'index.html', 'app.js', 'styles.css', 'agent-workbench.ico'}:
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
            engine.save_settings(value.get('config'))
            engine.schedule_copilot_sync()
        return web.json_response(engine.public_config())

    async def config_export(request):
        return web.json_response(settings.export())

    async def config_import_preview(request):
        try:
            value = await body(request)
        except (ValueError, TypeError):
            return web.json_response({'ok': False, 'error': '設定ファイルの JSON object が必要です。'}, status=400)
        revision = value.get('config_revision')
        if type(revision) is not int or revision != settings.revision:
            return web.json_response({'ok': False, 'code': 'settings_changed',
                'error': '保存済み設定を読み直してから設定ファイルを読み込んでください。'}, status=409)
        if engine.active():
            raise web.HTTPConflict(text='設定の読み込みは実行中のチームを停止してから行ってください')
        # Ownership is checked after body receipt. No await or mutation occurs
        # between that check and returning the validated, unsaved draft.
        try:
            if set(value) != {'config_revision', 'backup'}:
                raise ValueError('Unexpected import fields')
            draft, warnings = preview_settings_import(value['backup'])
        except (ValueError, KeyError, TypeError):
            # Do not echo untrusted file contents or remember imported secrets
            # in the redactor, even when validation rejects the backup.
            return web.json_response({'ok': False,
                'error': '設定ファイルの形式・バージョン・値を確認してください。秘密情報を含む設定は読み込めません。'}, status=400)
        return web.json_response({'config': draft, 'config_revision': settings.revision, 'warnings': warnings})

    def recovery_required():
        return web.json_response({'ok': False, 'code': 'settings_recovery_required',
            'error': '保存済み設定のパスを確認し、現在のPCに合わせて保存してから再実行してください。'}, status=409)

    async def copilot_status(request):
        return web.json_response(engine.copilot_status())

    async def copilot_start(request):
        value = await body(request)
        revision = value.get('config_revision')
        if type(revision) is not int or revision != settings.revision:
            return web.json_response({'ok': False, 'code': 'settings_changed',
                'error': '保存済み設定を読み直してから再接続してください。'}, status=409)
        if engine.active():
            raise web.HTTPConflict(text='再接続は実行中のチームを停止してから行ってください')
        if settings.restore_warnings:
            return recovery_required()
        engine.credentials.check_bindings(settings.value['providers'])
        engine.credentials.require_usable()
        if settings.value['copilot_agent']['enabled'] is not True:
            return web.json_response({'ok': False, 'code': 'copilot_agent_disabled',
                'error': 'Copilot agent モードを有効にして保存してください。'}, status=409)
        status = engine.copilot_status()
        # A repeated click must not cancel and restart an in-flight launch.
        # Ownership checks and scheduling are synchronous, as for config saves.
        if status.get('ready') is not True and status.get('state') not in {'pending', 'starting'}:
            engine.schedule_copilot_sync(force=True)
        return web.json_response(engine.public_config())

    async def secret(request):
        value = await body(request)
        revision = value.get('config_revision')
        if type(revision) is not int or revision != settings.revision:
            return web.json_response({'ok': False, 'code': 'settings_changed',
                'error': '保存済み設定が変わったか、設定の確認情報がありません。保存済み設定を読み直してからキーを入力してください。'}, status=409)
        ident = value.get('id')
        key = text(value.get('key'), 'key', 4096)
        if not isinstance(ident, str) or (ident not in {p['id'] for p in settings.value['providers']} | {'search'}
                and not (not key and engine.credentials.contains(ident))):
            raise ValueError('未知のプロファイル ID です')
        storage = value.get('storage', 'session')
        if any(ord(c) < 32 or ord(c) == 127 for c in key):
            raise ValueError('API キーに制御文字は使用できません')
        if key and ident == 'search':
            raise ValueError(SEARCH_KEY_UNSUPPORTED)
        # No await between saved-target validation and the atomic mutation.
        # Clearing an old value also requires the same revision precondition.
        engine.set_secret(ident, key, storage)
        source = settings.secret_sources().get(ident, {'source': 'none', 'saved': False})
        return web.json_response({'ok': True, 'id': ident, 'config_revision': settings.revision,
                                  'configured': source['source'] != 'none', 'storage': storage, **source,
                                  'credential_storage': engine._redact_tree(engine.credentials.public())})

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

    async def work_board(request):
        run_id = request.match_info['id']
        if request.method == 'GET':
            if set(request.query) - {'after_seq', 'limit'} or any(len(request.query.getall(key)) != 1 for key in request.query):
                raise ValueError('掲示板の取得条件が不正です')
            values = {}
            for key, default in (('after_seq', '0'), ('limit', '20')):
                raw = request.query.get(key, default)
                if re.fullmatch(r'[0-9]{1,3}', raw) is None:
                    raise ValueError('掲示板の取得条件は整数で指定してください')
                values[key] = int(raw)
            return web.json_response(engine.read_work_board(run_id, **values))
        value = await body(request)
        if set(value) - {'body', 'reply_to', 'client_post_id'} or not {'body', 'client_post_id'} <= set(value):
            raise ValueError('掲示板の投稿形式が不正です。投稿者の指定はできません')
        # Actual human session, current run and idempotency are checked after
        # receipt; no await separates the validation/commit from this response.
        return web.json_response(engine.post_work_board(run_id, value['body'],
            reply_to=value.get('reply_to'), client_post_id=value['client_post_id']))

    async def provider_test(request):
        engine.credentials.check_bindings(settings.value['providers'])
        engine.credentials.require_usable()
        value = await body(request)
        if settings.restore_warnings:
            return recovery_required()
        profile = next((p for p in engine.public_config()['effective_providers']
                        if p['id'] == value.get('provider_id')), None)
        if profile is None:
            raise ValueError('未知のプロファイルです')
        if settings.value['copilot_agent']['enabled'] and profile['id'] == COPILOT_PROFILE_ID:
            status = engine.copilot_status()
            if status.get('ready') is not True:
                return web.json_response({'ok': False, 'code': 'copilot_bridge_unavailable',
                    'error': status.get('message') or 'Copilot bridge の準備ができていません。'}, status=409)
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
    app.router.add_get('/api/config/export', config_export)
    app.router.add_post('/api/config/import-preview', config_import_preview)
    app.router.add_get('/api/copilot-agent-status', copilot_status)
    app.router.add_post('/api/copilot-agent-start', copilot_start)
    app.router.add_post('/api/secrets', secret)
    app.router.add_get('/api/state', state)
    app.router.add_post('/api/runs', start)
    app.router.add_post('/api/run-preflight', preflight)
    app.router.add_post('/api/runs/{id}/stop', stop)
    app.router.add_post('/api/agents/{id}/message', message)
    app.router.add_get('/api/runs/{id}/work-board', work_board)
    app.router.add_post('/api/runs/{id}/work-board', work_board)
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
