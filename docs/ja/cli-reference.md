# session-peer CLI リファレンス

[概要に戻る](../../README.ja.md)

## 受信セッションの世代を固定する条件（開発中）

`list --with-target-generation --json` は各行に `targetGeneration` と
`generationStatus` を追加します。OS のプロセス生成情報を確認できる Claude の受信先では、
`tg1:` トークンを `send --target-generation TOKEN` に指定できます。`--dry-run` と SSH でも
元の宛先のトークンを使います。これは送信の前提条件であり、秘密情報、権限、ACK、再送や
重複排除のキーではありません。指定しない場合、既存の出力と動作は変わりません。

送信直前に登録情報、プロセス生成情報と受信先を再確認し、接続したソケット・パイプの
サーバー PID を確認してから、メッセージや Windows の認証行を書き込みます。
名前・PID の再利用や受信先の変更は `stale_target` で拒否し、確認できない身元は推測しません。
同一プロセスの状態・名前の更新だけでは世代は変わりません。モデルの身元を認証したり、
同じ OS アカウントの悪意あるプロセスを防いだりする保証はなく、必要な OS API がなければ利用できません。
生成情報の粒度は OS に依存します（Linux は起動 ID と開始時刻の clock tick を使用）。
世界的に一意・複製不能な身元や、暗号学的な SSH ホスト鍵の連続性は保証しません。

`stale_target` の拒否には、元の要求で指定した Claude 世代の `lastSeenTarget` を含めます。
後継プロセスを再検索した結果ではありません。この限定的なメタデータには、プロセス生成値、
パス、ユーザー名やホスト名を含めません。

`{"status":"refused","reason":"stale_target","submitted":false,"retryAllowed":false,"lastSeenTarget":{"agent":"claude","targetGeneration":"tg1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}`

`target_generation_unavailable` は OS の身元を検証できないこと、
`unsupported_target_generation` は対象がこの前提条件に対応していないことを示します。
どちらも `lastSeenTarget` を含めず、再送を許可しません。
ソース転送・再起動の回帰テストは専用のプロトコル受信先とローカルの SSH 代替を使います。
実際の遠隔ホストやネイティブエージェントの検証を示すものではありません。

Codex キュー、Antigravity とペアリング済み機器には、この受信プロセス世代の保証はありません。
一般の世代固定要求はキュー投入・wake 前に拒否し、それぞれの既存契約を維持します。
Codex の書き込みプロセスを再確認しても、後からキューを消費するプロセスを原子的に制限できません。
#180 全体は未完了です。v1.0.4 の公開機能ではなく、自動フォールバックや再送も追加しません。

