# session-peerのリリース

1.0.4は1.0.3に続く2026-10-07付のメンテナンス版です。準備だけの承認では、タグ、ドラフト、ワークフロー実行や公開の前に停止します。このリリースを完了する明示的な指示は公開段階を承認しますが、必須の人によるPyPI環境レビューや本番配備を代替しません。準備、不変なGitHub公開、人によるPyPI環境レビュー、公開後検証を区別します。保護されたmainはレビュー済みの最新PRと、Pythonプラットフォーム行列、文書、シェル、パッケージ/単独ファイル/MCP/Relay/Control、統合試験、Python/Node依存監査を含むリリースゲートを要求します。

## 過去の証拠と現在の境界

5ホストのv1.0.0 RC4 rc4-rerun-02試験は14,436.65秒実行されました。complete記録、公開ヘルス241/241、プローブ147/147、送信21/21、Relay再起動復旧3.182秒でした。独立ACKは20/21です。T120 WindowsネイティブClaudeの元のACKはTUI終了で未確認で、別の単発確認では正確なACKを受信しました。所有者は#164で例外を受け入れました。20/21を維持してください。この過去の証拠はv1.0.4を検証しません。#161の外部停滞の根本原因は未確認です。

Python/PyPI版は1.0.4、対応するタグとGitHubリリースはv1.0.4です。公開承認後にのみ安定版・Latestにします。 プラグイン版は独立です。コアはPython 3.9+、MCPは3.10+、Relay受信側/サーバーはUnixまたはWSLとPython 3.11+が必要です。サービス受信側はサービスPATHのCodexまたは運用者所有のcodexBin設定が必要です。パッケージ公開はホスト対策の配備、機器群導入、本番再起動、実時間OAuthヘルスやACKを証明しません。不明な結果は自動再送を許可しません。

## ソースと設定のゲート

