"""Local admission preview. No network, inference, writes, or capability guesses."""
from .providers import _endpoint


def summarize(prepared):
    _, config, pm, workers, _, harness, web = prepared
    selected = dict.fromkeys([pm, *workers])
    destinations = []
    for profile in config['providers']:
        if profile['id'] not in selected:
            continue
        protocol = {'local': '/chat/completions', 'openai': '/responses', 'anthropic': '/messages'}[profile['kind']]
        destinations.append({'profile_id': profile['id'], 'label': profile['label'], 'model': profile['model'],
            'role': 'PM' if profile['id'] == pm else 'worker', 'kind': profile['kind'],
            'endpoint': _endpoint(profile['base_url'], protocol, allow_local_network=profile['kind'] == 'local'),
            'protocol': protocol, 'proxy': profile['proxy_url'] if profile['kind'] != 'local' else ''})
    warnings = []
    for kind, roots in (('read', harness.read_roots), ('write', harness.write_roots)):
        if not roots:
            warnings.append({'code': kind + '_scope_empty', 'message': 'ファイルの' + ('読み取り' if kind == 'read' else '書き込み') + 'は許可されていません。文章だけの作業は開始できます。'})
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
