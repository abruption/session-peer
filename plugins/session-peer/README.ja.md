# session-peer Codex プラグイン

Python 3.10+ で `session-peer[mcp]` をインストールし、CodexホストのPATHから `session-peer-mcp` を実行できるようにします。リポジトリのチェックアウトディレクトリで `codex plugin marketplace add /absolute/path/to/session-peer` を実行し、続けて `codex plugin add session-peer@session-peer` を実行します。チェックアウトには `.agents/plugins/marketplace.json` が含まれています。プラグインのマニフェストが、同梱の `.mcp.json` stdioサーバーを登録します。

サーバー環境の `SESSION_PEER_MCP_CONFIG` にポリシーファイルの絶対パスを設定します。設定がない場合は、ローカルセッションの一覧表示のみが許可されます。[MCP のセットアップとポリシー](../../docs/ja/mcp.md) を参照してください。このバンドルをインストールしても、Pythonの依存関係がインストールされたり、送信権限が付与されたりすることはありません。
