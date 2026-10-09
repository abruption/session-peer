# ペアリングされたデバイスとプライベートリレー (v1.0)

## 接続設定ガイド（明示的な選択）

`session-peer setup` はインストールを変更せず、ローカル・SSH と Relay を案内します。
ローカル・SSH は標準ライブラリの CLI だけ、Relay は Unix Python 3.11 以上と
任意の `[relay]` 依存関係が必要です。Node.js は不要です。不足時は元の管理ツールの
コマンドまたは単体 CLI と分離した環境を案内し、インストール実行・管理ツールの
切替はしません。スキル・プラグインはランタイムやホストサービスを導入せず、
公開サービスの可用性も保証しません。

```bash
session-peer setup
session-peer setup --mode local
session-peer setup --mode ssh --host worker
session-peer setup --mode relay --interactive --role receiver
session-peer setup --mode relay --interactive --role client --no-browser
```

両端で Relay ガイドを実行すると、初期化、ブラウザー・コード承認ログイン、名前付き
登録、ポリシー・招待作成、ペアリングごとに承認を求めます。クライアント初期化結果の
識別子を明示的に信頼し、現在の対象・実行ファイル・ホームを選びポリシーを確認します。
既定はそのデバイス・対象だけの `list`、`send` は別途選択です。秘密の招待ファイルを
10分以内に安全に渡します。登録はペアリングではなく、ペアリングはエージェント承認
でもありません。テストメッセージは送信しません。

画面のない環境では `--action init|login|enroll|policy|invite|pair|ready` と `--apply`
で各操作を承認します。対象・デバイス・パス・経路のオプションは `--help` にあります。
`plan`、`targets`、`--apply` なしのプレビューは Store・鍵・DB・ジャーナルの初期化や
移行を行いません。DB 一覧はチェックポイント済みの診断情報で、現在の権限の証明
ではありません。受信ロックと既知のサービスファイルを報告しますが、全サービスの
発見は保証せず既存サービスも変更しません。ポリシーは0600の秘密の新規ファイル作成
または同一ファイル再利用のみで、異なるポリシーの上書き・権限拡張はしません。
適用前に再確認しますが、その後もネイティブセッションが同一実体である保証はありません。
既存の鍵・DB が不完全、または有効なローテーション鍵がない場合は、初期化を承認
しても手動復旧が必要であり、設定ツールは再作成しません。

秘密の `setup.json` に元の登録 UUID・名前・サーバー・鍵識別子と登録要求全体を送信前に永続保存します。
中断・応答紛失後は同じ状態・名前で `enroll` を明示的に再開し、既存 API が同一操作を
照合します。新規変更へ置換せず、意図・鍵・要求（証明書 PEM の空白を含む）の変更はネットワーク接続前に拒否します。期限切れは `login` を
やり直しますが UUID は保持します。招待作成結果が不明なら運用者の照合を待ちます。
提示コマンドと `--action receiver --apply` は前景で Ctrl-C または `--seconds` まで
実行します。自動起動・サービス・プロファイルは導入せず、既存 launchd・systemd 管理
は別です。`--action cancel --apply`、EOF、Ctrl-C は設定待機のみ止め、完了登録・元の
送信は取り消しません。ディレクトリ0700・ファイル0600を守り、ジャーナル・トークン・
招待の秘密を共有しないでください。認証済み probe・一覧による状態確認は消費・ACK・
実行承認・可用性の証明ではありません。不確かな送信を再送せず、手動コマンドも使えます。

このオプションの Unix/Python 3.11+ トランスポートは、オペレーターが定義した Claude、Codex、または登録済みの Antigravity エンドポイントへリクエストを転送します。通常のローカル/SSH コマンドは依存関係のない状態を維持します。これは明示的な CLI ワークフローであり、モバイルアプリケーション、NAT トラバーサル、WireGuard トンネル、自動公開サービスなどはインストールされません。

