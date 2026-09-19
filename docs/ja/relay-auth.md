# プライベートリレーの制御と認証 (RC候補)

ステータス: #69 の実装候補であり、デプロイ済みの本番サービスではありません。
以下の control から relay への規約には、Python 所有者の最終的な
インターフェース指示が組み込まれています。実際のクロスサービス統合は別個のゲートのままです。本プロジェクトは、通常の Python インストール環境に対してリスナー、
OAuth アカウント、Node 依存関係を一切追加しません。

## 信頼境界

`control/` は、独立した Node 22/24 React/Vite + BetterAuth **1.7.5** サービスです。
GitHub と Google のみが構成されたログインプロバイダーです。プロバイダーの
認証情報が不足していても、偽のログインが公開されることはありません。パスワードによるログイン／登録は無効化されています。メールアドレスではなく、
OAuth アカウント ID が認可のアイデンティティとなります。すべての control
API 呼び出しは、ネイティブの BetterAuth セッション、明示的なホワイトリストまたはコミット済みの
公開サインアップ記録、そして内部ユーザー ID の所有権を再度チェックします。サインアップを一時停止しても、
すでにコミットされた公開アイデンティティが追放されることはありません。
メールに基づく自動的なアカウント連携は許可されません。同じメールアドレスを持つ別のプロバイダーを有効にしても、
既存ユーザーのデバイスが暗黙的に付与されることはありません。

ホワイトリスト専用の運用は、フェイルクローズのデフォルトとして維持されます。オペレーターは制限のない
検証済み公開サインアップを明示的に有効にできます。検証されたプロバイダーのコールバックは、
BetterAuth がユーザーを作成する前にそのアイデンティティを予約します。オペレーターが後に新規サインアップを
閉鎖した場合でも、コミットされたアイデンティティは引き続き使用可能です。アカウントおよびセッションの作成も
BetterAuth の DB フックによってチェックされます。拒否されたコールバックが永続的な
公開スロットを消費したり、control へのアクセス権を付与したりすることはありません。

Web の `/login`、`/device`、`/devices` は、本番環境で HTTP-only セキュアクッキーを使用します。
デバイスページにはコード、クライアント、スコープが表示され、コード一致の
確認と明示的な承認／拒否が要求され、予期しないリクエストに対する警告が表示されます。
追加の control クレームテーブルは、検証済みコードを単なるユーザーではなく**正確なブラウザ
セッション**にバインドします。BetterAuth 自身のファーストパーティクレームはユーザーにバインドされますが、
このラッパーはより厳密なセッション制限を提供します。

CLI ログインは BetterAuth `deviceAuthorization()` および `bearer()` を使用します:

- `POST /api/auth/device/code`, `client_id=session-peer-cli`.
- 提供された検証 URI を開き、認証を行ってコードを確認／承認します。
- 提示された間隔（5秒）で `POST /api/auth/device/token` をポーリングします。
  グラントは `urn:ietf:params:oauth:grant-type:device_code` です。
- `access_token` は**ファーストパーティの BetterAuth セッショントークン**であり、OAuth
  プロバイダーアクセストークン、OAuth 保護リソーストークン、またはリレー JWT ではありません。
- これを構成済みの control オリジンに対してのみ `Authorization: Bearer …` として送信します。
  トークンは BetterAuth セッション（24時間）とともに期限切れになります。リフレッシュトークンや
  永続的なバックグラウンドサインインの保証はここでは追加されません。OS 認証情報の保存と
  CLI UX は、Python/クライアント所有者の統合責任となります。
- ブラウザのクッキーセッションのみが検証／承認／拒否を行うことができ、bearer による承認は
  拒否されます。デバイスコードの有効期間は 5 分です。拒否、期限切れ、ポーリング制限、
  および 1 回限りの引き換えには、固定された BetterAuth 実装が使用されます。

OAuth コールバック（オペレーターのアプリ構成が必要）:

