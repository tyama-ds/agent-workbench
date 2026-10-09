"""Static first-task guidance agrees with the actual, unchanged tool boundary."""
from html.parser import HTMLParser
from pathlib import Path

from workbench.config import Settings
from workbench.engine import Engine
from workbench.harness import ToolExecutor


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'static/index.html').read_text(encoding='utf-8')
APP = (ROOT / 'static/app.js').read_text(encoding='utf-8')


class Elements(HTMLParser):
    """Small source tree; native visibility/keyboard/layout are checked in Edge."""
    def __init__(self):
        super().__init__()
        self.root = {'tag': 'root', 'attrs': {}, 'children': [], 'text': ''}
        self.stack = [self.root]
        self.ids = {}
        self.feed(HTML)

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs), 'children': [], 'text': ''}
        self.stack[-1]['children'].append(node)
        node['ancestors'] = tuple(self.stack)
        if 'id' in node['attrs']:
            self.ids[node['attrs']['id']] = node
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        assert self.stack[-1]['tag'] == tag
        self.stack.pop()

    def handle_data(self, text):
        for node in self.stack:
            node['text'] += text


def descendants(node):
    for child in node['children']:
        yield child
        yield from descendants(child)


def test_essential_limit_is_persistent_and_describes_the_task_input():
    tree = Elements()
    task, help_text = tree.ids['taskInput'], tree.ids['taskHelp']
    assert task['attrs']['aria-describedby'].split() == ['taskHelp']
    assert 'コマンド・ビルド・テストは実行できません' in help_text['text']
    assert '許可したファイル' in help_text['text']
    assert all(node['tag'] != 'details' and 'hidden' not in node['attrs'] for node in (*help_text['ancestors'], help_text))
    assert help_text['ancestors'][-1] is task['ancestors'][-1]
    assert task['text'] == ''  # No example becomes a pre-filled or submitted task.
    assert '次のメモ' in task['attrs']['placeholder']
    assert 'テスト結果' not in task['attrs']['placeholder']


def test_examples_are_native_optional_static_help_without_actions():
    tree = Elements()
    examples = tree.ids['taskExamples']
    assert examples['tag'] == 'details' and 'open' not in examples['attrs']
    assert examples['children'][0]['tag'] == 'summary'
    assert examples['children'][0]['text'] == '依頼例と必要な設定'
    sections = [node for node in descendants(examples) if node['tag'] == 'section']
    assert len(sections) == 3
    assert not any(node['tag'] in {'a', 'input', 'button', 'select', 'textarea', 'form', 'script'} for node in descendants(examples))
    assert all(not any(attr.startswith('on') for attr in node['attrs']) for node in descendants(examples))
    assert 'taskExamples' not in APP and 'taskHelp' not in APP  # No new mutation/network handler.
    assert 'モデルの設定が必要' in sections[0]['text']
    assert 'ファイルの許可や Web の設定は不要' in sections[0]['text']
    assert '上限を 0' in sections[0]['text']
    assert all(text in sections[1]['text'] for text in ('既存フォルダーの絶対パス', '読み取り', '書き込み', 'フォルダー作成・ファイル削除はできません'))
    assert all(text in sections[2]['text'] for text in ('Web を有効', '検索サービスの接続先と必要なキー', '検索とページ取得の利用状態', '公開 HTTP(S) テキスト', 'ログインや JavaScript の実行はできません'))


def test_text_only_example_is_admissible_without_files_web_or_tool_execution(tmp_path):
    settings = Settings(tmp_path / 'state')
    settings.value['providers'][0]['model'] = 'synthetic-first-task'
    engine = Engine(settings)
    request = {'task': '次のメモを、決定事項・担当・期限に整理し、不明点を列挙してください。\nメモ: 次回の日付は未定。',
               'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0}
    result = engine.preflight(request)
    assert result['can_start']
    assert result['scope']['read_roots'] == result['scope']['write_roots'] == []
    assert not result['web']['enabled']
    assert not result['inference_tested'] and not result['tools_tested']
    assert not engine.runs and not engine.agents and not engine.events
    capabilities = settings.public()['capabilities']
    assert capabilities['shell'] is False
    assert set(capabilities['office']) == {'docx', 'xlsx', 'pptx'}
    tool_names = {tool['name'] for tool in ToolExecutor(None).schemas()}
    assert {'read_text', 'write_text', 'docx_write', 'xlsx_write', 'pptx_write'} <= tool_names
    assert not tool_names & {'shell', 'exec', 'run_command', 'mkdir', 'delete_file'}


def test_initial_readme_uses_actual_control_labels_and_keeps_model_test_limits():
    text = (ROOT / 'README.md').read_text(encoding='utf-8').split('## 最初の設定', 1)[1].split('## チームの使い方', 1)[0]
    assert 'モデルのプロファイル' in text and '＋ 新しい作業' in text
    assert '「モデル一覧を確認」' in text and '「接続を確認」' not in text
    assert '推論・ツール動作は未確認' in text and '有料リクエストの成功を保証するチェックではありません' in text
    assert '文章だけの作業には手順3のフォルダー登録や Web の設定は不要' in text
    assert 'コマンド・ビルド・テストは実行できません' in text