受信側はデバイス認証前の直接接続を最大 16 本、Relay に attach された接続を最大 2 本まで許可し、認証済み接続 8 本とは別に管理します。TLS はネットワークとスケジューリングの遅延を含めて 2 秒以内に完了する必要があります。TLS 後、クライアント証明書のない初期ペアリング接続には、単一のペアリング要求と応答を完了するためにさらに 2 秒が与えられます。認証済み要求の期限は 45 秒のままです。この短い期限は正常な遅い接続も拒否する場合があります。アイドル状態または TLS が遅い直接ソケット 8 本があっても、ペアリング済みの直接接続と Relay 要求を受け付ける余地が残ります。ただし、認証前の直接接続枠 16 本がすべて埋まると、ペアリング済みの直接接続も拒否される可能性があり、予約された Relay 枠 2 本も飽和する場合があります。任意のフラッド攻撃に対する可用性は保証されません。超過ソケットや受信側のシャットダウン開始後のソケットには処理タスクを作成しません。集計した入場カウンターは ID を含めずに拒否とクリーンアップ失敗を保持します。明示的に有効化した `receiver_admission` イベントは、固定カウンターと許可リスト内の理由を 1 分に最大 1 回報告します。アプリケーションの自動再試行は有効になりません。

## 接続失敗の診断と安全な接続再試行

`no_authenticated_route` は `retryAllowed:false` と `consumptionConfirmed:false` を維持します。`routeFailures` は経路ごとの最後の `stage`、許可リスト内の `reason`、`attempts` を示します。限定された `attemptHistory` は各試行の段階・理由・`elapsedMs` を保持し、HTTP 拒否には `httpStatus`、WebSocket の切断には `closeCode` が含まれる場合があります。制御、入場、アップグレード、attach、ピア TLS、probe の失敗を区別し、URL・認証情報・生の例外・メッセージ本文は記録しません。2 回目で成功した場合は `setupDegraded:true`、`setupAttempts:2`、`setupFailureHistory` が付き、正常な安定性試験の合格とは見なしません。

**WebSocket アップグレード前の制御・入場タイムアウト**のみ、0.5 秒後にもう一度 Relay に接続します。attach、ピア TLS、probe のタイムアウトは再試行しません。WebSocket アップグレードのタイムアウトも、origin で既に受信側ルームがペアリングされた可能性があるため再試行しません。新しい入場チケットとチャネルを使い、消費済みチケットやエージェントへのメッセージを再送しません。HTTP 拒否、認証/証明書エラー、不明な失敗も再試行しません。直接経路が選択されると Relay 試行は取り消せます。送信後の応答喪失は引き続き `unknown` で、再送や経路切り替えは行いません。この限定的な緩和策は公開経路の障害解消を証明しません。デプロイ後に実際の ACK と長時間検証を再実施してください。

受信側は安全化した `relay_connection_failed` 警告を stderr に毎分最大一回出力します。通常のアイドル期限切れに見える切断は失敗警告と分けます。`device serve --diagnostic-events` と `relay serve --diagnostic-events` を明示すると、ルーム・attach・切断の段階、所要時間、許可リスト内の理由と切断コードだけを stderr に記録します。既定では無効で、デバイス ID、ルーム名、URL、ヘッダー、認証情報、本文は記録しません。Relay メトリクスにはルーム作成・ペアリング、各レグへの attach 送信、期限切れのカウンターも追加されます。attach 送信はクライアント受信の証明ではありません。受信側の `idle_expiry_like` はサーバー原因の確証ではありません。

WebSocket 切断の `closeSource` はコードの受信・送信方向を区別します。Relay のカウンターは受信側先着とクライアント先着のルームを区別します。`receiverWsAgeMs` は待機時間であり、接続の健全性を証明しません。ペアリングと受信側の `attach_received`・ピア TLS イベントの時刻を照合してください。

`stream_close.closeCode` はリモートから受信した切断コードです。`1006` は切断フレームを受信しなかったことを意味し、レグの停止を示す可能性があります。`peer_closed` は相手レグの終了後に Relay がこのレグを閉じた場合、`remote_going_away` は Relay の切断要求なしにリモート側が 1001 を送った場合です。`receiverRoleBusy`・`clientRoleBusy` は同じルームで拒否された重複レグの数です。受信側の値が増える場合、受信側の再接続中に Relay が古いレグを保持している可能性があります。