```
https://relay.abruption.dev/api/auth/callback/github
https://relay.abruption.dev/api/auth/callback/google
```

## 最終 control API (未リリース候補)

JSON 本文のみ、最大 16 KiB です。未知のプロトコルフィールドは拒否されます。
認証済み API リクエストは 60 回/ユーザー/分に制限されます。制限は、所有者あたり 16 個のアクティブな
チャレンジ、廃棄標識を含む合計 32 個のデバイスアイデンティティ、および 4096 個の永続
操作です。容量を確保するために操作記録が暗黙のうちに削除されることは決してありません。
保留中の操作を含め、制限はフェイルクローズします。

| Endpoint | Result / checks |
| --- | --- |
| `GET /api/relay/devices` | Only caller-owned devices; no certificates/secrets |
| `POST /api/relay/challenge` | `{operation: "register" | "admission", payload}`; owner/operation/full-payload bound nonce, 60-second window |
| `POST /api/relay/devices` | Initial registration or key renewal; payload + `challengeId`, new-key `proof`, old-key `previousKeyProof` for renewal |
| `GET /api/relay/operations/:id` | Owner-only pending/committed result, for lost-response reconciliation |
| `POST /api/relay/admission` | Admission payload + `challengeId`, `proof`; short-lived ES256 relay JWT |
| `POST /api/relay/devices/:principal/revoke` | Owner session; no lost-device key requirement; permanent tombstone |

### 登録および証明書の更新

```text
{ principal, certificatePEM, keyGeneration, name, operationId, expectedGeneration }
```

`principal` は、証明書とは分離された、固定されたランダムな 64 文字の小文字 16 進数デバイスアイデンティティです。`operationId` は、結果が
判明するまで保持される UUID v4 です。初回登録には、初回証明書 DER
SHA256 と等しい principal、存在しないデバイス、`keyGeneration=0`、
および `expectedGeneration` の省略が必要です。更新には、同一所有者の既存のアクティブな principal、
`expectedGeneration=current generation` および `keyGeneration=expectedGeneration+1` が必要です。
サーバーが増加分を計算／チェックするため、クライアントがジャンプやロールバックを選択することはできません。
最大世代は 2147483647 です。所有者、principal、既存の名前は
更新時に保持されます。`name` は初回登録に使用されます（更新時は既存の名前を
送信してください）。名前は制御文字を含まない 1〜80 文字です。

証明書の入力は、P-256 鍵を持ち、現在の有効期間が 60 秒を超えて残っている、8192 バイト以下の
公開 PEM 証明書が正確に 1 つです。新しい証明書は
保存されている証明書と異なる必要があります。同一鍵による証明書の更新は許可されています。
所持はパブリック CA 検証ではなく署名によって確立されます。登録が
エンドポイントの E2EE ペアリング／PIN 認可を置き換えることは決してありません。秘密鍵は絶対に送信しないでください。

初回登録と更新はどちらもチャレンジ操作 **register** を使用し、その後に
`POST /api/relay/devices` を実行します。新しい鍵の `proof` は、返された正確な `proofMessage` に署名します。
更新にはさらに、**同じメッセージ**に対する旧鍵の `previousKeyProof` が必要です。
ログインのみによる置き換えは許可されません。保存されている古い鍵の所持のみが
古い証明書の有効期限を無視し、期限切れ証明書の更新を可能にします。
新しい証明書の有効期間および通常の入場有効期間は引き続き強制されます。古い
鍵を紛失した場合は、所有者による失効と新しい principal が必要になります。失効したアイデンティティは、
登録、更新、または再試行によって復活することは決してありません。

ミューテーション、チャレンジの消費、およびコミットされたレシートは 1 つの SQLite トランザクションです。
更新は未処理の所有者チャレンジを無効化し、状態を即座に再公開し、
世代の変更を跨ぐ入場署名を拒否します。

### 操作結果 / 再試行の境界

登録チャレンジは、復帰する前に所有者／operationId／ペイロードダイジェストを永続的に
予約します。ミューテーション前の所有者検索は以下を返します:

