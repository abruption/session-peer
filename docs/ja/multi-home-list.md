# 複数ホームにまたがるCodexセッション

`session-peer list --json` は、既知のホーム全体にわたるClaudeおよび保存されたCodexセッションを含めます。`--agent codex` はCodexに絞り込み、`--agent claude` はCodexのインベントリ収集をスキップします。`--codex-home` を指定しない場合、接続先での候補は以下のとおりです:

1. デフォルトの `~/.codex`。
2. 空でない場合の `CODEX_HOME`。
3. macOSの `~/Library/Application Support/orca/codex-accounts/*/home` 直下のアカウントホーム。
4. 絶対パス（または `~/`）のホームパスのJSON配列である `SESSION_PEER_CODEX_HOMES`。

再帰的なファイルシステムスキャンやプロセス/認証情報の検査はありません。明示的な `--codex-home PATH` は、自動インベントリ収集や無関係な設定エラーをバイパスします。DBは読み取り専用で開かれます。send/wakeは既存のより厳密なホーム解決を維持します。一覧表示はアクティブなライターを選択しません。

## 行と探索

各Codex行には、正規の `codexHome` および絶対パスの `stateDb` パスが含まれます。識別基準はホスト + 正規ホーム + UUIDです。異なるホーム内の同一UUIDは分離されたままになります。同じホームのシンボリックリンクエイリアスは重複排除され、それらの `sources` はマージされます。Codex行は `updatedAt` の降順、次にホーム、UUIDの順でソートされます。`--all` は各ホームで個別にアーカイブされたレコードを含めます。人間向けの出力では、各行の横にホームが表示されます。

例（既存のschemaVersion 1エンベロープ内）:

```json
{
  "sessions": [
    {"agent": "codex", "id": "same-uuid", "codexHome": "/home/me/.codex", "stateDb": "/home/me/.codex/state_5.sqlite"},
    {"agent": "codex", "id": "same-uuid", "codexHome": "/home/me/custom", "stateDb": "/home/me/custom/state_5.sqlite"}
  ],
  "discovery": {
    "codex": {
      "status": "ok",
      "homes": [
        {"codexHome": "/home/me/.codex", "stateDb": "/home/me/.codex/state_5.sqlite", "sources": ["default"], "status": "ok", "sessionCount": 1},
        {"codexHome": "/home/me/custom", "stateDb": "/home/me/custom/state_5.sqlite", "sources": ["configured"], "status": "ok", "sessionCount": 1}
      ]
    }
  }
}
```

従来のトップレベルの `codexHome` は、インベントリ収集によってエラーなしで正確に1つの候補ホームが特定された場合にのみ残り、複数のホームが存在する場合は省略されます。利用側はスレッドUUIDから推測するのではなく、その行のホームを使用する必要があります。

ホーム診断では `status: ok | absent | error` を使用します。オプションのデフォルトまたはOrca DBが存在しないことはエラーではありません。`--codex-home`、`CODEX_HOME`、または `SESSION_PEER_CODEX_HOMES` によって明示的に指定されたホームが存在しない場合は、それがオプションの候補のエイリアスであってもエラーになります。正常に読み取られた空のDBは、セッション数0の `ok` になります。

エラーには安定したコードが含まれます: `state_db_missing`、`state_db_not_regular`、`permission_denied`、または `state_db_read_failed`（破損/非互換のDBを含む）。インベントリ収集の失敗は `discovery.codex.errors` に表示され、`source`、`error`、オプションの `path`、およびコード `home_resolution_failed`、`candidate_enumeration_failed`、または `invalid_home_configuration` が含まれます。無効な追加ホーム設定は全体として拒否されますが、デフォルト/環境変数/Orcaの結果は存続します。

いずれかの障害が発生すると、Codexの集約ステータスは `error` に、コマンドは `ok: false`、終了コード1に設定されますが、他のホームおよびClaudeの行は保持されます。読み取り可能なDBがなく、エラーもない場合、自動探索は `not_installed`、空のセッション、終了コード0を報告します。これは以前のデフォルトDB不在エラーからの変更点です。探索の成功は、アクティビティ、受領、またはキュー消費の証拠ではありません。

## SSH、send、MCP

SSH経由でストリーミングされたソースは、そのホスト自身のユーザー/環境を使用してそのホスト上のホームを列挙します。`--host` の繰り返し指定は既存の順序付きレスポンス配列を保持し、1つの失敗によって他のホストの結果が破棄されることなく全体が終了コード1になります。

選択した行のホームを明示的に使用してください:

```sh
session-peer list --host user@worker --agent codex --json
session-peer send --host user@worker --codex-home '/path/from/selected/row' --to codex:<uuid> 'message'
```

MCPは引き続き設定されたホームを明示的に渡します。このCLIのデフォルト動作によってMCPに他のホームへのアクセス権が付与されることはありません。追加のホーム用には別の認可された送信先を作成してください。Python 3.9スタンドアロンの依存関係は変更されません。
