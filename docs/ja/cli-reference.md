# session-peer CLI リファレンス

[概要に戻る](../../README.ja.md)

コマンドの詳細な動作、インストールオプション、トランスポートの制限、および過去の検証結果について以下に説明します。

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

<a id="install"></a>
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
パッケージマネージャーは `session-peer` コマンドをインストールしますが、[Claude Code スキル](#the-skill)はインストールしません。
Claude が自律的に session-peer を使用できるようにスキルを追加するには:

```bash
mkdir -p ~/.claude/skills/session-peer
curl -fsSL -o ~/.claude/skills/session-peer/SKILL.md \
  https://raw.githubusercontent.com/abruption/session-peer/main/skills/session-peer/SKILL.md
```

<a id="installsh"></a>
### install.sh

コマンドとスキルの両方をワンステップでインストールします。エアギャップ環境の
ホストや、SSH 経由でのリモートデプロイに使用します:

```bash
git clone https://github.com/abruption/session-peer && cd session-peer

./install.sh                          # this machine
./install.sh --host build-server      # a remote machine, over SSH
./install.sh --host web-01 --host db  # several at once
```

これにより、`session_peer.py` が `~/.local/share/session-peer/` に配置され、
[Claude Code スキル](../../skills/session-peer/SKILL.md) が `~/.claude/skills/session-peer/` にインストールされ、
`~/.local/bin/session-peer` がリンクされます。既存の cc-peer ファイルは保持されます。
削除するには `./install.sh --uninstall [--host ...]` を使用します。

`session-peer update` は、最新の GitHub リリースからスタンドアロンプログラムを更新します。
`./install.sh --host <host>` は、このチェックアウトのプログラムとスキルを SSH 経由でプッシュします。
`session-peer update --host <host>` は、インストールされているバージョンが異なる場合
または存在しない場合にのみプログラムをプッシュします。変更を加えずに報告するには `--check` を追加します。
パッケージ管理されたインストールおよびリモートの制限事項については、[更新](#updating)を参照してください。

**リモートインストールではファイルが SSH 接続自体を通じてプッシュされる**ため、ターゲットには
インターネットアクセスが不要です。スタンドアロンファイルをインストールするには、`python3` と SSH
アクセスが必要です。メッセージングには、送信先に選択したエージェントのネイティブな受信トレイまたはキューも
必要です。

あるいは、インストーラーを完全にスキップして、1つのファイルだけをコピーすることもできます:

```bash
curl -O https://raw.githubusercontent.com/abruption/session-peer/main/session_peer.py
chmod +x session_peer.py
```

<a id="the-skill"></a>
### スキル

スタンドアロンインストーラーは、プログラムを `~/.local/share/session-peer/` に配置し、
スキルを個別に `~/.claude/skills/session-peer/SKILL.md` に配置します。スキルの配置場所は、
デフォルトの前に `CLAUDE_CONFIG_DIR`、次に `ANTHROPIC_CONFIG_DIR` を優先します。
スキルは Claude によるターゲットとメッセージの選択を案内し、Python プログラムが
検出とトランスポートを実行します。これをインストールしても、Codex プラグインは
インストールされず、いずれのエージェントの権限やインバウンド設定も変更されません。

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

<a id="updating"></a>
### 更新

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
比較します。リモートバージョンの方が新しい場合でもプッシュするため、配布する前にまず確認し、
ローカルプログラムを更新してください。リモートのコピーが GitHub から取得することはありません。
リモートバージョンのプローブは `~/.local/share/session-peer/session_peer.py` のみを検査し、
pip/pipx/uv のインストールは検査しません。リモート更新は、そのスタンドアロンパスと CLI
リンクをインストールします。パッケージ管理されたリモート CLI の場合は、代わりにそのホスト上の
独自のマネージャーでアップグレードしてください。

ローカルまたはリモートの `update` のいずれも、Claude スキルを更新しません。スタンドアロンプログラムと
スキルの両方を更新するには、目的のリリースのチェックアウトから `install.sh` を再実行してください。
ローカルの `session-peer update --check` および `session-peer update` は、自動通知で
使用されるのと同じキャッシュも設定します。

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
機能します。`--codex-home` は明示的にそのコピーを選択しますが、アクティビティの証明にはなりません。
この明示的ホームの形式は、アクティブライターの解決機能より前のリリースでも
機能します。

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

UUID が複数の既知のホームに存在する場合、session-peer は一致する各ホーム内の正確な
`thread-writer-locks/<uuid>.lock` を検査します。カーネルのアドバイザリロックを個別にプローブし、
2 回の安定した `lsof` 観測を通じてオープンしているプロセスを関連付けます。同一ユーザーの安定した
Codex ライターがちょうど 1 つだけ存在する場合にそのホームが選択され、そのエビデンスは
キューへの投入直前に再度チェックされます。空きロックや古いロックは、単にそのファイルが
存在するというだけでは選択されません。

アクティブなライターが 0 または複数存在する場合、`lsof` の欠落、権限エラー、PID/inode の変動、
および競合するエビデンスがある場合は、キューイングの前にフェイルクローズ（安全側に倒して失敗）します。アーカイブされた保存済みコピーも
カウントされます。読み取り不能または互換性のない既知のデータベースや、設定されたデータベースの欠落も、
暗黙的な送信を妨げます。無関係なインベントリやアクティビティのチェックをバイパスするには、`--codex-home` を
明示的に選択してください。解決されたシンボリックリンクのエイリアスおよび重複するパスは、1 つのホームとしてカウントされます。

競合する保存済みホームがない場合、ネイティブのキュー動作が維持されます。`list` は、
`--codex-home` が正確に 1 つを選択しない限り、既知のホームを集約します。一般的なファイルシステムスキャンやプロセス
環境の検査は行われず、プロセス引数は公開されません。アクティビティの
検査は、SSH 経由を含め、送信先マシン上で実行されます。POSIX の
`flock` または `lsof` を備えていないプラットフォームでは、競合するホームを自動的に解決できないため、
`--codex-home` を使用する必要があります。未設定/カスタムのレイアウトや、チェック後に作成された
コピーは見落とされる可能性があります。送信を行わずに、選択されたホーム、限定された候補、
実行可能ファイル、およびサポートされている状態 DB スキーマを検査するには、`session-peer doctor` を使用してください。

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

共通エンベロープ内で、Codex send JSON には `target: {agent, id}`、
`status: queued`（dry-run の場合は `validated`）、`chars`、`dryRun`、およびオプションの
`queueId` が含まれます。また、以下も含まれます:

- `codexHome`: 送信者側の推測ではなく、解決された絶対的な送信先ホーム。
- `codexHomeResolution`: スキーマバージョン付きの `status`、`selected`、`reason`、および
  限定された候補のエビデンス。ステータスは `explicit`、`selected`、`ambiguous`、または
  `unknown` です。候補には、プロセスの引数や環境変数の値を含めることなく、
  保存されたスレッド、ライターロック、および安定した所有者 PID の事実が開示されます。
- `submitted`: キュー CLI が正常に完了した後にのみ `true`、dry-run の場合は `false`。
- `consumptionConfirmed`: 常に `false`。queued も validated も消費を確立するものではありません。

エラーの場合は共通エンベロープの `ok` が `false` に設定され、`error` が追加され、
ホームのエビデンスが障害の原因となった場合は `codexHomeResolution` が含まれます。
タイムアウトの場合は送信結果が不明です。エラー時に `submitted` が存在しないことを、
何もキューイングされなかった証拠として解釈してはなりません。一覧表示の結果は送信を
記述するものではなく、送信/消費フィールドはありません。

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
- **`--host` と `--ssh-opt` は ssh 設定と同程度に信頼されます。** これらは `ssh` に渡されるため、これらを制御する者が接続先を制御することになります。ssh にローカルコマンドを実行させるような値（`ProxyCommand` など）は拒否され、`-` で始まる `--host` は即座に拒否されます — しかし、エージェントに対して `session-peer` を許可リストに登録する場合、単なるメッセージングだけでなく SSH を許可するものとして扱ってください。メッセージ本文とセッション名にはそのようなリスクはありません。シェルに到達する前にクォートされます。
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
