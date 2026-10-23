"""Local admission preview. No network, inference, writes, or capability guesses."""
from .providers import _endpoint


def summarize(prepared):
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
    search_ready = web.enabled and not (web.provider == 'brave' and (not web.api_key or any(ord(c) < 32 for c in web.api_key)))
    if web.enabled and not search_ready:
        warnings.append({'code': 'search_key_missing', 'message': 'Brave 検索キーが未設定または無効です。検索は使えませんが、公開ページ取得とその他の作業は開始できます。'})
    return {'ok': True, 'can_start': True, 'blockers': [], 'warnings': warnings,
        'inference_tested': False, 'tools_tested': False, 'destinations': destinations,
        'scope': {'read_roots': [str(p) for p in harness.read_roots],
                  'write_roots': [str(p) for p in harness.write_roots],
                  'deny_roots': [str(p) for p in harness.deny_roots]},
        'web': {'enabled': web.enabled, 'search_configured': bool(search_ready), 'fetch_enabled': web.enabled,
                'search_endpoint': web.endpoint if web.enabled else '', 'proxy': web.proxy if web.enabled else None}}
