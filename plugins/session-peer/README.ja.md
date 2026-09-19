# session-peer Codex プラグイン

Python 3.10+ で `session-peer[mcp]` をインストールし、Codex ホストの PATH 上で `session-peer-mcp` を利用可能にします。リポジトリのチェックアウトから `codex plugin marketplace add /absolute/path/to/session-peer` を実行し、次に `codex plugin add session-peer@session-peer` を実行します。チェックアウトには `.agents/plugins/marketplace.json` が含まれています。このマニフェストは、同梱されている `.mcp.json` stdio サーバーを登録します。

サーバー環境の `SESSION_PEER_MCP_CONFIG` に絶対パスのポリシーファイルを設定します。これが設定されていない場合、ローカルの一覧取得のみが許可されます。[MCP のセットアップとポリシー](../../docs/ja/mcp.md) を参照してください。このバンドルをインストールしても、Python の依存関係がインストールされたり、送信権限が付与されたりすることはありません。