```json
{ "operationId": "<fixed UUID v4>", "committed": false }
```

完了した登録および `GET /api/relay/operations/:id` は以下を返します:

```json
{
  "operationId": "<fixed UUID v4>",
  "committed": true,
  "principal": "<unchanged ID>",
  "keyFingerprint": "<SHA256 certificate DER>",
  "keyGeneration": 1
}
```

未知の ID および別の所有者の ID はどちらも 404 を返します。保留中の予約は
チャレンジの期限切れ後も維持されます。同一の完了した所有者／ペイロード／operationId による再試行は、
チャレンジが期限切れになった場合やデバイスが後から失効した場合であっても、別のミューテーションや証明の実行を行うことなく、
保存されている過去のレシートを返します。ペイロードが変更された場合、
または異なる所有者による operationId の再利用は拒否されます。レシートは**現在のデバイス
ステータスではありません**。現在の世代／失効状態についてはデバイス一覧を使用してください。失効したレシートの
再試行によってデバイスが復活することはありません。公開に失敗するとミューテーションはロールバックされ、
その操作は未コミットのままになります。その間、ヘルスチェックは公開が回復するまで
入場をブロックします。応答が失われた場合は ID を保持してステータスを照会してください。新しい操作を
作成したり、すでに受け入れられている可能性があるネイティブエージェントの送信を自動的に再試行したりしないでください。

### チャレンジ証明と時間単位

レスポンス: `{challengeId, nonce, issuedAt, expiresAt, proofMessage}`。すべての control
API および公開状態の `issuedAt`/`expiresAt` の値は、UNIX の**秒**単位の数値です。
BetterAuth のネイティブ認証 API はインストールされた SDK の形状を保持します。`expires_in` および
`interval` は相対秒です。クライアントは、返された正確な UTF-8 メッセージに
P-256 ECDSA/SHA256 で署名し、DER 署名はパディングなしの base64url としてエンコードされます:

```text
session-peer-control-v1:
<origin>
<operation>
<challengeId>
<nonce>
<SHA256 of server-canonical payload JSON>
```

クライアントは `session-peer-control-v1:` プレフィックスを要求し、残りの部分を
パース／再構築することなく、返された正確な文字列に署名します。末尾の改行はありません。サーバーの正規化は operationId/expectedGeneration を
含むすべての登録フィールドをバインドするため、クライアント側での JSON 正規化は不要です。
入場証明には登録済み証明書の現在の鍵を使用します。登録証明には
提出された証明書を使用し、更新の previousKeyProof には保存されている古い鍵を使用します。

`keyFingerprint` は小文字の **SHA256(証明書 DER)** であり、既存の
Python fingerprint/keyId の意味と一致します。`cnf.jwk` はその証明書の
公開鍵から抽出されます。これは **SHA256(SPKI DER) ではありません**。JWK 単体では証明書
DER を再構築できません。リレーは署名された証明書のフィンガープリントを現在の状態と比較し、
認証された control 発行者による cnf への署名済みバインディングを信頼した上で、cnf を
使用して所持を検証します。JWK/SPKI ハッシュを計算してこのフィールドと比較しないでください。
署名用の `kid` は個別の control 署名鍵（現在は SPKI ハッシュ）を識別するものであり、
デバイス証明書のフィンガープリントではありません。

### 入場トークンとリレー交換

入場ペイロード:

```text
{ role: "client" | "receiver", devicePrincipal, receiverPrincipal }
```

両方の principal はアクティブであり、同一の内部ユーザー ID によって所有されている必要があります。receiver
ロールは自身を識別しなければなりません。Room = SHA256(UTF8(userId + NUL + receiverPrincipal)) であり、
ドメイン接頭辞はありません。呼び出し元が room/user/issuer/audience/TTL を設定することはできません。

