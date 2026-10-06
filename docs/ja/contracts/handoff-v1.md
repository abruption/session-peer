# Handoff v1 契約 — 設計提案 v0.2

## 状態と出典

これは Python #181 と TypeScript 0.4.0 設計レビューに向けた未実装の設計です。確定したプロトコルでも、リリースの約束でも、実際の ACK 対応の証拠でもありません。この文書のマージは、ランタイム実装、公開、ネイティブ送信、運用変更を許可しません。フィクスチャに含まれるのは合成した例であり、記録された配信ではありません。

公開済みの Python 参照版は [v1.0.3](https://github.com/abruption/session-peer/tree/0d252550ab40c26d1ac4a19193df6ca2f84d830b) です。通常出力のソースは [adapters](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/adapters.py)、[Codex](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/codex.py)、[SSH](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/ssh.py)、[output](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/output.py) です。[共有フィクスチャ](https://github.com/abruption/session-peer/blob/main/tests/fixtures/handoff-v1.json) は、正規化されたレガシーの例と、提案されたオプトインの例を分けています。ランタイム参照と設計フィクスチャの固定版は別です。TypeScript の公開済みの過去の参照を、未リリースの Python 版へ暗黙に変更しません。

## 証拠と互換性

送信とはネイティブのトランスポートによる受け付けを指し、配信とは正確な元のユーザーメッセージ ID が正確な元の対象世代に注入された証拠を指します。確認応答は、明示的に相関付けされた受領確認であり、完了、責任の引き受け、モデルが全バイトを読んだ証拠ではありません。キュー削除、プロセス終了、ターン完了、返信がないこと、状態照会の成功は ACK ではありません。不明なネイティブのターン状態が completed になることはありません。

通常の send 出力はランタイム固有のままです。Python Claude の成功時は status、submitted、consumptionConfirmed を省略します。Codex の queued 成功時は submitted true と consumptionConfirmed false を含みます。submitted false のレガシー unknown は、作用がなかったことの普遍的な証拠ではありません。欠けている false/null フィールドの追加、任意フィールドの不在の再解釈、consumptionConfirmed の上書き、通常の終了コードの変更を行わないでください。正規化されたフィクスチャ値は識別情報だけを隠します。各例は出典を記録しており、網羅的な出力スキーマではありません。

オプトインは、既存の外側の schemaVersion 1 の下で、各宛先の結果に handoff オブジェクトを 1 つ追加します。fanout 全体の handoff はありません。明示的な待機が変更できるのは外側の ok と終了コードだけです。ネイティブの status、target、queueId、submitted、consumptionConfirmed と、独立して有効なすべての送信証拠を保持します。結果の受信側は、この検証モードの選択に信頼できない返却フィールドではなく、自身の元の要求コンテキストを使う必要があります。元の要求が明示的な待機で、handoff が完全に検証され、ネイティブ送信の証拠と元のネイティブ対象の一致が確認された場合にだけ、queued/posted、submitted true、ok false、終了コード 1 の組み合わせを待機失敗として許可します。handoff の受信だけでは、オプトアウト要求でこの組み合わせを許可しません。この待機失敗の経路でも target/home を検証します。ベストエフォートの観測失敗はネイティブ送信の成功を変更できません。不正またはサイズ超過の handoff は、別途検証された正しい対象のネイティブスナップショットを消去したり ACK に昇格させたりできません。明示的な待機は再送信せずに検証に失敗します。不正なネイティブ対象は、独立して有効な送信証拠ではありません。

## 公開スキーマ

次の文法はこの提案の規範です。ランタイム固有の外側のエンベロープを除き、すべてのオブジェクトは閉じたオブジェクトです。疑問符は任意であり、利用できない場合は存在しないことを意味します。null を許容するフィールドは下記に明記します。条件付き規則は文法の後に続きます。

```text
handoff.schemaVersion = 1
handoff.correlationId = UUID-v4 lowercase canonical
handoff.ledgerEpoch = UUID-v4 lowercase canonical
handoff.state = validated | refused | submitted | delivered | acknowledged | unknown | timed_out_unknown
handoff.submission.status = not_attempted | submitted | refused | unknown
handoff.observation.status = not_requested | pending | observed | unsupported | failed
handoff.observation.injectionObserved = boolean
handoff.observation.clientUserMessageId? = safe-id
handoff.observation.turn? = {id: safe-id, status: running | completed | failed | interrupted | unknown}
handoff.ack.status = not_requested | pending | acknowledged | unsupported
handoff.ack.assurance? = token_possession | operator_confirmed
handoff.ack.receivedAtUtcMs? = safe-integer
handoff.ack.late? = boolean
handoff.wait.for = none | delivered | acknowledged
handoff.wait.status = not_requested | pending | satisfied | timed_out_unknown | stopped | unsupported | failed
handoff.wait.operationId? = UUID-v4 lowercase canonical
handoff.wait.deadlineAtUtcMs? = safe-integer
handoff.wait.reason? = insufficient_budget | deadline_before_effect | evidence_unsupported | evidence_failed | history_unavailable | stopped_by_operator | invalid_handoff
handoff.targetGeneration = safe-generation | null
handoff.decisionOwner = sender_operator
handoff.retry = {allowed: false, reason: receiver_dedup_unavailable}
handoff.nextActions = unique subset of [keep_waiting, reconcile, stop_waiting]
```

配信には、観測された注入、正確な clientUserMessageId、null ではない元の targetGeneration が必要です。ターンの証拠には観測された注入が必要です。ターンは受領状態とは別です。受領確認の受け付けは注入の証拠を作り出しません。acknowledged 状態には、assurance、受領時刻、late フラグを備えた acknowledged ack が必要です。他の ACK 状態ではこれらのフィールドを省略します。submitted、delivered、acknowledged 状態には submitted submission が必要です。validated には not_attempted、refused には refused、unknown には unknown が必要です。タイムアウト状態は submitted または unknown を許可し、refused/not_attempted は許可しません。

各明示的な待機には、作用前の拒否であっても operationId と期限があります。待機のない記録にはどちらもありません。satisfied の delivered 待機には注入の証拠が、satisfied の acknowledged 待機には有効な ACK が必要です。stopped/failed/unsupported の待機は既知の作用の証拠を保持します。nextActions は稼働中の検証済みチャネルと保持された履歴に依存します。未対応または期限切れのチャネルは keep_waiting を提示しません。stop_waiting は観測だけを終了し、ネイティブの作業を取り消しません。すべてのネイティブのローカル/SSH 結果は再試行を禁じます。v1 に resend_same_id アクションはありません。相関付けとユーザー承認だけでは安全な再送を確立できません。受信側の重複排除（#182）は、この再送禁止契約を実装する前提条件ではありません。

## 状態と終了コードのタプル

不在とは、レガシーフィールドが引き続き存在しないことを意味します。ネイティブとは、変更されていないランタイムごとのスナップショットを指します。同じ表がローカルと SSH に適用され、未実装のペアリングデバイスのトランスポートには適用されません。

| モード / 証拠 | state | submission | wait status | 外側の status / submitted | ok / 終了コード |
| --- | --- | --- | --- | --- | --- |
| 通常の send | 不在 | 不在 | 不在 | ネイティブ / ネイティブまたは不在 | ネイティブ |
| オプトインの dry-run | validated | not_attempted | not_requested | ネイティブ / ネイティブまたは不在 | true / 0 |
| 作用前に必須チャネルが利用不可 | refused | refused | unsupported | 存在すればネイティブ / 合成フィールドなし | false / 1 |
| 確実に作用前に予算が尽きた | refused | refused | failed | 存在すればネイティブ / 合成フィールドなし | false / 1 |
| キュー登録が既知、ベストエフォート観測者が失敗 | submitted | submitted | not_requested | queued / true | true / 0 |
| キュー登録が既知、明示的 ACK 期限が切れた | timed_out_unknown | submitted | timed_out_unknown | queued / true | false / 1 |
| 注入が既知、ACK 期限が切れた | timed_out_unknown | submitted | timed_out_unknown | ネイティブ / ネイティブまたは不在 | false / 1 |
| 作用が起きた可能性があり、受領確認なし | unknown | unknown | not_requested | ネイティブ / ネイティブまたは不在 | false / 1 |
| 有効な受領確認が明示的待機を満たす | acknowledged | submitted | satisfied | ネイティブ / ネイティブまたは不在 | true / 0 |
| 以前のタイムアウトの状態照会が成功 | timed_out_unknown | submitted | timed_out_unknown | 不在 / 不在 | true / 0 |

不正なフラグ、不正なタイムアウトの字句、対象の欠落、不正な ID は、使用法/対象なしの終了コード 2 を維持し、JSON/handoff がまったくない場合もあります。こうした失敗に合成の相関 ID やレガシーの false/null を作りません。割り込みは取り消し/再送なしで終了コード 130 を使います。成功した状態照会が報告するのは照会の成功であり、確認応答ではありません。

## 機能とブートストラップ

すべての機能は将来の受け入れ条件であり、現在の製品対応ではありません。経路は ACK 対応を表明する前に、受領確認の消費側、生成側、不変の元の対象世代を独立して検証する必要があります。null 世代は受領確認の権限を発行できず、必須の delivered/acknowledged 待機にも対応できません。その要件は作用前に wait unsupported として拒否します。ブートストラップの失敗は unsupported であり、汎用メッセージ配信を試みる許可ではありません。新たに発見した現在の世代で元の結合を置き換えることはありません。対象の再起動は新たな送信/再結合を防ぎますが、それだけで元の世代に結合された遅延受領確認を無効にしません。検証済みの元のタプルと元の権限が証明するのは委任されたトークン所持であり、元のエージェント/モデルの身元ではありません。後継の新しい世代は拒否します。コピーされた元のタプルと元の権限の両方を持つ後継や同一ユーザーの閲覧者は、token_possession の保証では区別できません。この仕組みがモデルの身元を認証してその再生を排除すると主張してはなりません。

| 経路 / 観測者 | 注入の観測 | 受領確認 ACK |
| --- | --- | --- |
| 同一マシンの非公開コレクターと互換生成側 | version/home/writer/ID の検証後の Codex のみ | 非公開ブートストラップ後に対応 |
| インストール済みの互換受領確認ハンドラーへの明示的に信頼されたリバース SSH | 別途検証された Codex 経路 | ハンドラー/設定の検証後に対応 |
| 互換ハンドラーのインストールなしでソースをストリーミングする SSH | 別途検証された Codex 経路 | 未対応 |
| Claude ネイティブ観測者 | デフォルトでは未対応 | 互換性のある明示的な受領確認生成側のみ |
| ペアリングデバイス、Relay、Side Session、wake | 初期経路の範囲外 | 未対応 |

必須の delivered または acknowledged 待機は、チャネルが未対応なら作用前に拒否します。ベストエフォートの相関付き send は、未使用の秘密の権限を発行せず、observation/ack unsupported で送信できます。コレクターは配信、wake、モデルのプロンプト、承認を呼び出しません。ネイティブ app-server からキューへのフォールバックは、元のネイティブ送信が開始した可能性が生じる前にだけ許可されます。試行後の不確実性や観測者の失敗は、別の送信を決して引き起こしません。version、platform、home、元の writer の識別情報の確認は必須です。トランスクリプトや任意の返信本文は走査しません。

## 受領確認のワイヤー形式とライフサイクル

Receipt v1 は Reply-To v1 とは別であり、そのパーサーと権限は変わりません。受領確認ハンドルは秘密ではないローカル選択子であり、URI や権限ではありません。実際の bearer 権限は、許可された非公開の作用入力と非公開ハンドラーの stdin を通じてだけ伝わります。秘密を含めない保証は、送信者/コレクターの argv、URI、環境、通常の JSON、診断、エラー/ACK 結果、および自身の生のジャーナル/永続化を対象とします。意図された受信者のネイティブキュー、履歴、トランスクリプトは対象ではありません。ネイティブの作用入力は CLI の管理外でそこに保持される可能性があり、同一ユーザーの閲覧者は委任された受領確認専用権限を取得できる場合があります。token_possession は独立したエージェント認証ではありません。私たちの観測者は引き続きトランスクリプトを読みません。失効、24 時間の TTL、最初の受領確認の原子的な受け付けは、新しい受領確認権限を制限するもので、受信者の保存期間を制限しません。

```json
{
  "schemaVersion": 1,
  "kind": "receipt",
  "ledgerEpoch": "11111111-1111-4111-8111-111111111111",
  "correlationId": "22222222-2222-4222-8222-222222222222",
  "targetGeneration": "fixture-generation",
  "receiptId": "33333333-3333-4333-8333-333333333333",
  "capability": "<PRIVATE_INPUT_ONLY>"
}
```

権限は、暗号学的にランダムな 32 バイトをパディングなしの base64url の 43 文字で符号化したものです。例のプレースホルダーは有効なワイヤー入力ではありません。保護されたコレクターは、epoch、相関、元の世代に結合された権限の SHA-256 ハッシュだけを保存します。読み取り専用の重複を含むすべてのハンドラー要求で定時間検証が必要です。最初の受領確認の原子的な永続コミットには、受領確認 ID/結合、証明された分類、assurance、late フラグ、コレクターの受領時刻と、それを正当化する待機順序/期限の事実を含みます。状態と関連する待機の遷移は、この記録と一貫してコミットし、後の別の書き込みでは行いません。不正な ID、不正なトークン、後継世代、競合する受領確認、期限切れの未コミット権限、不正なフレームは状態を進められません。ACK 到着時刻はコレクターが割り当てます。呼び出し側のタイムスタンプは権威ある根拠ではありません。

コレクターは送信者の会話から独立した、ユーザー所有のプロセスです。ファイル/ディレクトリは非公開の 0600/0700 です。エンドポイントは、ローカルの所有者確認付き非公開 IPC、または明示的に設定された信頼できるリバース SSH ハンドラーです。公開リスナー、自動 SSH 鍵インストール、プロファイル変更、トランスクリプト読み取り、秘密のエクスポート、汎用 CLI exec は許可しません。再起動ではコミット済みの受領確認ハッシュと分類済みの受領確認を復元します。試行済みの意図について、失われた生の権限を再生成しません。権限の寿命は意図のコミットから 24 時間で、詳細の期限切れ、失効、隔離、または最初の有効な受領確認で終わります。期限切れの唯一の例外は、すでにコミットされた同一の受領確認の読み取り専用取得です。元の epoch、相関、世代、receiptId と、元の権限ハッシュの定時間証明のすべてを要求します。TTL の期限切れ/最初の受領確認による権限消費は、新しい受領確認の受け付けや状態の作成/昇格を許可しません。失効、隔離、詳細の欠落/期限切れ、不正なトークンはこの例外も拒否します。識別子だけでは汎用の状態/照会権限は付与されません。許可された送信者オペレーターの状態照会は、別の所有者確認付きローカルインターフェースを使います。

手動の生成側は、提案された送信なしの handoff confirm 操作です。正確な epoch/ID/元の世代と、観測された明示的な相関付き返信に関するローカルの送信者オペレーターの申告を必要とします。stdin が受け取るのはメタデータだけで、トランスクリプト/本文ではありません。operator_confirmed を記録し、token_possession は決して記録しません。確認は新しい現在の証言/イベントであり、古い受領確認の到着時刻を遡って証明するものではありません。永続的な終端待機の事実などから元の待機の順序/遅延分類を証明できる場合だけ acknowledged になれます。それ以外では、ok false、終了コード 1、固定の reason receipt_order_unprovable で確認を拒否します。元の pending/unknown ACK と元の待機を保持し、受け付けた ACK をコミットしたり late の真偽値を作り出したりしません。すでにコミットされた有効な受領確認は、この確認失敗で降格または置換しません。トークン所持の生成側は、非公開入力を読むインストール済みの互換受領確認専用ハンドラーである必要があり、任意のコマンドを実行できません。両方の生成側は引き続き実装の受け入れ条件です。生成側を検証するまで assurance は表明しません。

## 送信者台帳、新規性、保持

単一の非公開で直列化された永続台帳がランダムな epoch を所有します。対象に結合された準備済みの意図は、作用前にコミットして同期します。作用意図のフェンスをコミットした後は、その無傷の epoch 内でネイティブの試行は 1 回だけ許可されます。そのコミット後のクラッシュは、実際の作用が始まる前のクラッシュも含めて unknown として復旧し、再送信しません。結合には agent、宛先、home/writer の識別情報、世代、保護された内部ペイロードダイジェストを含みます。ダイジェストは公開出力ではありません。競合や対象の再起動で意図を暗黙に再結合しません。

新しい ID は、自動準備または新しい作用なしの handoff prepare 操作によって生成・予約します。呼び出し側が渡した未知の UUID は、新規性を証明できないため作用前に拒否します。渡された既知の準備済み ID は、正確な結合に一致し、未試行でなければなりません。渡された試行済み ID は照会/照合専用であり、別の send には使えません。順序付き fanout は、宛先ごとに 1 つの意図を一度だけ生成して永続的に関連付けます。呼び出し側は 1 つの ID を複数の宛先に再利用できません。照合は ID や権限を再生成しません。

epoch ごとの上限は、保持する意図/フェンス記録 10,000 件と 32 MiB のジャーナルのうち先に満たされる方です。受け入れ時には送信後に容量を埋めるのではなく、作用前に終端記録と受領確認 1 件に必要な上限付き保存領域を予約します。フェンスの退去/LRU は許可しません。詳細の保持期間は準備から 30 日、権限の寿命は 24 時間、意図ごとの最大待機数は 64 です。期限切れの詳細は対象に結合されたコンパクトなフェンス tombstone となり、epoch 全期間保持します。tombstone は割り当てに数えます。待機枠を使い切った場合、ネイティブの作用の事実を変えずに新しい待機を拒否します。詳細の削除によって送信権限は戻りません。容量を使い切ると、自動リセットではなく明示的なオペレーターのアーカイブまで準備/作用を拒否します。

欠落、破損、詳細の期限切れ、または既知の復元済み履歴は、status/reconcile で unknown を返し、再試行を禁じます。既知の tombstone は元の epoch と対象の結合を保持します。state/submission unknown、ACK/注入の主張なし、keep_waiting なしの通常の handoff を返せます。台帳の欠落/破損や未知の ID ではそのコンテキストを復元できないため、handoff や架空の epoch を含めず、以下の別の照会エラーエンベロープを必ず返します。既存の台帳を自動再作成しません。初回利用には明示的なローカル初期化と新しい epoch が必要です。既知の復元は古いすべての意図を隔離し、保持された証拠の照合まで作用と受領確認の受け付けを無効にします。新しい epoch には明示的なオペレーター初期化と生成された新しい ID が必要であり、古い要求について何も保証しません。ローカルだけの設計では、印のないロールバックやマシン間の台帳複製を確実に検出できません。フェンシングの保証は、無傷で保持され、ロールバックされていないと証明された履歴に限られます。外部の単調アンカー/複製防止ストレージは v1 の範囲外です。この制限は、普遍的な exactly-once の主張の裏に隠さず、見える状態に保つ必要があります。

提案された照会エラーは終了コード 1 を使います。handoffQuery は表示されたフィールドだけを持つ閉じたスキーマで、context は ledger_missing、ledger_corrupt または id_unknown です。呼び出し側の構文上有効な correlationId はそのまま返しますが、履歴の証拠とは扱いません。ledgerEpoch、handoff、最上位の status/submitted/consumptionConfirmed、合成のネイティブスナップショットは追加しません。外側の host/command は照会先と handoff で、reason は handoff_history_unavailable です。これはオプトインの照会結果であり、通常のレガシーエラーの変更ではありません。

```json
{
  "schemaVersion": 1,
  "ok": false,
  "host": "fixture",
  "command": "handoff",
  "reason": "handoff_history_unavailable",
  "handoffQuery": {
    "schemaVersion": 1,
    "correlationId": "22222222-2222-4222-8222-222222222222",
    "status": "unknown",
    "context": "ledger_missing",
    "retry": {"allowed": false, "reason": "history_unavailable"}
  }
}
```

## 待機履歴と遅延した受領確認

各待機には異なる操作 ID、目標、単調時計の期限、不変の終端結果があります。status は、その意図について最後に開始した待機（直列化された順序）を返し、待機がなければ not_requested を返します。将来の別個の待機履歴 API を示唆しません。現在の受領確認/状態は独立して進められます。そのため遅延した ACK は現在の状態を acknowledged にできますが、返される元の待機は timed_out_unknown のままです。その待機を satisfied に書き換えません。

受領確認は、元の send 待機の観測期限と同時またはそれ以降に受け付けられた場合に遅延とします。send 待機がなければ最初の明示的な待機と比較します。待機がなければ late は false です。後の待機は受け付け済みの遅延した受領確認で満たせますが、ack の late フラグは true のままです。稼働中は受領確認の受け付けと期限の遷移を同じ単調時計に対して直列化し、証明された順序/分類を原子的に永続コミットします。完全にコミットされた有効な ACK は、元の分類、assurance、late、不変の待機の事実を復元します。再起動後の時計が変わったという理由だけで決して降格しません。コミット前のクラッシュやその他の未コミット/未分類の時刻証拠は、acknowledged になったり合成の late フラグを提供したりできません。必須の待機を未充足、既存の pending/unknown ACK をそのままにして、未分類の証拠として保持します。手動確認は上記の証明または拒否の規則による新しいイベントであり、遡って書き換えません。UTC タイムスタンプは診断専用です。繰り返し待機しても新たなネイティブ送信は行いません。

## 予算と制限

デフォルトの予算は宛先ごとに 30 秒です。CLI は、先頭のゼロ、符号、空白、小数点、指数を含まない ASCII の 10 進整数 1 から 60 だけを受け付けます。新しいフラグはレガシーの解析を変更しません。単調時計による合計予算は、セットアップ、事前検証、準備、作用、観測より前に開始します。その中でクリーンアップに正確に 5 秒を予約します。予算が 5 秒以下なら insufficient_budget で作用前に拒否します。観測/作用の打ち切りは開始時刻に予算を加え、5 秒を引いた時刻です。クリーンアップは開始時刻に予算を加えた限度を延ばせません。待機期限の診断はこの打ち切りを説明するもので、更新されたリモート予算ではありません。

SSH は残り時間だけを渡し、元の呼び出し側の期限を保持します。リモートハンドラーは予算をリセットしたり、UTC を使って作用を許可したりできません。残りの合計予算がクリーンアップの予約以下なら作用前に拒否します。打ち切りの境界では now >= cutoff を期限切れとします。打ち切りより厳密に前にコミットされた受領確認はその待機を満たせますが、打ち切り時刻以降のものは遅延です。作用の可能性が生じたら、タイムアウトは unknown です。再試行/フォールバックや新しい送信は許可しません。順序付き fanout は宛先ごとに固有の上限付き予算を与え、1 つのホストの予算を繰り返しません。上限内のクリーンアップ/所有リソースを保証できない実装は、その経路の対応を表明できません。

```text
safe-integer = JSON integer token, 0..9007199254740991; booleans/fractions/exponents rejected
safe-id = 1..128 UTF-8 bytes, no U+0000..001F or U+007F..009F, valid Unicode scalars
safe-generation = 1..256 UTF-8 bytes, same control/scalar rule
receipt/confirmation frame = raw strict UTF-8 JSON input, at most 4096 bytes including LF/whitespace
public handoff size = compact UTF-8 encoding of the handoff subtree, at most 8192 bytes
opt-in destination stdout frame = at most 1048576 bytes including LF/whitespace
opt-in fanout = at most 32 destinations and 34603008 total stdout bytes including LF/whitespace
duplicate JSON keys, unknown nested keys, NaN/Infinity and trailing data rejected
turn/native IDs are opaque; only correlation/epoch/wait/receipt IDs use UUID-v4 syntax
```

JSON の数値トークンは、損失を伴う解析の前に検証する必要があります。JavaScript Number が 1 と等しくても、字句の 1.0 と 1e0 は拒否します。字句の制約は handoff/handoffQuery サブツリーと非公開の受領確認/確認スキーマだけに適用し、無関係なレガシーの外側フィールドには適用しません。既存のレガシー解析と重複キー/非有限数の規則を維持します。handoff 要求があるというだけでレガシーフィールドが無効になることはありません。handoff サブツリーのサイズは正規のコンパクトな符号化で測ります（任意の空白なし、ASCII エスケープではなく UTF-8 スカラー文字、区切りはカンマ/コロン）。囲むワイヤーのサブツリー内の空白は、代わりに外側のフレーム制限に数えます。非公開の受領確認/確認の生の入力は、任意の末尾 JSON 空白と LF を含む全バイトを含めます。末尾の空白以外のデータは拒否します。改行のための追加許容量はありません。宛先/合計の制限は新しいオプトインモードだけに適用します。作用前に過剰な宛先数を拒否し、通常のオプトアウトのワイヤー/出力制限を変更しません。割り当て前に stdout を逐次制限します。上限付き集計形式はコンパクトな JSON と任意の LF です。上限内の完全な外側フレームに含まれる任意のサブツリーが不正またはサイズ超過の場合、独立して検証されたネイティブ証拠を保持し、ACK/明示的待機を拒否し、再送信しません。外側のフレーム制限を超えた場合、部分解析で成功にしてはなりません。すでに独立して検証された証拠だけを保持し、それ以外は unknown を返します。制限は切り詰め後ではなく永続化前に検査します。送信者/コレクターの通常の stdout、診断、エラー/ACK 結果、自身のジャーナルは権限やペイロードダイジェストを決して含みません。受信者のトランスクリプト/本文は読みません。上限付きメタデータ観測は、出力フィルタリングの裏に本文を返す API を隠してはなりません。

## 提案された CLI と送信ゼロの操作

これらは提案された表記であり、公開済みの Python で使えるコマンドではありません。準備は送信せずに send と同じ対象/メッセージ入力を結合します。確認はメタデータだけの非公開 stdin を受け付けます。明示的なローカル台帳初期化は、別個のオプトイン設定の前提条件であり、自動復旧動作ではありません。

```text
handoff init
handoff prepare --to TARGET --message-file PRIVATE_FILE
send --to TARGET --message-file PRIVATE_FILE --correlation-id PREPARED_UUID
send --to TARGET --request-ack
send --to TARGET --observe-delivery
send --to TARGET --wait-for delivered|acknowledged --wait-timeout SECONDS
handoff status --correlation-id UUID
handoff wait --correlation-id UUID --wait-for delivered|acknowledged --wait-timeout SECONDS
handoff confirm --receipt -
ack --receipt -
```

correlation-id がなければ、request-ack/observe-delivery/wait-for は新しい意図を自動予約します。それ以外の通常の send は変わりません。相関だけの send はベストエフォートの証拠を使い、明示的な待機を行いません。status、wait、confirm、ack、init、prepare はネイティブ送信を一切行いません。受領確認の選択子は秘密を含みません。確認の stdin は schemaVersion、ledgerEpoch、correlationId、targetGeneration と、呼び出し側の confirmed=true という申告を含みます。追加のフィールド/本文/権限を拒否し、operator_confirmed だけを記録します。フラグの非互換性と未対応経路の要件は、永続的な作用意図の前に検査します。リモート設定とホストオプションは、任意の受領確認ルーティングではなく、既存の SSH 信頼制約に従う必要があります。

ACKの証拠にはnullではない元のtargetGenerationとsubmitted submissionも必要であり、有効な受領確認を受け入れると現在の状態はacknowledgedになります。観察された注入は常にsubmitted submissionを意味します。指定する準備済みIDは、効果前の終端拒否を含む過去の実際のsend呼び出しに属していてはなりません。dry-runは最初の送信権限を消費しません。dry-runはrequest-ack、observe-delivery、wait-forと併用できず、使用法終了コード2になります。correlation-only dry-runは既に準備されたIDを使用します。

再起動したコレクターが権限の寿命に関する単調時計の連続性を証明できない場合、TTL を延長したり権限を再生成したりせず、未使用の新しい受領確認権限を保守的に失効させます。有効にコミットされた受領確認の分類/assurance/late は引き続き復元できます。認証された同一受領確認の読み取り専用重複は、明示された期限切れの例外に従います。既に試行した意図への新しい待機で予算が不足した場合、その待機だけが失敗し、送信・注入の事実は維持されます。元の意図を refused に再分類しません。reconcile アクションは状態・証拠の照合であり、新たな送信や暗黙の修復コマンドではありません。

## 確定と実装の受け入れ条件

この提案は確定前に、正確なコミットとフィクスチャの TypeScript レビューを必要とします。新しい prepare/confirm の表記、ledgerEpoch と待機の operationId フィールド、5 秒のクリーンアップ予約、数値トークン検証、復元の制限は、明示的な v0.2 の改訂であり、すでに受け入れられたりリリースされたりした機能ではありません。

フィクスチャは、ランタイムごとの任意フィールドの不在、要求コンテキストで許可される queued true の明示的待機タイムアウト、偽造されたオプトアウト handoff、不正なネイティブ対象、認証済み/不正トークン/期限切れの重複、コミット済み/コミット前/順序不明の受領確認の復旧、手動確認の拒否、元の/新しい/null 世代、秘密の反映がないこと、コンテキスト欠落の照会エラーと既知の tombstone の区別、待機履歴、欠落/復元済み/期限切れ/満杯の台帳、ユーザー指定の未知の ID、期限/フレームの境界、不正なスキーマ、SSH の保持をカバーする必要があります。厳密な SSH オプトイン検証は、handoff が拒否されても有効なネイティブスナップショットを保持する必要があります。レガシー Claude の再構築や汎用の失敗経路でそれを破棄してはなりません。完全な応答は、元の要求を認識する同じ厳密なパーサーを通じてだけトランスポートのタイムアウト/非ゼロ終了後にも保持されます。部分フレームは unknown のままです。

実装の受け入れ前に、生成側のブートストラップとコレクターの所有権/再起動、永続的な意図と容量予約、対応する各 platform/version/home でのクリーンアップ、メタデータ専用 Codex 観測、厳密なローカル/SSH タプル、送信ゼロの status/wait/ack/confirm 操作を検証します。この設計 PR はネイティブ/実動作の証拠を提供しません。Side Session と wake の実験は別の将来の作業であり、前提条件ではありません。ペアリングデバイス/Relay の重複排除とオペレーター監視を暗黙に追加しません。
