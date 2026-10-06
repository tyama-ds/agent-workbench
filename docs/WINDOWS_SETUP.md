# Windows 11・会社 PC へのセットアップ

## 最短の手順

Python の導入・パス指定前に、展開先のコマンドプロンプトで `Setup.cmd --help` を実行すると手順とオプションを表示します。`Setup.cmd -h` / `Setup.cmd /?` も同じです。ヘルプ指定は最初の引数として単独で使い、ほかの引数が続く場合はセットアップせずエラーになります。通常のオプションは別の実行に分けてください。ヘルプは Python を起動せず、`.venv` の作成、パッケージのインストール、ネットワーク接続、前提条件の診断も行いません。

1. 組織の認可を受け、アプリとは別に **64-bit の通常版 CPython 3.13** をインストールします。3.11 / 3.12 も対応対象です。管理者権限はアプリのセットアップには不要です。Python の導入に社内申請が必要なら IT 担当へ依頼してください。
2. ソース ZIP を**すべて展開**し、自分が書き込めるローカルフォルダーに置きます。例: `%LOCALAPPDATA%\AgentWorkbenchApp`。ZIP の中から直接実行したり、Program Files、ネットワーク共有に置いたりしないでください。
3. 展開先でコマンドプロンプトを開き、IT 担当が指定した実際の `python.exe` のフルパスを設定してから `Setup.cmd` を実行します。次のパスは例です。

   ```bat
   set "WORKBENCH_PYTHON=C:\Approved Python\python.exe"
   Setup.cmd
   ```

4. `Setup complete` が出たら `Launch.cmd` をダブルクリックします。起動のたびに Python のパスを設定し直す必要はありません。

Git、WSL、Docker、Node.js、Office、管理者 PowerShell は不要です。セットアップはプロジェクト内の `.venv` に依存ライブラリーを入れます。Python は同梱せず、本体のダウンロード・インストールも行いません。Windows の PATH、実行ポリシー、証明書ストア、プロキシ設定を変更しません。通常の利用に PowerShell は使いません。

起動中のコンソールを閉じるか Ctrl+C でサーバーを終了します。すべてのチームの履歴と画面で入力した API キーが失われるため、先に必要な報告・保存記録を「成果・保存記録」で1件ずつ選んで `.txt 保存` し、ブラウザー側でダウンロード完了を確認してください。環境変数のキーは次の起動時の環境を使います。設定と既に保存した作業ファイルは終了時に削除しません。保存記録にはファイル本体は含まれず、現在のファイルの存在・内容は未確認です。

ブラウザーのタブを閉じたり再読み込みしても、サーバーと実行中の作業は停止しません。画面の「停止」は選択したチームだけを止め、履歴は保持します。未送信の下書きの復元や、認証 Cookie を失った後の再接続は保証しません。1起動あたり20作業に達した場合は、必要な報告・保存記録を保存し、すべての作業完了後にサーバーを再起動してください。完了・停止した作業も20件に数えます。

フォルダーは移動しないでください。移動する場合は新しい場所にソースを展開し、再セットアップします（`.venv` のコピーは不可）。アプリの設定は `%LOCALAPPDATA%\AgentWorkbench` に残ります。

**社内ポリシーで Python / CMD / ローカルサーバーの起動が禁止されている場合は IT 担当に確認してください。** SmartScreen、AppLocker、WDAC、ウイルス対策や証明書の警告を回避する手順はありません。配布元と内容を確認し、会社の承認を得て使ってください。

## Python が見つからないとき

セットアップは `WORKBENCH_PYTHON` で指定された、別途認可・導入済みの実際の `python.exe` のみを使います。`py` / `python` エイリアスは未導入の Python を自動インストールする場合があるため、自動探索・実行しません。パスを指定していない場合や実行ファイルがない場合は停止します。ドライブ名で始まるローカルのフルパスを使い、Microsoft Store / Python Install Manager のエイリアスや `.venv` 内の Python は指定しないでください。実行前に標準インストールの `Lib\os.py`、`Lib\venv`、`Lib\ensurepip` を確認します。これは構成の確認であり、会社による認可をアプリが判定するものではありません。

32-bit、PyPy、free-threaded 版、未検証の 3.14 以降は利用対象外です。Python 3.13 の通常版 x64 を推奨します。ARM64 Windows は未検証であり、依存 wheel の対応を別途確認する必要があります。

承認済み Python が別の場所にある場合は、コマンドプロンプトで指定できます。

```bat
set "WORKBENCH_PYTHON=C:\Approved Python\python.exe"
Setup.cmd
```

