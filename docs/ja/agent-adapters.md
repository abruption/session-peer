# 内部エージェントアダプターの開発

これはソース拡張ガイドであり、外部プラグインのインストールインターフェースではありません。契約のバージョニング、互換性、結果のセマンティクス、および信頼境界については、[アーキテクチャ決定](architecture/agent-transports.md)を参照してください。

アダプターは `AgentAdapter` をサブクラス化し、一意の小文字の `name` を宣言し、`list(context)` および `submit(context, text)` を実装します。`main()` が実行される前に `AGENTS.register(...)` で明示的に登録してください。SSH経由で動作する必要がある場合は、その実装をスタンドアロンソース内に保持してください。基本的な新しいアダプターのためにCLIルーターやSSHディスパッチャーの変更は必要ありません。

決定論的な最小の例（テスト専用）:

```python
class ExampleAdapter(AgentAdapter):
    name = "example"
    capabilities = AgentCapabilities()  # list/send; no wake/wait/ack

    def list(self, context):
        return {"sessions": [{"agent": self.name, "id": "one", "status": "idle"}],
                "discovery": {"status": "ok"}}

    def submit(self, context, text):
        target = self.identity(context.options.to, context)
        return {"ok": True, "target": {"id": target.identifier},
                "status": "validated" if context.options.dry_run else "submitted",
                "submitted": not context.options.dry_run,
                "consumptionConfirmed": False}

AGENTS.register(ExampleAdapter())
```

この例には実際の受信箱がありません。実際の配信アダプターとして出荷しないでください。テスト専用の `tests/fixtures/agent_adapter.py` が契約テストで使用される実行可能な例を提供しており、公開ディストリビューションからは除外されています。

- `list` は `sessions` と、`status` が `ok`、`error`（`error` テキストを含む）、または `not_installed` である `discovery` オブジェクトを返します。すべての行がそのエージェントを識別します。ネイティブの識別フィールドを保持してください。異なる行レイアウト用に `display_row`/`render` を実装します。Codexはさらに既存のトップレベルホームメタデータを保持します。
- `submit` は検証済みのラップされたメッセージを厳密に1回受け取ります。ネイティブの副作用の前にドライランを尊重してください。ネイティブの送信事実を返します。ソケット/キューの受領から確認応答を推論しないでください。既知の送信後のネイティブの障害は、そのIDと部分的な結果を保持しなければなりません。
- `identity` および `target` はネイティブのアイデンティティとCLI/Reply-Toターゲットを変換します。デフォルトは `name:identifier` です。Claudeはプレフィックスのない名前/PIDを保持します。
- `diagnose`、`diagnostic_text`、`listing_notes`、`submission_text`、`remote_submission`、および `remote_options` は、共通のルーティングを変更することなく、証拠および既存の出力互換性を特化させます。引数オプションは引き続きパーサーで明示的に宣言される必要があります。エージェントがシェルコードを挿入することはできません。
- 機能の真偽値は実装のサポート状況のみを報告します。falseの機能は送信前に失敗します。wakeを提示してもネイティブのランタイムチェックやMCP認可がスキップされることはありません。wait/ackはこのバージョンにはCLI実装がありません。

MCPは明示的に認可された送信先とエージェントのみを許可します。ソースの登録だけでリモート/送信権限が付与されることは決してありません。オプションの依存関係はコアのインポートパスの外部に留める必要があります。バックエンドの依存関係を追加するには個別のパッケージング決定が必要です。公開外部読み込みおよびインストールは実装されていません。

オプションのMCP SDKがない状態とある状態の両方で、既存のスイートと共有契約テストを実行してください。また、wheelとsdistを個別にビルド/インストールし、分離されたスタンドアロンインストーラーテストを実行してください。新しい契約カバレッジには本番セッションではなくフィクスチャトランスポートを使用してください。
