# 必要な Python とパッケージ

アプリを動かすために必要な Python パッケージは、直接使う4件と、その依存13件の **合計17件**です。固定バージョンと配布ファイルのハッシュは [requirements-runtime.lock](../requirements-runtime.lock) に記載しています。Python 本体は同梱せず、別途承認・導入された **通常版 CPython 3.11～3.13、Windows x64** を使います。

## どのファイルを使うか

| ファイル | 用途 |
| --- | --- |
| [runtime.example.json](../runtime.example.json) → `runtime.local.json` | この PC の `python.exe`、導入済みライブラリの場所、起動オプションを指定するひな形 |
| [requirements-runtime.lock](../requirements-runtime.lock) | 外部の Python 環境でアプリを実行するための17パッケージ。バージョン・ハッシュ付き |
| [requirements.lock](../requirements.lock) | 実行用17件、テスト用7件、セットアップ用1件の合計25件。従来の `Setup.cmd` と CI が使用 |
| [pyproject.toml](../pyproject.toml) | アプリの直接依存と対応バージョン範囲。個別 PC のパス設定ではない |
| [requirements-build.lock](../requirements-build.lock) | 廃止済みの Python 同梱版に関する履歴。現在の導入・起動には使用しない |

`Setup.cmd` は従来どおり、プロジェクト内の `.venv` に `requirements.lock` の25件を導入します。外部環境を明示する `Launch-Configured.cmd` は、設定された Python と導入済みパッケージで起動する入口です。起動時にパッケージをインストールしません。実行だけなら `pip`、`setuptools`、`pytest` は不要です。

## 実行に必要な17パッケージ

下記のバージョンは、このリポジトリの lock に固定された値です。インストール名と Python の `import` 名が異なるものがあります。

`Launch-Configured.cmd` は確認・起動の両方でこの固定版との一致とimportを検査します。不足・版違いは表示して停止し、別の場所からの自動取得や更新は行いません。パッケージ本体と `.dist-info` を揃えた通常のインストール済みフォルダーを指定してください。

| インストール名 | 固定バージョン | import 名 | 用途 |
| --- | --- | --- | --- |
| `aiohttp` | 3.14.3 | `aiohttp` | 直接依存。画面用のローカル HTTP サーバー、推論 API、Web 検索・取得の HTTP 通信 |
| `python-docx` | 1.2.0 | `docx` | 直接依存。Word の `.docx` 読み書き・編集 |
| `openpyxl` | 3.1.5 | `openpyxl` | 直接依存。Excel の `.xlsx` 読み書き・編集 |
| `python-pptx` | 1.0.2 | `pptx` | 直接依存。PowerPoint の `.pptx` 読み書き・編集 |
| `aiohappyeyeballs` | 2.7.1 | `aiohappyeyeballs` | `aiohttp` の接続先アドレス選択 |
| `aiosignal` | 1.4.0 | `aiosignal` | `aiohttp` の非同期通知 |
| `attrs` | 26.1.0 | `attrs` / `attr` | `aiohttp` 内部のデータ構造 |
| `et_xmlfile` | 2.0.0 | `et_xmlfile` | `openpyxl` の XML 書き出し |
| `frozenlist` | 1.8.0 | `frozenlist` | `aiohttp`・`aiosignal` のリスト管理 |
| `idna` | 3.20 | `idna` | `yarl` の国際化ドメイン名処理 |
| `lxml` | 6.1.3 | `lxml` | `python-docx`・`python-pptx` の XML 処理 |
| `multidict` | 6.9.1 | `multidict` | `aiohttp`・`yarl` の複数値を持つ HTTP ヘッダ・URL データ |
| `pillow` | 12.3.0 | `PIL` | `python-pptx` の画像処理 |
| `propcache` | 0.5.4 | `propcache` | `aiohttp`・`yarl` のプロパティのキャッシュ |
| `typing_extensions` | 4.16.0 | `typing_extensions` | Office ライブラリ等が利用する型機能の互換性 |
| `xlsxwriter` | 3.2.9 | `xlsxwriter` | `python-pptx` の埋め込み Excel データの作成 |
| `yarl` | 1.25.1 | `yarl` | `aiohttp` の URL 処理 |

## テスト・セットアップにだけ必要なもの

次の8件も従来の `requirements.lock` には含まれますが、外部環境からアプリを実行するだけなら不要です。

