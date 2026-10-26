"""Local admission preview. No network, inference, writes, or capability guesses."""
from .providers import _endpoint
from .config import ORCHESTRATION_DEFAULTS


def summarize(prepared, *, orchestration=None):
    _, config, pms, workers, _, harness, web = prepared
    selected = dict.fromkeys([*pms, *workers])
    destinations = []
    for profile in config['providers']:
        if profile['id'] not in selected:
            continue
        protocol = {'local': '/chat/completions', 'openai': '/responses', 'anthropic': '/messages'}[profile['kind']]
        destinations.append({'profile_id': profile['id'], 'label': profile['label'], 'model': profile['model'],
            'role': 'PM' if profile['id'] in pms else 'worker', 'kind': profile['kind'],
            'pm_count': pms.count(profile['id']), 'worker_available': profile['id'] in workers,
            'endpoint': _endpoint(profile['base_url'], protocol, allow_local_network=profile['kind'] == 'local'),
            'protocol': protocol, 'proxy': profile['proxy_url'] if profile['kind'] != 'local' else ''})
    warnings = []
    if config['copilot_agent']['enabled'] and 'copilot-agent' in selected:
        warnings.append({'code': 'copilot_bridge_destination', 'message':
            'Copilot Agent はローカル bridge を経由して、ログイン中の Microsoft 365 Copilot に依頼とツール結果を送信します。'
            '接続確認はモデル回答・ツール動作の成功を保証しません。'})
    if config['selenium']['enabled']:
        warnings.append({'code': 'selenium_normal_user', 'message':
            'Selenium は通常の Windows ユーザー権限で新規ブラウザーを起動します。'
            'Python の LPAC フォルダー隔離は適用されません。ファイル許可はツール経由のスクリーンショット保存に適用されます。'
            'ページ操作は外部サイトを変更する場合があります。'})
    for kind, roots in (('read', harness.read_roots), ('write', harness.write_roots)):
        if not roots:
            action = ('入力フォルダーを「読み取りを許可する場所」に登録してください。' if kind == 'read' else
                      'ファイルやフォルダーを作成・保存するには、既存の出力フォルダーを「書き込みを許可する場所」に登録してください。')
            warnings.append({'code': kind + '_scope_empty', 'message': 'ファイルの' + ('読み取り' if kind == 'read' else '書き込み') +
                'は許可されていません。設定 → ファイルへのアクセスで、' + action +
                '設定を保存してから新しい作業を開始します。依頼文にパスを書くことだけでは許可されません。文章だけの作業は開始できます。'})
        for root in roots:
            if any(root.is_relative_to(denied) for denied in harness.deny_roots):
                warnings.append({'code': kind + '_scope_denied', 'message': f'{root}: 拒否範囲に含まれるため使用できません。'})
    return {'ok': True, 'can_start': True, 'blockers': [], 'warnings': warnings,
        'orchestration': orchestration or {**ORCHESTRATION_DEFAULTS, **config.get('orchestration', {})},
        'inference_tested': False, 'tools_tested': False, 'destinations': destinations,
        'scope': {'read_roots': [str(p) for p in harness.read_roots],
                  'write_roots': [str(p) for p in harness.write_roots],
                  'deny_roots': [str(p) for p in harness.deny_roots]},
        'web': {'enabled': web.enabled, 'search_configured': bool(web.enabled), 'fetch_enabled': web.enabled,
                'search_endpoint': web.endpoint if web.enabled else '', 'proxy': web.proxy if web.enabled else None}}
