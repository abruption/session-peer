# session-peer のリリース

GitHub Release を公開すると `.github/workflows/publish.yml` が固定資産を検証し、環境の承認後に wheel と sdist を Trusted Publishing で PyPI にアップロードします。ドラフトは公開しません。準備、最終承認、公開、検証を分けてください。保護された `main` には最新の PR と、全プラットフォームの Python、ドキュメント、シェル、パッケージ、MCP、Relay、control、統合、依存関係監査を含む `release gate` が必要です。ライブ OAuth、エージェント ACK、運用 Relay の状態は別の運用証拠です。

## 不変リリースの準備（次の承認済みリリース）

2026-10-03に所有者がGitHub Immutable Releasesと `refs/tags/v*` の有効なタグルール
24408525を設定しました。迂回なしで更新・削除を禁止し、作成は許可します。
既存の `v1.0.2` は資産がなく `immutable: false` のままで、検証済み単体リリースでは
ありません。毎回設定を再確認してください。この変更は公開の準備であり公開承認ではありません。

所有者が保護された `main` の正確なタグコミットで `prepare-release.yml` を手動実行します。
ソース・参照・バージョン・祖先関係、再現ビルドとインストールを確認し、空の安定版ドラフトに
wheel、sdist、`session_peer.py`、`install.sh`、`SKILL.md`、`SHA256SUMS`、
`release-provenance.json` の七資産を証明して添付します。マニフェストは五ペイロードを対象にし、
署名された証明はマニフェストと証拠も対象にします。添付は公開しません。公開でファイルが固定され、
`publish.yml` は再ビルドや資産追加なしで固定パッケージを検証しPyPIに送ります。
PyPIのワークフローと環境の対応を維持してください。

```bash
# Set the next approved version; no tag/version is changed by this document.
release_tag=vX.Y.Z
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
# Review successful preparation, the seven draft assets, and their attestations.
# Obtain final approval before the separate publication command:
gh release edit "$release_tag" --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

検証済み単体インストール・更新には、署名ワークフロー、ソース参照・ダイジェストとホスト型
ランナーポリシーを扱う最新GitHub CLIの `gh attestation verify` が必要です。
既定で最新の検証済み不変リリースを使います。`--local-source` は隣接ソースを明示的に信頼し、
`--main` は未検証の開発コードを選択します。古いリリースや証明不足時の自動代替はありません。
検証リリース公開前はpipx/uv/pipを使ってください。実行前のインストーラー認証には
以下を使います（軽量バージョンタグが必要）。

```bash
set -eu
repo=abruption/session-peer
tag=$(gh api "repos/$repo/releases/latest" --jq \
  'if .immutable == true and .draft == false and .prerelease == false then .tag_name else error("no immutable stable release") end')
commit=$(gh api "repos/$repo/git/ref/tags/$tag" --jq '.object | select(.type == "commit") | .sha')
case "$commit" in ????????* ) ;; * ) echo "expected a lightweight release tag" >&2; exit 1 ;; esac
staging=$(mktemp -d)
trap 'rm -f "$staging/install.sh"; rmdir "$staging"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' \
  --max-filesize 262144 --max-time 30 \
  "https://github.com/$repo/releases/download/$tag/install.sh" -o "$staging/install.sh"
gh attestation verify "$staging/install.sh" --repo "$repo" \
  --signer-workflow "$repo/.github/workflows/prepare-release.yml" \
  --source-ref refs/heads/main --source-digest "$commit" \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  --deny-self-hosted-runners --format json
