# AIを利用したセットアップと運用

[概要に戻る](../../README.ja.md)

このガイドは、コーディングエージェントやAIアシスタントに渡す簡潔な作業指示です。
AIが最小構成を選び、作業と検証を完了し、残る制約を報告できるようにします。
新しい権限を与えたり、送信済みメッセージを受信側が読んだ証拠に変えたりはしません。

## この依頼文をコピーする

角括弧内を書き換え、ブロック全体をAIに渡してください。質問する前に、AIが現在の
マシンとリポジトリを確認できるようにします。

```text
Read AGENTS.md if it exists, then read docs/ai-assistant-guide.md and every guide it links that is relevant to this goal.

Goal: [install session-peer / connect an SSH host / configure MCP / configure Antigravity / configure paired devices / diagnose a failure]
Environment: [operating system, local or remote, SSH alias if any]
Target agents: [Claude Code / Codex / Antigravity]

Work through the goal to a verified result. Reuse authorization already given in this conversation. Before account changes, OAuth consent, DNS or firewall changes, service deployment, reboot, payment, merge, release, or publication, confirm that the action is explicitly authorized. Never ask me to paste secrets into chat; use an existing credential manager or protected file. Start with read-only discovery, use dry-run where available, preserve unknown message outcomes, and do not retry a send merely to turn an unknown result into success.

At the end report: outcome, files or systems changed, commands and tests run, message acknowledgement evidence, remaining limitations, and any rollback instructions. Redact tokens, cookies, session IDs, private paths, conversation text, and private keys.
```

## 最小の範囲を選ぶ

- 同じマシンまたはSSHホスト上のセッションには、基本CLIだけをインストールします。
- 対象エージェントが必要とする場合だけ、追加アダプターを設定します。
- MCPクライアントがsession-peerツールを必要とする場合だけ、MCPを追加します。
- SSHが適さず、運用者が追加の識別・復旧・サービス作業を受け入れる場合だけ、
  ペアデバイスまたは暗号化リレーを使います。

リポジトリにリレーコードがあるという理由だけでリレーを配備しないでください。
通常の利用では、依存関係が少なく単純なローカル・SSH経路を既定にします。

## 必須の作業手順

1. OS、Pythonバージョン、インストール方法、現在のユーザー、接続先アカウント、
   エージェントのホーム、対象がローカル・SSH・MCP・ペアデバイスのどれかを確認します。
2. ファイルを変更する前に、関連ガイドとインストール済みバージョンを確認します。
   検出結果が異なるエージェントホームを示す場合、既定パスを仮定しません。
3. 読み取り専用の調査から始めます。実際のメッセージを送る前に、doctor、list、
   dry-runで正確な対象と転送経路を確定します。
4. 最小限で元に戻せる変更を行います。共有サービスやリモートホストを変更する前に、
   既存設定を保存し、ロールバック方法を記録します。
5. 資格情報をコマンド、ログ、ソース管理、Issueコメント、チャットに含めません。
   保護ファイル、システムの資格情報機能、またはユーザーの資格情報管理を使います。
6. インストール先と実際に求められた転送手段を検証します。ローカルの単体テストだけでは、
   SSH、OAuth、公開WSS、受信モデルの動作は証明できません。
7. 制約を添えて事実を報告します。submitted、posted、queuedは確認応答ではありません。
   完了が重要な場合は、明示的な返信を求めて観測します。

## 基本コマンド

分離されたツールとしてのインストールを優先します。ネイティブWindowsでは、
POSIXシェルインストーラーではなくPythonパッケージマネージャーを使います。

```bash
python3 --version
pipx install session-peer
# Alternative: uv tool install session-peer

session-peer --version
session-peer doctor
session-peer list --output-format json
```

メッセージを配信せずに対象を解決します。リモート接続先の場合だけSSHホストを追加します。

```bash
session-peer doctor --host SSH_ALIAS
session-peer list --host SSH_ALIAS --output-format json
session-peer send --host SSH_ALIAS --to TARGET --dry-run --message "hello" --output-format json
```

dry-runで意図したセッションを一つ解決した後、新しいメッセージを一度だけ送ります。
READMEにある架空の名前や識別子をそのまま使わないでください。

```bash
session-peer send --host SSH_ALIAS --to TARGET --message "Reply with: SESSION-PEER-ACK-UNIQUE-MARKER" --output-format json
```

## セキュリティと承認の境界

- エージェントDB、受信箱、会話記録、Cookie、OAuthトークン、デバイス状態、
  秘密鍵、リプレイ状態、資格情報ファイルを非公開情報として扱います。
- ブラウザプロファイルや資格情報をマシン間でコピーしません。対話的な同意が必要なら、
  ユーザーの認証済みセッションを既に持つブラウザを使います。
- テストを通すために、ホスト鍵確認、認証、ファイアウォール規則、ブラウザ完全性保護、
  サービスのサンドボックスを弱めません。
- インストールや診断の依頼だけでは、アカウント変更、公開、支払い、破壊的な整理、
  再起動、マージ、タグ、リリース、パッケージ公開は承認されません。
- 操作が明示的に承認済みなら、同じ許可を何度も尋ねず、元に戻せる準備と検証を完了します。
- タイムアウトや応答消失の後も、要求IDと操作IDを保持します。重複操作を作らず、
  状態を照合します。

## 完了報告

AIは次の形式で短く報告します。

```text
Outcome:
Changes:
Validation:
Acknowledgement evidence:
Remaining limitations:
Rollback:
```

新しいシェルで意図したコマンドを実行できて初めて、インストール完了です。
転送設定は、要求されたローカル・SSH・MCP・ペア経路を実際に試して初めて完了です。
リレー配備では、サービスの健全性、永続状態、再起動、バックアップ、復元も検証します。
除外または中断したテストを合格と表現しないでください。

## 関連ガイド

- [CLIリファレンス](cli-reference.md)
- [診断と返信](diagnostics.md)
- [MCP設定](mcp.md)
- [エージェントアダプター](agent-adapters.md)
- [Antigravity](antigravity.md)
- [Wakeの動作](wake.md)
- [ペアデバイスと暗号化リレー](paired-devices.md)
- [セキュリティポリシー](../../SECURITY.ja.md)
