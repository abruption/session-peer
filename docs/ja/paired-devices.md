# ペアリングされたデバイスとプライベートリレー (v0.9 ベータ)

このオプションの Unix/Python 3.11+ トランスポートは、オペレーターが定義した Claude、Codex、または登録済みの Antigravity エンドポイントへリクエストを転送します。通常のローカル/SSH コマンドは依存関係のない状態を維持します。これは明示的な CLI ワークフローであり、モバイルアプリケーション、NAT トラバーサル、WireGuard トンネル、自動公開サービスなどはインストールされません。

## インストール

両方のデバイス上の隔離された環境に、PyPI から session-peer v0.9.0 以降をインストールします:

```sh
python3 -m venv ~/.local/share/session-peer-relay/venv
~/.local/share/session-peer-relay/venv/bin/pip install 'session-peer[relay]'
```

relay エクストラは v0.9.0 から PyPI で利用可能になり、ベータ版のままです。公開されたからといって長期的な運用安定性が確立されたわけではありません。以下ではインストールされた `session-peer` 実行可能ファイルを使用してください。管理コマンド（`device`/`relay`）は JSON を出力します。パッケージバージョンが異なる Python 環境を混在させないでください。

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
      "codexHome": "/home/alice/.codex"
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

Linux/macOS ターゲットは両実行ファイルフィールドを省略します。Windows クライアントは通常のローカル CLI を使用します。送信成功も `consumptionConfirmed: false` であり、消費確認には独立した応答が必要です。ポリシーやレシーバーの更新後も unknown 送信を自動再試行しないでください。

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

`submitted`/`queued` は、消費とは区別されたままです。`consumptionConfirmed` は常に false です。モデルの ACK は個別に確認する必要があります。ネイティブ操作は制限されたサブプロセスで実行されるため、アドミッションや失効をブロックすることはできません。永続的なリクエストの意図は、ネイティブな影響が発生する前にコミットされます。同じリクエスト ID と正規のターゲットバインディング/ボディは記録された結果を返します。ターゲットやボディを変更すると競合します。

試行識別子を保持するには `--request-id UUID` を使用します。応答が失われた後は、新しい ID を生成するのではなく元の ID を問い合わせてください:

```sh
session-peer device status --state /private/client-state --peer RECEIVER-FINGERPRINT \
  --request-id ORIGINAL-UUID --admission-file /private/client.token
```

`unknown`（レシーバー/ワーカーのクラッシュを含む）の場合、自動的な再実行は決して許可されません。これは最大 1 回の実行試行であり、厳密に 1 回の消費ではありません。ジャーナルは最大 10,000 件のリクエストで制限され、満杯になると以降の新規送信を拒否します。保留中のエントリを削除したり、unknown を再試行するためにジャーナルをクリアしたりしないでください。保持/ローテーションおよび長期実行フリート管理は、RC の強化作業として残されています。

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