JWT は **ES256**、認識された署名 `kid`、`typ=JWT` を使用します。クレームは `iss`/`aud` =
構成されたリレーオリジン、`sub` = 内部の不透明なユーザー ID、`devicePrincipal`、
`receiverPrincipal`、`keyFingerprint`、`keyGeneration`、`role`、`room`、`iat`、
`exp` (iat+60秒)、`jti`、`cnf.jwk` (公開 EC P-256 のみ、秘密鍵素材なし) です。
レスポンス `{token, expiresAt, room}` は UNIX 秒の有効期限を使用します。プロバイダー
アクセストークンもファーストパーティセッショントークンも、Python リレーには渡されません。

リレー交換:

```http
Authorization: Bearer <JWT>
X-Session-Peer-Proof: <unpadded base64url DER ECDSA signature>
```

デバイスは、P-256 ECDSA/SHA256 かつ末尾の改行なしで、正確な UTF-8 の `session-peer-admission-v1:` + **JWT 全体**に
署名します。これは control の nonce 証明とは別個のものです。
Python は、アトミックな 1 回限りの jti 消費およびクッキー発行の前に、署名／発行者／対象者／時刻／有効期間<=60／認識された kid、
公開 P256 cnf、現在の状態／所有者／世代／フィンガープリント／ロール／受信者／room、および
所持を検証しなければなりません。失敗した証明によって別のデバイスの jti が消費されてはなりません。リプレイストレージは、
JWT の有効期限まで再起動／複数ワーカーを跨いで検証される必要があります。これらは Python 統合ゲートです。
control 形式のテストは、Python レシーバーがそれらを実装していることを証明するものではありません。
OAuth ログイン／登録は、エンドポイントの E2EE ペアリング／PIN ポリシーを置き換えるものではありません。

## オペレーターメトリクス

`GET /api/admin/metrics` はブラウザセッション専用のオペレーターエンドポイントです。オペレーターとは、
`SESSION_PEER_ALLOWED_ACCOUNTS` に明示的にリストされているプロバイダーアイデンティティを少なくとも
1 つ持つ認証済みユーザーであり、公開サインアップによってこのロールが付与されることは決してありません。
レスポンスには、集計されたサービスヘルス、サインアップステータスと件数、デバイス数、
操作数、および現在の公開状態リビジョンが含まれます。メールアドレス、
プロバイダーアカウント ID、内部ユーザー ID、デバイス principal、証明書、トークン、または
シークレットは決して返されません。React ルートは `/admin/metrics` であり、30 秒ごとに
集計ビューを更新します。

`admin.abruption.dev` は既存の Authelia 管理ポータルのままです。その
ルートおよび `/api/*` ルートはすでに認証コンソールによって所有されています。正確な
`/session-peer` ポータルリンクを使用するか、
`https://relay.abruption.dev/admin/metrics` へのリダイレクトによって session-peer を統合してください。既存の
管理コンソールを置き換えたり、その上にプロキシしたりしないでください。ポータルリダイレクト
後も、リレーオペレーターチェックの権威は維持されます。

### アトミックな公開状態と規約の移行

```text
{ schemaVersion: 1, revision, issuer, audience, issuedAt, expiresAt,
  jwks: { keys: [public signing JWK with kid/alg/use] },
  devices: { principal: { userId, keyFingerprint, generation, revoked } } }
```

名前、メールアドレス、証明書、セッション/OAuth トークン、秘密鍵は含まれません。ユーザー ID は
仮名の所有権メタデータです。公開 HTTP ルートがディレクトリを配信することはありません。
単一ファイルのバインドではなく、読み取り専用の**ディレクトリバインド**により、プライベート DB／署名鍵／オントロジー／その他のサービスファイルへの
アクセス権を与えることなく、アトミックな置き換えが公開されます。
プライベートな兄弟要素を露出させるように DynamicUser の親ディレクトリを拡張しないでください。

