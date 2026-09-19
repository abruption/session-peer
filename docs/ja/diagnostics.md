# 診断と返信先アドレス契約

`session-peer doctor` は、対象セッションを保持するマシンを検査します。
`--host` を指定すると、同じ標準ライブラリスクリプトがSSH経由でそのホスト上で実行されるため、パス、ユーザー、プロセス、ソケット、データベースが適切なセキュリティ境界内で評価されます。

このコマンドは読み取り専用です。Claudeの受信箱への接続、Codexキュー項目の送信、任意のファイルシステムルートのスキャン、権限の変更、SSHホストキーの登録、エージェント設定の変更は行いません。

## JSONモデル

Doctorは共通のレスポンスエンベロープを使用します。`ok` は診断コマンドが実行されたかどうかを示し、すべてのオプションエージェントがインストールされていることや利用可能であることを意味するものではありません。
そのためにはネストされたステータスを使用してください:

```json
{
  "schemaVersion": 1,
  "ok": true,
  "host": "worker.example.ts.net",
  "command": "doctor",
  "status": "partial",
  "claude": {
    "status": "inbox_unavailable",
    "sessionsDir": "/home/alice/.claude/sessions",
    "records": 1,
    "invalidRecords": 0,
    "aliveSessions": 1,
    "availableInboxes": 0,
    "checks": [
      {"status": "warning", "code": "inbox_unavailable", "message": "..."}
    ]
  },
  "codex": {
    "status": "available",
    "selectedHome": "/home/alice/.codex",
    "homeSource": "default",
    "executable": "/home/alice/.local/bin/codex",
    "homes": [
      {
        "codexHome": "/home/alice/.codex",
        "stateDb": "/home/alice/.codex/state_5.sqlite",
        "status": "available",
        "code": "state_db_readable",
        "sessionCount": 12
      }
    ],
    "checks": []
  },
  "capabilities": {
    "replyObservation": {
      "status": "unsupported",
      "reason": "no_cross_agent_acknowledgement_api",
      "claudeLocalIdleNotice": "native_claude_only",
      "automatedWait": false
    }
  }
}
```

トップレベルの `status` は、両方のエージェントトランスポートが利用可能な場合は `healthy`、片方が利用可能な場合は `partial`、どちらも利用できない場合は `issues_found` になります。エージェントステータスには以下が含まれます:

| ステータス | 意味 |
| --- | --- |
| `available` | 必要なローカルの証拠が読み取り可能で存在しています。Claudeの受信箱の検証は、実際の送信が行われるまではファイルシステム上のみです。 |
| `unavailable` | 稼働中の使用可能なセッションが見つかりませんでした。 |
| `inbox_unavailable` | 稼働中のClaudeプロセスが記録されていますが、利用可能な受信箱がありません。 |
| `missing_tool` | 接続先にCodex実行可能ファイルが存在しません。 |
| `missing_home` | 設定されたセッションディレクトリまたはCodex state DBが存在しません。 |
| `wrong_home` | 設定されたパスのファイルタイプが正しくありません。 |
| `permission_denied` | 接続先のOSユーザーに必要なパスまたはレコードを検査する権限がありません。 |
| `unsupported` | 既知のファイルが存在しますが、そのスキーマはサポートされていません。 |
| `unknown` | 検査によってより具体的な状態を証明できませんでした。 |

コード値は安定した機械可読な理由です。メッセージは人間向けであり、スキーマの変更なしに、より具体的になる場合があります。

## 返信ルートの確認

`doctor --host worker --check-return-route` は、検出された送信元に戻るSSHコマンドをテストするよう `worker` に要求します。`--reply-to USER@HOST` はその検出されたアドレスを上書きします。このチェックでは、バッチモード、パスワードおよびキーボードインタラクティブ認証の無効化、厳格なホストキーチェック、ホストキー更新の無効化を適用した固定の `true` コマンドを使用します。認証情報を使って再試行したり、ポリシーを緩和したりすることは決してありません。

```json
{
  "returnRoute": {
    "status": "failed",
    "transport": "ssh",
    "host": "alice@origin.example.ts.net",
    "reason": "authentication_failed",
    "sshUser": "alice",
    "sshUserSource": "explicit"
  }
}
```

返信ステータスは `verified` または `failed` です。失敗の理由には、`return_host_unavailable`、`ssh_executable_missing`、`authentication_failed`、`host_key_failed`、`timeout`、`transport_failed`、`remote_command_failed` があります。現在のマシン上の現在のユーザーに対する返信先アドレスは、検証済みのローカルルートに正規化され、SSHを起動することはありません。