1. v1.0.4の変更を1.0.3と4言語のリリースノートに照合します。統合mainにメンテナンス修正#262、#263、#264、#265、#266、#267の6件を要求します。公開済みv1.0.3のセキュリティ履歴と、独立したスキルの版/最小/全機能対応の契約を保持します。パッケージ/生成版、4つのREADMEの安定版案内とアーカイブ内ノートを確認します。cc_peer.pyは凍結して配布から除外し、資格情報、鍵、DB、リプレイ状態、ブラウザープロファイル、ローカル証拠と会話を除外します。
2. 全ローカル試験とPRリリースゲートを実行します。マージ後の統合済み公開mainの正確なコミットでCI成功を要求します。非公開勧告フォークの検査はその公開リリースゲートを代替しません。クリーンなwheel/sdist導入、隔離された導入済みimport、正確なCLI版、初期化済みホームのJSON list、extrasとpip checkを検証します。明示的な空Codexホームはstate_db_missingで安全に失敗すべきです。実時間メッセージは送信しません。
3. PyPIに1.0.4ファイルがないことを確認します。2026-10-07の準備確認で版JSONはHTTP 404でした。GitHub Immutable Releasesとv*タグ規則で作成のみ許可し、迂回なしの更新/削除禁止を確認します。所有者は2026-10-03に有効化し (規則24408525)、2026-10-05には厳格なmainリリースゲートを確認しました。2026-10-07のGitHub API確認でImmutable Releases有効、規則24408525有効、refs/tags/v*範囲、迂回なしの更新/削除禁止を再確認しました。過去のv1.0.2は非不変・資産なしで、検証済み単独ファイルリリースではありません。公開前に現状を再確認します。
4. Trusted Publisherがsession-peerをabruption/session-peer、publish.yml、pypiに対応させることを確認します。2026-10-05にログイン済みPyPIブラウザーで対応を検証しました。これは過去の証拠で、新たなPyPIブラウザー再検証ではありません。2026-10-07のGitHub API確認でレビュー担当`abruption`必須、自己レビュー許可 (`prevent_self_review: false`)、`v*`タグ許可を再確認しました。2026-10-05の確認時には管理者迂回が有効でした (`can_admins_bypass: true`)。この過去の観測を新たな迂回ポリシー確認として扱いません。所有者の以前の[2026-09-29対応確認](https://github.com/abruption/session-peer/issues/235#issuecomment-5882178667)も過去の証拠です。設定を再確認し、通常の人のレビューを経て、黙って迂回しません。

## 不変ドラフトの準備

準備PRのマージ後、正確なmainコミットを記録し、そのコミットに軽量タグを作ります。既存タグを移動しません。所有者が保護されたmainのそのコミットで準備を実行します。実行要求と検証の間にmainが進むと安全に失敗します。

```bash
git fetch origin main --tags
release_tag=v1.0.4
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
```

prepare-release.ymlはソース/ref/版/系譜を検証し、2回の再現ビルド、アーカイブ検査、隔離導入試験、依存監査を実行します。空ドラフトにwheel、sdist、session_peer.py、install.sh、SKILL.md、SHA256SUMS、release-provenance.jsonの正確に7資産を証明して添付します。manifestは5payload、署名された来歴はmanifestと証拠も含みます。既存資産は上書きしません。成功した準備実行、正確なコミット、7ファイル、ハッシュと証明を公開前にレビューします。ドラフト添付は公開ではありません。

## 固定されたGitHubリリースの公開

この版の所有者の明示的な承認で公開します。既にリリース完了を指示していれば手続きの承認要件を満たすので、この文書だけを理由に二度目の確認を要求しません。必須の人によるpypi環境レビューは代替しません。公開はタグと資産を固定しpublish.ymlを開始します。

```bash
gh release edit v1.0.4 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

publish.ymlは所有者、正確なタグ/ソース/main系譜を確認し、固定された不変資産を取得して認証された来歴とmanifestを検証します。再ビルドや資産追加は行いません。PyPIジョブ前に導入検査と現在の依存監査を再度通過する必要があります。準備時の監査成功は現在の監査証拠ではありません。

## 保留中のPyPI配備の人によるレビュー

1. アップロード前に正確なActions実行がpypiレビュー待ちであることを観測します。実行URL/ID、試行番号、タグ、コミット、SHA256SUMS、release-provenance.json、保留時刻を記録します。ソース試験や設定だけでは停止を証明できません。次のリリースでの観測が#235受け入れ検査です。
2. 必須の人のレビュー担当が候補証拠と現状のTrusted Publisher/環境設定を確認します。**Review deployments**で**pypi**を選び、承認時のみ明示的に**Approve and deploy**を選択します。GitHub公開承認はこのレビューを代替しません。配備が保留状態になったら必須の人によるレビューを依頼し、環境ゲートを維持します。
3. 拒否するには**pypi**を選択し理由を添えて**Reject**を選びます。期待した停止や制御がなければアップロード前に中止・キャンセルします。拒否/キャンセル実行を保持して原因を解決します。拒否回避のためタグを移動したり版を再利用しません。
4. 担当、判断、コメント、時刻と結果を記録し、アップロード/検証証拠を保持します。拒否は公開成功や承認停止検証成功ではありません。管理者迂回は例外で別途明示的な所有者承認が必要で、理由、実行者、時刻、実行、タグ、コミットを記録します。

## 公開の検証または復旧

正確なタグ/コミットでpublish.ymlとPyPI検証が成功したことを確認します。PyPIの2ファイルを取得し、正確な一覧とハッシュを固定候補/来歴と比較して、クリーン環境でそれぞれ導入します。隔離版、初期化済みホームのJSON list、extrasとpip checkを再確認します。安定版/Latestと通常の更新によるv1.0.4選択を確認します。マイルストーン終了前に証拠を記録し、#161を監視として維持します。

GitHubとPyPI公開は別々の不可逆な段階です。GitHub公開後の監査失敗で、PyPIファイルのない固定リリースが残る場合があります。両実行と正確な資産を保持します。監査迂回、変更済み資産の再アップロード、既存ファイルの無視、版の再利用は禁止です。部分的な1.0.4アップロードや不一致は昇格を停止します。最初の失敗ゲートを診断し、レビュー済み変更と新しい版、通常1.0.5で修正します。yankしても再利用はできません。

## 検証済み単独ファイルの導入

新しい認証済みGitHub CLIがgh attestation verify、署名ワークフロー、ソースref/digest、OIDC issuer、ホストランナーポリシーをサポートする必要があります。試験基準は2.102.0で、全フラグ対応の最初の版は未確定です。リポジトリ/証明の読み取り権限で十分で、公開権限は不要です。[GitHub CLI検証ソース](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go)にポリシーフラグがあります。ローカルfixtureはポリシー/順序/エラーを確認し、実際の署名受け入れを証明しません。

インストーラーは検証済みLatest不変資産を既定とします。--local-sourceは隣接ソースを明示的に信頼し、--mainは未検証開発ソースを選択します。証明欠如や古い未署名版は安全に失敗します。検証できなければpipx/uv/pipを使います。実行前にinstall.shを認証します:

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

取得上限は単独ファイル8 MiB、補助ファイル256 KiB、メタデータ1 MiBです。認証されたmanifest/来歴、正確なタグ/版と候補の--version確認が置換に先行します。送信側がSSH配備前に検証し、オフライン宛先はPythonのみ必要です。検証失敗で既存ファイルは変わりません。SSH許可リスト、既存ペアリングバインディングのレビュー、Controlログイン移行はリリースノートを参照してください。