sh "$staging/install.sh"
```

確認したGitHub CLIの基準は2.102.0であり、全ポリシーフラグに対応する最初の版は
確定していません。オンライン証明取得には認証済みgh（`gh auth login` または `GH_TOKEN`）が
必要です。インストーラーにはリポジトリ・証明の読み取り権限だけが必要で、公開権限は不要です。
[GitHub CLI検証器のソース](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go)を参照してください。
ローカルfixtureはポリシー・順序・失敗動作の確認であり、実際の署名受理の証拠ではありません。

GitHubとPyPIの公開はそれぞれ不可逆な別の段階です。準備時とPyPI送信直前の両方で
依存関係監査を必須に維持します。その間に新たなCVEが公開されると、固定されたGitHub
リリースだけが公開され、PyPI版がない状態になり得ます。準備時の成功は現在の監査証拠では
ありません。公開ワークフローとPyPI検証が成功するまで未完了として扱い、両実行の記録と
正確な資産を保持して失敗原因を調査し、必要ならレビュー済みの新バージョンで前進修正します。
この手順は監査の迂回を許可しません。監査方針の変更には別途所有者の判断が必要です。

上限は単体8 MiB、補助資産256 KiB、メタデータ1 MiBです。置換前に認証された
マニフェスト・証明、正確なタグとバージョン、ステージ済み `--version` の成功が必要です。
SSH転送前に送信側で検証するため、オフライン宛先にはPythonだけ必要です。
検証失敗時は既存ファイルを維持します。以下のv1.0.2手順は過去の記録です。
今後は上記準備ワークフローを使ってください。


## v1.0.0 の証拠と v1.0.2 メンテナンス条件

レビュー済み RC4 ランタイムは 5 ホストの `rc4-rerun-02` で 14,436.65 秒の `complete`、公開 health 241/241、probe 147/147、送信 21/21、Relay 再起動から 3.182 秒で復旧しました。独立 ACK は 20/21 です。元の T120 Windows native Claude ACK は TUI 終了のため未確認ですが、同じ経路の別の単発検査では正確な ACK を確認しました。ユーザーは #164 でこの運用上の例外を明示的に受け入れました。元の結果を 21/21 に書き換えないでください。#161 の外部停滞箇所は未確定で、緩和は根本原因の修復ではありません。これは v1.0.0 の履歴上の証拠であり、v1.0.2 の変更を検証した結果ではありません。

Python/PyPI 版は `1.0.2`、Git タグと GitHub Release は `v1.0.2` です。プレリリースにせず Latest にします。通常のアップグレードと standalone の更新通知は v1.0.1 ではなく v1.0.2 を選択し得ます。プラグイン版は独立です。コアは Python 3.9+ で依存関係なし、MCP は 3.10+、Relay 受信側/サーバーは Unix または WSL の 3.11+ が必要です。パッケージ公開はホスト型 Relay/OAuth の可用性を保証しません。サービス起動の macOS・Linux 受信側 PATH に対象 TUI の `codex` ディレクトリを追加するか、運用者管理の絶対 `codexBin` パスを設定してください。Relay ログインは期限切れになり、再承認が必要な場合があります。#161 は原因未確定のまま開きます。

レガシー URL 用のルート `cc_peer.py` は残し、wheel と sdist から除外します。4 言語の README、セキュリティポリシー、安定版ノート、Relay 文書、任意のランタイムは含めます。資格情報、デバイス鍵、認証 DB、replay 状態、ブラウザプロファイル、ローカル証拠、会話は含めません。

## Trusted Publisher

PyPI プロジェクト `session-peer` は GitHub `abruption/session-peer` の `publish.yml` と環境 `pypi` に対応します。長期 PyPI 資格情報はリポジトリに置きません。過去の成功だけに頼らず、公開前に現在の設定を確認してください。

所有者は [2026-09-29 に PyPI の対応を確認しました](https://github.com/abruption/session-peer/issues/235#issuecomment-5882178667)。これは所有者の確認記録で、新たな PyPI UI 検査ではありません。2026-10-03 の GitHub API 確認では、`pypi` の必須レビュアーは `abruption`、自己レビューは許可され（`prevent_self_review: false`）、`v*` に一致するタグに限定したカスタムデプロイポリシーがありました。ワークフローソースではなくリポジトリの設定なので、公開前に再確認してください。

管理者によるバイパスは有効です（`can_admins_bypass: true`）。通常の環境レビューを使ってください。例外的なバイパスには所有者の明示的な承認と、理由、実行者、時刻、ワークフロー実行、タグ、コミットの記録が必要です。バイパスは承認待機が機能した証拠になりません。黙ってレビューを回避したり、バイパスが無効だと説明したりしないでください。

## 準備と検証

1. v1.0.2 マイルストーンで完了した修正を確認し、#161 は原因未確定の監視として開いたままにします。v1.0.1 との差分と v1.0.2 ノートを確認します。`release/0.9.x` を `main` にマージしません。
2. `session_peer.__version__ == "1.0.2"`、生成した `session_peer.py`、4 言語 README のインストールコマンド、sdist 内の 4 言語安定版ノートを確認します。ローカル一式、PR の `release gate`、マージ後の正確な `main` CI を通します。
3. 正確な候補から `python3 -m build` で wheel と sdist を作り、内容を検査します。各アーカイブを別のクリーン環境にインストールし、`session-peer --version`、初期化済みエージェントホームの JSON `list`、`pip check`、Relay/MCP 拡張と help を確認します。明示的に空の Codex ホームは `state_db_missing` で失敗する必要があり、インストール失敗ではありません。ライブモデルへの送信は含みません。
4. CI 成功後のみマージし、`main` の正確なコミット、版、ノートを再確認します。PyPI にまだ `1.0.2` ファイルがないことも確認します。

## ドラフトと公開

準備 PR をマージした後にドラフトを作ります。squash/merge でリリースコミットは変わります。公開済みタグは移動しません。

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.2 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.2" \
  --notes-file docs/releases/v1.0.2.md \
  --draft --latest
```

