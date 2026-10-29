# チームの進行を確認する

「協働の進行」には、アプリが記録した現在の段階を表示します。担当を押すと、右側の担当ログへ移動します。丸いノードの概要にも同じ状態が表示されます。

- 順番付きの作業では、現在の手番と担当、PMの候補監査待ち、採用済みの手数、訂正と巻き戻しの回数を表示します。
- 正式報告は、現在版・報告版・配送版・PMが取り込んだ版・PMが承認した版を区別します。古い版への承認は現在版の承認になりません。
- モデルの呼び出しでは、Local受付待ちとAPI応答待ちを分け、観測した経過時間と設定上限を表示します。受付待ちにはGPU確認や開始間隔の待機も含みます。ソケットの接続時刻やサーバー内部の推論開始を測定した表示ではありません。
- 「配送の追跡」は同じメールID・差出人・宛先の送信と取込を結びます。片側の記録が最新100イベントの範囲にない場合は未確認と表示します。取込は理解や実行の完了を保証しません。
- 手順用に文脈を抜粋した場合は、送信前後の件数と省略数を表示します。AI要約とは別で、元の履歴にも保持上限があります。

表示はモデルへの指示や実行権限を変更しません。画面を開いただけで推論や再試行を増やすこともありません。接続が切れた場合は最後の観測と明示し、画面側で経過時間を推測して増やしません。順番付き作業の進行は保存履歴から閲覧できますが、再実行や手番の復元には使いません。APIの細かな呼び出し段階は現在の起動中の観測で、再起動後の履歴には保存しません。

固定参照との一致、PMの承認、アプリが完了を受理したこと、成果の内容が正しいことは別の確認です。監視表示だけでモデル判断の改善や一般的な自律成功が証明されるわけではありません。

## 参照資料を使う作業の監査記録

アプリが原本との照合後に発行した監査イベントは、「固定参照との構造化照合」として表示します。手番・担当・提出世代・実際の前の語・必要な先頭文字・提出値・意味・参照IDとSHA-256を確認できます。正式報告では対象の担当IDと報告版も示します。行が多い場合は事実の一覧内をスクロールでき、キーボードでも移動できます。

PMが書いた自由文は「PMの判断・コメント（文章の正しさは未検証）」として別に表示します。構造化された事実が一致していても、コメントの誤りや訂正漏れは解消されません。固定資料との一致は、一般辞書の正しさ・意味理解・自由な語彙生成の成功を保証しません。

専用表示は、予約された `reference_audit` イベント、同じチームのPM、厳密なバージョン1の構造を確認できる記録だけに適用します。メールや掲示板の本文に似たJSONを書いても照合記録にはなりません。旧 `ordered_reviewed` / `worker_report_review` は「過去のPMコメント／構造化照合記録なし」と表示し、過去の文章を書き換えません。壊れたJSON、保持上限で切れた記録、必要な事実がマスクされた記録は未検証の原文表示に戻ります。秘密を復元して照合することはありません。

これらは記録時点の照合です。保存履歴では保存時点の事実として読むだけで、現在の承認・完了・手番の実行権限を復元しません。新しい監査表示からモデル呼び出しや送信は行いません。

## 参照した実装と採用範囲

2026-10-28に[Orreryのcommit 71b88cb](https://github.com/gyroid-eth/orrery/tree/71b88cb432e17e162cc70bffe79b9816ff77677e)を読み、次の処理を確認しました。

- [cockpit.html の pollAgents / pollMail](https://github.com/gyroid-eth/orrery/blob/71b88cb432e17e162cc70bffe79b9816ff77677e/bridge/cockpit.html#L9249): 監視データ取得の遅延と接続不能を分け、メールIDで重複を除いて表示イベントへ渡します。
- [mail_view.js の normalizeMessage / mergeMessage](https://github.com/gyroid-eth/orrery/blob/71b88cb432e17e162cc70bffe79b9816ff77677e/bridge/mail_view.js#L53): 宛先とスレッド情報を正規化し、同じメールを統合します。この表示処理だけからモデルの文脈取込や理解を証明するものではありません。
- [orrery_view.js の observedMailTime / receiveMail](https://github.com/gyroid-eth/orrery/blob/71b88cb432e17e162cc70bffe79b9816ff77677e/bridge/orrery_view.js#L990): 記録時刻に基づく通信表示と受信イベントによるアニメーションを使います。
- [orrery_backend.py の prepare_agents_payload](https://github.com/gyroid-eth/orrery/blob/71b88cb432e17e162cc70bffe79b9816ff77677e/bridge/orrery_backend.py#L487): 稼働中の待機担当に対し、ターミナルの質問検出を補助的に行います。AWBでは文字列から質問や手番を推定せず、既存の実ツール・待機状態を使います。

参照したのは、観測の根拠を追えること、担当と通信を一緒に見られること、取得できない情報を成功扱いしないという設計です。外部コード・素材・依存パッケージの取り込みはありません。Orrery自体を起動して検証した結果ではなく、公開ソースを読んだ比較です。

連携先の[Orrery Telemetry c4d1985](https://github.com/gyroid-eth/orrery-telemetry/tree/c4d1985c2a0c9587ce412da10f53d8085606912c)も確認しました。[delivery.py](https://github.com/gyroid-eth/orrery-telemetry/blob/c4d1985c2a0c9587ce412da10f53d8085606912c/integrations/codex_app/src/agentstack_codex_app/delivery.py#L208)はSQLite上の所有者付き配送状態を更新し、[wake.py](https://github.com/gyroid-eth/orrery-telemetry/blob/c4d1985c2a0c9587ce412da10f53d8085606912c/integrations/codex_app/src/agentstack_codex_app/wake.py#L438)は再開プロセスの終了結果から配送結果を確定します。[provider_stalls.py](https://github.com/gyroid-eth/orrery-telemetry/blob/c4d1985c2a0c9587ce412da10f53d8085606912c/dashboard/provider_stalls.py#L204)は古い観測で新状態を巻き戻さず、通知前に記録を確保して結果不明を区別します。これらの意味は成果内容の正しさとは異なります。AWBでは既存の実受信・世代・正式報告・PM監査の判定を維持し、今回の監視追加で自動再開や再送を増やしていません。
