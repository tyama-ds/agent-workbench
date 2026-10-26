"""Selenium settings remain an explicit permission with a separate boundary."""
from test_frontend import APP, run_javascript
from test_settings_save_frontend import check
from test_task_guidance import Elements
from workbench.config import DEFAULT


def test_selenium_fields_match_config_and_have_bounded_controls():
    prefix = APP[:APP.index('const $ =')]
    result = run_javascript(prefix + 'console.log(JSON.stringify({fields:FIELD_GROUPS.selenium,bounds:NUMBER_BOUNDS.selenium}));')
    assert {field[0] for field in result['fields']} == set(DEFAULT['selenium'])
    assert result['fields'][0] == ['enabled', 'Selenium のブラウザー操作を許可', 'checkbox']
    assert result['bounds'] == {'timeout_seconds': [10, 300], 'max_memory_mb': [256, 8192], 'max_output_chars': [1000, 100000]}


def test_selenium_defaults_off_and_does_not_inherit_search_proxy_or_enable_python():
    check(r'''
await setup();const group=$('seleniumFields'),field=key=>group.querySelector(`[data-key="${key}"]`);
assert.equal(group.querySelectorAll('[data-key]').length,9);
assert.equal(field('enabled').checked,false);assert.equal(field('browser').value,'edge');
assert.deepEqual(field('browser').children.map(option=>option.value),['edge','chrome']);
assert.equal(field('enabled').getAttribute('aria-describedby'),'seleniumRuntimeHelp seleniumBoundaryHelp');
assert.equal(field('timeout_seconds').min,'10');assert.equal(field('timeout_seconds').max,'300');
assert.equal(field('max_memory_mb').min,'256');assert.equal(field('max_memory_mb').max,'8192');
assert.equal(field('max_output_chars').min,'1000');assert.equal(field('max_output_chars').max,'100000');
const pythonBefore=structuredClone(ui.config.python);
$('searchFields').querySelector('[data-key="proxy_url"]').value='http://search-proxy.example:8080';
field('enabled').checked=true;$('settingsForm').listeners.change({target:field('enabled')});
assert(ui.settingsDirty);assert.equal(requests.length,0);assert.equal(ui.config.selenium.enabled,false);
const draft=collectConfig();assert.equal(draft.selenium.enabled,true);assert.equal(draft.selenium.proxy_url,'');
assert.equal(draft.search.proxy_url,'http://search-proxy.example:8080');assert.deepEqual(draft.python,pythonBefore);
clearTimeout(ui.preflightTimer);
''')


def test_selenium_config_saves_and_renders_paths_proxy_and_browser_without_enabling_general_python():
    check(r'''
await setup();const before=structuredClone(ui.config),field=key=>$('seleniumFields').querySelector(`[data-key="${key}"]`);
$('pythonFields').querySelector('[data-key="executable"]').value='C:\\Approved Python\\python.exe';
$('pythonFields').querySelector('[data-key="network_enabled"]').checked=true;
field('enabled').checked=true;field('browser').value='chrome';
field('browser_executable').value='C:\\Approved Browser\\chrome.exe';
field('driver_executable').value='C:\\Approved Driver\\chromedriver.exe';
field('library_paths').value='C:\\Approved Library One\nC:\\Approved Library Two';
field('proxy_url').value='http://selenium-proxy.example:3128';
field('timeout_seconds').value='90';field('max_memory_mb').value='2048';field('max_output_chars').value='50000';
$('settingsForm').listeners.change({target:field('enabled')});const pending=submit();
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config');
const submitted=requests[0].options.body.config;
assert.deepEqual(submitted.selenium,{enabled:true,browser:'chrome',browser_executable:'C:\\Approved Browser\\chrome.exe',
 driver_executable:'C:\\Approved Driver\\chromedriver.exe',library_paths:['C:\\Approved Library One','C:\\Approved Library Two'],
 proxy_url:'http://selenium-proxy.example:3128',timeout_seconds:90,max_memory_mb:2048,max_output_chars:50000});
assert.equal(submitted.python.enabled,false);assert.equal(submitted.python.network_enabled,true);
assert.equal(submitted.python.executable,'C:\\Approved Python\\python.exe');
assert.deepEqual(submitted.search,before.search);assert.deepEqual(submitted.paths,before.paths);
assert($('seleniumFields').querySelectorAll('[data-key]').every(node=>node.disabled));
accept();await pending;assert.deepEqual(ui.config.selenium,submitted.selenium);renderSettings();
assert(field('enabled').checked);assert.equal(field('browser').value,'chrome');
assert.equal(field('library_paths').value,'C:\\Approved Library One\nC:\\Approved Library Two');
assert.equal(field('proxy_url').value,'http://selenium-proxy.example:3128');
assert($('seleniumFields').querySelectorAll('[data-key]').every(node=>!node.disabled));
ui.state.runs=[{id:'active',status:'running'}];setSettingsLock();
assert($('seleniumFields').querySelectorAll('[data-key]').every(node=>node.disabled));
ui.state.runs=[];setSettingsLock();assert($('seleniumFields').querySelectorAll('[data-key]').every(node=>!node.disabled));
clearTimeout(ui.preflightTimer);
''')


def test_selenium_rejected_save_keeps_draft_and_does_not_turn_on_network_or_retry():
    check(r'''
await setup();const field=key=>$('seleniumFields').querySelector(`[data-key="${key}"]`);
field('enabled').checked=true;$('settingsForm').listeners.change({target:field('enabled')});
const pending=submit();requests[0].reject(new Error('Python network permission is required.'));await pending;
assert.equal(requests.length,1);assert(ui.settingsDirty);assert(field('enabled').checked);
assert.equal(ui.config.selenium.enabled,false);assert.equal(ui.config.python.network_enabled,false);
assert.equal($('pythonFields').querySelector('[data-key="network_enabled"]').checked,false);
assert($('settingsStatus').textContent.includes('Python network permission is required.'));
clearTimeout(ui.preflightTimer);
''')


def test_selenium_help_describes_runtime_permissions_and_transfer_limits():
    tree = Elements()
    panel = tree.ids['seleniumFields']['ancestors'][-1]['text']
    for term in ('既存の Edge / Chrome', 'WebDriver', 'Selenium ライブラリ', '既定は無効', 'ダウンロード・インストールは行いません',
                 'Python 設定の python.exe', '「Python スクリプト実行を有効にする」は不要', '「Python のネットワーク接続を許可」は必要',
                 '設定を保存した後に開始する新しい作業', '通常の Windows ユーザー権限', '専用の新しい headless ブラウザー',
                 'LPAC によるフォルダー隔離は適用されません', 'スクリーンショット保存などツールによる転送だけ',
                 '普段のブラウザープロファイルは使いません', '企業 SSO などの完全な隔離は保証できません',
                 'URL の表示・クリック・フォーム入力・テキスト取得・PNG 保存', '任意の JavaScript 実行',
                 'アップロード・ダウンロードはできません', 'シェル・子プロセスを起動することは引き続きできません',
                 'Selenium 専用プロキシは空欄なら直接接続', 'Web 検索のプロキシ設定は引き継ぎません'):
        assert term in panel
    for identifier in ('seleniumRuntimeHelp', 'seleniumBoundaryHelp', 'seleniumProxyHelp'):
        help_text = tree.ids[identifier]
        assert not any(node['tag'] == 'details' or 'hidden' in node['attrs'] for node in (*help_text['ancestors'], help_text))
