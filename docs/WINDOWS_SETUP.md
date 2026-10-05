# Windows 11・会社 PC へのセットアップ

## 最短の手順

1. 社内で許可された **64-bit の通常版 CPython 3.13** を用意します。3.11 / 3.12 も対応対象です。管理者権限はアプリのセットアップには不要です。Python の導入に社内申請が必要なら IT 担当へ依頼してください。
2. ソース ZIP を**すべて展開**し、自分が書き込めるローカルフォルダーに置きます。例: `%LOCALAPPDATA%\AgentWorkbenchApp`。ZIP の中から直接実行したり、Program Files、ネットワーク共有に置いたりしないでください。
3. `Setup.cmd` をダブルクリックします。`Setup complete` が出たら `Launch.cmd` をダブルクリックします。

Git、WSL、Docker、Node.js、Office、管理者 PowerShell は不要です。セットアップはプロジェクト内の `.venv` に依存ライブラリーを入れます。Python 本体を勝手にダウンロードしたり、Windows の PATH、実行ポリシー、証明書ストア、プロキシ設定を変更したりしません。通常の利用に PowerShell は使いません。

起動中のコンソールを閉じるか Ctrl+C で停止します。フォルダーは移動しないでください。移動する場合は新しい場所にソースを展開し、再セットアップします（`.venv` のコピーは不可）。アプリの設定は `%LOCALAPPDATA%\AgentWorkbench` に残ります。

**社内ポリシーで Python / CMD / ローカルサーバーの起動が禁止されている場合は IT 担当に確認してください。** SmartScreen、AppLocker、WDAC、ウイルス対策や証明書の警告を回避する手順はありません。配布元と内容を確認し、会社の承認を得て使ってください。

## Python が見つからないとき

セットアップは Python Launcher で 3.13 → 3.12 → 3.11 を探し、なければ PATH の `python` を確認します。32-bit、PyPy、free-threaded 版、未検証の 3.14 以降は利用対象外です。Python 3.13 の通常版 x64 を推奨します。ARM64 Windows は未検証であり、依存 wheel の対応を別途確認する必要があります。

承認済み Python が別の場所にある場合は、コマンドプロンプトで指定できます。

```bat
set "WORKBENCH_PYTHON=C:\Approved Python\python.exe"
Setup.cmd
```

この指定はそのコマンドプロンプトだけに適用されます。Microsoft Store のエイリアスだけが存在する場合は、実際の Python を IT 担当に用意してもらってください。

## インストール前の確認

展開先でコマンドプロンプトを開きます。

```bat
Setup.cmd --check
```

Python の対応範囲、必要ファイル、フォルダーの書き込み可否、wheel フォルダー指定を確認します。パッケージをインストールせず、ネットワークにも接続しません。書き込み確認用の一時ファイルは直ちに削除します。既存 `.venv` の健全性、ネットワーク疎通、会社のアプリ実行許可までは保証しません。

この診断はプロキシの認証情報・URL・環境変数の値を出しません。ただし実際のインストールでは pip が独自のエラーを表示するため、出力を共有する前にパスワード、トークン、社内アドレス、ユーザー名を確認して伏せてください。

## プロキシ・証明書

会社の指定値を使います。アプリ内の API プロキシ設定とインストール時の設定は別です。

```bat
Setup.cmd --proxy "http://proxy.example.local:8080" --certificate "C:\Certificates\company-ca.pem"
```

証明書指定が不要なら `--certificate` は省略します。プロキシは HTTP(S) のホスト・ポート指定に対応し、PAC URL や認証情報入り URL は拒否します。通常モードでは既存 pip 設定・`PIP_PROXY` / `HTTP_PROXY` / `HTTPS_PROXY` を引き継ぎます。認証方法、社内パッケージミラー、PEM CA バンドルについては IT 担当へ確認してください。Windows に CA が登録済みでも、同梱 pip のバージョンによっては明示した CA バンドルが必要です。pip を未固定で自動更新しません。

- `ConnectTimeout` / `ProxyError`: プロキシのホスト・ポート、接続許可を確認
- `407`: プロキシ認証を確認。パスワードをチャットや Issue に貼らない
- `CERTIFICATE_VERIFY_FAILED`: 正規の CA バンドルを確認。TLS 検証を無効化しない
- `No matching distribution`: Python の版・アーキテクチャ、ミラー / wheelhouse の内容を確認
- `.venv` が不完全: 自動削除はしません。IT 担当に確認するか、新しくソースを展開してやり直す

`--timeout 120 --retries 3` で待機を調整できます。接続先・認証の誤りは待機を延ばしても直りません。ダウンロードに失敗しても通常は `.venv` を消さず再実行できます。

## オフライン / IT 配布用 wheel フォルダー

IT 担当が、**対象と同じ Windows アーキテクチャ・Python minor 版**の通信可能な承認済み環境で、同じソース版の lock を使って準備します。

```bat
python -m pip download --only-binary=:all: --require-hashes -r requirements.lock -d wheelhouse
```

ソース一式と `wheelhouse` を会社の承認済み手段で対象 PC に運び、実行します。

```bat
Setup.cmd --wheelhouse "C:\Approved Packages\wheelhouse"
```

このモードはパッケージインデックスを利用せず、外部 find-links と pip 設定ファイルも読み込みません。依存ファイルのハッシュ照合は引き続き必須です。必要な wheel が欠けていたら停止し、オンラインにフォールバックしません。proxy / certificate オプションとは併用しません。Python 本体は別途必要です。`.venv` を他 PC からコピーしないでください。

オンライン・オフラインとも依存ライブラリーのソースビルドを禁止しています。Visual C++ Build Tools の追加を求めたり、ソース配布を暗黙にコンパイルしたりしません。アプリ自身は同梱のソースを editable install します。最後に `pip check` と主要モジュールの import が成功してから完了と表示します。

## 起動オプション・互換 PowerShell

```bat
Launch.cmd --port 8820
Launch.cmd --state-dir "C:\Users\me\AppData\Local\AgentWorkbench-test"
```

旧式の `-Port` / `-StateDir` / `-NoBrowser` も受け付けます。デスクトップから起動したい場合は、Explorer で `Launch.cmd` のショートカットを作成できます。

既存の PowerShell スクリプトは互換入口として残っています。会社の実行ポリシーで許可されている場合だけ利用してください。`Setup-Windows.ps1` の `-ProxyUrl` / `-CertificatePath` / `-PythonExecutable` / `-CreateDesktopShortcut` に加え、`-Wheelhouse` / `-CheckOnly` に対応します。実行ポリシーを変更する必要はありません。

## 配布・検証の限界

この手順は Python が必要なソース配布です。Python 同梱 EXE、署名済みインストーラー、会社の端末管理ツール向けパッケージではありません。依存パッケージは固定されていますが、会社ごとの通信許可、証明書、端末制御の検証は対象 PC で必要です。