すべての公開は、デバイスのミューテーション・トランザクションやファイル置換の前に、control
SQLite データベースで新しい安全な整数の `revision` を永続的に予約します。
予約はミューテーションのロールバック後も存続します。ギャップは許容されますが、再利用は許可されません。SQLite は
同期 FULL を指定した WAL を使用します。起動時、既存の公開ファイルより
古いカウンターは拒否されます。Python はさらに最高リビジョンとコンテンツハッシュを永続化します。
完全なホストのロールバックには依然として外部のリカバリーフェンシングが必要です。復元された
カウンターが追いつくのを待つ方法を、失効したデバイスを復活させるために使用しては決してなりません。

公開ディレクトリは、umask 0077 の下であっても明示的に 0755 です。新しい各状態
ファイルは、fsync/rename/ディレクトリ fsync の前に fchmod 0644 されます。そのプライベートな親ディレクトリと
プライベートデータベース／署名素材は保護されたままです。ディレクトリのバインドマウントは、
ディレクトリの置き換えなしにアトミックなファイル置換を認識します。

状態は **60 秒**ごとに再公開され、**issuedAt+180 秒**で期限切れとなり、
ミューテーション発生時に即座に公開されます。Python は、状態の欠落／不正／
期限切れ、または issuedAt>now+5 秒の場合にフェイルクローズします。入場ごとに再読み込みを行い、
既存の接続を毎秒再チェックして、失効／ローテーションされたセッションを切断します。JWT の TTL
だけではアクティブセッションの失効になりません。実際の接続／時計／再起動の挙動には、
Python/ステージングでの検証が必要です。公開の失敗は DB のミューテーションをロールバックし、
ヘルスを失敗としてマークします。SQLite とファイルは分散アトミックトランザクションではありません。
公開に続いて DB コミットが失敗すると一時的にアクセスが拒否される可能性があります。その失敗した
操作を成功として報告したり、古い状態チェックをバイパスしたりしないでください。

最終規約は、未公開の候補 55ff3bb/6815e1e/fae9029（SPKI デバイスハッシュ、
ミリ秒チャレンジ、個別ドメインの rotate エンドポイント、2s/10s
状態）に優先します。古い成果物／クライアントをこの検証機能と混在させないでください。起動時、保存された
SPKI デバイスの行は `contract_migration_required` により拒否されます。古い
デバイスのフィンガープリントや操作履歴を暗黙的に再解釈することは決してありません。また、登録スキーママーカーは、
世代の再採番やレシートの破棄を行うことなく、以前のデータが投入された候補データベースを
拒否します。新しい隔離された候補状態を使用するか、
古い状態を保持するオペレーターレビュー済みの明示的なマイグレーションを計画してください。ここでは自動的な
認証情報／デバイス状態の削除は行われません。

## ビルド、シークレットおよび運用

`control/` から:

```
npm ci
npm run typecheck
npm test
npm run build
```

本番環境では、1 つの HTTPS オリジン（ワイルドカードの信頼済みオリジンは不可）、
32 文字以上のランダムな BetterAuth シークレット、オプションの緊急時用
プロバイダーアカウント ID ホワイトリスト、明示的な公開サインアップスイッチ、および有効化された
オペレーター所有の OAuth アプリを明示的に構成する必要があります。**非シークレット**の値の例:

```
NODE_ENV=production
SESSION_PEER_CONTROL_ORIGIN=https://relay.abruption.dev
SESSION_PEER_ALLOWED_ACCOUNTS=[{"provider":"github","accountId":"REPLACE_WITH_NUMERIC_PROVIDER_ID"}]
SESSION_PEER_PUBLIC_SIGNUP=true
SESSION_PEER_CONTROL_DATA=/var/lib/session-peer-control/private
SESSION_PEER_RELAY_PUBLIC=/var/lib/session-peer-control/relay-public
GITHUB_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
GOOGLE_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
```