明示的に有効にした Relay と受信側のライフサイクルイベントには `eventTimeUtcMs`（UTC Unix ミリ秒）が含まれます。クライアントは Relay 接続の試行ごとにランダムな UUIDv4 `attemptId` を生成し、成功結果または試行ごとの失敗メタデータに記録します。新しい Relay はこの ID をペアリング済みルームイベントに記録し、attach 通知で新しい受信側へ渡します。受信側の `attach_received` と peer-TLS イベントにも同じ ID が記録されます。この ID は ID 情報、ルーム名、リクエスト ID、メッセージ内容から導出されず、認可や再送の安全性も変えません。失敗を帰属させるには、完全一致する `attemptId` が Relay のルーム一つと受信側レグ一つだけに対応することを確認し、時計のずれを考慮して UTC 時刻を比較してください。イベントが欠ける、重複する、または旧バージョンのレグの場合は、時刻や集計カウンターから推測せず `unattributed` と記録してください。

公開経路の停止が再発した場合、明示的に有効にした Relay の `stream_close` イベントで、各レグの `ingressFrames`/`ingressBytes`、`egressCompletedFrames`/`egressCompletedBytes`、最初と最後の UTC フレーム時刻を比較できます。これは暗号化された WebSocket フレームの数であり、メッセージ数ではありません。送信完了は Relay のソケット send が戻ったことだけを示し、Cloudflare、受信側、TLS、アプリケーションがバイトを消費した証明ではありません。同じルームと `attemptId` の両方のロールを比較してから受信側イベントと照合してください。イベントが欠けるか一致が曖昧なら `unattributed` のままにします。カウンターだけで Cloudflare、OCI、中間ホップの責任は特定できません。メタデータの時刻とフレームサイズからも活動が分かるため、opt-in ログは非公開で期間を限定して保持してください。

1 秒以上開いていた待機ルームが Relay により正常に閉じられた場合、受信側はバックオフを増やさず 0.5 秒後に再接続します。その他の失敗と 1 秒以内に閉じたルームは、引き続き最大 5 秒まで指数バックオフします。Relay レグは両端で 10 秒の WebSocket ping 間隔・タイムアウトを使うため、停止したレグを約 40 秒ではなく約 20 秒で検出します。これは再接続の空白を減らすだけで、停止したネットワーク経路を修復するものではありません。

## インストール

両方のデバイス上の隔離された環境に、PyPI から session-peer v0.9.0 以降をインストールします:

```sh
python3 -m venv ~/.local/share/session-peer-relay/venv
~/.local/share/session-peer-relay/venv/bin/pip install 'session-peer[relay]'
```

relay エクストラは v0.9.0 から PyPI で利用できます。パッケージ公開はホスト型 Relay の可用性を保証しません。以下ではインストールされた `session-peer` 実行可能ファイルを使用してください。管理コマンド（`device`/`relay`）は JSON を出力します。パッケージバージョンが異なる Python 環境を混在させないでください。

## アイデンティティ、ポリシー、ペアリング

各エンドポイントで実行します:

```sh
session-peer device init --state /private/device-state
```

返される `device` は、その公開証明書のフィンガープリントです。各デバイスは独自の秘密鍵を保持します。その秘密鍵をリレーや他のエンドポイントに絶対にコピーしないでください。新しいプライベートな状態ディレクトリ（0700）を使用してください。ユーザーデータを暗黙的に chmod するのではなく、安全でない既存のファイル/ディレクトリは拒否されます。このデータベースは session-peer 独自のデバイスジャーナルであり、Codex の会話 DB やオントロジーの vault DB ではありません。

受信側のマシンで 0600 のポリシーファイルを作成します。クライアントのフィンガープリント、エージェントターゲット、およびホームを個別に確認した値に置き換えてください。例:

```json
{
  "targets": {
    "review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/home/alice/.codex",
      "codexBin": "/home/alice/.local/bin/codex"
    }
  },
  "peers": {
    "CLIENT-64-HEX-FINGERPRINT": {
      "capabilities": ["list", "send"],
      "targets": ["review"]
    }
  }
}
```

