# session-peer のリリース

GitHub Release を公開すると `.github/workflows/publish.yml` が対象タグの wheel と sdist をビルドし、Trusted Publishing で PyPI にアップロードします。ドラフトは公開しません。準備、最終承認、公開、検証を分けてください。保護された `main` には最新の PR と、全プラットフォームの Python、ドキュメント、シェル、パッケージ、MCP、Relay、control、統合、依存関係監査を含む `release gate` が必要です。ライブ OAuth、エージェント ACK、運用 Relay の状態は別の運用証拠です。

## 安定版 v1.0.0 の条件

レビュー済み RC4 ランタイムは 5 ホストの `rc4-rerun-02` で 14,436.65 秒の `complete`、公開 health 241/241、probe 147/147、送信 21/21、Relay 再起動から 3.182 秒で復旧しました。独立 ACK は 20/21 です。元の T120 Windows native Claude ACK は TUI 終了のため未確認ですが、同じ経路の別の単発検査では正確な ACK を確認しました。ユーザーは #164 でこの運用上の例外を明示的に受け入れました。元の結果を 21/21 に書き換えないでください。#161 の外部停滞箇所は未確定で、緩和は根本原因の修復ではありません。RC4 からランタイム動作を変えず、正確な `main` の CI を再実行する必要があります。

Python/PyPI 版は `1.0.0`、Git タグと GitHub Release は `v1.0.0` です。プレリリースにせず Latest にします。通常のアップグレードと standalone の更新通知は v0.9.2 ではなく v1.0.0 を選択し得ます。プラグイン版は独立です。コアは Python 3.9+ で依存関係なし、MCP は 3.10+、Relay 受信側/サーバーは Unix または WSL の 3.11+ が必要です。パッケージ公開はホスト型 Relay/OAuth の可用性を保証しません。サービス起動の macOS・Linux 受信側 PATH には対象 TUI の `codex` ディレクトリが必要です（`codexBin` は WSL 専用）。Relay ログインは期限切れになり、再承認が必要な場合があります。

レガシー URL 用のルート `cc_peer.py` は残し、wheel と sdist から除外します。4 言語の README、セキュリティポリシー、安定版ノート、Relay 文書、任意のランタイムは含めます。資格情報、デバイス鍵、認証 DB、replay 状態、ブラウザプロファイル、ローカル証拠、会話は含めません。

## Trusted Publisher

PyPI プロジェクト `session-peer` は GitHub `abruption/session-peer` の `publish.yml` と環境 `pypi` に対応します。長期 PyPI 資格情報はリポジトリに置きません。過去の成功だけに頼らず、公開前に現在の設定を確認してください。

## 準備と検証

1. v1.0.0 マイルストーンと #152 の文書ゲートを整理し、#164 の運用例外を記録します。#161 は原因未確定の v1.0.1 監視として残します。RC4 との差分は版、生成物、文書、テストだけにします。`release/0.9.x` を `main` にマージしません。
2. `session_peer.__version__ == "1.0.0"`、生成した `session_peer.py`、4 言語 README のインストールコマンド、sdist 内の 4 言語安定版ノートを確認します。ローカル一式、PR の `release gate`、マージ後の正確な `main` CI を通します。
3. 正確な候補から `python3 -m build` で wheel と sdist を作り、内容を検査します。各アーカイブを別のクリーン環境にインストールし、`session-peer --version`、空のホームの JSON `list`、`pip check`、Relay/MCP 拡張と help を確認します。ライブモデルへの送信は含みません。
4. CI 成功後のみマージし、`main` の正確なコミット、版、ノートを再確認します。PyPI にまだ `1.0.0` ファイルがないことも確認します。

## ドラフトと公開

準備 PR をマージした後にドラフトを作ります。squash/merge でリリースコミットは変わります。公開済みタグは移動しません。

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.0 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.0" \
  --notes-file docs/releases/v1.0.0.md \
  --draft --latest
```

タグ、対象、タイトル、ノート、ドラフト、安定版、Latest の意図を確認します。ドラフトは公開の承認ではありません。

## 公開

**公開直前にユーザーの最終承認が必要です。** 公開コマンド:

```bash
gh release edit v1.0.0 \
  --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

ワークフローはタグ/版/保護された main、再現可能な wheel・sdist、アーカイブ・インストール・監査、SHA256SUMS と provenance を確認してから OIDC でアップロードします。既存 PyPI ファイルはエラーです。失敗後に変更した成果物を再アップロードしません。`1.0.0` の部分公開やハッシュ不一致なら昇格を止め、証拠を保存し、レビューした新しい版（通常 `1.0.1`）で修正します。yank しても版は再利用できません。

## 公開後の検証

1. 正確なタグとコミットの `publish.yml` 成功を確認します。PyPI の wheel と sdist のハッシュをワークフローの候補・provenance と照合し、各々を新しい環境にインストールします。
2. 版、空ホームの JSON `list`、Relay/MCP、`pip check`、GitHub の安定版/Latest、通常の更新選択を確認します。ホスト型 Relay は別途検証し、queued を ACK と見なしません。
3. 証拠を記録してから v1.0.0 マイルストーンを閉じます。全機器への導入や運用サービスの再起動は別の運用判断です。