ホワイトリストが欠落している場合、オペレーターが明示的に `SESSION_PEER_PUBLIC_SIGNUP=true` を
設定しない限り、デフォルトですべて拒否されます。公開サインアップには招待リストやユーザー数の
上限はありません。これを `false` に戻すと新規登録は締め切られますが、以前に
コミットされた公開アイデンティティと明示的なホワイトリストエントリは引き続き使用可能です。
プロバイダーの検証は最大 10 分間保留中のアイデンティティ予約を作成し、
SQLite の `IMMEDIATE` トランザクションにより同時コールバックが同一のアイデンティティで
競合するのを防止します。OAuth シークレットおよび BetterAuth シークレットは
`*_SECRET_FILE`/`BETTER_AUTH_SECRET_FILE` および systemd の LoadCredential から取得されます。
これらをコミットしたりブラウザの認証情報をコピーしたりしないでください。オペレーターが管理する
ローカル／テスト環境向けに未加工の環境変数値もサポートされていますが、環境ダンプを出力してはなりません。
有効化された GitHub/Google プロバイダーについては、デプロイオーバーライドに LoadCredential エントリと対応する
`GITHUB_CLIENT_SECRET_FILE`/`GOOGLE_CLIENT_SECRET_FILE` パスを追加してください。
中途半端に構成された認証情報が存在しない場合は起動が拒否されます。無効化されたプロバイダーは、
クライアント ID もシークレットファイルも構成されていてはなりません。

`npm run db:migrate` を実行する際は同じ保護された構成を使用し、その後に
`npm start` を実行してください。マイグレーションは明示的です。本番環境が起動ごとに
認証スキーマを暗黙的に書き換えることはありません。ローカル開発では localhost
または 127.0.0.1 でのみ HTTP が許可され、本番シークレットを使用してはなりません。状態はソースの外部かつ
iCloud の外部になければなりません。プライベート署名鍵はモード 0600 で一度だけ生成され、
再起動後も存続します。すべてのプライベート DB／状態の親ディレクトリは所有者専用です。バックアップには、
control SQLite の一貫したスナップショット、署名鍵、および OAuth ポリシーを個別の
保護されたリソースとして含める必要があります。これは中央オントロジー SQLite では**ありません**。

`deploy/session-peer-control.service` はインストールテンプレートであり、有効化された
ユニットではありません: ループバック 3770、DynamicUser、排他的 flock ライターロック、プライベート永続
状態、保護された homes/system/kernel、読み取り専用の control ツリーのみを公開する隔離された
`/opt` マウント、アクセス不能な他サービスの data/config/log パス、ケーパビリティ
なし、256MiB/50% CPU/64 タスク。
デプロイでは、`/usr/bin/node` にサポート対象の Node を提供し、ビルドされた
control ツリーをインストールし、サービスのプライベート状態で認証スキーマを移行し、プロバイダーの
認証情報／ポリシーを設定する必要があります。起動ロックにより、systemd control の同時書き込みが防止されます。
手動起動でも同じロックを使用する必要があります。インストール時にロックの所有権／状態パスを確認してください。
Node のメモリ／ランタイムの挙動には、依然としてステージングでの観察が必要です。

Caddy 統合では、`/api/control/*`、`/api/auth/*`、`/api/relay/*`、および
Web ページ／アセットを、既存の Python リレーの WebSocket／入場パスから 3770 に振り分ける必要があります。
統合された成果物とリソースの隔離がステージング所有者とレビューされるまでは、Caddy を
リロードしたりホスト名を公開したりしないでください。未知のパスは 404 を返します。
`.env` やソース／状態ファイルは静的アセットではありません。セキュリティヘッダーには
no-store、厳格な CSP、アンチフレーミング、no-referrer が含まれます。HTTP サーバーは
X-Forwarded-Host も任意の Host 値も信頼しません。プロキシは構成された
オリジン Host を保持する必要があります。サーバーはループバックソケットから自身の認証 IP ヘッダーを上書きします。信頼できない
X-Forwarded-For が認証リミッターを回避することはできません。この保守的な候補は
ローカルプロキシ全体で認証エンドポイントの制限を共有するため、マルチユーザー容量には依然として
ステージングでの測定が必要です。複数の Set-Cookie ヘッダーは個別に保持されます。
リクエストの URL／ヘッダー／本文／トークンのログ記録は有効になっていません。診断
メッセージには固定の運用エラーコードのみが含まれます。