この指定はそのコマンドプロンプトだけに適用されます。同じ画面から `Setup.cmd` を実行してください。Microsoft Store のエイリアスだけが存在する場合は、実際の Python を IT 担当に別途導入してもらってください。会社の設定・環境変数は変更しません。

## インストール前の確認

展開先でコマンドプロンプトを開き、上の手順で `WORKBENCH_PYTHON` を指定します。

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

## どの段階で止まったか（0.1.1.dev10）

コンソールの最後の `Setup step:` と `Setup stopped:` を確認してください。

- `Create private environment`: Python 本体またはフォルダー権限を IT 担当へ確認。不完全な `.venv` は消さず、新しくソースを展開して再実行します。
- `Validate private interpreter`: `.venv` の移動・破損・対応外 Python の可能性があります。元の `.venv` をコピーせず、新しい展開先で作り直します。
- `Check private pip`: `--python` に対応する pip 22.3 以降が必要です。承認済み Python の修復を IT 担当へ依頼してください。セットアップは pip を自動更新しません。
- `Check pip configuration`: 依存インストール先を変える設定、別の Python を使う設定、追加の入力、TLS 検証を省く設定を検出した場合は停止します。設定値は表示せず、既存の設定も変更しません。IT 担当による確認、または承認済み wheelhouse を利用してください。
- `Install locked dependencies`: 上記のプロキシ・CA・対応 wheel を確認。接続エラーなら条件を直して同じセットアップを再実行できます。
- `Install local application`: ソース一式と固定されたビルド用パッケージを確認。オンライン取得への切り替えはありません。
- `Check package consistency` / `Check application imports`: 最終確認は未完了です。表示されたエラーを IT 担当へ確認し、成功するまでは `Setup complete` と見なしません。

通常モードでは `PIP_PYTHON` / `PIP_ROOT` / `PIP_TRUSTED_HOST` と、それに相当する pip 設定も拒否します。承認済みの proxy / CA / パッケージミラーは引き続き利用できます。設定の検査中だけ、出力を隠す quiet や設定ファイル範囲の指定を無効化し、検査出力のファイル保存を止めます。ユーザーの設定ファイルは変更しません。既存 `.venv` が実際にそのフォルダーの仮想環境であることも確認します。

新しい `.venv` を作る際は Python に同梱された ensurepip で pip を用意します。これはネット接続をしない標準の初期化です。その後、安全に読み取った pip 設定を確認してから依存パッケージを入れます。`--check` では環境変数の拒否設定までは調べますが、pip 設定ファイルと既存 `.venv` の健全性は検査しません。

会社の実行制御で止まった場合は、失敗した時刻と画面のエラー、対象の Python / CMD / DLL 名を IT 担当へ伝えてください。IT 担当は既存の CodeIntegrity / AppLocker イベントで原因を調べられます。管理者実行や保護機能の変更で回避しないでください。pip 自身が出したログには秘密や社内情報が含まれる可能性があるので、外部共有前に内容を確認してください。

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

既存の PowerShell スクリプトは互換入口として残っています。`-PythonExecutable` または `WORKBENCH_PYTHON` で、上記と同じ実際の Python のフルパスを指定してください。自動探索は行いません。会社の実行ポリシーで許可されている場合だけ利用してください。`Setup-Windows.ps1` の `-ProxyUrl` / `-CertificatePath` / `-PythonExecutable` / `-CreateDesktopShortcut` に加え、`-Wheelhouse` / `-CheckOnly` に対応します。実行ポリシーを変更する必要はありません。

## 配布・検証の限界

この手順は Python が必要なソース配布です。Python 同梱 EXE、署名済みインストーラー、会社の端末管理ツール向けパッケージではありません。依存パッケージは固定されていますが、会社ごとの通信許可、証明書、端末制御の検証は対象 PC で必要です。

## Python 同梱版の終了

`0.1.1.dev23` から、Python 同梱版の試作・ビルド・配布準備は行いません。旧 `tools/build_portable.py` と `tools/portable.spec` は、評価用・直接実行を含めて処理開始前に停止します。同梱版の CI ジョブも削除しています。

過去の notice・manifest・検証記録、および一部の検証用補助コードは履歴を保つため残しています。`requirements-build.lock` は旧同梱版専用の記録であり、インストールに使用しません。過去の再配布調査が完了しても、この同梱禁止方針が自動で変わることはありません。

現在の導入手順は、この文書の `Setup.cmd` / `Launch.cmd` のみです。Python 本体の版・パッチ更新と利用許可は、組織の承認手順で別途管理してください。
