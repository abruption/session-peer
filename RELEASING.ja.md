# session-peerのリリース

## v1.3.0 準備

公開済み1.2.1を基準に2026-10-23に準備しました。[リリースノート](docs/ja/releases/v1.3.0.md)はマージ済み機能PR6件と残る制限を説明します。統合ソースの基準はバージョン準備コミットより前の `a0e7af032fd372334782cc3ac3d97b21c71dd797` です。そのCI・CodeQLは成功していますが、最終準備レビュー、保護されたmainの正確なコミットでのCI、依存関係監査、生成された単独ファイル、パッケージとインストールの検証は引き続き必要です。スキルとプラグインのバージョンは独立しています。

所有者はバージョン準備・タグ作成・公開を承認しましたが、リポジトリ保護や必須の人手によるPyPI環境承認は免除されません。ビルド前に公開状況を断定しないノートを固定します。preparation workflowの実行後、attach-draftの成功を待ち、不変の成果物7件、SHA256SUMS、release-provenance.json、認証済みattestationを正確なタグとコミットに照合します。実際の公開証拠は別途記録します。ローカルビルドは事前検証であり、パッケージ公開はサービス配備やインストール済み機器の更新を含みません。以下の節は過去の手順を保存するもので、古いタグの再利用を指示するものではありません。

