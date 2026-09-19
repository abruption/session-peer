# オプションの Codex MCP 統合

Python 3.10 以降でインストールします: `pipx install 'session-peer[mcp]'`（または隔離された venv にエクストラをインストール）。依存関係のない Python 3.9 CLI および `install.sh` は引き続きサポートされます。シェルインストーラーは MCP の依存関係をインストールしません。Python 3.9 では、MCP エントリポイントが Python 3.10+ が必要である旨を報告します。

`session-peer-mcp --config /absolute/path/policy.json` を起動します。ポリシーがない場合、サーバーは起動環境の Codex ホームを使用して、ローカルの一覧取得のみを許可します。ポリシーを指定するとデフォルトが置き換えられます。例:

```json
{
  "schemaVersion": 1,
  "destinations": {
    "local": {
      "agents": ["claude", "codex"],
      "capabilities": ["list"],
      "codexHome": "/Users/me/.codex"
    },
    "worker": {
      "host": "ubuntu@worker.example.ts.net",
      "agents": ["claude", "codex"],
      "capabilities": ["list", "send"],
      "codexHome": "/home/ubuntu/.codex"
    }
  }
}
```

実際のユーザー名と SSH 送信先、設定済みの鍵、および known_hosts を使用してください。このファイルにパスワードを含めてはなりません。すべての Codex 送信先は、その送信先での絶対パスのホームを固定する必要があります。ホームを追加する場合は、個別の送信先 ID を追加してください。信頼できないプロセスによる変更からポリシーを保護してください。SSH 設定はオペレーターが管理する状態を維持します。

`codex mcp add session-peer -- /absolute/path/session-peer-mcp --config /absolute/path/policy.json` を使用して登録するか、リポジトリの `plugins/session-peer` バンドルを使用します: `codex plugin marketplace add /absolute/path/to/session-peer`、続いて `codex plugin add session-peer@session-peer`。このプラグインは PATH から `session-peer-mcp` を起動し、環境変数に設定されている場合は `SESSION_PEER_MCP_CONFIG` を読み取ります。最初に Python エクストラをインストールしてください。Python パッケージをインストールしても、既存の Codex 設定が変更されることはありません。

## ツールとパーミッション

- `list_sessions(destination="local", agent=null, include_inactive=false)` は CLI の構造化された一覧を返します。Agent は `claude` または `codex` です。省略した場合は許可されたエージェントを一覧表示します。
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` は、`send` が明示的に許可されている場所にのみ 1 回送信します。Target は Claude 名/PID、`codex:<UUID>`、または設定されたホストとホームに正確に一致する Reply-To URI です。

MCP ツールのアノテーションは、一覧取得を読み取り専用、送信を非冪等としてマークします。必要に応じてホストクライアントのツール承認を設定してください。サーバーポリシーは宛先を個別に制限し、サンドボックスやホストの承認をバイパスすることはありません。別のホスト名が同じマシンに解決される場合でも、Reply-To URI 内の SSH エイリアスはポリシーと完全に一致する必要があります。そうでない場合は、直接ターゲットと設定済みの宛先 ID を使用してください。

応答は MCP の structuredContent と text の両方で CLI の JSON フィールドを保持します。一覧取得の部分的な失敗では、検出されたセッションを保持し、isError を設定します。キューへの送信は消費ではありません。結果が unknown の送信を自動的に再試行しないでください。リモート送信後にキャンセルやトランスポートの切断が発生する可能性があります。received/status/wait ツールはありません。[明示的な wake](wake.md) には、`send` に加えて個別の `wake` ケーパビリティが必要です。wake を有効にする場合は、クライアントツールのタイムアウトを 150 秒に設定してください。

共有 MCP プロセスは、呼び出し元のスレッドを確実には識別できません。サーバーを起動したセッションに帰属させるのではなく、メッセージは `session-peer MCP (caller session unavailable)` と識別し、Reply-To を省略します。認証のためにこのヘッダーに依存しないでください。メッセージ本文はシェルコマンド文字列ではなく stdin 経由で渡されます。通常の CLI の制限が依然として適用されます。

## 検証

MCP エクストラの有無の両方で `python -m unittest discover -s tests -v` を実行します。オプションのテストでは実際の stdio MCP サーバーを起動し、モデルの認証情報なしで初期化、スキーマ、ポリシー拒否、および CLI の部分的な失敗を検証します。wheel と sdist の両方のインストールをテストしてください。実環境チェックでは Codex バージョン、OS、およびホストの承認設定を記録する必要があります。UDS アクセスは環境依存であり、承認のバイパスを約束するものではありません。メッセージには専用のテストセッションを使用してください。

公式リファレンス: [Codex MCP](https://developers.openai.com/codex/extend/mcp), [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)。

### 非対話型クライアントの承認

Codex `exec` は、サーバーポリシーが許可している場合でも「requires approval, but approval policy is never」として send ツールを拒否することがあります。`approval_mode="auto"` は無条件の承認ではありません。非対話型統合を明示的に承認するオペレーターは、制限された宛先ポリシーと併せて、その特定の MCP サーバー/ツールに対して `mcp_servers.session_peer.tools.send_message.approval_mode="approve"` を設定できます。プラグインがこの設定を有効にすることはありません。対話型クライアントは、代わりに通常の承認プロンプトを使用できます。テストクライアントがこの承認設定を無関係なサーバーやツールにコピーしてはなりません。