## 構造化Reply-To

メッセージには、非アクティブでバージョン管理されたURIと、それに続く従来のコマンドが含まれるようになりました:

```text
Reply-To: session-peer://v1/reply?agent=claude&session=api-worker&transport=ssh&host=alice%40origin
Reply: python3 /path/to/session_peer.py send --host alice@origin --to api-worker --no-reply-to
```

URIは `send --to URI` として渡すことができます。バージョン、フィールド名、重複フィールド、エージェント、トランスポート、UUID、ホスト、制御文字、および競合するCLIルーティングフラグは、探索やディスパッチの前に検証されます。その内容がシェル構文として解析されることはありません。フィールドは以下のとおりです:

| フィールド | 要件 |
| --- | --- |
| `agent` | 必須: `claude` または `codex`。 |
| `session` | 必須のセッション名/PID、または完全なCodex UUID。 |
| `transport` | 必須: `local` または `ssh`。 |
| `host` | `ssh` の場合のみ必須。判明している場合はSSHユーザーを含みます。 |
| `codexHome` | Codexにおいて送信者がアクティブに設定されたホームを識別できる場合は省略可能。 |

送信JSONには、送信メッセージ内に配置されたルートを示す `replyRoute` が含まれます。ローカルルートは `verified` となり、SSHルートはオプトインのdoctorプローブが成功するまで、理由 `reverse_ssh_not_checked` を伴う `unverified` となります。`--to` で構造化アドレスを使用する場合、`addressResolution` には選択されたトランスポートおよび任意の `ssh_self` 正規化が記録されます。

## 一般的なwaitが存在しない理由

Claude Codeは、メインのClaude会話が別のローカルClaudeセッションを監視するためのネイティブなワンショットの `notify_when_idle` サブスクリプションを文書化しています。同じドキュメントでは、これをそのマシン上のセッションに限定しており、サブエージェント、エージェントチームのチームメイト、およびそのマシン外のセッションは除外されています。Codexキューの送信も、session-peerを介したエージェント間の確認応答を公開していません。

結果として、移植性のある `--wait` は、変更可能なトランスクリプトから完了を推論する必要があります。新しいトランスクリプトイベントは別のリクエストに属している可能性があり、イベントが見つからない場合は、保留中の入力、オフラインのセッション、変更されたストレージ形式、または未完了のターンを意味する可能性があります。session-peerは、誤った確認応答を返す代わりに、この機能を `unsupported` として報告します。完了ワークフローについては、要件と関連付けトークンをメッセージに含め、対象に対してその `Reply-To` URIに新しいメッセージを送信するよう依頼してください。

参考資料: [Claude Codeのメッセージ配信](https://code.claude.com/docs/en/cross-session-messaging#message-delivery)、
[アイドル通知](https://code.claude.com/docs/en/cross-session-messaging#get-a-notice-when-another-session-goes-idle)、
および[セッション受信箱ソケット](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket)。

## listの探索結果

`list` はデフォルトで両方のエージェントを対象とします。`--agent claude|codex` は片方を選択します。
`discovery` オブジェクトは、要求された各エージェントを報告します。Claudeは `ok`/`error` を保持し、Codexは `ok`、`not_installed`、または `error` に加えてホームごとの診断を報告します。
失敗した場合でも成功した行は保持されますが、`ok=false`、トップレベルのエラーサマリー、および終了コード1が設定されます。Codexが自動インストールされていない場合は `not_installed` となり、終了コード0の空の結果になります。明示的に設定されたホームが存在しない場合はエラーのままです。
Claudeのセッションディレクトリが存在しない場合は空の結果となり、読み取り不可能なディレクトリはエラーになります。SSHは部分的な結果と重複指定されたホストのエンベロープを保持します。
すべての行に `agent` 識別子があります。候補の探索、メタデータ、および権限境界については、[マルチホーム一覧](multi-home-list.md)を参照してください。

## CLIの入力および出力の選択

結果エンベロープを取得するには、list/send/doctor/updateで `--output-format json` を使用します。`--json` は引き続きエイリアスです。`--output-format text` はデフォルトの人間向け出力です。
これらのオプションは、送信本文をJSONとして解釈することはありません。`send --message TEXT`（または `-m TEXT`）、従来の引数位置によるメッセージ、または標準入力（`--message -`）を使用してください。
矛盾する出力フラグは使用法エラー（標準エラー出力、終了コード2）になります。競合する本文ソースは、標準入力の読み取りやディスパッチの前に失敗し、選択された結果形式と終了コード1が返されます。既存のCLI、SSH、およびMCPの送信/受領セマンティクスは変更されません。
