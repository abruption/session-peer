# session-peer ドキュメント

英語版が正本です。韓国語、日本語、簡体字中国語版は同じナビゲーションと規範的な
動作を維持します。目的に合う最短のガイドから始めてください。プロトコルと検証記録は
レビュー資料であり、別のインストール経路ではありません。

## ユーザー

- [CLIリファレンス](cli-reference.md)はローカル・SSHでの検出、送信、JSON、更新、制限を説明します。
- [診断と返信](diagnostics.md)は正確な送信状態と安全なトラブルシューティングを説明します。
- [複数のCodexホーム](multi-home-list.md)、[明示的なwake](wake.md)、[Antigravity](antigravity.md)はオプションのエージェントワークフローを扱います。

## AI支援セットアップと統合

- [AIアシスタントガイド](ai-assistant-guide.md)は、エージェントにセットアップや検証を任せるための制限付き引き継ぎ文書です。
- [MCP](mcp.md)と[エージェントアダプター](agent-adapters.md)はオプション統合とポリシー境界を説明します。

## ペアデバイスと運用者

- [ペアデバイス](paired-devices.md)は、直接またはホスト型のエンドツーエンド暗号化リレーを使うユーザー向け経路です。
- [リレー認証](relay-auth.md)、[ライフサイクルと復旧](relay-lifecycle.md)、[ウォッチドッグ](relay-watchdog.md)、[エッジポリシー](relay-edge-policy.md)は運用者向け資料です。
- [デプロイ資料](../../deploy/README.md)は再利用可能な例とAbruption KRの運用参照を分離します。

## 開発と履歴

- [v1互換性契約](compatibility-v1.md)はstable、versioned、migrated、internal、experimentalなsurfaceを分類します。
- [エージェント転送アーキテクチャ](architecture/agent-transports.md)と[リレー開発計画](relay-development-plan.md)は実装境界を説明します。
- [リリースノート](releases/v1.0.0-beta.1.md)は公開済み動作を説明し、[検証記録](validation/69-rc.md)は範囲付きの証拠と制限を保存します。
- 完了したrelay69プロトタイプのソースは、固有の回帰テストを製品リレースイートへ移した後に削除しました。旧プロトタイプコードはGit履歴に残ります。