Claude バインディングは `agent: claude` と、ホームを指定しない正確なセッション名/PID を使用します。Antigravity バインディングは `agent: antigravity`、`target: antigravity:UUID`、および `antigravityHome` を使用します。まず [そのブリッジ手順](antigravity.md) を使用して TUI を登録してください。レシーバーはこれらのエージェントセッションを所有するアカウントとして実行します。単に他のユーザーのセッションにアクセスするためだけにレシーバーを root として実行しないでください。

ペアリングはデバイス鍵の所持を証明します。**ネイティブエージェントへのアクセスを許可するものではありません**: 受信ポリシーでフィンガープリント、操作、およびターゲットエイリアスを個別に許可する必要があります。ピアは実行可能ファイル、ホーム、wake フラグ、SSH 送信先、または任意のネイティブコマンド引数を指定することはできません。ポリシーの変更はレシーバーの再起動後に有効になります。制限事項: 設定可能なターゲットは 8 個、ポリシーデバイスは 128 台です。

launchd や systemd で起動した受信側は、ログインシェルではなくサービスマネージャーの最小限の `PATH` を引き継ぎます。macOS/Linux の Codex 対象では、対象 TUI が使う `codex` のディレクトリを受信サービスの `PATH` に追加するか（例: launchd の `EnvironmentVariables.PATH`、systemd の `Environment=PATH=...`）、管理者が所有するバインディングの `codexBin` に `/opt/homebrew/bin/codex` のような `codex` で終わる絶対パスを指定します。受信側は起動時に実行可能な通常ファイルを検証し、シンボリックリンクを実際の対象に解決します。Unix Codex では `codexPython` を使用しません。既存の稼働中 writer と home の検証は維持されます。実際の送信前に同じ受信環境で `send --dry-run` を確認してください。実行ファイルが見つからなければ、送信前に `codex_executable_not_found` で拒否します。結果が unknown の送信を自動再試行しないでください。

## ネイティブ Windows Codex 用の WSL レシーバー

同じ Windows ワークステーションで Codex セッションと CLI がネイティブ実行される場合、レシーバーは WSL2 で実行します。ペアリング済みピアではなく、オペレーターポリシーがマウント済み状態ホームと実行可能ファイルの両方を固定します:

```json
{
  "targets": {
    "windows-review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/mnt/c/Users/alice/.codex",
      "codexBin": "/mnt/c/Users/alice/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe",
      "codexPython": "/mnt/c/Python313/python.exe"
    }
  },
  "peers": {
    "CLIENT-64-HEX-FINGERPRINT": {
      "capabilities": ["list", "send"],
      "targets": ["windows-review"]
    }
  }
}
```

`codexHome` はローカル Windows ドライブ上の絶対 WSL パスです。`codexBin` と必須の `codexPython` はそれぞれ `codex.exe` と `python.exe` という名前の絶対パスで、管理者が管理する実行可能な通常ファイルでなければなりません（シンボリックリンク不可）。Microsoft Store の実行エイリアスではなく、インストール済みのネイティブ Windows Python 3.9+ を指定します。

固定引数の `/usr/bin/wslpath` で変換し、standalone コアをネイティブ Python にストリーミングします。シェルは使用しません。Windows SQLite/WAL と writer ロックをネイティブ側で検査し、一意の所有者・同一ユーザー SID・プロセス作成時刻・Codex 実行ファイルを確認します。Linux SQLite で Windows DB を開いたり writer 検査を省略したりしません。非アクティブ・曖昧・検査不能な writer は拒否します。既存の WSL ポリシーにも `codexPython` が必要で、未指定・不正な場合は `native_windows_python_required` または `invalid_codex_python` で拒否します。

Linux/macOS ターゲットでは `codexPython` を省略し、上記のように `codexBin` を任意で設定できます。Windows クライアントは通常のローカル CLI を使用します。送信成功も `consumptionConfirmed: false` であり、消費確認には独立した応答が必要です。ポリシーやレシーバーの更新後も unknown 送信を自動再試行しないでください。