2026-10-15 に native Codex [0.162.1](https://github.com/openai/codex/tree/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs) のキュー入力経路を確認しましたが、元の書き込みプロセスの世代を原子的に検査する、利用可能な前提条件は見つかりませんでした。確認したソースでは、ロック取得経路は世代トークンを記録せず、スレッドの `sessionId` は再開後も維持され、`thread/queue/add` は世代の前提条件ではなくスレッド・入力・クライアントメッセージ ID を受け取ります。確認した `turn/steer` 経路はアクティブターンのロック内で `expectedTurnId` を検査しますが、session-peer はこのターン固有の検査を書き込みプロセスの世代として使いません。これは固定した経路に限った調査であり、すべての native API や将来のバージョンで機能が存在しないことを証明しません。PID・開始時刻・ロックの再確認、キュー ID、`canAcceptDirectInput`、`sessionId` は必要な元世代の保証を確立しないため、Codex の `targetGeneration` は引き続き `unsupported` と報告します。#180 は別途検証された native 契約のため未完了のままです。

コマンドの詳細な動作、インストールオプション、トランスポートの制限、および過去の検証結果について以下に説明します。
機械consumerは[v1互換性契約](compatibility-v1.md)にも従ってください。

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/pypi/pyversions/session-peer)](https://pypi.org/project/session-peer/)

単一の CLI から、ローカルまたは SSH 経由で **Claude Code および Codex セッション**にメッセージを送信します。
Claude ターゲットはネイティブの受信トレイソケット/パイプを使用し、Codex ターゲットは `codex queue` を使用します。
SSH は送信先で同じ Python スクリプトを実行するため、送信（send）や一覧取得（list）のリクエストを受信するために送信先に session-peer がインストールされている必要はありません。

本プロジェクトは、Git の履歴と Issue 番号を維持したまま cc-peer を継続したものです。
session-peer のリリースは [PyPI](https://pypi.org/project/session-peer/)
および [GitHub](https://github.com/abruption/session-peer/releases) で公開されており、古い PyPI の
cc-peer プロジェクトは最終リリース 0.5.1 の後にアーカイブされています。
具体的な移行手順については、[cc-peer からの移行](#moving-from-cc-peer)を参照してください。

## サポートとセキュリティ

- **バグおよび機能リクエスト:** [Issue テンプレート](https://github.com/abruption/session-peer/issues/new/choose)を使用してください。まず既存の Issue を検索してください。
- **セキュリティの脆弱性:** [非公開で報告](https://github.com/abruption/session-peer/security/advisories/new)してください。[SECURITY.md](../../SECURITY.ja.md) を参照してください。
- **非公開の質問:** 件名に `[session-peer]` を含めて [support@abruption.dev](mailto:support@abruption.dev?subject=%5Bsession-peer%5D%20Support) にメールを送信してください。非公開の脆弱性報告が利用できない場合は、メールも代替手段となります。

公開 Issue は誰でも閲覧できます。編集済みの最小限の再現手順を共有してください。
会話履歴、セッションデータベース、認証ファイル、トークン、秘密鍵は添付しないでください。
メールは手動で確認され、自動的に Issue として公開されることはありません。
サポートはベストエフォートであり、応答時間は保証されません。
英語および韓国語での報告を歓迎します。

## クイックスタート

CLI は `pipx install session-peer` または `uv tool install session-peer` でインストールします。
スタンドアロン CLI と Claude スキルについては、[インストール](#install)を参照してください。

```bash
session-peer list                              # Claude, Codex + registered Antigravity
session-peer list --agent claude                # Claude-only filter
session-peer list --agent codex                 # saved Codex threads
session-peer list --agent codex --host worker   # saved threads on an SSH host

session-peer send --to api-worker --message "message"     # Claude name or PID
session-peer send --to 'codex:<full-thread-uuid>' --message "message" --output-format json
session-peer send --host worker --to 'codex:<full-thread-uuid>' --dry-run -m "message"
```

`<full-thread-uuid>` を送信先の Codex 一覧の完全な ID に置き換えてください。
`list` はデフォルトですべての登録済みアダプターを含めます。Antigravity は、明示的に登録された実行中のブリッジのみを一覧表示します。**フィルタリングには
`--codex` ではなく `--agent codex` を使用してください**: `--codex` はサポートされているフラグではなく、
`--codex-home` や `--codex-bin` と曖昧になります。`send` は `--agent` フラグではなくターゲットからエージェントを
選択します。

**投稿済み/キュー投入済みは受領確認ではありません。** 保存された Codex スレッドが実行中であるとは
限りません。通常の送信ではセッションはアクティブ化されません。[明示的な `--wake`](wake.md)
はオプトインであり、消費または返信を確認するものではありません。

<a id="delivery-explanation"></a>

<a id="配信説明開発中"></a>

### 配信説明（v1.3.0）

v1.3.0 から利用できます。`send --dry-run` に `--explain` を追加すると、選択したローカル・SSH・ペアリング済みデバイスの宛先、既存の検証結果、配信方法、観測上の制限を読みやすく表示します。`doctor --explain` は既存の診断スナップショットと宣言された対応機能を説明するもので、個々の宛先の送信準備状態を確認するものではありません。`handoff status --explain` は既存の intent に保存された証拠を説明します。処理した SSH の宛先ごとに説明を表示しますが、予期しないエラーが発生すると既存のホスト処理が中断され、後続の宛先が処理されない場合があります。

```bash
session-peer send --host worker --to 'codex:<full-thread-uuid>' --message "Review the patch" --dry-run --explain
session-peer send --device RECEIVER_FINGERPRINT --to review --message "Review the patch" --dry-run --explain
session-peer doctor --explain
session-peer handoff status --correlation-id PREPARED_UUID --explain
```

説明は選択したコマンドの既存の結果を再利用し、診断、native バージョン、SSH の追加照会、宛先の起動、別途の `list` 処理は行いません。既存の dry-run 自体にはバージョン確認が含まれる場合があります。実際の送信時には再検証するため、プレビューの成功は宛先の予約や投入・消費・完了を保証しません。宣言された対応機能、実際の検証結果、不明な事実を区別して表示します。`--wake` を指定しない場合、起動の適格性は確認しません。指定した場合も既存の事前検証結果だけを説明します。

ペアリングの dry-run は、受信側ポリシーに従う既存の `resolve` 処理を維持します。既存の接続確認で対応を通知した受信側とのみ、任意の説明 context をネゴシエートします。この内部 context にはバージョンが付けられ、許可されたフィールドのみが認められます。サイズの上限は 8 KiB です。一般の JSON 出力や handoff スキーマは追加しません。選択された受信側のエージェント・宛先・home は、報告され検証された場合だけ表示し、送信側のプロファイルから推測しません。旧バージョンの受信側でも、独立に確認された native の結果は維持し、報告されない context は不明のまま扱います。代替経路への切り替え、追加照会、再送は行いません。

Handoff status は読み取り専用スナップショットを再利用し、intent・receipt capability・wait・collector の作成や台帳への書き込みは行いません。投入、入力注入の観測、明示的な receipt、最後に保存された wait は別々に扱います。Receipt が acknowledged でも、タスクの完了を証明するものではありません。保存された観測は古い場合があります。報告された receipt の観測時刻だけを観測時刻として説明し、説明の生成時刻や診断スナップショットの時刻を配信の観測時刻として扱いません。通常送信に receipt ACK の対応が追加されるわけではありません。

この範囲はテキスト出力のみで、`--explain` と `--json` または `--output-format json` の併用は使用法エラーになります。`--dry-run` が必要なのは `send --explain` だけで、`doctor --explain` と `handoff status --explain` には不要です。Send では引き続き、実験的 handoff の `--correlation-id`、`--request-ack`、`--observe-delivery`、`--wait-for` と `--explain` の組み合わせを、メッセージ入力や宛先・台帳処理の前に拒否します。新しいオプションを使わない既存コマンドの出力・JSON・終了契約は維持されます。説明によって、状態照会の成功が ACK の証拠に変わったり、元のコマンドの終了結果の意味が変わったりすることはありません。

Send の通常のメッセージ入力要件と上限は変わりません。従来どおり `--message`、`--message-file` または stdin を使い、仮の本文は自動生成しません。説明フィールドに本文や receipt の秘密値は含めません。通常の説明は stdout に、失敗した結果や予期しない投入の証拠に関する説明は stderr に出力し、既存の要約・エラーの出力先は変えません。不明な証拠は不明のまま表示し、実際の送信結果が不確実な場合は自動再送しません。

### オプションのペアリング済みデバイスと Antigravity (v0.9)

これらの機能は PyPI v0.9.0 以降で利用可能です。Antigravity は引き続き
実験的機能であり、ペアリングトランスポートはベータ版のままであるため、運用上の検証
が引き続き必要です。エクストラは `pipx install 'session-peer[relay]'` でインストールしてください。
`[relay]` エクストラ (Unix、Python 3.11+) により、直接またはセルフホストされた WSS リレーを経由した
認証済みペアリングデバイスへの配信が可能になります。ペアリングによってデバイス ID が固定（ピン留め）され、
個別のオペレーターポリシーにより個々のエージェントターゲットと操作が許可されます。ブラインドリレーは
アプリケーションメッセージを復号できません。エンドポイントを公開する前に、
[ペアリング済みデバイスのセットアップおよび運用ガイド](paired-devices.md)に従ってください。
ベータ版では NAT トラバーサルやホスト型のパブリックサービスは提供されません。

Antigravity には、既存の TUI 内で明示的に起動されたブリッジが必要です。
[Antigravity のセットアップ](antigravity.md)を参照してください。これはオプトインであり、
Claude/Codex の検出には影響しません。実行中の Antigravity 登録もフィルターなしの
一覧表示に含まれます。通常のローカルおよび SSH コマンドは、標準ライブラリのみの
インストールパスを維持します。[v0.9 リリースノート](releases/v0.9.0.md)を参照してください。

### メッセージ入力と結果出力

`--message TEXT` (短縮形 `-m`) は送信先に送るテキストを指定します。
`--output-format text|json` は、メッセージ形式ではなくコマンド結果の形式を
選択します。これは `list`、`send`、`doctor`、および `update` で使用可能であり、デフォルトは
`text` です。既存の `--json` は `--output-format json` のエイリアスとして維持されます。

```bash
session-peer send --to worker --message "Report progress" --output-format json
session-peer send --to worker -m - --output-format json < message.txt
session-peer list --output-format json
```

従来の位置指定メッセージおよびメッセージ省略時の標準入力入力は引き続き機能します。
位置指定メッセージまたは `--message` のいずれか一方のみを使用し、両方を同時に使用しないでください。`--message -` は
標準入力を読み取ります。明示的な空のメッセージは引き続き拒否されます。ダッシュで
始まるテキストを送信するには、`--message='--literal text'` または標準入力を使用してください。内部的な SSH `--b64` 入力は、
どちらの公開メッセージ形式とも組み合わせることはできません。

`--json --output-format json` は有効です。`--json` と
`--output-format text` の組み合わせは、指定順序にかかわらずエラーになります。無効または矛盾する出力
オプションは argparse の使用法エラー（stderr、終了コード 2）となり、メッセージソースの競合
は通常のコマンドエラー（要求された場合は JSON、終了コード 1）となります。いずれの場合もメッセージは
送信されません。JSON 結果は受信ではなく送信を表すことに変わりはありません。
これらのフラグによって構造化された JSON メッセージ入力プロトコルが導入されるわけではありません。

<a id="route-presets"></a>

<a id="ローカル経路プリセット開発中"></a>

## ローカル経路プリセット（v1.3.0）

v1.3.0 から利用できます。任意の `preset` コマンドが保存するのは受信者ではなく接続経路です。Mac/Linux では `--preset` でローカルまたは SSH の経路を一つ選び、通常の Claude Code・Codex の一覧取得や送信に利用します。Windows のプリセット操作は拒否し、既存の Windows コマンドは変更しません。

```bash
session-peer preset add work-mac --host user@work-mac --agent codex --codex-home /Users/user/.codex
session-peer preset list
session-peer preset show work-mac --json
session-peer list --preset work-mac
session-peer send --preset work-mac --to 'codex:<full-thread-uuid>' --message "Review the patch" --dry-run
session-peer send --preset work-mac --preset-revision 'dp1:<HASH>' --to 'codex:<full-thread-uuid>' --message "Review the patch"
session-peer preset replace work-mac --expect-revision 'dp1:<HASH>' --host user@new-mac --agent codex --codex-home /Users/user/.codex
session-peer preset remove work-mac --expect-revision 'dp1:<CURRENT-HASH>'
```

UUID は現在の一覧で確認した値に、ハッシュは選択したプリセットに表示された正確な revision に置き換えます。実際の送信には `--preset-revision` が必要で、dry-run では省略できます。`dp1:` ハッシュが対象とするのはプリセット名と検証済み経路の正確な値だけであり、DNS、SSH 設定、ホスト鍵、native 所有権、権限、世代、ACK は証明しません。経路の値が変わったら再確認が必要で、同じ値に戻すと同じハッシュになります。変更・削除には `--expect-revision` が必要で、同じ名前の追加は拒否します。

受信者の名前、PID、UUID、世代トークンは保存しません。`--to` は引き続き必須で、名前は既存の規則で現在の宛先を検索する値であり、以前のセッションに固定されたアドレスではありません。既存の明示的な `--target-generation`、writer・保存先の検査、不確実な結果で自動再送しない原則を維持します。プリセット名は人物の身元や配信を証明しません。

保存先は `$XDG_CONFIG_HOME/session-peer/destinations.json` で、変数が未設定なら `~/.config/session-peer/destinations.json` です。指定する基点は絶対パスに限ります。アプリ用ディレクトリは所有者専用の 0700、ファイルは所有者専用の 0600 またはそれより厳しい権限です。シンボリックリンク、安全でない所有権・権限、JSON の重複・未知のキー、不正な UTF-8、128 件を超える項目、64 KiB を超えるファイルは、別経路に切り替えず拒否します。名前の形式は `[a-z][a-z0-9_-]{0,63}` です。スキーマが保存するのは接続方式・エージェント、必要な場合の SSH ホスト一つ、Codex 経路の絶対 home だけです:

```json
{"schemaVersion":1,"presets":{"work-mac":{"transport":"ssh","agent":"codex","host":"user@work-mac","codexHome":"/Users/user/.codex"}}}
```

プリセットと明示的な `--host`、`--codex-home`、`--agent`、`--ssh-opt`、`--codex-bin` は値が同じでも併用できません。Reply-To URI、ペアリング済み機器、Antigravity、wake、実験的 handoff との組み合わせも対象外です。認証情報、実行ファイルのパス、SSH コマンドやオプション、承認設定、receipt の秘密値は保存しません。既存の運用者所有の SSH 設定は引き続き適用されます。

`preset list` と `preset show` は設定を読むだけで、native の検索、SSH、更新通知、バックグラウンド更新は実行しません。読み取りで存在しない保存先を初期化することもありません。一方、`list --preset` は既存のリモート照会や部分失敗の処理を含め、選択した一経路の通常の一覧取得を明示的に実行します。他のプリセットへの接続やグループ一斉送信は行いません。

テキスト形式の一覧取得・送信では、既存の処理前に選択した経路と revision を stderr に表示します。既存の native 結果 JSON、stdout、終了契約は維持し、プリセットのフラグ、revision、ローカルファイルのパスは SSH に転送しません。各呼び出しは読み取った一つのスナップショットを使います。後から変更・削除しても既に展開した呼び出しは取り消されず、実際の投入は native 宛先を再検証します。これは保存先・所有権の原子的な証明、受信側の重複抑止、消費、ACK、タスク完了を保証するものではありません。

`preset_commit_unconfirmed` は、原子的な置換が既に見えている可能性がある一方、永続化を確認できなかったことを示します。再試行する前に現在の設定を確認してください。自動的には元に戻しません。

検査する上位経路は root または現在のユーザーが所有し、他のユーザーが書き込めない必要があります。root 所有の sticky 一時ディレクトリは例外で、設定の直上ディレクトリは現在のユーザー所有に限ります。全ての経路要素をシンボリックリンクを追わずに開きます。専用保存先の拡張 ACL エントリーは保守的に拒否します。macOS の上位経路では deny-only ACL を許可しますが、allow エントリーや検証できない ACL は拒否し、Linux POSIX ACL も検査します。空または相対パスの `XDG_CONFIG_HOME` は別の場所に黙って切り替えず拒否します。既存の権限は自動修復しません。安全なユーザー専用の絶対経路を選ぶか、非公開のバックアップを保持してから不正な設定をオフラインで確認・修正し、内容は公開しないでください。

macOS で所有権を無視するマウントは `preset_ownership_unenforced`、マウント照会が利用できない、または検証できない場合は `preset_mount_unverifiable` で拒否します。モードビットだけを所有権が強制される証拠とは扱いません。Linux では上位経路の ACL も、ACL 状態を検証できないファイルシステムも拒否します。管理コマンドを中断した後は、変更が既に見えている可能性があるため現在の設定を確認してください。ディレクトリの同期失敗を黙って成功とは扱いません。

<a id="受信先アドレス帳開発中"></a>

### 受信先アドレス帳（v1.3.0）

v1.3.0 から利用できます。経路プリセットが保存するのは引き続き経路だけです。別途オプトインするアドレス帳は、ユーザーが付けた表示名を、ローカルまたは SSH の Mac/Linux 経路で明示的に選択した Claude Code・Codex の受信先に結び付けます。表示名は人物の身元を認証しません。ペアリング済みデバイス、Antigravity、Windows は拒否します。明示的なアドレス帳操作または `--address` がないコマンドはアドレス帳設定を読みません。自動移行や代替経路への切り替えは追加しません。

```bash
session-peer address resolve --preset work-mac --to 'codex:<full-thread-uuid>' --json
session-peer address add review --label Review --preset work-mac --to 'codex:<full-thread-uuid>' --expect-selection 'as1:<HASH>'
session-peer address discover --address review --json
session-peer send --address review --dry-run --message 'Review the patch'
session-peer send --address review --address-revision 'ab1:<HASH>' --confirm-target 'codex:<full-thread-uuid>' --message 'Review the patch'
session-peer address reselect review --expect-revision 'ab1:<OLD_HASH>' --to 'codex:<new-full-thread-uuid>' --expect-selection 'as1:<NEW_HASH>'
session-peer address remove review --expect-revision 'ab1:<HASH>'
```

プレースホルダーは実際に報告された正確な値に置き換えます。`add` の前に `address resolve` の結果を確認し、その `as1:` 観測 revision を使います。`reselect` の前には同じプリセットで希望する新しい宛先をもう一度 resolve し、新しい `as1:` を確認してください。`as1:` は観測した選択メタデータの revision であり、権限、native epoch、消費の証拠ではありません。追加または再選択が成功するたびに新しい `bindingId` が作られ、`ab1:` アドレス revision の計算対象になります。同一のアドレスを削除して作り直しても、以前の revision は再利用できません。経路の `dp1:` は引き続き値のハッシュです。同じプリセット値を復元すると、新しい epoch ではなく同じハッシュになります。

`address list` と `address show` は設定だけを読みます。`address resolve` と `address discover` は、仮のメッセージ、native CLI・バージョンの照会、モデル・セッションの起動を行わず、選択した受信先のメタデータを明示的に調べます。既存の OS プロセスメタデータ検査は行われる場合があります。Discover は重複しない `--address` 名を最大 16 個受け付け、経路・home と固定された SSH 鍵の context がすべて同じ場合だけグループ化し、各グループを一度調べます。アドレスごとの部分失敗を保持し、どれか一つでも検査に失敗するか保存された選択と一致しなくなると終了コード 1 を返します。ネットワーク全体の探索やグループ一斉送信は行いません。参照先プリセットの欠落や経路・revision の変更は拒否し、保存された古い経路には切り替えません。

Claude アドレスは選択した `tg1:` 世代を保存し、投入前に既存の接続相手を検証する前提条件を適用します。Codex アドレスは完全なスレッド UUID、正確な home、`aw1:` writer 観測を保存し、副作用が発生する前に既存の検査を繰り返します。Codex の世代は引き続き**未対応**です。Writer の観測と再検証は、元の native インスタンス世代を原子的に検証する保証ではありません。Writer が変わった、または確認できない場合は明示的な再選択が必要で、自動的な宛先変更や再実行は行いません。SSH の選択には実際の接続で検証されたホスト鍵が必要で、実際の送信でも同じ鍵に固定します。これは人物を認証するものでも、SSH 設定や SQLite 保存先の同一性を証明するものでもありません。

実際の送信には現在の `--address-revision` と正確な `--confirm-target` の両方が必要で、dry-run では省略できます。`--address` は `--to`、`--preset`、明示的なホスト・native・SSH の上書き、ペアリング済みデバイス、wake、handoff、Reply-To URI の経路指定とは併用できません。通常のメッセージ入力と上限は変わりません。不確実な結果でも自動再送は許可されません。通常のメッセージ入力とともに `send --address NAME --dry-run --explain` を使うと、テキスト形式の配信プレビューを確認できます。上記の JSON・wake・handoff の制限は引き続き適用されます。

保存先は `destinations.json` の隣にある別の `addresses.json` です。`schemaVersion: 1`、64 KiB の上限、最大 128 件の項目を使用します。プリセットと同じ所有者・権限・ACL・マウントの検査と、シンボリックリンクをたどらない経路検査を適用し、ファイルの自動修復や移行は行いません。アドレス名はプリセット名の構文に従います。表示名は NFC に正規化して 128 文字に制限し、制御文字・双方向制御文字・書式文字を拒否します。管理操作の commit が未確認でも変更が既に見えている可能性があるため、再試行前に現在の設定を確認してください。結び付けの revision は、受信側の重複抑止、ACK、タスク完了の証拠を追加しません。

<a id="install"></a>
## 任意の対話型短縮コマンド

これらのファイルを含むリリースでは、Bash/zsh と PowerShell で現在のシェルだけに有効な `sp` エイリアスを任意で利用できます。現在選択されている `session-peer` コマンドに同じ引数と標準入力を渡し、出力、終了コード、権限も変えません。別の引数解析器や Python/TypeScript の選択器ではありません。スクリプト、SSH リクエスト、自動生成される返信手順では正式なコマンドを使ってください。両実装を同時にインストールせず、元のインストール管理ツールで切り替え、シェルがどのコマンドを先に選ぶか確認してください。

wheel とソース配布物には `session_peer_shorthand` 内に有効化ファイルが含まれます。インストールだけでは有効化されず、プロファイルや PATH も変更しません。選択したインストールの Python インタープリターでファイルを探してください。pip の有効な仮想環境、または `pipx environment --value PIPX_LOCAL_VENVS` や `uv tool dir` で確認したツール環境のインタープリターを使います。通常、Unix のツール環境には `session-peer/bin/python`、Windows には `session-peer/Scripts/python.exe` があります。場所を決めつけず実際の環境を確認してください。モジュールはファイルのパスだけを出力します。シェルで読み込む前に内容を確認してください。

```bash
asset=$("/path/to/tool/python" -I -m session_peer_shorthand bash)
source "$asset"
sp --version
source "${asset%/*}/sp-remove.sh"
```

```powershell
$asset = & 'C:\path\to\tool\Scripts\python.exe' -I -m session_peer_shorthand powershell
. $asset
sp --version
. $asset -Remove
```

既に `sp` という実行ファイル、エイリアス、関数がある場合は上書きせず有効化を拒否します。PowerShell は通常 `sp` を `Set-ItemProperty` のエイリアスとして定義するため、既定では有効化できません。競合を自分で管理すると決めない限り、正式なコマンドを使い続けてください。Bash/zsh では source、PowerShell では dot-source で読み込む必要があります。cmd.exe は対応していません。エイリアスはシェルの通常の展開規則に従います。Bash の非対話型スクリプトでは既定で展開が無効なため、正式なコマンドを使ってください。

この方式で作成したエイリアスを変更していなければ、繰り返し有効化しても追加変更なく成功します。削除は同じシェルで作成したエイリアスにだけ作用し、別のエイリアスやコマンドに変更されていれば拒否します。シェルを閉じるとエイリアスも消えます。元の管理ツールで更新した後も、コピーしたランタイムではなく正式なコマンドを参照します。アンインストールや実装の切り替え前にエイリアスを削除してください。パッケージの削除は実行中のシェルを変更しません。永続設定と削除を自分で管理する場合以外は、プロファイルに追加しないでください。

standalone のインストールは変更されず、これらのファイルも自動で配置しません。standalone と併用する場合は、確認済みのチェックアウトからファイルを取得するか、対応するリリースの検証済みソース配布物から `session_peer_shorthand` を展開してください。未検証のダウンロードを直接読み込まず、[リリースの検証](../../RELEASING.ja.md)に従ってください。正式なコマンドを PATH で見つけられる状態にして、確認したローカルファイルを直接読み込みます。手動で選択したファイルの更新と削除は利用者の責任であり、standalone、pipx、uv、pip の管理主体は変わりません。競合検査は現在のシェルと PATH から見えるコマンドだけを対象とし、別のシェルや今後の PATH 変更は確認しません。

## インストール

Python 3.9 以上、標準ライブラリのみ — 外部依存関係はありません。

### pip

アクティベートされた仮想環境内:

```bash
python -m pip install session-peer
```

または、分離されたインストールのために [pipx](https://pipx.pypa.io/) を使用します:

```bash
pipx install session-peer
```

あるいは、`uv tool install session-peer` を使用します。
パッケージマネージャーは `session-peer` コマンドをインストールしますが、[エージェントスキル](#the-skill)はインストールしません。
Claude Code、Codex、Antigravity 用のスキルは専用リポジトリからインストールします。

```bash
npx -y skills@latest add abruption/session-peer-skill \
  --skill session-peer --global \
  --agent claude-code --agent codex --agent antigravity \
  --copy --yes
```

<a id="installsh"></a>
### install.sh

検証済み単体インストールには証明検証に対応する最新GitHub CLIが必要です。検証済み不変リリースの公開まではpipx/uv/pipを使ってください。既存v1.0.2には検証済み単体資産がありません。ダウンロードしたコードの実行前に[ブートストラップ手順](../../RELEASING.ja.md)でインストーラーを認証してください。以下は既に信頼したチェックアウトが前提で、既定では最新検証済みリリースを取得します。ローカルファイルには明示的な `--local-source`、未検証開発mainには `--main` が必要です。

コマンドとスキルの両方をワンステップでインストールします。エアギャップ環境の
ホストや、SSH 経由でのリモートデプロイに使用します:

```bash
git clone https://github.com/abruption/session-peer && cd session-peer

./install.sh                          # this machine
./install.sh --host build-server      # a remote machine, over SSH
./install.sh --host web-01 --host db  # several at once
```

これにより、`session_peer.py` が `~/.local/share/session-peer/` に配置され、
[session-peer スキル](https://github.com/abruption/session-peer-skill/blob/main/session-peer/SKILL.md) の互換コピーが `~/.claude/skills/session-peer/` と `~/.agents/skills/session-peer/` にインストールされ、
`~/.local/bin/session-peer` がリンクされます。別の管理ツールで導入したスキルやシンボリックリンク、
既存の cc-peer ファイルは保持されます。`./install.sh --uninstall [--host ...]` ではインストーラーが
所有するファイルのみを削除し、所有権マーカーのない既存スキルは残します。

`session-peer update` は、最新の GitHub リリースからスタンドアロンプログラムを更新します。
`./install.sh --host <host>` は最新リリースを検証し、そのプログラムとスキルをSSHで転送します。
`session-peer update --host <host>` は、インストールされているバージョンが異なる場合
または存在しない場合にのみプログラムをプッシュします。変更を加えずに報告するには `--check` を追加します。
パッケージ管理されたインストールおよびリモートの制限事項については、[更新](#updating)を参照してください。

**リモートインストールではファイルが SSH 接続自体を通じてプッシュされる**ため、ターゲットには
インターネットアクセスが不要です。スタンドアロンファイルをインストールするには、`python3` と SSH
アクセスが必要です。メッセージングには、送信先に選択したエージェントのネイティブな受信トレイまたはキューも
必要です。

明示的に信頼したローカル開発ソースの場合:

```bash
# Explicitly trust reviewed local source for development only.
./install.sh --local-source
```

<a id="the-skill"></a>
### スキル

公開スキルの正本は [session-peer-skill リポジトリ](https://github.com/abruption/session-peer-skill)で管理します。
スタンドアロンインストーラーはエアギャップと SSH インストール用の互換コピーを保持し、
Claude Code 用の `~/.claude/skills/session-peer/SKILL.md` と Codex 用の
`~/.agents/skills/session-peer/SKILL.md` に配置します。Claude の配置場所はデフォルトの前に
`CLAUDE_CONFIG_DIR`、次に `ANTHROPIC_CONFIG_DIR` を優先します。別途管理されたスキルを上書き・削除しません。Claude Code、Codex、
Antigravity 全体へグローバルインストールする場合は、上記の Skills CLI コマンドを使用してください。
スキルがターゲットとメッセージの選択を案内し、Python プログラムが検出と転送を実行します。
インストールしてもエージェントの権限やインバウンド設定は変更されません。

## 使用方法

```bash
session-peer list                                  # Claude + Codex on this machine
session-peer list --host web-01                    # Claude + Codex over there
session-peer list --host web-01 --all              # Claude stale records / no inbox
session-peer list --agent codex --all              # include archived Codex threads
session-peer doctor                                # local inbox/tool/home diagnostics
session-peer doctor --host web-01                  # run the same checks there
session-peer doctor --host web-01 --check-return-route  # also test SSH back here

session-peer send --to api-worker "message"        # local session
session-peer send --host web-01 --to api-worker "message"
session-peer send --host deploy@web-01 --to api-worker "message"  # explicit SSH user
session-peer send --host web-01 --to 4011 "message"          # address by pid
git log --oneline -5 | session-peer send --host web-01 --to api-worker -   # stdin

session-peer send --host web-01 --to api-worker --dry-run "x"   # resolve only
session-peer list --host web-01 --json             # machine-readable
session-peer list --no-update-notice                # disable cached update notices/checks

session-peer send --host web-01 --ssh-opt=-p --ssh-opt=2222 --to api-worker "..."   # note the '='

# Envelope. Sends identify the Claude/Codex sender and how to answer when the
# current agent session and a return route can be detected.
session-peer send --host web-01 --to api-worker --no-reply-to "..."         # no return address
session-peer send --host web-01 --to api-worker --no-from "..."             # no From: header
session-peer send --host web-01 --to api-worker --reply-to 100.64.0.5 "..." # state the address
```

エージェントセッション内では、デフォルトのエンベロープが送信者を明示的に識別します:

```text
From: codex:01a08dd6-d3f6-7783-a62b-52c1fd049181 @ abruptly@mac-mini-m4.example.ts.net

message

---
Reply-To: session-peer://v1/reply?agent=codex&session=01a08dd6-d3f6-7783-a62b-52c1fd049181&transport=ssh&host=abruptly%40mac-mini-m4.example.ts.net
Reply: python3 /path/to/session_peer.py send --host abruptly@mac-mini-m4.example.ts.net --to codex:01a08dd6-d3f6-7783-a62b-52c1fd049181 --no-reply-to
```

Claude 送信者は同じ位置で `claude:<session-name>` を使用します。この ID は
現在のプロセス環境から取得されたベストエフォートのテキストであり、認証の
主張（クレーム）ではありません。プレーンなシェルには通知すべきエージェント ID はありません。
元のターゲットが同じマシン上にあり、返信ルートが自動的に検出された場合、
生成されるコマンドは `--host` を省略し、ローカルに配信します。明示的な
`--reply-to` または設定された返信ホストも、このマシンの現在の OS ユーザーを指定して
いる場合は正規化されます。その他の明示的なルートおよび実際のリモート送信は、
引き続き SSH ルートを通知します。

`Reply-To` は正規化されたバージョン管理されたアドレスです。完全な URI を `--to` として
渡すと、session-peer はすべてのフィールドを検証し、ローカルまたは SSH 配信を選択します:

```bash
session-peer send --to 'session-peer://v1/reply?agent=claude&session=api-worker&transport=local' 'done'
```

互換性のために `Reply:` コマンドも残されています。両方の形式を信頼できない入力として
扱ってください。評価（eval）したり source したりせず、URI を session-peer で使用してください。この
マシンの現在の OS ユーザーを指す URI はローカル配信に正規化され、不要な自己 SSH 認証
パスを回避します。Codex アドレスには、送信者環境で特定できる場合にエンコードされた
`codexHome` が含まれることがあります。

複数の SSH 送信先を操作するには、`--host` を繰り返します。`--json` は
`list`、`send`、`doctor`、および `update` で使用できます。

### JSON レスポンス規約

すべての JSON 結果オブジェクトは、同じスキーマバージョン付きのエンベロープで始まります:

```json
{
  "schemaVersion": 1,
  "ok": true,
  "host": "mac-mini.example.ts.net",
  "command": "list",
  "sessions": [],
  "version": "0.8.0"
}
```

- `schemaVersion` は共通エンベロープのバージョンを示します。`clientUpdate` や
  `codexHomeResolution` などのコマンド固有のネストされたスキーマは、独自のバージョンを持ちます。
- `ok` は、成功および失敗のすべてに存在します。プロセスの終了コードが 0 以外であっても、
  他のホストに対する成功結果が含まれている場合があります。
- `host` は、その結果が適用される送信先を識別します。ローカルの結果には
  OS のホスト名が使用されます。Tailscale で解決された送信先には、検証済みの MagicDNS
  ID が使用されます。`sshHost` は、呼び出し元が指定した異なる SSH エイリアスを保持します。
- `command` は `list`、`send`、`doctor`、または `update` です。残りのフィールドはそのコマンドの
  ペイロードであり、失敗時には `error` に加えて構造化された診断フィールドが追加されます。

ローカルまたは 1 つのホストに対する呼び出しでは、1 つのオブジェクトが出力されます。`--host` を
繰り返すと、リクエスト順にこれらの同一の独立して帰属可能なオブジェクトの配列が出力されます。
無効なメッセージ入力など、接続前に発生した失敗であっても、要求された送信先ごとに 1 回
出力されます。このカーディナリティ（多重度）は 4 つのコマンドすべてで共有されるため、コンシューマーは
オブジェクトか配列かによってのみ分岐し、同じエンベロープフィールドを使用できます。

通常のコマンドは、専用の 24 時間更新キャッシュを読み取ります。キャッシュが存在しない、期限切れ、
または無効である場合、デタッチされたベストエフォートの GitHub リフレッシュが 1 回開始されますが、
要求されたコマンドが遅延したり変更されたりすることはありません。最新のキャッシュによって、呼び出し元の CLI が
安定版リリースより遅れていることが判明した場合、JSON 結果に `clientUpdate` が追加されます:

```json
{
  "clientUpdate": {
    "schemaVersion": 1,
    "status": "available",
    "current": "0.7.0",
    "latest": "0.7.1",
    "checkedAt": "2026-09-16T10:00:00Z",
    "source": "github_release_cache",
    "command": "session-peer update"
  }
}
```

人間向けの出力では、stderr に同じ簡潔な案内が表示されます。クライアントが最新である場合、
キャッシュが利用できないか古い場合、ホストがオフラインである場合、または通知が無効化
されている場合、このフィールドは省略されるため、フィールドが存在しないことだけでクライアントが
最新であるとは証明されません。複数ホストのコマンドの場合、この情報は 1 つの呼び出し元 CLI の
スコープにとどまり、各結果オブジェクトにコピーされます。送信先の `remoteVersion` フィールドは
個別の意味を維持します。リモートのサブプロセスが独自のリフレッシュを実行することはありません。

ローカルの `tailscale status --json` がデバイスのホスト名、短い MagicDNS 名、完全な MagicDNS 名、
または Tailscale IP によって `--host` を特定した場合、session-peer は現在の MagicDNS FQDN を
検証し、`host` として報告します。SSH は引き続き指定された値を宛先エイリアスとして受け取り、
異なる場合は別個に `sshHost` として報告されますが、`HostName` オーバーライドによって接続がその FQDN に
ルーティングされ、`HostKeyAlias` は既存のホストキー検索を維持します。これにより、一致する
`Host`、`User`、`Port`、および `IdentityFile` の設定が維持されます。オフラインと報告された既知のピアは、
SSH の前に失敗します。tailnet マップに存在しないホストは、通常の SSH 送信先のままとなります。

ホストの ID はログインアカウントを提供するものではありません。`known_hosts`、Tailscale ピア、
および MagicDNS 名はマシンを識別するものであり、その OS ユーザーを識別するものではありません。アカウントは
`--host USER@HOST` として指定するか、元のエイリアスに対して設定してください:

```sshconfig
Host web-01
    User deploy
```

明示的な `USER@HOST` が優先されます。そうでない場合、session-peer は同じエイリアスと
オプションで `ssh -G` を実行し、有効な OpenSSH 設定またはローカルユーザーのデフォルトを
報告します。別のマシンから推測したり、異なるユーザー名で失敗したログインを再試行したり
することはありません。

リモートでの成功結果および SSH 接続の失敗には `sshUser` と `sshUserSource` が
追加されます。ソースは `explicit`、`ssh_config_or_local_default`、または
`ssh -G` で解決できない場合は `unknown` です。接続の失敗には `sshFailure` も追加され、
`authentication_failed`、`host_key_failed`、`timeout`、または `transport_failed`
として分類されます。認証エラーは呼び出し元を `--host USER@HOST` または元のエイリアスの
SSH `User` 設定に誘導し、再試行されることはありません。

終了コード: `0` 成功したコマンド（一覧表示または dry-run を含む）、`1` 運用エラー、
`2` CLI の使用法エラーまたはターゲットなしとして報告された未解決のターゲット、および
`130` 中断（Ctrl-C）。ロールアウトの欠落を含む Codex キューの拒否は運用エラー（`1`）です。
dry-run 中の保存済みスレッドの欠落は `2` を返します。send における終了コード `0` は、
消費または返信を確認するものではありません。

<a id="時間制限付き-handoff-監視v13-候補"></a>

### 時間制限付き handoff 監視（v1.3.0）

```sh
session-peer handoff status --correlation-id PREPARED_UUID --json
session-peer handoff watch --correlation-id PREPARED_UUID --watch-timeout 30 --interval-ms 1000 --json
```

ローカル所有者の POSIX 記録にある準備済み UUID を使用します。状態照会は単一スナップショットのままです。監視は 1..60 秒（既定 30）、1000..5000 ミリ秒間隔（既定 1000）で最大 61 回照会し、値は ASCII 整数のみ受け付けます。予算内に有効な公開結果を構成できる場合だけ最初のスナップショットを出力し、その後は公開メタデータ/historyPhase の変更だけを出力します。スナップショットが一つも出ない場合があります。JSON 監視出力は operation watch、event snapshot または end の共通 schemaVersion 1 NDJSON エンベロープを使い、スナップショットに従来の handoff オブジェクトを内包します。status JSON は変わりません。期限完了の終了コード 0 は監視の完了だけを表し、ACK や待機成功ではありません。SIGINT は 130、履歴・出力の失敗は 1、不正な引数は 2 です。履歴の欠落・破損や ledgerEpoch の変更で監視を終了します。 historyPhase は prepared、attempted、terminal、tombstone または quarantined です。attempted は永続的な試行フェンスを意味し、実行中を意味しません。

監視は読み取り専用で、intent・待機・受領確認の作成、記録の書き込み、提出や起動を行いません。ホスト・機器・Windows 経路や Codex ACK は追加しません。フレームは 16 KiB、総量は 256 KiB に制限し、終了用に 2 KiB を予約します。実ファイル記述子の標準出力には専用の分離された Python 出力補助プロセスを一つ使用します。サイズ制限付きの直列化された公開バイトだけを受け取り、共有記述子フラグを変えず、記録やネイティブデータも読みません。親は IPC を含め元の総予算を適用し、新しい記録読み取り・検証段階の前にも期限を確認します。総時間内に最終出力と終了処理用の 100 ms を確保するため、照会は早めに終わる場合があります。タイムアウト、SIGINT、エラー時には補助プロセスを終了・回収しますが、中断不能な OS 操作の厳密リアルタイム保証ではありません。部分書き込みや完了応答がない場合は終了を含む後続フレームを禁止し、利用側は切れた最後の NDJSON 行を拒否する必要があります。補助プロセスの完了は OS 書き込み完了であり、受信者の消費ではありません。スナップショットは全イベントを欠落なく伝えるストリームではなく、ローカル UTC 観測は ACK 到着順序を証明しません。プライバシー、保持する提出・ACK・待機の意味、読み取り専用コレクター照会、従来の隔離の制約は [handoff ランタイムガイド](handoff-runtime.md)を参照してください。監視はネイティブメッセージプロセスやコレクターを起動しません。ペイロード・権限のダイジェストは公開せず、公開 targetGeneration の既存契約は維持します。 読み取り専用記録は不変のスナップショットバイトを読み終えた後、解析・検証の前に共有ロックを解放します。 中断時の最終出力と終了処理は、残りの総予算内で最大 100 ms に制限します。 全体の成功には完全な成功終了フレームと終了コード 0 の両方が必要です。そのフレームの後に終了処理が失敗する場合があります。非ゼロの終了は全体の失敗であり、ACK を格上げしたり、独立して有効な提出事実を捨てたり、再試行を許可したりするものではありません。

<a id="信頼するローカル-ssh-設定-v13-候補未公開"></a>

### 信頼するローカル SSH 設定 (v1.3.0)

Linux と macOS では、`--host` を指定したローカル CLI の `list`、`send`、`doctor`、`update` で、`--ssh-config ABSOLUTE_PATH` と `--trust-ssh-config` を併用して既存の OpenSSH 設定を選択できます。両方のフラグが必要です。次のパスは例であり、引用符で囲んだ空白も利用できます。

```bash
session-peer list --host worker --ssh-config '/home/alice/SSH Profiles/work.conf' --trust-ssh-config
session-peer doctor --host worker --ssh-config '/home/alice/SSH Profiles/work.conf' --trust-ssh-config --check-return-route
```

この選択は設定にローカルコード実行権限を与えます。`Match exec` は `ssh -G` によるユーザー確認や `send --dry-run` 中でも実行され得ます。運用者は `Include` ファイル、`ProxyCommand`、その他の外部依存先も信頼する必要があります。検証は設定のサンドボックスではなく、依存先を再帰的に検証しません。既存のプロファイルや設定ファイルは編集しません。

絶対パスが必要で、`..` 要素、制御文字、パス内のシンボリックリンクは許可しません。選択したファイルは現在の実効ユーザーが所有する通常ファイルで、ハードリンク数が 1、最大 64 KiB である必要があります。グループ・その他の書き込み権限、および setuid/setgid/sticky ビットも拒否します。祖先ディレクトリは root または現在の実効ユーザーの所有で、グループ・その他から書き込み不可である必要があります。ただし root 所有の sticky ディレクトリは例外です。Linux では拡張アクセス ACL とディレクトリのデフォルト ACL、macOS では allow ACL エントリと所有権が無効のボリュームを拒否します。ACL や所有権を確認できない場合も拒否します。これは保守的な検査であり、実効権限の完全な解釈ではありません。

同じ CLI 呼び出し内で、ローカル `ssh -G` 照会、doctor、リモート一覧・バージョン確認、更新の調査・インストール・検証、send/handoff の SSH に同じ選択を使います。各 SSH 起動前にファイルの識別情報、メタデータ、内容ハッシュ、保存場所の安全性を再検証します。変更を検出すると、既定設定にフォールバックせず拒否します。OpenSSH は元のパスを開きます。不変のバイトスナップショットではなく、検証から OpenSSH の読み取りまでの間に同じユーザーが変更する競合は残ります。

このモードでは `StrictHostKeyChecking=yes`、`UpdateHostKeys=no`、`ForwardAgent=no`、`PermitLocalCommand=no`、`BatchMode=yes` を強制し、接続の多重化を無効にします。既存の明示的なホスト鍵固定が優先されます。`--ssh-opt` の許可リストは変更せず、そこでの `-F` と `ProxyCommand` は引き続き禁止します。選択したローカルパスはリモートコマンド、返信経路、公開 JSON に渡しません。逆方向の doctor はリモート側自身の設定を使用し、このパスを継承しません。順方向の成功は逆方向の認証、メッセージ消費、ACK を証明しません。

環境変数、MCP リクエスト、ReplyTo アドレス、保存済みプリセットからは選択できません。Windows、`setup`、ペアリング済みデバイス経路、プリセットとの併用、返信 URI 宛先、`--host` のない呼び出しは、設定を読む前および SSH 起動前に拒否します。両フラグを省略した場合は従来の既定 SSH 動作を維持します。

<a id="ワンタイムペアリングリンクv13候補"></a>

### ワンタイムペアリングリンク（v1.3.0）

両端で `pairing-offer-v1` と既存のUnix Python 3.11+ relay追加依存関係が必要です。以下のコマンドは v1.3.0 から利用できます。

```sh
session-peer device rotation-status --state /private/client-state
session-peer device offer --state /private/device-state --peer-key CLIENT-CURRENT-64-HEX-KEY --direct PRIVATE-IP:3770 --show-link
session-peer device pair --state /private/client-state --link --route direct
session-peer device offer-status --state /private/device-state --offer-id OFFER-UUID
session-peer device offer-cancel --state /private/device-state --offer-id OFFER-UUID
```

作成時に双方のIDを確認し、所有者の端末だけにリンクを表示します。`--link` に値は付けません。上限付きの非表示入力を使い、クライアントが独立して確認した受信端末の現在の鍵のフィンガープリントを入力してから信頼登録・接続を行います。端末がなければ入力表示や自動承認に切り替えず拒否します。リンクを引数、ブラウザー履歴、ログ、Issueに残さないでください。設定ガイドはリンク・非公開ファイルを選択でき、既存のファイル用コマンドも維持します。取消しはそのオファーの保留信頼だけに適用され、完了済みペアリングには明示的な失効操作が必要です。履歴のない期限切れリンクは拒否し、完全一致する保存記録がある場合だけ完了済みの認証結果を確認できます。ペアリングは受信対象のポリシーやネイティブCLIの承認の代わりにはなりません。鍵更新の制限、期限、回数制限、中断、脅威モデルは[ペアリングガイド](paired-devices.md)を参照してください。

<a id="updating"></a>
### 更新

macOS/Linux では、指定した安定版一つの自動ランタイム通知を非表示にするか、
その設定を解除できます。

```bash
session-peer update --dismiss-runtime-notice 1.3.1
session-peer update --clear-runtime-notice-dismissal
```

上記のバージョンは使用例であり、リリースの告知ではありません。これらはローカルの
設定だけをオフラインで変更し、リリースの確認・インストール・承認は行いません。
リモート/SSH オプションや確認オプションとは併用できません。正規化したバージョンが
完全に一致する通知だけを非表示にするため、後続リリースは通知されることがあります。
解除すると通常の動作に戻ります。明示的なローカル確認は実際の最新バージョンと
更新の要否を保持し、通知設定は別の情報として報告します。リモート確認、スキル通知、
既存の全通知無効化設定は変更しません。リモートコマンドでも呼び出し元 CLI 自体の
キャッシュ通知が表示される場合があります。そのローカル設定は対象ごとではなく一度だけ
読み取り、リモートのバージョンや結果を非表示にはしません。

設定は更新キャッシュと分けて
`$XDG_CONFIG_HOME/session-peer/update-notices.json` に保存します。環境変数が未設定か
空の場合は `~/.config/session-peer/update-notices.json` を使います。
ディレクトリとファイルには安全な所有権と非公開の権限が必要です。安全でないパスは
修復や迂回をせず拒否します。設定ファイルが不正または将来のスキーマの場合は、
通知を非表示にしません。どちらのコマンドもそのファイルを上書きしないため、
まず専用の設定ファイルを確認してください。
Windows はまだバージョン別設定に対応していませんが、通常の更新・確認と
全通知無効化は引き続き利用できます。

安全確認は POSIX の所有者と権限ビットが対象であり、ACL（追加のアクセス権）の
完全な監査や物理媒体への永続化の保証ではありません。上位パスのシンボリックリンクや
相対指定の設定パスは、代替パスに切り替えず拒否します。ファイルシステムには、
ディレクトリ基準の入出力、ファイルロック、ディレクトリの fsync（同期）が必要です。
不正な設定を確認・バックアップした後、運用者は専用の JSON ファイルだけを明示的に
削除し、設定コマンドを再実行できます。書き込みが動作中の可能性がある場合は
ロックファイルを削除しないでください。自動修復は行いません。

パッケージ管理されたインストールの場合は、コマンドをインストールしたのと同じマネージャーを使用します:

```bash
pipx upgrade session-peer
# or: uv tool upgrade session-peer
# or, in its virtual environment: python -m pip install --upgrade session-peer
```

これらのインストールでは、ローカルの `session-peer update` はパッケージが所有するファイルを
置き換えることなく、パッケージマネージャーのガイダンスを出力します。`session-peer update --check` は
最新の安定版 GitHub リリースを確認し、共有キャッシュを更新して正確なアップグレードコマンドを
報告しますが、それらのファイルを置き換えることはありません。

スタンドアロンプログラムの場合:

```bash
session-peer update --check                       # check the latest GitHub release
session-peer update                               # update the local program
session-peer update --host web-01 --check         # inspect the remote standalone copy
session-peer update --host web-01                 # push this program if versions differ
```

リモート更新は、最新の GitHub リリースではなく、**ローカルプログラムのバージョン**と
比較します。リモートのコピーがない場合か古い場合だけプッシュし、新しい場合は変更しません。
配布する前にまず確認し、ローカルプログラムを更新してください。
リモート側で GitHub からプログラムを取得することはありません。
リモートバージョンのプローブは `~/.local/share/session-peer/session_peer.py` のみを検査し、
pip/pipx/uv のインストールは検査しません。リモート更新は、そのスタンドアロンパスと CLI
リンクをインストールします。パッケージ管理されたリモート CLI の場合は、代わりにそのホスト上の
独自のマネージャーでアップグレードしてください。

ローカルまたはリモートの `update` のいずれも、Claude スキルを更新しません。スタンドアロンプログラムと
スキルの両方を更新するには、目的のリリースのチェックアウトから `install.sh` を再実行してください。
ローカルの `session-peer update --check` および `session-peer update` は、自動通知で
使用されるのと同じキャッシュにもデータを書き込みます。

### Orca が管理する Claude プロファイル

macOS で `CLAUDE_CONFIG_DIR` と `ANTHROPIC_CONFIG_DIR` を指定しない場合、
`~/.claude/sessions` と同じユーザーが所有する既知の Orca ディレクトリ
`~/Library/Application Support/orca/claude-profiles/*/home/sessions` を検索します。
環境変数による明示指定は従来の優先順位と範囲を維持し、他のプロファイルへ広げません。
1 つだけ確認するには
`CLAUDE_CONFIG_DIR="/path/to/profile/home" session-peer list --agent claude --json`
を使います。インストール先は変わりません。

すべてのプラットフォームで、既定・明示指定の登録先検索は全体で 4,096 項目、
登録ファイルごとに 1 MiB に制限されます。追加の Orca プロファイル検索だけが macOS 専用で、
直下 128 項目が上限です。自動検索するプロファイルのシンボリックリンク、再解析ポイント、
他のユーザーの所有権は拒否します。検索と doctor は認証情報、受信箱の鍵、会話履歴を読みません。
同じ実体の登録ディレクトリの別名は 1 回だけ検索します。別の記録が同じ生存 PID または
受信箱を主張すれば、公開メタデータが同一でも矛盾です。

正常な一覧は残しますが、**生存セッションの矛盾を含む検索エラーが 1 件でもあれば、
無関係な正常 PID も含めてすべての送信先選択を拒否**します。dry-run・送信・handoff が対象です。
明示指定で他のプロファイルのエラーを分離できますが、指定先内部の矛盾や検索上限は解消しません。
従来の単一ディレクトリでの不正な記録の扱いは変更しません。
選択した記録・受信箱を、他のプロファイルへ再検索せず確認します。通常の Unix ソケット別名は
維持しますが、既存の任意世代検査の制限も維持します。世代トークンは送信権限や ACK ではありません。
モデル認証、すべてのファイルシステム競合の排除、受信証明は提供しません。
他の Orca 構成や任意の設定ディレクトリは自動検索しません。

### 環境変数

| 変数 | 効果 |
| :-- | :-- |
| `SESSION_PEER_REPLY_HOST` | 通知される返信ホストをオーバーライドします: `--reply-to` → `SESSION_PEER_REPLY_HOST` → `CC_PEER_REPLY_HOST` → 自動検出された Tailscale MagicDNS 名または IP。返信行には、検出可能な Claude または Codex 送信者セッションが引き続き必要です。 |
| `CC_PEER_REPLY_HOST` | レガシーフォールバック。新しい設定には `SESSION_PEER_REPLY_HOST` を推奨します。 |
| `CLAUDE_CONFIG_DIR` | Claude Code が設定を保持する場所（デフォルトは `~/.claude`）。セッション検出のために `session-peer list` によって、またスキルの配置のために `install.sh` によって尊重されます。 |
| `ANTHROPIC_CONFIG_DIR` | `CLAUDE_CONFIG_DIR` が設定されていない場合のフォールバック。 |
| `CODEX_HOME` | Codex の検出/キューホーム（デフォルトは `~/.codex`）。`--codex-home` によってオーバーライドされます。 |
| `SESSION_PEER_CODEX_HOMES` | 暗黙的な送信/dry-run の前に、重複するスレッド UUID と安定したアクティブなライターをチェックするための追加の送信先ホーム。シェルコマンドやパス区切りのリストではなく、絶対パス（または `~/…`）の JSON 配列。一覧をマージするものではありません。明白なアクティブライターによって暗黙的な送信ホームが変更される場合があります。 |
| `SESSION_PEER_NO_UPDATE_NOTICE` | `1`、`true`、`yes`、または `on` に設定すると、自動キャッシュ更新通知およびバックグラウンドリフレッシュが無効になります。コマンドごとの同等機能は `--no-update-notice` です。明示的な `session-peer update --check` は引き続き確認を実行します。 |
| `XDG_CACHE_HOME` | 更新キャッシュのベースディレクトリ。それ以外の場合は `~/.cache/session-peer/update.json` が使用されます。 |

`--host` を使用した場合、検出には送信先の環境が使用されます。ローカルの環境変数は
自動的には転送されません。`--codex-home` および `--codex-bin` は、その送信先上の
パスを明示的に選択します。

## Codex セッション

Codex の検出は、読み取り専用の SQLite 接続を使用して `state_5.sqlite` を読み取ります。
この内部スキーマは実験的なものであり、macOS 上の Codex CLI 0.154.0 でテストされています。
クロスプラットフォームのフィクスチャテストは、すべての OS でのライブ Codex 検証を主張するものではありません。
保存されたセッションがアクティブであるとは限りません。`--all` にはアーカイブされたスレッドが含まれます。

`--codex-home` は送信先の `CODEX_HOME`（デフォルトは `~/.codex`）をオーバーライドします。
`--codex-bin` は送信用の `codex` の PATH 検索をオーバーライドします。SSH ではこれらは
リモートパスになります。送信には `queue` コマンドを備えた Codex 実行可能ファイルと、
そのホーム内の適切な保存済みスレッド/ロールアウトが必要です。一覧表示だけでは
キューがそれを受け入れられることは証明されません。

### SQLite ストレージの境界

単独の `list` はメタデータだけを調べます。Codex の実行やバージョン照会は行わず、`--codex-bin` を指定しても検出用のバージョンが確認されたことにはなりません。そのため macOS では候補の SQLite DB を開く前に、通常の設定と強制設定の両方を保守的に検査します。旧ローダーで既定ホームの古い DB を誤って読むことを防ぎますが、通常の設定を無視する新しいローダーの正常な環境も拒否する場合があります。拒否はエラーとして返し、成功した空一覧や別 DB への切り替えとして扱いません。他のエージェントの正常な結果は検出不完全のエラーとともに保持します。診断ではストレージ設定の曖昧さを示し、運用者に既知の設定層と有効な `com.openai.codex` の設定・要件と意図したホーム・ストレージ構成の確認を求めます。`--codex-home` の変更だけでは全体設定の曖昧さは解消しません。エラーを隠すために設定、管理プロファイルや DB を自動削除しないでください。native ローダーが実際に値を無視していても、この構成の検出は保守的に未対応とし、正確なバージョン別検出は別の改善で扱います。send の事前検証内の検出では、すでに選択した送信方針を再利用し、追加のバージョン照会をしません。

送信とその事前検証では、選択した native 実行ファイルによって macOS 設定の検査方針が異なります。確認した Codex 0.162.1 は強制設定だけを読みますが、Codex [0.154.0](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/config/src/loader/macos.rs) は `CFPreferencesCopyAppValue` で通常の設定も読みます。macOS の通常のキュー送信と事前検証は、選択したホームと作業ディレクトリで `--version` 子プロセスを一度実行します。照会は3秒、後処理は2秒、標準出力は1 MiB、診断出力は64 KiBに制限します。出力内容を外部に返しません。形式が不正、取得不能、未調査のバージョンでは、バージョンだけを理由に拒否せず通常の設定も保守的に調べます。後処理が不確実なら投入前に拒否し、中断は期限内の後処理を試みた後に伝播します。厳密に `codex-cli 0.162.1` の場合だけ強制設定専用にし、後のバージョンも同じとは仮定しません。handoff は既存のバージョン照会と元の期限を再利用し、投入まで方針を保持します。対応する0.154.0の wake 経路は、稼働中の writer にキューだけを投入する場合も通常の設定を調べます。予算予約と子プロセス起動の境界でストレージと独自マーカーを再確認します。macOS 以外では新たなバージョン照会をせず、結果をキャッシュせず、wake の対応範囲も増やしません。確認済みのキュー投入後に拒否しても投入の事実を保持し、再送しません。これはソースに基づく検査と模擬回帰テストであり、新たな native 設定や MDM の実測ではありません。

所有するキューと wake の子プロセスには、祖先の別名も含めて厳密に解決した、存在する物理的な作業ディレクトリを使います。プロジェクト検索、子の `cwd`、POSIX の `PWD`、wake の `thread/resume.cwd` は同じディレクトリです。保存済みの consumer ディレクトリが存在する場合、物理的な表記と異なる論理的な表記の両方を、同じマーカー境界と独自マーカーの代替規則で調べるため、別名設定を保守的に拒否する場合があります。失われた consumer ディレクトリには検査する層がないという既存の扱いを維持します。実行中の writer の起動設定を確認するものではなく、検査後の別名や設定の変更も起こり得ます。 結果の `wake.cwd` もこの物理的な表記を使うため、保存された別名と異なる場合があります。

native ローダーの層一覧コメントには `<cwd>/config.toml` とありますが、固定した[プロジェクト層の構成コード](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/config/src/loader/mod.rs#L1652)は `.codex/config.toml` を読み込みます。この検査は古いコメントではなく実装に従います。Windows Known Folder の取得が成功しても、返されたパスが不正または上限超過の場合、別のディレクトリへ黙って切り替えず拒否します。

wake は予算予約前に既知のストレージ設定を調べますが、予約後に設定や書き込みプロセスの証拠が変わると、後続の再検査で拒否される場合があります。変換された native ホームの経路は継承した cwd を維持し、Windows の消費側ディレクトリは調べません。

2026-10-09 のソース調査では native Codex [0.154.0](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/core/src/config/mod.rs) と [0.159.0](https://github.com/openai/codex/blob/687a119f0fcaace47e1f1abcc77cec6c813fd6da/codex-rs/core/src/config/mod.rs) を確認しました。両版は設定済みの `sqlite_home`、空でない `CODEX_SQLITE_HOME`、`CODEX_HOME` の順で SQLite ストレージを選択します。相対的な環境変数のパスは native が解決した作業ディレクトリを基準にします。[管理要件](https://github.com/openai/codex/blob/687a119f0fcaace47e1f1abcc77cec6c813fd6da/codex-rs/core/src/config/requirements.rs) はコマンドライン指定を含むストレージ設定を置き換えられます。[native のキュー経路](https://github.com/openai/codex/blob/687a119f0fcaace47e1f1abcc77cec6c813fd6da/codex-rs/tui/src/session_queue_commands.rs) は稼働中の共有サーバーを再利用できるため、新しいクライアントの環境だけではサーバーのストレージを確認できません。これはソース上の確認であり、新たな実送信やプラットフォーム検証ではありません。

2026-10-15 の native Codex [0.162.1](https://github.com/openai/codex/tree/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs) の調査では、ストレージの優先順位は管理要件、統合された設定層、`CODEX_SQLITE_HOME`、`CODEX_HOME` の順でした。`sqlite_home` を設定できる層は、システムファイル、macOS の管理プロファイル、ユーザーの `config.toml`、`--profile` で選択したプロファイルファイル、native プロセスの作業ディレクトリのプロジェクト層（作業ディレクトリから最も近い既定の `.git` ルートまでの `.codex/config.toml`。ルートがなければ作業ディレクトリのみ。信頼済みプロジェクトでのみ有効）です。従来の `[profiles.*]` テーブルにはストレージのキーがありません。`codex queue` は、ホームの `app-server-control/app-server-control.sock` で接続を受け付ける app-server デーモンが稼働中であればそのデーモン経由で、そうでなければ内蔵サーバー経由で投入します。native TUI は `--no-daemon` などで除外しない限り、既定でこのデーモンを自動起動します。デーモンの QueueStore は起動時に選んだデータベースを保持しますが、`config/read` は現在のディスク上の設定層を読み直します。`initialize` はホームとプラットフォームを返しますが、確認した `initialize`、`config/read`、キュー API には起動時の SQLite の同一性を証明する安定した契約がありません。スレッド UUID の一致や同じサーバーへの接続はストレージの同一性を意味せず（コピーしたデータベースにも同じ UUID があり得ます）、キュー API には期待するストレージやプロセス世代の前提条件がありません。キューのメッセージを消費するプロセスは自身のストレージのキューをポーリングします。これはソース上の確認であり、実送信やプラットフォーム検証ではありません。

session-peer は継承された `CODEX_SQLITE_HOME` が空でない場合、または調べるホームの設定にルートの `sqlite_home` がある場合、検出、事前検証、キュー投入の前に拒否します。設定パスが選択したホームと同じ場合も拒否し、引用符・エスケープを含むルートキー、ルートのドット区切りキーやテーブルも対象です。選択されていない入れ子のキーはルートのストレージ設定と見なしません。空の環境変数指定は native 子プロセスの環境から除去します。環境変数名は POSIX では大文字と小文字を区別し、Windows では区別しません。既存の native ホームのパス変換は維持し、ストレージの移動には対応しません。 また、システムの設定・要件ファイル（`/etc/codex/config.toml`、`/etc/codex/managed_config.toml`、`/etc/codex/requirements.toml`、Windows では Known Folder API の ProgramData ディレクトリ配下の `OpenAI\Codex\config.toml` と `requirements.toml`）と macOS の管理プロファイルの値にルートの `sqlite_home` がある場合、プロジェクトの信頼状態に関係なく拒否します。キュー投入は調べたホームで native プロセスを起動するため、呼び出し元のディレクトリはプロジェクト層を追加しません。事前検証は キュー・app-server の子プロセスを起動せずに（wake と macOS の通常のキューの事前検証では native のバージョン確認プロセスを実行する場合があります）同じ実行計画（ホーム、子プロセスの作業ディレクトリ、環境、既知の設定層、消費ディレクトリ）を調べ、実際の送信は効果の直前に再確認します。どちらも native Codex が設定を読むまでの時間差をなくさないため、事前検証の成功は次の送信でのストレージ一致を保証しません。ユーザーの方針により、デーモンの制御ソケットは稼働中か残存かに関係なく拒否理由にならず、session-peer は接続も試みません。デーモンと内蔵サーバーの選択は従来どおり native Codex が行い、ストレージの権限は主張しません。変換された native ホームの経路を除き、事前検証、キュー投入、wake は、消費する書き込みプロセスや wake サーバーが通常起動する、保存済みスレッドのディレクトリのプロジェクト層も調べ、スレッドのメタデータを読み取れない場合や形式が不正な場合は拒否します。wake は対象ごとの予算を予約する前にこれらのストレージ検査を行います。拒否理由は `sqlite_environment_override`、`sqlite_home_configuration`、`sqlite_home_system_configuration`、`sqlite_home_managed_configuration`、`sqlite_home_project_configuration`、`consumer_directory_unverifiable`、`storage_config_unreadable`、`storage_config_unverifiable` です。

調べる TOML ファイルは最大 1 MiB の UTF-8 通常ファイルであり、シンボリックリンクであってはなりません。Windows のシステムディレクトリは `SHGetKnownFolderPath(FOLDERID_ProgramData)` で取得し、API 失敗時は native Codex と同じ固定値 `C:\ProgramData` を使います。`ProgramData` 環境変数は使用しません。macOS では CoreFoundation で Codex の設定ドメインを同期し、所有値を解放します。強制設定専用の方針ではコピー後に強制状態を再確認し、通常のユーザー設定を無視します。バージョンで選ぶ保守的な方針では、上記のとおり通常の設定も読みます。選択する base64 文字列は最大 2 MiB、デコード後の UTF-8 TOML は最大 1 MiB です。同期・型・デコード・サイズのエラーは拒否します。TOML ファイルや設定値の欠落は許可します。既定の探索は最も近い非ディレクトリの `.git` 項目（metadata のみ確認）、または `HEAD` を持つ .git ディレクトリで止まります。シンボリックリンクのマーカーは保守的に拒否し、ルートがなければ作業ディレクトリだけを調べます。`<cwd>/config.toml` はプロジェクト層ではありません。既知の設定にルートの `project_root_markers` 指定があれば、カスタムマーカーを正確に解釈したとは主張せず、上位ディレクトリ全体を保守的に調べます。API はモックで検証しており、移動された実際の Windows Known Folder や強制 MDM プロファイルは未検証です。読み取り不能、変更、サイズ超過、キー構文を分類できない場合は内容を表示せず拒否します。外部依存のないキー分類器は Python 3.9 に対応しますが、完全な TOML・スキーマ検証器ではありません。他の値は引き続き native Codex が検証します。キュー投入と wake は子プロセスの起動前にこの境界を再確認します。拒否結果は `status=refused`、`submitted=false`、`retryAllowed=false` となり、通常の既存出力と書き込みプロセスの所有権検査は変わりません。SSH では送信元の環境ではなく送信先で検査します。

変換された native ホーム（WSL の relay 受信側から native Windows Codex へのキュー投入）は既存の投入契約を維持しますが、ストレージ検証には対応していません。この POSIX プロセスは Windows 側のホーム表記、大文字小文字の規則、環境、システム・管理・プロジェクト層を調べられません。このような経路を効果の前に拒否する厳格モードは将来可能ですが、実装していません。

これは範囲を限定した防御の強化であり、すべての設定で native ストレージが一致する証明ではありません。調べないものは、パッケージ既定の設定、エンタープライズのクラウド設定バンドル、実行中の共有デーモンの起動時ストレージ、すでに実行中の書き込みプロセスの `--profile` による選択・`-c` による上書き・環境変数、保存済みスレッドのディレクトリ以外で起動したかディレクトリが失われた書き込みプロセス、変換された native ホームの Windows 側のシステム・管理・プロジェクト層です。最後の検査後に設定が変わる場合もあります。検査の成功だけからストレージの一致を推測しないでください。[#268](https://github.com/abruption/session-peer/issues/268) は、この契約の native プラットフォーム検証のため未完了のまま維持します。擬似子プロセスのテストが示すのは拒否と環境処理のみであり、実際の誤送信、セキュリティ上の悪用、新たな native 互換性を証明しません。wake の対応バージョン範囲は変わりません。

### Orca と複数の Codex ホーム

Orca で起動されたセッションはアカウントごとのホームを使用でき、別のターミナルまたは
SSH コマンドは `~/.codex` を使用できます。同じ UUID が両方に存在する可能性があります。
一方のコピーへのキュー投入が成功しても、目的のセッションがそのホームを使用していることは
証明されません。

明示的な送信先ホームが引き続き最も強力な選択肢です。たとえば、`<account-id>` と
`<full-thread-uuid>` を目的のアカウントとスレッドに置き換えます:

```bash
session-peer list --host mac --agent codex \
  --codex-home '~/Library/Application Support/orca/codex-accounts/<account-id>/home' --json
session-peer send --host mac --to 'codex:<full-thread-uuid>' \
  --codex-home '~/Library/Application Support/orca/codex-accounts/<account-id>/home' \
  --dry-run --json "message"
```

ローカルで使用する場合は `--host mac` を省略します。実際に送信する準備ができたときにのみ `--dry-run` を削除してください。
`~` をクォートすることで送信先での展開が維持されます。絶対リモートパスも
機能します。現在のリリースは `--codex-home` を送信先の制約として扱いながら、一致するすべての
既知ホームのライターエビデンスを検証します。以前のリリースも明示的ホームの構文を受け付けますが、
この安全性は保証しません。

重複ホームの拒否ベースラインは v0.6.1 でリリースされました。後述のアクティブライターの
選択、再検証、および詳細な `codexHomeResolution` エビデンスは v0.6.2 でリリースされています。
v0.6.1 では、同じスレッド UUID が複数の既知のホームに存在する場合、明示的な `--codex-home` が必要です。

`--codex-home` がない場合、選択には引き続き送信先の `CODEX_HOME`、次に
`~/.codex` が使用されます。送信または dry-run の前に、曖昧さガード（ambiguity guard）が制限付きのインベントリをチェックします:

- 選択されたホーム、および状態 DB が存在する場合はデフォルトの `~/.codex`。
- macOS のみ、`~/Library/Application Support/orca/codex-accounts/*/home`
  の直下に存在する状態 DB。
- 送信先の `SESSION_PEER_CODEX_HOMES` からの追加ホーム。例:

```bash
export SESSION_PEER_CODEX_HOMES='["/srv/codex/account-a", "/srv/codex/account-b"]'
```

これを送信先コマンドの環境で設定します。ローカルの export は `--host` によって
転送されません。Windows では、JSON で要求されるようにバックスラッシュをエスケープした
絶対 Windows パスを使用します。空の設定配列は許可されます。設定が不正な形式である場合、
暗黙的な送信ではエラーになります。

すべての送信と dry-run で、session-peer は UUID を保存する既知のホームをすべて検出し、
各ホームの正確な `thread-writer-locks/<uuid>.lock` を検査します。候補が 1 つの場合や明示的な
`--codex-home` も対象です。カーネルのアドバイザリロックを個別にプローブし、2 回の安定した
`lsof` 観測を通じてオープンしているプロセスを関連付けます。暗黙的な送信では、同一ユーザーの
安定した Codex ライターが唯一存在するホームを選択します。明示したホームはそのライターと一致する
必要があり、別のホームが唯一のライブライターを所有する場合、コマンドは構造化された競合を返し、
ホームを暗黙に変更しません。選択された PID、プロセス開始時刻、および保持中のロックは、キューへの
投入直前に再確認されます。空きロックや古いロックは、単にファイルが存在するだけでは選択されません。

不明なエビデンス、複数のライブライター、`lsof` の欠落、権限エラー、PID/開始時刻/inode の変動、
および競合するエビデンスは、キューイング前にフェイルクローズします。アーカイブされた保存済みコピーも
カウントされます。読み取り不能または互換性のない既知のデータベースや、設定されたデータベースの欠落も
送信を妨げます。すべての保存済みコピーが非アクティブな場合、将来の resume 用に意図してキューへ
入れるには、明示的な `--codex-home` と `--allow-inactive-codex-home` を併用する必要があります。
`--wake` はすでに明示的なアクティベーションの opt-in として扱われます。明示したホームなしで
inactive フラグだけを指定すると拒否されます。解決されたシンボリックリンクのエイリアスおよび
重複するパスは 1 つのホームとしてカウントされます。

`list` は `--codex-home` が正確に 1 つを選択しない限り、既知のホームを集約します。一般的な
ファイルシステムスキャンやプロセス環境の検査は行われず、プロセス引数は公開されません。アクティビティの
検査は SSH 経由を含め送信先マシン上で実行されます。POSIX の `flock` または `lsof` を備えていない
プラットフォームではライブライターの所有権を確立できず、そのエビデンスが必要な場合はフェイルクローズ
します。未設定/カスタムのレイアウトや、チェック後に作成されたコピーは見落とされる可能性があります。
送信を行わずに、選択されたホーム、限定された候補、実行可能ファイル、およびサポートされている状態 DB
スキーマを検査するには、`session-peer doctor` を使用してください。

### 送信と JSON 結果

送信には `codex queue` を使用し、直接のデータベース書き込みは決して行いません。`queued` は
CLI が送信を受け入れたことを意味し、ターンがそれを消費したことや確認応答したことを意味するものではありません。
session-peer はセッションをウェイクまたは再開しません。キュー DB の書き込みおよび Claude ソケット
接続には、呼び出し元の実行環境で承認が必要になる場合があります。このツールはサンドボックスやインバウンドのポリシーを変更しません。キューのタイムアウト（30 秒）は
送信結果が不明であることを意味します。再試行する前に送信先を検査してください。これは
返信を待つためのタイムアウトではなく、session-peer が自動的に再試行することはありません。

Codex メッセージは、測定された Codex サーバーの制限ではなく session-peer の移植性ポリシーとして、
送信者/返信ヘッダーを含めて UTF-8 で 32 KiB に制限されています。NUL 文字を CLI 引数として
渡すことはできません。`--dry-run` はキューイングを行わずに実行可能ファイルと保存されたターゲットを
検証しますが、その後の送信が成功することを保証するものではありません。

ローカルの Codex list JSON は共通のレスポンスエンベロープを使用し、`sessions`、
`version`、および `discovery.codex.homes` 内のホームごとの診断情報を含みます。各セッションエントリには、
`agent`、`id`、`name`（先頭行、最大 120 文字）、`cwd`、`updatedAt`
（Unix 秒）、`archived`、正規の `codexHome`、および `stateDb` が含まれます。トップレベルの
`codexHome` は、インベントリエラーのない単一の候補ホームの場合にのみ保持されます。
成功した各リモート結果には同じフィールドが含まれ、インストールされたスタンドアロンコピーに対するオプションの `remoteVersion` も
含まれます。1 つのリモートホストはオブジェクトを返し、複数のホストは配列を返します。

インストール済みバージョンの照会は補助情報です。照会が失敗しても、検出結果と主処理の終了状態を保持します。
この場合は `remoteVersion` を省略し、生の照会診断を含めず、限定された理由
（`timeout`、`transport_failed`、`authentication_failed`、`host_key_failed`、
`invalid_response`、`probe_failed`）を持つ `remoteVersionProbe: {status: "unknown", reason: ...}`
を含めます。人間向けの出力にはバージョン不明の通知を表示します。未インストールが確認されたリモートでは、
従来どおり両方のバージョンフィールドを省略します。リモート更新のバージョン検証は引き続き必須です。

共通エンベロープ内で、Codex send JSON には `target: {agent, id}`、
`status: queued`（dry-run の場合は `validated`）、`chars`、`dryRun`、およびオプションの
`queueId` が含まれます。また、以下も含まれます:

- `codexHome`: 送信者側の推測ではなく、解決された絶対的な送信先ホーム。
- `codexHomeResolution`: スキーマバージョン付きの `status`、`selected`、`reason`、および
  限定された候補のエビデンス。ステータスは `explicit`、`selected`、`ambiguous`、または
  `unknown` です。候補には、プロセスの引数や環境変数の値を含めることなく、
  保存されたスレッド、ライターロック、安定した所有者 PID、およびプロセス開始時刻の事実が開示されます。
- `submitted`: キュー CLI が正常に完了した後にのみ `true`、dry-run の場合は `false`。
- `consumptionConfirmed`: 常に `false`。queued も validated も消費を確立するものではありません。

エラーの場合は共通エンベロープの `ok` が `false` に設定され、`error` が追加され、
ホームのエビデンスが障害の原因となった場合は `codexHomeResolution` が含まれます。
タイムアウトの場合は送信結果が不明です。エラー時に `submitted` が存在しないことを、
何もキューイングされなかった証拠として解釈してはなりません。一覧表示の結果は送信を
記述するものではなく、送信/消費フィールドはありません。

ローカルの Codex キューのタイムアウト、または信頼できる完全な応答がない SSH
送信では、`status: unknown`、`reason: outcome_unknown`、`retryAllowed: false`
が公開されます。SSH の終了コード 255 または 137、欠落または不正な stdout、
認証・ホストキー・インタープリターの診断だけでは、何も送信されなかったと証明できません。
バージョンを明示した完全な応答は、その後 SSH が失敗またはタイムアウトしても、成功・拒否およびネイティブの
送信事実を保持します。診断 stderr の不正な UTF-8 は有効なプロトコル stdout を
無効にしません。実行前の失敗と完了した拒否は既存のフィールドを保持します。
自動再試行やフォールバックは行わず、結果が不明な場合に `submitted: false` を
追加しません。再試行のメタデータがないことは、再送の許可ではありません。

スキーマのない従来の送信オブジェクトは、`ok` が真偽値で、`command` フィールドがある場合は
`send` であれば、通常の終了コード 0/1/2 で引き続き受け入れます。異常終了または終了処理の
タイムアウトが発生した場合、このオブジェクトだけでは完了を証明できません。

すべてのコマンドにおいて、1 つのリモートホストはフラットなオブジェクトを返し、複数のホストは
配列を返します。`CODEX_THREAD_ID`（または互換性のための
フォールバックである `CODEX_SESSION_ID`）が存在する場合、メッセージエンベロープと返信コマンドは
発信元の Codex スレッドを識別します。

### 診断と返信の観測

`doctor` は、セッションを所有するマシン上で読み取り専用のチェックを実行します。Claude の
設定済みセッションディレクトリと受信トレイの可用性、Codex の実行可能ファイルと
限定されたホーム/状態 DB の候補、サポートされていない DB スキーマ、および権限エラーや
不明な障害を個別のコードとして報告します。受信トレイへの接続、キューへの書き込み、
任意のディレクトリのスキャン、エージェント/SSH 設定の変更は行いません。

リバース SSH は `--check-return-route` を指定した場合にのみチェックされます。送信先は、
プロンプト、パスワード認証、ホストキー登録、および設定変更を無効にした状態で、
固定の `ssh ... true` プローブを実行します。フォワード SSH の成功が、リバースパスが機能する
証拠として再利用されることは決してありません。Tailscale の自動検出で発信元を特定できない場合は、
`--reply-to USER@HOST` を使用してください。JSON の詳細とステータス値については、
[docs/diagnostics.md](diagnostics.md) に記載されています。

意図的に一般的な `--wait` は用意されていません。Claude Code にはネイティブの
同一マシン向け `notify_when_idle` 機能がありますが、リモートセッション、サブエージェント、
または Codex は対象外であり、ソケット/キューへの送信が成功したからといって受領確認には
なりません。そのため、session-peer は可変のトランスクリプトを追跡して誤った一致のリスクを
冒す代わりに、`capabilities.replyObservation.status: unsupported` を報告します。
完了が重要な場合は、提供された `Reply-To` アドレスに明示的な返信を送信するようターゲットに
依頼してください。オプションの wake は引き続き [#46](https://github.com/abruption/session-peer/issues/46)
で追跡されています。

<a id="moving-from-cc-peer"></a>
## cc-peer からの移行

リポジトリ名の変更とパッケージの移行は完了しました:
[session-peer 0.6.0](https://pypi.org/project/session-peer/0.6.0/) が公開され、
[cc-peer 0.5.1](https://pypi.org/project/cc-peer/0.5.1/) が最後の Claude 専用
互換性リリースとなります。**古い PyPI の cc-peer プロジェクトはアーカイブされました。GitHub の
session-peer リポジトリは引き続きアクティブです。** 既存のレガシー配布物は引き続き
ダウンロード可能であり、移行のためにヤンク（公開停止）されることはありません。完了した[移行
Issue #48](https://github.com/abruption/session-peer/issues/48) を参照してください。

新しい製品は、`pipx install session-peer`、`uv tool install session-peer`、
または[スタンドアロンインストーラー](#installsh)を使用して明示的にインストールしてください。
`cc-peer` コマンドのエイリアスはインストールされません。両方の製品は共存できます。
ワークフローを確認した後、インストールしたのと同じマネージャーを使用して古いパッケージを削除してください
（例: `pipx uninstall cc-peer`）。スクリプトによるインストールの場合は、固定された cc-peer v0.5.1 タグの
`install.sh --uninstall` を使用してください。実行する前にパスを確認し、ローカルのカスタマイズを
バックアップしてください。新しいアンインストールは session-peer のファイルのみを削除します。

スクリプトとエージェントの指示を更新して `session-peer` を呼び出し、古い
`~/.claude/skills/cc-peer/cc_peer.py` ではなく新しいスタンドアロンプログラムパス `~/.local/share/session-peer/session_peer.py` を
使用するようにしてください。新しい Claude スキルは `~/.claude/skills/session-peer/` に個別に配置されます。Claude/Codex の
設定、セッションデータ、古いインストールは自動的に移行または削除されません。都合の良いときに
`CC_PEER_REPLY_HOST` を `SESSION_PEER_REPLY_HOST` に置き換えてください。古い変数は
フォールバックとして残ります。

最終的な cc-peer リリースは、継続的な機能やセキュリティのメンテナンスを約束するものでは
ありません。凍結されたルートの `cc_peer.py` は、古い自己更新 URL 用にタグ内に保持されますが、
新しい wheel および sdist からは除外されています。そのローカル更新コマンドは、別の製品を
インストールする代わりにユーザーをここに誘導します。

## Claude Code セッション

### まず公式機能の使用を検討する

Claude 間（Claude-to-Claude）のワークフローについては、まず Claude Code に組み込まれている
[セッション間メッセージング](https://code.claude.com/docs/en/cross-session-messaging)
および [Remote Control](https://code.claude.com/docs/en/remote-control) の使用を検討してください。
session-peer は、そのワークフローが利用できないか適していない場合にシェルベースのローカル/SSH パスを
提供し、Claude および Codex ターゲット向けの共通 CLI を提供します。このセクションの
Claude 固有のガイダンスは、Codex キューの前提条件ではありません。

### 受信トレイのトランスポートの仕組み

Claude Code の[セッション受信トレイソケット](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket)
は次の JSON 行を受け入れます:

```json
{"type":"user","message":{"role":"user","content":"your message"}}
```

session-peer は、その受信トレイを所有するマシン上で接続します。SSH 送信の場合、
Unix ソケットを転送するのではなく、ソースをリモートの `python3 -` にパイプしてそこで
接続を確立します。ネイティブ Windows ターゲットは、代わりに名前付きパイプと
セッションの `.key` ファイルからの認証行を使用します。

セッションレコードは通常 `~/.claude/sessions/<pid>.json` に配置され、
`messagingSocketPath` にソケットパスが保持されます。`/tmp/cc-socks/` を推測で決め打ちしないでください: 以前の
テストでは、その配置と `/run/user/1001/cc-socks/` の両方が見つかりました。バインドされた受信トレイを持たない
アクティブな PID は、到達不能として扱われます。レコードスキーマは内部
インターフェースであり、変更される可能性があります。古くなったレコードや受信トレイのない
レコードを検査するには、`session-peer list --all` を使用してください。レコードまたはソケットが
存在するからといって、呼び出し元にそこへの書き込み権限があることが保証されるわけではありません。

### 受信側が次に何が起こるかを決定する

**「投稿済み」は「配信済み」ではありません。** ソケットへの書き込みは成功しますが、Claude がそのメッセージを読み取るかどうかは、そのセッションの[インバウンド制御](https://code.claude.com/docs/en/cross-session-messaging#control-inbound-messages)次第です。

メッセージは承認のために保留されるか、拒否される可能性があります。以前の検証では、
バイパスモードの受信者はスクリプト発信のメッセージを承認されるまで保留しました。
ソケット書き込みの成功から受信を推測したり、テストを通過させるために権限モードを
変更したりしないでください。

ワーカーが無人で着信メッセージを受け入れるように明示的に設定したい場合は、
その受信者を明示的に設定してください:

```json
{ "crossSessionInbound": "accept" }
```

これが 1 つのワーカーを対象としている場合は、プロジェクト設定または `--settings` でスコープを設定してください。
ユーザー設定はその OS ユーザーの他のセッションにも影響します。メッセージを受け入れると、
受信ターンが開始され、使用量が消費される可能性があります。session-peer がこの設定を代わりに適用
することは決してなく、受信者自身のツール権限が引き続き適用されます。

### なぜ `tmux send-keys` ではないのか？

ターミナルのキーストロークは、意図したチャット入力ではなく、実行中のサブプロセスや
権限プロンプトに届いてしまう可能性があります。session-peer は代わりにエージェントの受信トレイ/キューの境界を
使用します。Claude は受信トレイのメッセージを、ユーザーが承認を入力したものではなく、
[受信セッションのルール](https://code.claude.com/docs/en/cross-session-messaging#how-a-session-treats-an-incoming-message)
に従うピアテキストとして扱います。

## 制限事項

- **送信者 ID はベストエフォートです。** 検出可能な Claude または Codex セッション内で
  実行されている場合、session-peer はエージェント修飾されたテキストの `From:` ヘッダーを追加します。
  そのコンテキストの外では省略されることがあります。これは認証された ID プロトコル
  ではありません。環境変数とセッションレジストリはローカルのヒントです。
- **通知される返信には機能するリターンパスが必要です。** エージェントの送信者と
  返信ホストを特定できる場合、`Reply-To` および互換性のための `Reply:` 行が
  リターンルートを記述します。フォワード SSH の成功は、リバース SSH アクセスを
  証明するものではありません。オプトインの doctor チェックを使用してください。このアドレスはいかなる
  アクセス権も付与せず、session-peer は返信の関連付けや待機を行いません。
- **Tailscale のステータスはローカルのルーティングヒントです。** 既知のオンラインピアはその
  現在の MagicDNS 名でアドレス指定され、既知のオフラインピアは SSH の前に拒否されます。
  未知の送信先は通常の SSH のままです。session-peer はすべての SSH ホストが
  tailnet に属していると主張するものではありません。
- **踏み台（bastion）を越えた検出はできません。** `--host` は単一の SSH ホップです。SSH 設定の `ProxyJump` を使用して自分でチェーンしてください。
- **送信先のユーザーおよび実行権限が重要です。** Claude の受信トレイと
  Codex の状態/キューは送信先のアカウントに属します。正しいアカウントと
  ホームを使用してください。`known_hosts` エントリはそのアカウントを保存しません。呼び出し元のサンドボックスが
  アクセスを拒否する可能性があります。session-peer はどちらのエージェントの権限やクォータも
  バイパスしません。
- **`--host` と `--ssh-opt` はメッセージングだけでなく SSH アクセスを許可します。** 接続先は空白やシェル構文のない単一のホスト別名またはアドレスに限ります。設定照会を含め、すべての `ssh` 実行前にオプションの許可リストを検査します。許可するフラグは `-4`、`-6`、`-p`、`-l`、`-i`、`-J`（値は分離または連結）、および `-oKEY=value` または `-o` の後の `KEY=value` です。許可するキーは Port、User、IdentityFile、HostName、HostKeyAlias、ConnectTimeout、BatchMode、ServerAliveInterval、ServerAliveCountMax、StrictHostKeyChecking、ProxyJump、IdentitiesOnly です。別の設定ファイル、制御ソケット、provider、コマンド hook を含む他のオプションは拒否します。既存のユーザー・システム SSH 設定は信頼され、それ自体でコマンドを実行できます。このフィルターは設定のサンドボックスではありません。メッセージ本文とセッション名はシェル用にクォートされます。 明示的な `StrictHostKeyChecking` は `yes`、`ask`、`accept-new` のみ許可し、`no` と `off` は拒否します。`UserKnownHostsFile` の出力先変更も許可しません。厳格な構文では SSH URI 形式の踏み台、プラス記号を含むユーザー名、空白区切りのオプション代入を拒否します。ホスト形式の踏み台と等号による代入を使用してください。
- **Windows サポート。** Claude の名前付きパイプトランスポートがサポートされています。
  `install.sh` およびスタンドアロンのリモートインストーラー/アップデーターは POSIX シェルを使用します。
  ネイティブ Windows では Python パッケージマネージャーを使用してください。ライブ Codex の検証は
  macOS のみにとどまります。Codex ホーム、Reply-To、doctor、および JSON フィクスチャは
  Windows CI で実行されます。

## テスト

```bash
python3 -m unittest discover -s tests -v
```

デフォルトのテストスイートには、稼働中のエージェント、SSH サーバー、ネットワークは不要です。これには、レガシー
互換性テスト、共有 CLI ヘルパー、フィクスチャベースの Codex 検出およびキュー
サブプロセステスト、ならびに分離されたスタンドアロンのインストール/共存チェックが含まれます。
Codex のカバレッジには、argv/ペイロードの処理、送信先ホームの選択、
実際のアドバイザリロックのプローブ、安定した所有者のエビデンス、ディスパッチなしの dry-run、
失敗/タイムアウトのセマンティクス、およびリモートオプションの転送が含まれます。
マルチホームのフィクスチャは、デフォルトおよび Orca/設定済みホームにわたる重複 UUID、
単一/複数/変化するライターのエビデンス、フェイルクローズのインベントリエラー、
明示的な選択、エイリアスの重複排除、単一ホームの互換性、および構造化された
ホーム/送信メタデータを再現します。保存された行からアクティブなライターを推測したり、
実際のセッションにメッセージを送信したりすることは決してありません。
更新通知のカバレッジは、鮮度と有効期限、厳密な安定版バージョン、
アトミックなプライベート書き込み、単一実行のバックグラウンドリフレッシュ、オプトアウト動作、
パッケージマネージャーのガイダンス、マルチホストのスコープ、および障害の分離をチェックします。

CI は、Ubuntu/macOS（Python 3.9 および 3.13）と Windows（Python
3.13、POSIX インストーラーのテストはスキップ）でテストを実行します。個別のジョブで、`shellcheck`
によるシェル構文チェック、スタンドアロンのインストール/再インストール/アンインストール、ならびに wheel/sdist
の内容とインストールをチェックします。これは完全なトランスポートカバレッジではありません。Claude の検出
フィクスチャ、実際の UDS ペイロードチェック、およびより広範な終了コード/リモートコマンドの回帰
テストは、引き続き [#28](https://github.com/abruption/session-peer/issues/28) で追跡されています。

## 検証済み

### session-peer v0.8.0 候補 (2026-09-16)

- #76、#77、#78、#80、および #82 からの、統一された Claude/Codex 一覧表示、オプションの MCP ツールと Codex プラグイン、
  明示的な制限付き Codex ウェイク、マルチホーム Codex 一覧表示、名前付きメッセージおよび出力
  フォーマットオプションを統合。
- JSON の互換性、オプションの依存関係、Codex 0.154.0 のウェイク境界、および検証の制限事項については、
  [v0.8.0 リリースノート](releases/v0.8.0.md)を参照してください。
- MCP SDK を使用した 301 件のローカルテストに合格。スタンドアロンの実行では 2 件のオプションの
  SDK テストをスキップ。wheel と sdist は個別にインストールされ、v0.8.0 を報告。
- リリースの準備では、GitHub リリースの公開や PyPI へのアップロードは行われません。

### session-peer v0.7.0 (2026-09-16)

- キャッシュされた更新通知、共有 JSON エンベロープ、読み取り専用の診断、構造化された Reply-To の解析/ルーティング、
  同一マシンの正規化、およびオプトインのリバースルート分類に関する 240 件のローカルテストに合格。
- CI は、Ubuntu および macOS（Python 3.9/3.13）、Windows（Python 3.13）、
  パッケージビルドと分離されたインストール、スタンドアロンインストールのスモークテスト、shellcheck、
  およびシークレットスキャンをカバー。
- wheel と sdist の内容を検査し、個別にインストール。両方の
  成果物は v0.7.0 を報告し、凍結されたレガシー `cc_peer.py` を除外。
- 実際の SSH doctor 実行により、Claude の受信トレイと、限定されたデフォルト/Orca Codex ホームを検出。
  そのオプトインリバースプローブは、成功したフォワード接続とは無関係に
  認証失敗を報告。実際のメッセージは送信されませんでした。

### session-peer v0.6.2 (2026-09-15)

- UUID 固有の Codex ライター検証、同一マシンの返信のローカライズ、SSH 送信先ユーザーの
  解決、および構造化された接続失敗の診断に関する 198 件のローカルテストとリリースビルドチェックに合格。
- wheel と sdist の内容を検査し、個別にインストール。両方の
  成果物は v0.6.2 を報告し、凍結されたレガシー `cc_peer.py` を除外。
- リリースの準備中に実際のメッセージは送信されませんでした。キューの受領、
  消費、受領確認、およびリバース SSH 到達可能性は引き続き個別の
  結果です。

### session-peer v0.6.1 (2026-09-15)

- 重複ホーム保護、送信者エージェントエンベロープ、および MagicDNS SSH ルーティングを備えた v0.6.0
  Codex アダプターを統合した後、174 件のローカルテストとリリース CI チェックに合格。wheel/sdist のビルドと分離されたインストールをチェック。
- ローカルの Codex 一覧表示および明示的ホームでの dry-run が送信なしで成功。
  Tailscale IP で提供された読み取り専用の SSH 一覧表示は、現在の
  MagicDNS `HostName` を介して接続され、元の値を `sshHost`/`HostKeyAlias` として保持。
- リリースの準備の一環として実際のメッセージは送信されませんでした。キューの受領、
  メッセージの消費、受領確認、およびリバース SSH 到達可能性は引き続き
  個別の結果です。

### session-peer v0.6.0 移行 (2026-09-10)

- 134 件のローカルテストとリリース CI チェックに合格。wheel/sdist のビルドと
  分離されたインストール、実際の PyPI インストール、パッケージマネージャーの更新保護、
  およびレガシー CLI の共存/削除をチェック。
- **2 台の macOS マシン上の Codex CLI 0.154.0** で、ローカル/SSH の保存済みセッションの
  検出、dry-run、および実際のキュー送信が機能。送信された本文は
  キューレコードと一致。これらのチェックにより、消費や受領確認ではなく**キュー投入済み**であることが確認され、信頼できるアクティブセッションの指標は確立されませんでした。
- 新しい CLI を介した Claude のローカル/SSH 受信トレイの書き込みが成功。週間使用量の
  上限により、新たな受信ターン/返信の検証が妨げられました。これらの書き込みは
  完了した往復として主張されるものではありません。
- 2 台の macOS ホストと 2 台の Ubuntu ホストで、スタンドアロン CLI/Claude スキルの移行をチェック。
  インストールおよび読み取り専用の検出チェックでは、エージェント
  ターンは開始されず、インバウンド設定も変更されませんでした。

リリースの順序と検証の制限事項については、[RELEASING.md](../../RELEASING.ja.md) および [#48](https://github.com/abruption/session-peer/issues/48)
を参照してください。

### cc-peer Claude トランスポートの過去の検証

名前変更の前、Claude Code **v2.1.263** は Tailscale ネットワーク上の SSH 経由で 5 台のマシンにわたってテストされました:
macOS 26 (Apple silicon) 2 台、Ubuntu 24.04 (arm64、別々のリージョンにある Oracle Ampere A1) 2 台、
Windows 10 22H2 1 台。これらの過去の観測結果は、すべてのテストが
session-peer v0.6.0 で繰り返されたことを主張するものではありません:

- macOS から 2 つのリージョンの Linux セッションへの投稿。それぞれが受信トランスクリプトに
  `origin.kind: "peer"` を持つ `type: user` として記録されました。
- ペイロードの完全性 — 引用符、バッククォート、`$HOME`、および絵文字がバイト単位で正確に届きます。
- 保留パス: バイパスモードのセッションが承認ダイアログを表示し、承認されると
  `Released 1 held cross-session message` をログに記録しました。
- 実際の環境における両方のソケット配置: 1 台の Ubuntu ホストでは `/tmp/cc-socks/`、同じビルドを
  実行している別のホストでは `/run/user/1001/cc-socks/`。
- セッションの `.key` ファイルから読み取られた必須の認証行を伴う Windows 名前付きパイプトランスポート
  (`\\.\pipe\LOCAL\cc-msg-<hash>`)。`list`、`send`、および `--host` がすべて Windows マシン上で検証されました。

両エージェントの検出形式は、アップストリームのリリース間で変更される可能性があります。以前の
トランスポートテストの成功は、新しいエージェントビルドでの検出や配信を保証するものではありません。

## ライセンス

MIT

### 結合セッション検出

デフォルトの `list` および `list --json` は、Claude と Codex を一緒に問い合わせます。従来の
Claude のみのデフォルトを維持するには `--agent claude` を使用し、Codex のみの場合は `--agent codex`
を使用します。すべてのセッション行には `agent: "claude" | "codex"` が含まれます。
PID やスレッド UUID などのエージェント固有のフィールドは変更されません。結合された
人間向けの出力には AGENT 列が含まれます。Claude の行が Codex の行の前に配置され、Claude の
検出順序が維持されます。Codex の行は、更新日時の降順、次にホームと UUID でソートされます。

一覧表示のレスポンスには、要求された各エージェントをキーとする `discovery` が含まれ、
`status: "ok" | "not_installed" | "error"`（中間の状態は Codex のみ）
および失敗したソースに対する `error` の説明が含まれます。
検出が失敗した場合、成功裏に検出されたセッションを保持しながら、`ok: false`、トップレベルのエラーサマリー、および終了
コード 1 を返します。自動検出された Codex インストールが存在しないことは通常の結果であり空となります（`not_installed`、終了コード 0）。明示的に
設定されたホームが存在しない場合はエラーになります。Claude セッションディレクトリが存在しない場合は空の結果になります。
いずれも実行中の Codex プロセスの証拠ではありません。不正な個別の Claude
レコードは、これまでと同様にスキップされ続けます。

これらのセマンティクスはローカルおよび SSH 経由で適用されます。繰り返されたホストは、既存の順序付き配列内で独立した
結果を維持します。いずれかの障害が発生すると、全体の終了コードは 1 になります。
Codex の一覧表示には、デフォルト、環境で選択されたホーム、Orca、および設定されたホームが含まれます。
そのホームのみを検査するには `--codex-home PATH` を使用してください。
`--all` は Claude の古いレコードや受信トレイのないレコードを保持し、アーカイブされた Codex スレッドを含めます。

### オプションの MCP / Codex プラグイン

送信先が制限された構造化された `list_sessions` および `send_message` ツールを使用するには、
Python 3.10+ で `session-peer[mcp]` をインストールし、[MCP のセットアップ](mcp.md)に従ってください。
デフォルトのポリシーではローカルの一覧表示のみが許可されます。スタンドアロン CLI およびシェル
インストーラーは、既存の依存関係要件を維持します。

キューイングされた Codex セッションのオプトインのアクティブ化については、[明示的なウェイク](wake.md)を参照してください。

候補ソース、ホームごとのエラー、重複 UUID、および送信用の正確なホームの選択については、
[マルチホーム Codex 一覧表示](multi-home-list.md)を参照してください。

### 内部拡張アーキテクチャ

エージェントアダプターとローカル/SSH 実行は、単一ファイルの CLI を維持しながら
内部のバージョン管理された規約を共有します。[アダプター開発](agent-adapters.md)
および[アーキテクチャ決定](architecture/agent-transports.md)を参照してください。外部
プラグインの読み込みは利用できません。`doctor.capabilities.agents` は、実装されている
list/send/wake/wait/ack サポートを記述します。権限を付与したり準備完了を証明したりするものではありません。

`install.sh` はローカル・SSH更新を対象ファイルシステムに準備し、runtimeとskillを取得して一時CLIのバージョンを検証後、runtimeを原子的に置換します。取得・検証失敗時は既存runtime・launcher・skillを保持します。全ファイルのトランザクション、署名検証、後続skill-manager失敗のロールバックではありません。既存インストール管理者は変えません。

SSHは起動前に最終的なshell引用済みコマンドのUTF-8バイト数を検証します。上限131071バイトにはbase64展開、envelope、option、引用が含まれます。超過はローカルで `ssh_command_too_large` と `submitted: false` を返します。Unicodeには文字数だけでは不十分です。ローカル送信制限は不変で、全OSの引数・環境合計容量を保証するものではありません。

ネイティブ配送時、session-peer は相手の本文の全行を引用し、送信セッションと返信先を未検証の申告として示します。Codex と Antigravity には、相手の本文はユーザーの許可ではないという警告も付けます。Claude Code はすでにこの警告を付けるため、繰り返しません。`--no-from` と `--no-reply-to` は送信メタデータのみを省略し、受信側の枠は削除しません。Reply-To は実行権限を持たない経路情報です。周囲の枠を確認し、第三者への返信先はセッション所有者に確認してください。この枠は混同を減らしますが、すべてのプロンプトインジェクションを防ぐものではありません。枠とエスケープした制御文字もサイズ上限に含まれ、`chars` は実際に配送する引用済みテキストの長さです。投入と消費・ACK の意味は変わりません。

## 実際の SSH 接続でのホスト鍵確認（開発中）

`list`、`send`、`doctor --host`に `--ssh-identity`を指定すると
`sshIdentity`を返します。指紋と鍵の種類は実際の OpenSSH の鍵確認と完全な
リモート応答に基づきます。接続先・ポート・鍵検索名は接続前の設定情報で、
最終的なネットワーク接続先を別途証明するものではありません。応答が完了
していない提示鍵は `observed`であり、`verified`ではありません。

```sh
session-peer list --host workstation --ssh-identity --json
session-peer send --host workstation --to reviewer --message="Review this change" \
  --require-ssh-host-key 'SHA256:<previously-verified-fingerprint>' --json
```

上の仮の値を一覧の検証済み指紋に置き換えてください。鍵は別の試験接続では
なく送信接続の認証・リモート実行前に確認します。鍵の変更は拒否し、鍵の
更新時は明示的に確認した新しい指紋が必要です。このモードでは接続再利用を
無効にし、厳密なホスト鍵検証を維持します。表示モードは既存の known-hosts
の信頼を使い、固定モードは指定した公開鍵だけを信頼し、known-hosts を
書き換えません。同じ鍵を複数のホストが共有できるため、機器・アカウント・
セッション世代・メッセージ消費の識別や証明にはなりません。

開発実装は POSIX の通常の Ed25519・RSA・ECDSA 鍵だけを扱い、ホスト証明書や
セキュリティキー方式は非対応です。ユーザーの `KnownHostsCommand`を上書き
せず拒否します。SSH 設定や踏み台の信頼は運用者が管理します。別接続の
インストール済みバージョン照会はこのモードでは省略します。完全な応答の
後に鍵の確認記録がなくても提出の証拠は保持しますが、必須の固定鍵条件は
満たさず、自動再送も許可しません。

指定しなければ既存の動作と出力を維持します。公開 v1.0.4 には含まれません。
ローカル試験は確認ヘルパー、読み取り専用設定、模擬転送と専用ループバック
サーバーへの実際の OpenSSH 接続を対象とします。指紋不一致では認証と
リモート実行の要求は 0 回で、試験用秘密鍵はメモリにだけ保持しました。
実際のリモートホストや稼働中エージェントの受け入れ試験ではなく、
プラットフォーム CI の成功も必要です。