## 検証境界

ローカルテストでは、実際の BetterAuth／SQLite／device-code エンドポイント、生成されたフィクスチャ
P-256 証明書と暗号、およびループバック上のコンパイル済み HTTP サーバーを使用します。認証
フィクスチャは、プライベートな一時 control DB にテストユーザー／アカウント／セッションをシードします。
個別のコールバックテストでは、フィクスチャ認証情報と署名済みフィクスチャ Google トークンを使用して、アウトバウンドの
GitHub/Google トランスポートのみをモックします。これらは固定されたネイティブの OAuth
state/PKCE/callback/allowlist/account-linking パスを実行します。プロバイダーへのリクエストは送信されません。
**本番用の偽 OAuth エンドポイントや認証バイパスは存在しません**。OpenSSL はテスト専用です。
テストは、所有者の隔離、ポリシー失効、CSRF、正確なブラウザセッションクレーム、
コードの承認／拒否／期限切れ／引き換え、チャレンジの期限切れ／リプレイ／改ざん、鍵
交換の拒否、デュアルキーローテーション、世代の競合、同一メッセージに対する previousKeyProof、所有者専用の永続操作の
検索／保留中／コミット済み／再オープンされた DB での再試行、
期限切れ証明書の更新、失効した廃棄標識、アトミックな状態公開の失敗
および非シークレット状態、
ループバック／静的／Host／ボディ制限の挙動、拒否された偽造 Google ID トークン、および
ホワイトリスト外／同一メールアドレスの異なるプロバイダーアイデンティティをカバーしています。これらは、認証情報を用いたプロバイダー
OAuth、Mac ユーザーブラウザ、Python JWT 統合、24 時間稼働、または実際の Claude
クォータ回復のテストではありません。RC PR の前に、それぞれを個別に記録してください。本実装によって
マージ、リリースタグ、公開、またはリモートプッシュが承認されることはありません。

公式リファレンス（インストールされた 1.7.5 ソースに対して実装を検証済み）:
- https://better-auth.com/docs/plugins/device-authorization
- https://better-auth.com/docs/plugins/bearer
- https://better-auth.com/docs/concepts/users-accounts

## 登録例

これらの省略された形状は説明用です。新しいチャレンジを取得し、返された
正確な `proofMessage` に署名してください。証明書、署名、およびチャレンジのプレースホルダーは、
実行可能な認証情報ではありません。

初回チャレンジペイロード (`operation: "register"`):

```json
{
  "principal": "<initial certificate DER SHA256>",
  "certificatePEM": "<device certificate>",
  "keyGeneration": 0,
  "name": "laptop",
  "operationId": "11111111-1111-4111-8111-111111111111"
}
```

そのペイロードに加えて `challengeId` と新しい鍵の `proof` を
`POST /api/relay/devices` に送信します。初めてローテーションする場合は、同じ principal を保持し、
`expectedGeneration: 0` および `keyGeneration: 1` を設定し、交換用
証明書と新しい安定したローテーション操作 UUID を指定します。同じチャレンジメッセージに対して
古い鍵からの `previousKeyProof` を追加します。不確実な応答が発生してもその操作 ID を
保持し、`GET /api/relay/operations/<operationId>` を使用して所有者専用の過去のレシートを
照会してください。

初回登録では `expectedGeneration` を省略しなければなりません。これはローテーションで必須です。
古い候補で使用されていた世代を推測したり暗黙的に変換したりしないでください。
`tests/test_control_integration.py` にある実行可能な Node/Python フィクスチャは、
登録、入場、失効した認証情報、所有者間の拒否、および応答消失を
伴うローテーションをカバーしています。シードされたフィクスチャセッションは、実際の OAuth の証拠ではありません。