ネイティブローカル CLI 対応は、すべての Windows SSH シェルへの対応を意味しません。ソースをストリーミングする SSH には動作する python3 と POSIX 互換リモートシェルが必要です。Windows Store 実行エイリアスでは不十分です。ローカルのネイティブ CLI または Python をインストールした WSL SSH エンドポイントを使用してください。

直接接続のレシーバーを起動します（デフォルトはループバック。他のマシンの場合は到達可能なプライベートインターフェースを選択してください）:

```sh
session-peer device serve --state /private/device-state \
  --policy /private/receiver-policy.json --bind PRIVATE-IP --port 3770 --seconds 3600
session-peer device invite --state /private/device-state \
  --direct PRIVATE-IP:3770 --out /private/invitation.json
```

信頼できるチャネル経由で招待状をクライアント上のプライベートファイルに転送し、10 分以内に実行します:

```sh
session-peer device pair --state /private/client-state \
  --invite /private/invitation.json --route direct
```

招待状には、ワンタイムシークレットと固定（ピン留め）されたレシーバー証明書が含まれています。保留中のペアリングは、同じデバイス鍵を証明することで失われたコミット応答を照合できます。証明書のすり替えは失敗します。招待状ファイルにはシークレットが含まれているため、ペアリング後に削除してください。IPv6 の直接アドレスは `[address]:port` を使用します。直接アクセスには TCP の到達可能性が必要です。ルーター、ファイアウォール、VPN、NAT の自動設定はありません。

## プライベートリレーのプロビジョニング

信頼できる管理マシンで実行します:

```sh
session-peer relay provision --out /private/new-room --room personal
```

これにより、`accounts.json`（アドミッションハッシュ）、`receiver.token`、および `client.token` が作成されます。各トークンは 0600 ファイルに保管してください。リレーサーバーにはハッシュのみがインストールされます。レシーバー/クライアントのアドミッショントークンは、プライベートなデバイス識別鍵とは別に配布してください。トークンはリレーへのアドミッションを制御し、内部のピン留めされた TLS がペアリングとネイティブアクセスを個別に制御します。リレーがエンドポイントの秘密鍵を取得することは決してありません。

```sh
session-peer relay serve --accounts /private/accounts.json \
  --bind 127.0.0.1 --port 3769 --seconds 3600
```

永続的な Linux ホスティングの場合、wheel を `/opt/session-peer-relay/venv` にインストールし、ハッシュを `/etc/session-peer-relay/accounts.json` に保存して、レビュー済みの [systemd テンプレート](../../deploy/examples/static-account/session-peer-relay.service) を適合させてください。有効化する前に `systemd-analyze verify` で検証してください。テンプレートは、動的ユーザー、ケーパビリティなし、アクセス不可のホームディレクトリ、読み取り専用システム、プライベートな一時ディレクトリ、および明示的なリソース制限で動作します。これは**ブラインドリレー**用であり、ネイティブのレシーバー用ではありません。後者はエージェントが所有するランタイムパスとソケットが必要です。

ループバックリレーを専用ホスト名の HTTPS/WSS リバースプロキシの背後に配置します:

```caddyfile
relay.example.com {
    reverse_proxy 127.0.0.1:3769
}
```

この例は、既存の本番環境の Caddyfile をリロードするよう指示するものではありません。デプロイメントの既存の証明書/DNS ポリシーを使用し、正確な差分を検証し、既存の WebSocket ユーザーを確認して、ロールバックを計画してください。リロードやエッジの更新によって接続が切断される可能性があります。URL/クエリにトークンを含めてはなりません。ヘッダー/ボディのデバッグログは避けてください。プロキシは IP、ホスト名、アドミッションメタデータを認識しますが、アプリケーションメッセージとペアリングシークレットはエンドポイントの TLS 1.3 の内部に保護されたままです。外部 TLS の検証を無効にしないでください。

レシーバーを `--relay wss://relay.example.com/v1/connect` および `--admission-file /private/receiver.token` で起動し、その `--relay` URL（およびオプションで `--direct`）を指定して招待状を作成します。クライアントは `--route relay` および `--admission-file /private/client.token` を使用してペアリングできます。平文の `ws://` は、隔離されたテスト用のループバックに限定されています。レシーバーの準備完了出力はローカルリスナーを確認するものであり、`relayReadyConfirmed: false` は意図的にエンドツーエンドのリレー準備完了を主張するものではありません。

