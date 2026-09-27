# session-peer のリリース

GitHub Release を公開すると `.github/workflows/publish.yml` が対象タグの wheel と sdist をビルドし、Trusted Publishing で PyPI にアップロードします。ドラフトは公開しません。準備、最終承認、公開、検証を分けてください。保護された `main` には最新の PR と、全プラットフォームの Python、ドキュメント、シェル、パッケージ、MCP、Relay、control、統合、依存関係監査を含む `release gate` が必要です。ライブ OAuth、エージェント ACK、運用 Relay の状態は別の運用証拠です。

## v1.0.0 の証拠と v1.0.1 メンテナンス条件

レビュー済み RC4 ランタイムは 5 ホストの `rc4-rerun-02` で 14,436.65 秒の `complete`、公開 health 241/241、probe 147/147、送信 21/21、Relay 再起動から 3.182 秒で復旧しました。独立 ACK は 20/21 です。元の T120 Windows native Claude ACK は TUI 終了のため未確認ですが、同じ経路の別の単発検査では正確な ACK を確認しました。ユーザーは #164 でこの運用上の例外を明示的に受け入れました。元の結果を 21/21 に書き換えないでください。#161 の外部停滞箇所は未確定で、緩和は根本原因の修復ではありません。これは v1.0.0 の履歴上の証拠であり、v1.0.1 の変更を検証した結果ではありません。

Python/PyPI 版は `1.0.1`、Git タグと GitHub Release は `v1.0.1` です。プレリリースにせず Latest にします。通常のアップグレードと standalone の更新通知は v1.0.0 ではなく v1.0.1 を選択し得ます。プラグイン版は独立です。コアは Python 3.9+ で依存関係なし、MCP は 3.10+、Relay 受信側/サーバーは Unix または WSL の 3.11+ が必要です。パッケージ公開はホスト型 Relay/OAuth の可用性を保証しません。サービス起動の macOS・Linux 受信側 PATH に対象 TUI の `codex` ディレクトリを追加するか、運用者管理の絶対 `codexBin` パスを設定してください。Relay ログインは期限切れになり、再承認が必要な場合があります。#161 は原因未確定のまま開きます。

レガシー URL 用のルート `cc_peer.py` は残し、wheel と sdist から除外します。4 言語の README、セキュリティポリシー、安定版ノート、Relay 文書、任意のランタイムは含めます。資格情報、デバイス鍵、認証 DB、replay 状態、ブラウザプロファイル、ローカル証拠、会話は含めません。

## Trusted Publisher

PyPI プロジェクト `session-peer` は GitHub `abruption/session-peer` の `publish.yml` と環境 `pypi` に対応します。長期 PyPI 資格情報はリポジトリに置きません。過去の成功だけに頼らず、公開前に現在の設定を確認してください。

## 準備と検証

1. v1.0.1 マイルストーンで完了した修正を確認し、#161 は原因未確定の監視として開いたままにします。v1.0.0 との差分と v1.0.1 ノートを確認します。`release/0.9.x` を `main` にマージしません。
2. `session_peer.__version__ == "1.0.1"`、生成した `session_peer.py`、4 言語 README のインストールコマンド、sdist 内の 4 言語安定版ノートを確認します。ローカル一式、PR の `release gate`、マージ後の正確な `main` CI を通します。
3. 正確な候補から `python3 -m build` で wheel と sdist を作り、内容を検査します。各アーカイブを別のクリーン環境にインストールし、`session-peer --version`、初期化済みエージェントホームの JSON `list`、`pip check`、Relay/MCP 拡張と help を確認します。明示的に空の Codex ホームは `state_db_missing` で失敗する必要があり、インストール失敗ではありません。ライブモデルへの送信は含みません。
4. CI 成功後のみマージし、`main` の正確なコミット、版、ノートを再確認します。PyPI にまだ `1.0.1` ファイルがないことも確認します。

## ドラフトと公開

準備 PR をマージした後にドラフトを作ります。squash/merge でリリースコミットは変わります。公開済みタグは移動しません。

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.1 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.1" \
  --notes-file docs/releases/v1.0.1.md \
  --draft --latest
```

タグ、対象、タイトル、ノート、ドラフト、安定版、Latest の意図を確認します。ドラフトは公開の承認ではありません。

## 公開

**公開直前にユーザーの最終承認が必要です。** 公開コマンド:

```bash
gh release edit v1.0.1 \
  --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

ワークフローはタグ/版/保護された main、再現可能な wheel・sdist、アーカイブ・インストール・監査、SHA256SUMS と provenance を確認してから OIDC でアップロードします。既存 PyPI ファイルはエラーです。失敗後に変更した成果物を再アップロードしません。`1.0.1` の部分公開やハッシュ不一致なら昇格を止め、証拠を保存し、レビューした新しい版（通常 `1.0.2`）で修正します。yank しても版は再利用できません。

## 公開後の検証

1. 正確なタグとコミットの `publish.yml` 成功を確認します。PyPI の wheel と sdist のハッシュをワークフローの候補・provenance と照合し、各々を新しい環境にインストールします。
2. 版、初期化済みエージェントホームの JSON `list`、Relay/MCP、`pip check`、GitHub の安定版/Latest、通常の更新選択を確認します。ホスト型 Relay は別途検証し、queued を ACK と見なしません。
3. 証拠を記録し、#161 を明示的に移すか解決した場合だけ v1.0.1 マイルストーンを閉じます。全機器への導入や運用サービスの再起動は別の運用判断です。
