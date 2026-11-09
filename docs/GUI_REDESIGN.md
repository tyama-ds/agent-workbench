# Agent Workbench — cockpit GUI

## 変更内容

- 画面を「左: エージェント / 中央: 作業ログと入力欄 / 右: 親子関係とメール」の3列に再構成しました。
- 黒に近い背景、暖色の文字、控えめなアンバーの選択表示、細い罫線、コンパクトな見出しを採用しました。
- 新しい作業と設定はダイアログで開きます。閉じるボタン、Escape、外側クリックで閉じられます。入力中の値は閉じても保持します。
- エージェント検索、回答待ちの絞り込み、中央のエージェント切り替えタブを追加しました。下書きは以前と同じくエージェント別に保持します。
- チーム図は API の `parent_id` から構築します。図の担当者を押すと、その人のログへ切り替わります。
- 定期更新によるキーボードフォーカスの消失を抑えています。新規作業/設定保存の二重送信も抑止します。
- 既存のモデル/API設定、実行上限、ファイル権限、検索設定、キーの一時保存、Windowsセットアップは維持しています。

中央は既存 API の作業ログです。CLI端末、tmux、契約プランの残量、独立した任意エージェントの起動など、未実装の機能を示す操作はありません。

## 担当の状態表示の再設計 (2026-11-09)

コックピットの担当の状態表示（左の CREW と中央の担当ネットワーク）を、ORRERY の設計の考え方（暗い計器盤と担当者の組み合わせ、ほぼ単色の配色、限定したアンバー、丸い肖像と状態リング）に合わせて作り直しました。コードと色の値は今回新しく書いたもので、ORRERY から転載したものはありません。

- 配色: 青緑と紺の配色をやめ、黒に近いスレート、羊皮紙色の文字、アンバー1色（選択・注意）に統一しました。状態を示す色は状態表示だけに使います。
- 状態の示し方: 状態ごとに色・記号・文字を組み合わせます。色だけで区別はしません（▶ 作業中、⏎ 回答待ち、⋯ 順番待ち、Ⅱ 待機、✓ 完了、! エラー、■ 停止・中断、◇ 保存履歴）。作業中はリングが回り、回答待ちはリングが明滅します。「動きを減らす」設定の端末では動きを止め、記号と文字だけで状態が分かります。表示する状態名は従来の `stateLabel()` の文言のままです。
- CREW のカード: 丸いアバターの周りに状態リングを付け、右下に状態の記号を重ねました。名前、状態、役割（PM / LEAD・WORKER と深さ / REVIEWER）、開始時のモデル、担当内容、回答待ちの質問やエラー（強調表示）、CTX の推定トークン数とターン数を、この順に並べます。担当は親子の順に並べ、子の担当は字下げして親とつなぐ線を引きます。階層の説明は、選択中のカードでだけ表示します（ほかのカードでも読み上げとツールチップで確認できます）。
- 状態の内訳: CREW の見出しの下に、状態ごとの人数（記号・文字・人数）と割合を示す帯、「完了 n / 全体」を追加しました。
- 担当ネットワーク: 丸いノードに状態リングと記号のバッジを付けました。PM は二重の縁取りで区別します。選択中の担当は、外側の細い静止リングで示します。縮小表示（66%未満）では、役割と状態の文字を隠して略称・名前・記号を大きく表示します。役割と状態の詳細は、ノードに重ねるかフォーカスすると開く概要で確認できます。凡例に状態の記号を追加しました。
- 1280px 幅でも3列のまま表示できるよう、列の幅を調整しました。キーボード操作、DOM の id・`data-agent-id`・`data-focus-key`、ネットワークの座標計算は変更していません。

検証: `pytest -k frontend` 834 passed、`tests/test_frontend.py` と `tests/test_cockpit_frontend.py` 52 passed。合成データ（推論なし）で実際の Chromium に表示した変更前後の画面（1440×900・1280×800）は PR に添付しています（このリポジトリの証跡はテキストのみのため画像は含めません）。`tools/browser_smoke.cjs` は質問一覧の読み位置の確認（`424 !== 423`）で失敗します。変更前の static ファイルでも同じ箇所で失敗するため、今回の変更による失敗ではありません。

## デザインの参照元と独立実装

視覚的な参照元: [ORRERY](https://github.com/gyroid-eth/orrery)、[cockpit overview](https://github.com/gyroid-eth/orrery/blob/master/docs/images/cockpit_overview.png)、[design guide](https://github.com/gyroid-eth/orrery/blob/master/docs/DESIGN.md)。

ORRERY の配布物は [PolyForm Perimeter License 1.0.1](https://github.com/gyroid-eth/orrery/blob/master/LICENSE) の条件下にあります。本変更では、画面の構成や視覚的な原則を参考に、Agent Workbench 用の HTML/CSS/JavaScript を独自に記述しています。ORRERY のソース、スタイルシート、肖像画、ピクセルアート、フォントファイル、ブランドロゴは転載していません。丸いアバターは CSS と役割の文字で描画しています。外部 CDN への接続は追加していません。Agent Workbench の MIT ライセンスは変更していません。

## 検証 (2026-10-04)

- Python全テスト: **210 passed, 4 skipped**。スキップは Windows の junction、cmd.exe、PowerShell 5.1、mutex/console process group の4項目です。
- `node --check static/app.js`、`node --check tools/browser_smoke.cjs`、`node --check tools/dom_smoke.cjs`: 成功。
- DOM回帰テスト: 成功。空/実行中の表示切替、ダイアログの繰り返し開閉、17人の親子図、循環した入力データへの防御、検索/回答待ち、文字列エスケープ、下書き、更新時のフォーカス、設定ロック、停止状態を確認しました。
- DOMテストでは `jsdom` を使用し、ダイアログ API を代用しています。実ブラウザのフォーカストラップ、Escape、背景クリック、レイアウト、描画の実証にはなりません。
- `tools/browser_smoke.cjs` は新しい操作導線、1366×768、390×844、キー操作、検索/絞り込み、フォーカス保持に対応しました。**今回の環境では未完走です**。

### 実描画の未検証理由

クラウドブラウザからローカルサーバーへのアクセスは `net::ERR_BLOCKED_BY_CLIENT`。インストール済み Chromium の標準起動は `process_singleton_posix.cc: socket() failed: Operation not permitted` で終了しました。Playwright の同梱 headless shell は未インストールで、公式ダウンロードも不完全な ZIP 応答により失敗しました。

このため、本変更後の実ブラウザのスクリーンショットは作成できていません。CSS の静的な確認と DOM テストは、実描画の確認の代わりにはなりません。Windows上の表示/操作も今回未検証です。ユーザーのPCへの変更、リポジトリへの push は行っていません。

### 再検証

既存のテスト環境で:

```sh
python -m pytest -q -rs
node --check static/app.js
node tools/browser_smoke.cjs
```

Windows の browser smoke は既存の Edge を使用します。他の環境では Playwright の標準 Chromium を使用し、任意で `WORKBENCH_TEST_PYTHON` と `WORKBENCH_BROWSER_EXECUTABLE` を設定できます。`runtime/verification/` にスクリーンショットと検証結果を出力します。作業チームはテスト用の模擬 API データで、モデル推論や外部送信は行いません。

任意の DOM テストは別途 `jsdom` を開発用にインストールして `node tools/dom_smoke.cjs` で実行できます。実行時アプリに jsdom は必要ありません。