## 一覧取得、送信、および照合

```sh
session-peer list --device RECEIVER-FINGERPRINT --device-state /private/client-state \
  --relay-admission-file /private/client.token --json
session-peer send --device RECEIVER-FINGERPRINT --device-state /private/client-state \
  --relay-admission-file /private/client.token --device-route auto \
  --to review --message 'Please inspect the proposed change' --json
```

`--to` は受信側ポリシーで許可されたターゲットエイリアスであり、任意のネイティブ UUID やシェルコマンドではありません。`--agent` は許可された一覧結果をフィルタリングします。デバイスルーティングは `--host` と排他的です。ネイティブホーム/バイナリ/SSH オプションは受信側ポリシーに属し、ペアリングされたリクエストでは拒否されます。ここでは `--wake` および明示的な SSH Reply-To はサポートされていません。説明的な From ヘッダーは保持されますが、自動的なペアリング Reply-To ルートは通知されません。このベータ版では MCP デバイス宛先は実装されておらず、既存のローカル/SSH ポリシーは変更されません。

自動ルーティングは、認証済みの準備完了プローブを競争させ、両方が同時に完了した場合は direct を優先します。選択された **1 つ** の接続でアプリケーションリクエストを送信します。不確実な送信の後にフェイルオーバーして再送信することはありません。パスを強制するには、`--device-route direct` または `relay` を設定してください。メッセージはエンベロープの後で 32 KiB UTF-8 に制限されます。`--dry-run` はネイティブへの送信を行わずに、設定されたネイティブターゲットを解決します。

32 KiB は送信者エンベロープを含む UTF-8 メッセージのバイト上限です。エスケープ済みのアプリケーション JSON 全体は 64 KiB、運用者のバインディングパスを含む内部 worker JSON は 256 KiB 以下に収めます。エスケープの多い本文は 32 KiB 未満でもアプリケーション上限に達する場合があります。確実なサイズ超過はアプリケーション書き込みやネイティブ journal intent の前に `refused` となります。その後の不確実な I/O 失敗は `unknown` のままで、自動再送を許可しません。

`submitted`/`queued` は、消費とは区別されたままです。`consumptionConfirmed` は常に false です。モデルの ACK は個別に確認する必要があります。ネイティブ操作は制限されたサブプロセスで実行されるため、アドミッションや失効をブロックすることはできません。永続的なリクエストの意図は、ネイティブな影響が発生する前にコミットされます。同じリクエスト ID と正規のターゲットバインディング/ボディは記録された結果を返します。ターゲットやボディを変更すると競合します。

試行識別子を保持するには `--request-id UUID` を使用します。応答が失われた後は、新しい ID を生成するのではなく元の ID を問い合わせてください:

```sh
session-peer device status --state /private/client-state --peer RECEIVER-FINGERPRINT \
  --request-id ORIGINAL-UUID --admission-file /private/client.token
```

`unknown`（レシーバー/ワーカーのクラッシュを含む）の場合、自動的な再実行は決して許可されません。これは最大 1 回の実行試行であり、厳密に 1 回の消費ではありません。ジャーナルは最大 10,000 件のリクエストで制限され、満杯になると以降の新規送信を拒否します。保留中のエントリを削除したり、unknown を再試行するためにジャーナルをクリアしたりしないでください。v1.0 CLI はジャーナルを自動ローテーションせず、長期運用のフリートも管理しません。未解決の結果を破棄しない範囲で容量と保持を計画してください。

## 失効、再起動、および回復

```sh
session-peer device peers --state /private/device-state
session-peer device revoke --state /private/device-state --peer CLIENT-FINGERPRINT
```

失効は新しい承認済み作業を防止し、追跡されているチャネルを閉じます。すでに受け入れられたネイティブ呼び出しは完了する可能性があるため、その ID を照合してください。レシーバーの再起動では、アイデンティティ、ペアリング、およびジャーナルが保持されます。リレーの再起動では接続が切断されます。エンドポイントは再接続し、新しいアドミッションを取得します。新しい送信の前に準備完了プローブが成功する必要があります。リレーチケットは短命で使い捨てです。接続とフレームは制限されています。リレー上には平文/オフラインのネイティブリクエストのキューは存在しません。