1.1.0は公開済みです。GitHubはコミット8ca77cf31254c8287a2593fe484bb30a7dba2727のv1.1.0を2026-10-09 06:46:41 UTCに公開し、PyPIはwheelとsdistをそれぞれ08:04:35と08:04:37 UTCに公開しました。[GitHubリリース](https://github.com/abruption/session-peer/releases/tag/v1.1.0)と[PyPIバージョン記録](https://pypi.org/pypi/session-peer/1.1.0/json)を参照してください。公開は本番環境への配備や実験的handoffの全受け入れ条件の完了を意味しません。

以下のソース・設定の確認から公開検証・復旧までは、2026-10-09のリリース手順の過去の記録であり、再実行の依頼ではありません。v1.1.0を再作成、移動、再利用せず、公開例を再実行しないでください。将来の版では、新しくレビューしたバージョン、最新の証拠、明示的な承認で各条件を再確認します。準備、不変のGitHub公開、必須の人手によるPyPI環境レビュー、本番環境への配備は別です。保護されたmainでは、レビュー済みで最新のPRと、Pythonのプラットフォーム別テストマトリクス、ドキュメント、シェル、パッケージ/単独ファイル/MCP/Relay/Control、統合テスト、Python/Nodeの依存関係監査を含む統合リリースゲートへの合格が必要です。

## 公開済みv1.1.2 — 過去の準備記録

GitHubはf3993bf8988dd301b7e14402e63e8ac04e5e2300のv1.1.2を2026-10-13 06:39:11 UTCに公開しました。以前の未公開候補という説明は過去の記録です。v1.1.2を再作成、移動、再利用しないでください。下記のv1.1.0コマンドも過去の例です。

```bash
# Historical v1.1.2 example: do not rerun or reuse this version.
git fetch origin main --tags
release_tag=v1.1.2
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
```

実行要求の後で停止してください。`gh workflow run`は準備の完了前に戻ります。正確なリリースコミットに対応するv1.1.2の実行を特定し、`gh run watch <prepare-run-id> --repo abruption/session-peer --exit-status`で完了を待ちます。`attach-draft`を含む実行が成功するまで、下の公開コマンドを実行しないでください。リリースを下書きのまま保ち、添付資産が正確に7個あること、SHA256SUMS、release-provenance.jsonと認証済み証明がタグ・コミットに一致することを確認します。失敗、欠落または未検証の証拠があれば、公開せず停止します。この独立した検証の完了後にのみ、下のコマンドを実行してください。

```bash
# Historical v1.1.2 example: do not rerun or reuse this version.
gh release edit v1.1.2 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

## v1.2.1準備 — 公開権限なし

公開済み1.2.0を基準に2026-10-19に準備しました。[候補ノート](docs/ja/releases/v1.2.1.md)はPR #319/#317（macOS Orca Claudeの制限付き検索）、#320/#318（制限付きスキルfrontmatter）、#303/#302（正本の互換スキル0.3.3）を記録します。統合ソース基準`32e76d2c85d945d66466f630d9729ec0be5288d8`は最終準備・公開コミットではありません。プラグイン・スキルのバージョンはPython 1.2.1と独立し、グローバル導入や本番配備は含みません。 準備PR #321には#322の対象信号に対する一時領域の所有パス引き継ぎ修正も含みます。制御したローカル再現と原因未確定の元CI失敗は別です。SIGKILL、ホスト喪失、削除の任意中断は保証せず、unknownは自動再試行を許可しません。

対象PR 3件はすべてマージ済みです。最終コミット検証、独立レビュー、パッケージ導入検査、最新依存関係監査を完了します。別途承認された準備PRのマージ後、正確な保護mainのCI成功が必要です。2026-10-19のタグ・PyPI未使用確認は日時点の観察であり、バージョン予約ではありません。現在の非公開Trusted Publisher設定の検証は主張せず、必須の人手pypi環境承認を維持します。#316と残るnative・handoff受け入れ条件は別で、この準備では閉じません。

この節は実行用コマンドを提供せず、マージ、タグ・ドラフト作成、ワークフロー実行、公開・配備を承認しません。別途承認後に全ゲートを再確認し、実行依頼後はattach-draft成功まで停止して、不変資産7個、SHA256SUMS、release-provenance.jsonと認証された証明を正確なタグ・コミットと照合します。ローカル準備ビルドは公開用資産ではなく、公開完了を先に宣言したりメタデータ変更のため不変資産を置換したりしません。

## v1.2.0 — 公開記録と過去の準備

GitHubは`4fc526f36afc65bb6ec460439eb0986c09ecc8ee`から安定・不変のv1.2.0を2026-10-16 12:39:13 UTCに公開しました。PyPIのwheelは12:41:38.903354 UTC、sdistは12:41:40.537212 UTCにアップロードされました。2026-10-19の読み取り専用再確認で[GitHubリリース](https://github.com/abruption/session-peer/releases/tag/v1.2.0)と[PyPI記録](https://pypi.org/pypi/session-peer/1.2.0/json)を確認しました。以下の未公開・PR #315が未マージという表現は2026-10-15/16の準備時点の記録で、現在の状態や実行指示ではありません。v1.2.0の再利用や不変資産の変更は禁止します。

公開版1.1.2を基に2026-10-15に準備しました。マイルストーン目標は2026-10-18で、公開の約束ではありません。PR #305、#311、#310、#308、#313、#314をこの順にマージし、正確なマージコミットを[候補ノート](docs/ja/releases/v1.2.0.md)に記録しました。このバージョン・文書のみの準備にはmainの対象変更が含まれます。Issue #180、#181、#268、#304、#306、#307は未完了のままです。

統合ソースの基準`21a0be0c0c5bcb8bca214d90a873b7479d7ba97a`を反映し、2026-10-16に更新しました。PR #315は最終コミットのローカル検証・CI・レビューのためオープンのままです。この基準は最終リリース準備・公開コミットではなく、v1.2.0は未公開です。

#311のmacOS検出はメタデータのみの方針を維持します。単独listはCodexの実行やバージョン照会を行わず、通常値と強制値の両方を保守的に検査します。通常値を無視する新しいnative環境も拒否する場合があります。send/dry-runは制限されたnativeバージョン証拠を使い、正確にレビューした0.162.1のみ強制値専用検査を選択します。旧版・確認不能・未レビュー版では通常値も検査します。物理child cwdと消費側の別名経路検査は既知の設定の曖昧さを減らすだけで、起動時の保存先や原子的な識別の不確実性は解消しません。

send/dry-runのバージョン照会は3秒でタイムアウトし、別途最大2秒の後処理時間を認めます。メタデータのみのlistにはこの照会を含みません。

原因不明のRelay exit139と別のローカルtransport生成・終了診断は#316で監視します。再実行成功は原因・関連性・修正の証拠ではありません。テスト・監査・保護規則を迂回しません。

PR #315のマージ・公開前に最終コミットをレビューし、単独CLI再生成と文書ハッシュを検査して全テスト、パッケージのインストール、最新の依存関係監査を再実行します。別途承認された準備PRのマージ後、正確なmainコミットのCI成功が必要です。v1.2.0/PyPI 1.2.0の未使用と不変リリース・タグ規則を再確認します。所有者が現在の非公開Trusted Publisher設定の再確認を省略したため、検証済みとは記録しません。PR #315のマージ、タグ・ドラフト作成、ワークフロー実行、公開には引き続き明示的承認が必要で、必須の人手によるpypi環境レビューは省略しません。承認後の準備実行依頼では、attach-draft成功とSHA256SUMSとrelease-provenance.jsonを含む7資産とその証明が正確なコミットと一致するまで停止します。この準備には実行用リリースコマンドを示しません。本番配備は別です。

リリース準備PRは対象6件のPRをすべてマージした後、最後にマージします。統合mainを反映した準備PRの最終コミットを更新・レビューし、過去の承認をv1.2.0の承認とみなしません。準備ブランチのCIとローカル統合成果物は予行検証の証拠であり、公開用リリース資産ではありません。最終リリースビルド前に、4言語READMEの状態案内を公開の前後によらず正確な表現で固定します。保護された最終mainのCI成功後、承認済み準備ワークフローでその正確なmainコミットから資産を再ビルド・検証し、公開前にSHA256SUMSとrelease-provenance.jsonを含む不変資産7個とその証明をすべて確認します。公開時は実際の公開証拠に基づく別の文書記録を追加します。固定済みメタデータを変えるために不変資産を再ビルド・置換せず、公開完了を先に宣言しません。


## 過去の証拠と現在の境界

5台のホストで行ったv1.0.0 RC4 rc4-rerun-02キャンペーンは14,436.65秒間実行されました。記録はcomplete、公開ヘルスチェックは241/241、プローブは147/147、送信は21/21、Relay再起動後の復旧時間は3.182秒でした。独立して確認できたACKは20/21です。T120のWindowsネイティブClaudeでは、TUIが終了したため元のACKを確認できませんでした。後の別の単発テストでは正確なACKを受信し、所有者は#164でこの例外を受け入れています。20/21という値は変更しないでください。この過去の記録はv1.0.4またはv1.1.0の検証にはなりません。#161は未解決のままで、外部で発生した停滞の根本原因も未確認です。

2026-10-09時点の過去の記録：公開済みのPython/PyPI版は1.1.0で、タグとGitHubリリースはv1.1.0です。プラグインのバージョンは別管理です。コアCLIはPython 3.9以上、MCPは3.10以上、Relayの受信側/サーバーはUnixまたはWSLとPython 3.11以上が必要です。サービス管理下で起動する受信側には、サービスのPATH上にあるCodexか、運用者が管理するcodexBin設定が必要です。パッケージ公開は、ホスト型サービスへの修正適用、フリート全体への導入、本番環境の再起動、稼働中のOAuthの健全性、エージェントからのACKを証明するものではありません。不明な結果が自動再送を許可することはありません。

## ソースと設定のゲート

1. v1.1.0候補を公開版1.0.4と4言語のノートで照合します。PR #261と機能PR #283–#290は通常の保護手順で統合基準 `3b328799b73b69e3640534ce229ec5ba565ca894` にマージ済みです。準備PRの正確なコミットと最終統合mainの検査を必須とし、両方のparser保護と固定契約のバイトを維持し、#180/#181/#268の未対応条件と別のスキルPR #30を再確認します。公開済みv1.0.3のセキュリティ履歴とスキル0.3.2/最低0.9.1/全機能1.0.1を維持します。パッケージ・生成物のバージョン、4言語READMEの公開版/候補の区別、アーカイブを確認します。cc_peer.pyは凍結し配布から除外します。資格情報、鍵、DB、リプレイ状態、ブラウザープロファイル、ローカル証拠と会話も除外します。
2. ローカルテスト一式とPRのリリースゲートを実行します。マージ後、統合済みの公開mainにおける正確なコミットでCIが成功していることを確認します。非公開のセキュリティアドバイザリー修正用フォークの検査は、公開mainに対するこのリリースゲートの代わりにはなりません。クリーンな環境でwheel/sdistをインストールし、隔離環境からインストール済みパッケージをimportできること、正確なCLIバージョン、初期化済みホームでのJSON list、extras、pip checkを検証します。明示的に選択したCodexホームに状態DBがなければstate_db_missingでfail closed（安全側に停止）する必要があります。これはすべての空の探索結果を意味するものではありません。このゲートでは実際のメッセージを送信しません。
3. PyPIに1.1.0のファイルがないことを確認します。2026-10-07の準備確認では、過去の1.0.4バージョンのJSONがHTTP 404を返しました。GitHub Immutable Releasesとv*タグ規則を確認し、タグの作成は許可され、迂回手段なしで更新・削除は禁止されていることを確かめます。所有者は2026-10-03に有効化しました（規則24408525）。2026-10-05の確認では、厳格なmainリリースゲートが有効でした。2026-10-07のGitHub API確認では、Immutable Releasesと規則24408525が有効で、対象はrefs/tags/v*、タグの更新・削除は禁止され、迂回手段もないことを再確認しました。過去のv1.0.2は不変ではなく、リリースアセットも含まれていませんでした。これは検証済みの単独ファイルリリースではありません。公開前に現在の設定を再確認します。
4. Trusted Publisherがsession-peerをabruption/session-peer、publish.yml、pypiに対応づけていることを確認します。2026-10-05にログイン済みPyPIブラウザーでその対応を確認しましたが、これは過去の証拠であり、PyPIブラウザーによる新たな再確認ではありません。2026-10-07のGitHub API確認では、レビュー担当者`abruption`が必須であること、自己レビューが許可されていること (`prevent_self_review: false`)、`v*`タグが許可されていることを再確認しました。2026-10-05の確認時点では管理者による迂回が有効でした (`can_admins_bypass: true`)。この過去の観測を、現在の迂回ポリシーの確認として扱わないでください。所有者による以前の[2026-09-29対応確認](https://github.com/abruption/session-peer/issues/235#issuecomment-5882178667)も過去の証拠です。設定を再確認し、通常の人手レビューを経てください。無断で迂回しないでください。

## 不変ドラフトの準備

準備PRのマージ後、正確なmainコミットを記録し、そのコミットに軽量タグを作成します。既存タグは移動しません。リポジトリ所有者が、保護されたmain上のそのコミットを指定して準備を実行します。実行要求から検証までの間にmainが進んだ場合は、fail closed（安全側に停止）します。

```bash
# Historical v1.1.0 example: do not rerun or reuse this version.
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
# Historical v1.1.0 example: do not rerun or reuse this version.
gh release edit v1.1.0 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

publish.ymlは所有者、正確なタグ/ソース/main系譜を確認し、固定された不変資産を取得して認証された来歴とmanifestを検証します。再ビルドや資産追加は行いません。PyPIジョブ前に導入検査と現在の依存監査を再度通過する必要があります。準備時の監査成功は現在の監査証拠ではありません。

## 保留中のPyPIデプロイに対する人手レビュー

1. #235: アップロード前に、対象のActions実行がpypiのレビュー待ちで停止していることを確認します。実行URL/ID、試行回数、タグ、コミット、SHA256SUMS、release-provenance.json、承認待ちを実際に観測した時刻を記録します。ワークフローやアセットの時刻だけでは待機開始を示せません。ソーステストや設定でも停止は証明できないため、各リリースで直接確認した証拠を記録します。
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

取得上限は単独ファイル8 MiB、補助ファイル256 KiB、メタデータ1 MiBです。ファイルを置き換える前に、認証済みのmanifest/provenance、正確なタグ/バージョン、ステージングしたファイルの--versionを確認します。送信側がSSH配備前に取得・検証するため、接続先にはSSH接続権限、Python、POSIXシェルが必要ですが、インターネット接続や導入済みsession-peer CLIは不要です。その後の送信には対象エージェントのネイティブ受信箱やキューも必要で、ランタイムファイルの導入だけでは受信セッションを作成しません。検証に失敗しても既存のファイルは変更されません。SSHオプションの許可リスト、既存ペアリングバインディングの確認、Controlログインの移行についてはリリースノートを参照してください。