タグ、対象、タイトル、ノート、ドラフト、安定版、Latest の意図を確認します。ドラフトは公開の承認ではありません。

## 公開

GitHub ドラフトの公開直前に所有者の最終承認を得てください。承認がなければドラフトのままにします。公開すると GitHub Release が公開され、ワークフローが開始しますが、PyPI アップロードは保留中の `pypi` デプロイに対する別の明示的なレビューを待つ必要があります。

```bash
gh release edit v1.0.2 \
  --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

ワークフローはタグ/版/保護された main、再現可能な wheel・sdist、アーカイブ・インストール・監査、SHA256SUMS と provenance を確認してから OIDC でアップロードします。既存 PyPI ファイルはエラーです。

## 保留中の PyPI デプロイのレビュー

1. ビルド、wheel/sdist インストール検査と依存関係監査が成功したら、GitHub Actions で正確なワークフロー実行を開きます。アップロード前に公開ジョブが `pypi` のレビューを待っていることを確認します。実行 URL/ID と試行番号、タグ、コミット、SHA256SUMS と release-provenance.json の候補ハッシュ、保留状態と時刻を記録します。ソーステストと API 設定だけではこの待機を証明できず、次のリリースでの観察は #235 の未完了の受け入れ条件です。
2. 必須レビュアーは候補の証拠と現在の Trusted Publisher/環境設定を確認します。**Review deployments** で `pypi` を選択し、公開が承認された場合のみ **Approve and deploy** を明示的に選びます。GitHub ドラフトの公開承認はこのレビューの代わりにはなりません。
3. 公開を拒否するには **Review deployments** で `pypi` を選択し、理由を入力して **Reject** を選びます。想定したレビュー操作や待機がない場合は停止し、アップロード前に実行をキャンセルします。拒否・キャンセルした実行を保存し、拒否を回避するためにタグを移動したり版を再利用したりしないでください。レビューを通した準備で理由を解消し、新たな承認を得ます。
4. 実行・候補の証拠とともにレビュアー、承認または拒否、コメント、時刻、デプロイ結果を記録します。承認後は最初のアップロードと公開後の検証結果を保存します。拒否したデプロイを公開成功や承認待機の検証成功として記録しないでください。

失敗後に変更した成果物を再アップロードしません。`1.0.2` の部分公開やハッシュ不一致なら昇格を止め、証拠を保存し、レビューした新しい版（通常 `1.0.3`）で修正します。yank しても版は再利用できません。

## 公開後の検証

1. 正確なタグとコミットの `publish.yml` 成功を確認します。PyPI の wheel と sdist のハッシュをワークフローの候補・provenance と照合し、各々を新しい環境にインストールします。
2. 版、初期化済みエージェントホームの JSON `list`、Relay/MCP、`pip check`、GitHub の安定版/Latest、通常の更新選択を確認します。ホスト型 Relay は別途検証し、queued を ACK と見なしません。
3. 公開の証拠を記録してから v1.0.2 マイルストーンを閉じます。#161 は既存の監視マイルストーンで開いたままにし、根本原因の修復を主張しません。全機器への導入や運用サービスの再起動は別の運用判断です。
