# session-peerのリリース

1.1.0は2026-10-09に準備した未公開の候補で、現在の公開安定版は1.0.4です。 準備のみの承認では、タグ作成、ドラフト作成、ワークフローの起動、公開には進みません。このリリースを完了するよう明示的に指示された場合、公開手順は承認されたものとして扱います。ただし、必須の人手によるPyPI環境レビューや本番環境への配備が不要になるわけではありません。準備、変更できないGitHub公開、人手によるPyPI環境レビュー、公開後の検証を区別します。保護されたmainでは、レビュー済みで最新のPRと、Pythonのプラットフォーム別テストマトリクス、ドキュメント、シェル、パッケージ/単独ファイル/MCP/Relay/Control、統合テスト、Python/Nodeの依存関係監査を含む統合リリースゲートへの合格が必要です。

## 過去の証拠と現在の境界

5台のホストで行ったv1.0.0 RC4 rc4-rerun-02キャンペーンは14,436.65秒間実行されました。記録はcomplete、公開ヘルスチェックは241/241、プローブは147/147、送信は21/21、Relay再起動後の復旧時間は3.182秒でした。独立して確認できたACKは20/21です。T120のWindowsネイティブClaudeでは、TUIが終了したため元のACKを確認できませんでした。後の別の単発テストでは正確なACKを受信し、所有者は#164でこの例外を受け入れています。20/21という値は変更しないでください。この過去の記録はv1.0.4またはv1.1.0の検証にはなりません。#161は未解決のままで、外部で発生した停滞の根本原因も未確認です。

Python/PyPI候補は1.1.0で、予定するタグとGitHubリリースはv1.1.0です。準備ではどちらも作成しません。公開の承認を得た後にのみ、安定版およびLatestとして設定します。プラグインのバージョンは別管理です。コアCLIはPython 3.9以上、MCPは3.10以上、Relayの受信側/サーバーはUnixまたはWSLとPython 3.11以上が必要です。サービス管理下で起動する受信側には、サービスのPATH上にあるCodexか、運用者が管理するcodexBin設定が必要です。パッケージ公開は、ホスト型サービスへの修正適用、フリート全体への導入、本番環境の再起動、稼働中のOAuthの健全性、エージェントからのACKを証明するものではありません。不明な結果が自動再送を許可することはありません。

## ソースと設定のゲート