デフォルトのフォアグラウンドサービスのライフタイムは 1 時間です。`--seconds 0` はサービスマネージャー用の永続的な動作を明示的に選択します。SIGTERM で停止し、クリーンアップの前に制限されたネイティブシャットダウンを待機してください。一貫した SQLite スナップショットと識別ファイルを使用してプライベート状態をバックアップし、そのバックアップを保護し、アクティブな DB をその WAL とは無関係に単独でコピーしないでください。識別証明書の有効期限は 1 年です。期限切れの際は、デバイスのピンを暗黙的に置き換えるのではなく、計画的な新しいアイデンティティの作成/再ペアリングが必要です。

隔離された実稼働検証ではループバック/SSH トンネルを使用しており、VPN オフでのパブリック WSS の準備完了を確立するものではありません。パブリックパイロット、再起動/エージングテスト、およびリリースゲートは [アクティブな開発計画](relay-development-plan.md) で追跡されています。

### ペアリングされたルートの更新

ペアリングされたデバイスがアドレスを変更した場合でも、ピン留めされたアイデンティティと配信ジャーナルを保持します。これにより保存されたルートが置き換えられます。保持したいすべてのルートを含めてください。

```sh
session-peer device routes --state ./client-state --peer RECEIVER_FINGERPRINT \
  --relay wss://relay.example.com/v1/connect
```

ルートの変更によって新しいアイデンティティが承認されたり、失効したデバイスが復活したりすることはありません。制限された実稼働 Antigravity テストおよび残りのリリースゲートについては、[パブリックパイロットの証拠](relay-public-pilot-2026-09-17.md) を参照してください。

## 公開Relayへの初回接続

Python 3.11+のmacOS/Linux(WindowsはWSL)と別途Relay extraが必要です。skill/pluginだけでは導入されません。新規pipx環境は `pipx install --python python3.11 'session-peer[relay]'` を使い、既存環境は元の管理者を維持してください。standaloneはlocal/SSH用のまま、Relay環境を別途選びます。両端で個別のprivate stateを使い、`FULL-UUID`を新しい操作UUIDに置き換えます。不確実な応答では同じUUIDを保持します。

```sh
session-peer device init --state /private/device-state
session-peer device login --state /private/device-state --server https://relay.abruption.dev
session-peer device enroll --state /private/device-state --name laptop --operation-id FULL-UUID
```

上記schemaのreceiver policyを作り、`session-peer` `device serve --state /private/device-state --policy /private/receiver-policy.json --relay wss://relay.abruption.dev/v1/connect --login --seconds 3600` を起動します。別terminalで `session-peer` `device invite --state /private/device-state --relay wss://relay.abruption.dev/v1/connect --out /private/invite.json` を実行し、招待を安全にclientへ渡します。login・enroll済みclientで10分以内に `session-peer` `device pair --state /private/client-state --invite /private/invite.json --route relay --login`、続いて `session-peer list --device RECEIVER-ID --device-state /private/client-state --device-route relay --relay-login --json` を実行します。receiverを動かし続けてください。enroll、pairing、native権限は別です。送信前はdry-run、queuedはACKではありません。自動install/login/retryはしません。一般403/404や `no_authenticated_route` からreceiver停止を断定しません。既知のlogin欠落・失効、device照会失敗のみ区別し、不確実な送信は再送せず照合します。

ペアリング済み受信側は、認証した TLS 証明書のフィンガープリントを引用本文の外に表示します。これはペアリングした機器の鍵を識別するもので、人物やネイティブエージェントのセッションを識別するものではありません。本文中の From や Reply-To の申告で置き換えることはできません。引用後の本文、フィンガープリント、警告は、記録の開始やネイティブ配送の前に 32 KiB の上限に収まる必要があります。Reply-To の信頼性は周囲の枠の信頼性を超えません。第三者への経路はセッション所有者に確認してください。この枠は承認を回避せず、プロンプトインジェクションへの完全な防御も保証しません。