| インストール名 | 固定バージョン | 用途 |
| --- | --- | --- |
| `pytest` | 9.1.1 | Python テストの実行 |
| `pytest-asyncio` | 1.4.0 | 非同期処理のテスト |
| `colorama` | 0.4.6 | Windows 上の pytest の色表示 |
| `iniconfig` | 2.3.0 | pytest の設定解析 |
| `packaging` | 26.3 | pytest のバージョン判定 |
| `pluggy` | 1.6.0 | pytest のプラグイン管理 |
| `Pygments` | 2.21.0 | pytest のコード表示 |
| `setuptools` | 84.0.0 | `Setup.cmd` によるアプリの editable install |

`Setup.cmd` は、承認済み Python に付属する `venv` / `ensurepip` と、`--python` オプションを利用できる `pip 22.3` 以降を使用します。pip の自動更新はしません。外部環境のパッケージを準備するときだけ pip を使い、起動時には使いません。

Edge の画面操作テストを開発者が実施する場合は、別途 Node.js と [テスト用 package-lock](../tools/browser-tests/package-lock.json) の Playwright 1.62.1 を使います。これらはアプリの実行には不要です。

## Python とライブラリの場所を指定する

1. `runtime.example.json` を同じフォルダーへ `runtime.local.json` という名前でコピーします。
2. `python_executable` に、使う `python.exe` のフルパスを記入します。
3. `library_paths` に、必要なパッケージを導入済みのフォルダーを記入します。これは Python の標準ライブラリ `Lib` 自体ではなく、`aiohttp`・`docx`・`openpyxl`・`pptx` などが入っているフォルダーです。
4. 必要なら `port`、`state_dir`、`open_browser` を変更します。API プロファイルや作業フォルダーの権限は、これまでどおりアプリ内の設定を使います。
5. `Launch-Configured.cmd --check` で確認し、問題がなければ `Launch-Configured.cmd` で起動します。

パスは、その PC の実際の場所に置き換えます。JSON では `C:/ApprovedPython/python.exe` のような `/` 区切りを使うと、バックスラッシュの二重記述を避けられます。

`site-packages` と `wheelhouse` は別物です。

| フォルダー | 中身 | 指定する場所 |
| --- | --- | --- |
| 導入済みライブラリ / `site-packages` | パッケージのフォルダー、`.dist-info`、`.pyd` など | `runtime.local.json` の `library_paths` |
| `wheelhouse` | 導入前の `.whl` ファイル | pip の `--find-links`、または従来の `Setup.cmd --wheelhouse` |

wheel を置いただけのフォルダーを `library_paths` に指定しても、導入済みライブラリにはなりません。`lxml` や `aiohttp` などのネイティブ拡張 `.pyd` は、使用する Python の minor バージョンと Windows x64 に対応するものが必要です。別 PC の `.venv` をそのままコピーせず、対象環境に合う wheel から準備します。

## 外部ライブラリを準備する場合の例

既に承認済みのライブラリが用意されている場合は、この操作は不要です。以下は IT 担当等が導入を行うための PowerShell の例です。Python と導入先のパスは例示であり、実際の承認済みパスへ置き換えます。プロジェクトのルートで実行します。

```powershell
& "C:\ApprovedPython\python.exe" -m pip install --only-binary=:all: --require-hashes -r .\requirements-runtime.lock --target "C:\ApprovedPackages\AgentWorkbench\site-packages"
```

この場合、`library_paths` には `C:/ApprovedPackages/AgentWorkbench/site-packages` を指定します。取得時のプロキシ・社内 CA は、組織が指定する pip の設定を使用します。アプリの API プロキシ設定とは別です。

対象の Python 版・Windows x64 に合う承認済み wheel が揃っている場合は、パッケージインデックスを使わず準備できます。

```powershell
& "C:\ApprovedPython\python.exe" -m pip install --no-index --find-links "C:\ApprovedPackages\wheelhouse" --only-binary=:all: --require-hashes -r .\requirements-runtime.lock --target "C:\ApprovedPackages\AgentWorkbench\site-packages"
```

`requirements-runtime.lock` の17件は、`requirements.lock` から同じバージョンとハッシュを抽出したものです。依存を更新するときは、両方の lock とこの一覧を合わせて更新します。

## 通常の実行には不要なもの

OpenAI / Anthropic の Python SDK、PyTorch、CUDA Toolkit、Node.js、Git、Microsoft Office 本体は、通常のアプリ実行には不要です。API 呼び出しには `aiohttp` を使い、Office ファイルは上記の Python ライブラリで操作します。GPU 監視機能を有効にするときだけ、NVIDIA ドライバー付属の `nvidia-smi` が別途必要です。ローカル LLM を提供するサーバーとモデル本体は、このアプリの依存パッケージには含まれません。