1. v1.1.0候補を公開版1.0.4と4言語のノートで照合します。PR #261と機能PR #283–#290は通常の保護手順で統合基準 `3b328799b73b69e3640534ce229ec5ba565ca894` にマージ済みです。準備PRの正確なコミットと最終統合mainの検査を必須とし、両方のparser保護と固定契約のバイトを維持し、#180/#181/#268の未対応条件と別のスキルPR #30を再確認します。公開済みv1.0.3のセキュリティ履歴とスキル0.3.2/最低0.9.1/全機能1.0.1を維持します。パッケージ・生成物のバージョン、4言語READMEの公開版/候補の区別、アーカイブを確認します。cc_peer.pyは凍結し配布から除外します。資格情報、鍵、DB、リプレイ状態、ブラウザープロファイル、ローカル証拠と会話も除外します。
2. ローカルテスト一式とPRのリリースゲートを実行します。マージ後、統合済みの公開mainにおける正確なコミットでCIが成功していることを確認します。非公開のセキュリティアドバイザリー修正用フォークの検査は、公開mainに対するこのリリースゲートの代わりにはなりません。クリーンな環境でwheel/sdistをインストールし、隔離環境からインストール済みパッケージをimportできること、正確なCLIバージョン、初期化済みホームでのJSON list、extras、pip checkを検証します。明示的に指定した空のCodexホームはstate_db_missingでfail closed（安全側に停止）する必要があります。このゲートでは実際のメッセージを送信しません。
3. PyPIに1.1.0のファイルがないことを確認します。2026-10-07の準備確認では、過去の1.0.4バージョンのJSONがHTTP 404を返しました。GitHub Immutable Releasesとv*タグ規則を確認し、タグの作成は許可され、迂回手段なしで更新・削除は禁止されていることを確かめます。所有者は2026-10-03に有効化しました（規則24408525）。2026-10-05の確認では、厳格なmainリリースゲートが有効でした。2026-10-07のGitHub API確認では、Immutable Releasesと規則24408525が有効で、対象はrefs/tags/v*、タグの更新・削除は禁止され、迂回手段もないことを再確認しました。過去のv1.0.2は不変ではなく、リリースアセットも含まれていませんでした。これは検証済みの単独ファイルリリースではありません。公開前に現在の設定を再確認します。
4. Trusted Publisherがsession-peerをabruption/session-peer、publish.yml、pypiに対応づけていることを確認します。2026-10-05にログイン済みPyPIブラウザーでその対応を確認しましたが、これは過去の証拠であり、PyPIブラウザーによる新たな再確認ではありません。2026-10-07のGitHub API確認では、レビュー担当者`abruption`が必須であること、自己レビューが許可されていること (`prevent_self_review: false`)、`v*`タグが許可されていることを再確認しました。2026-10-05の確認時点では管理者による迂回が有効でした (`can_admins_bypass: true`)。この過去の観測を、現在の迂回ポリシーの確認として扱わないでください。所有者による以前の[2026-09-29対応確認](https://github.com/abruption/session-peer/issues/235#issuecomment-5882178667)も過去の証拠です。設定を再確認し、通常の人手レビューを経てください。無断で迂回しないでください。

## 不変ドラフトの準備

準備PRのマージ後、正確なmainコミットを記録し、そのコミットに軽量タグを作成します。既存タグは移動しません。リポジトリ所有者が、保護されたmain上のそのコミットを指定して準備を実行します。実行要求から検証までの間にmainが進んだ場合は、fail closed（安全側に停止）します。

```bash
git fetch origin main --tags
release_tag=v1.1.0
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
```

prepare-release.ymlはソース/ref/バージョン/系譜を検証し、再現可能なビルドを2回行い、アーカイブ検査、隔離環境でのインストールテスト、依存関係監査を実行します。空のドラフトにwheel、sdist、session_peer.py、install.sh、SKILL.md、SHA256SUMS、release-provenance.jsonの計7つのアセットを証明付きで添付します。マニフェストは5つのペイロードを対象とし、署名済みのprovenanceはマニフェストと証拠も対象に含みます。既存アセットは上書きしません。公開前に、準備実行の成功、正確なコミット、7つのファイル、ハッシュ、証明を確認します。ドラフトへの添付は公開ではありません。

## 固定されたGitHubリリースの公開

このバージョンを公開するのは、所有者から明示的な承認を得た場合に限ります。このリリースを完了するよう既に指示されている場合は、手続き上の承認要件を満たしているため、この手順書だけを理由に再度確認を求めません。ただし、必須の人手によるpypi環境レビューに代わるものではありません。公開するとタグとアセットが固定され、publish.ymlが開始します。

```bash
gh release edit v1.1.0 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

publish.ymlは所有者、正確なタグ/ソース/main系譜を確認し、固定された不変資産を取得して認証された来歴とmanifestを検証します。再ビルドや資産追加は行いません。PyPIジョブ前に導入検査と現在の依存監査を再度通過する必要があります。準備時の監査成功は現在の監査証拠ではありません。

## 保留中のPyPIデプロイに対する人手レビュー

1. アップロード前に、対象のActions実行がpypiのレビュー待ちで停止していることを確認します。実行URL/ID、試行回数、タグ、コミット、SHA256SUMS、release-provenance.json、保留時刻を記録します。ソーステストやリポジトリ設定だけでは停止を証明できません。次回リリースで実際の停止を確認することが#235の受け入れ条件です。
2. 必須の人手レビュー担当者が候補の証拠と現在のTrusted Publisher/環境設定を確認します。**Review deployments**で**pypi**を選びます。所有者からこのバージョンの公開について明示的な承認を得た後に限り、権限を持つ担当者が**Approve and deploy**を選択します。GitHub公開の承認は、このレビューの代わりにはなりません。デプロイが保留になったら必須の人手レビューを依頼し、環境ゲートを維持します。
3. アップロードを拒否するには、**pypi**を選び、理由を説明して**Reject**を選択します。想定した停止や操作項目がない場合は、アップロード前に停止して実行をキャンセルします。拒否またはキャンセルした実行の記録を保持し、原因を解決します。拒否を回避するためにタグを移動したり、バージョンを再利用したりしないでください。
4. レビュー担当者、判断、コメント、時刻、結果を記録し、アップロードと検証の証拠を保持します。拒否されたことは、公開の成功や承認ゲートが想定どおり停止したことの検証を意味しません。管理者による迂回は例外として扱い、別途、所有者の明示的な承認を得てください。その場合は理由、実行者、時刻、実行、タグ、コミットを記録します。

## 公開の検証または復旧

正確なタグとコミットでpublish.ymlおよびPyPIの検証が成功したことを確認します。PyPIから2つのファイルを取得し、ファイル一覧とハッシュが固定済み候補/provenanceと一致することを確認して、クリーンな環境にそれぞれインストールします。隔離環境でのバージョン、初期化済みホームでのJSON list、extras、pip checkも再確認します。安定版/Latestに設定され、通常の更新でv1.1.0が選択されることを確認します。マイルストーンを終了する前に証拠を記録し、#161は監視用として未解決のまま維持します。

GitHub公開とPyPI公開は、それぞれ別の不可逆な手順です。GitHub公開後に監査が失敗すると、PyPIファイルがないまま固定されたリリースが残る場合があります。両方の実行記録と正確なアセットを保持してください。監査の迂回、変更したアセットでの再アップロード、既存ファイルのスキップ、バージョンの再利用は禁止です。1.1.0の一部だけがアップロードされた場合や不一致があった場合は、昇格を停止します。最初に失敗したゲートを調べ、レビュー済みの変更と新しいバージョン（通常は1.1.1）で修正します。yankしてもバージョンは再利用できません。

## 検証済み単独ファイルの導入

最近のバージョンで認証済みのGitHub CLIは、gh attestation verifyに加えて、署名ワークフロー、ソースref/digest、OIDC issuer、GitHubホステッドランナーのポリシーをサポートする必要があります。試験の基準は2.102.0ですが、すべてのフラグに対応した最初のバージョンは未確認です。リポジトリ/証明の読み取り権限で十分で、公開権限は不要です。[GitHub CLI検証ソース](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go)にポリシーフラグがあります。ローカルfixtureはポリシー/順序/エラーの動作を確認するもので、実際の署名が受け入れられることを証明するものではありません。

インストーラーは、検証済みのLatest不変アセットを既定で使用します。--local-sourceは隣接するソースを明示的に信頼し、--mainは未検証の開発用ソースを選択します。証明がない場合や古い未署名リリースの場合はfail closed（安全側に停止）します。検証できない場合はpipx/uv/pipを使用してください。実行前にinstall.shを認証します:

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

取得上限は単独ファイル8 MiB、補助ファイル256 KiB、メタデータ1 MiBです。ファイルを置き換える前に、認証済みのmanifest/provenance、正確なタグ/バージョン、ステージングしたファイルの--versionを確認します。送信側はSSH配備の前に検証し、オフラインの接続先に必要なのはPythonだけです。検証に失敗しても既存のファイルは変更されません。SSHオプションの許可リスト、既存ペアリングバインディングの確認、Controlログインの移行についてはリリースノートを参照してください。
