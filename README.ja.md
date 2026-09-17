# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

[English](https://github.com/abruption/session-peer/blob/main/README.md) · [한국어](https://github.com/abruption/session-peer/blob/main/README.ko.md) · **日本語** · [简体中文](https://github.com/abruption/session-peer/blob/main/README.zh-CN.md)

**ひとつのCLIで、ローカルやSSH接続先のClaude Code・Codexセッションを検索し、メッセージを送信できます。**

別のマシンのセッションに変更のレビュー、進捗報告、作業の引き継ぎを依頼できます。
例えば、SSHホスト`worker`の`api-worker`セッションに変更のレビューを依頼します。
各エージェントの標準の受信箱やキューを使い、受信したメッセージの扱いは受信側が決定します。

## クイックスタート

Python 3.9以上が必要です。基本CLIにサードパーティーのPython依存パッケージはありません。

```bash
pipx install session-peer
# 別の方法: uv tool install session-peer

session-peer list
session-peer list --host worker
```

## 最初のメッセージを送る

以下の名前とUUIDは架空の例です。まず接続先を検索し、実際のセッションに置き換えてください。

```bash
session-peer send --to api-worker --message "進捗を教えてください"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "変更をレビューしてください"
```

`worker`をSSHホストまたはエイリアス、`api-worker`を取得したセッション名に置き換えてください。
例のUUIDは接続先で取得した完全なスレッドIDに置き換えてください。
接続先にはPythonと対象エージェントの受信箱・キューが必要ですが、SSH経由の検索・送信のために
session-peer自体をインストールする必要はありません。

**`posted` / `queued`は送信処理の成功を表し、既読や作業完了を意味しません。**
保存されたCodexスレッドは停止中の場合もあります。完了確認が必要なら、明示的に返信を依頼してください。

## よく使う機能

| 操作 | コマンド / ガイド |
|---|---|
| エージェントで絞り込む | `session-peer list --agent codex` |
| 接続・設定を診断する | `session-peer doctor --host worker` |
| 送信せずに宛先を確認する | `session-peer send --to api-worker --dry-run -m "hello"` |
| JSONで結果を取得する | `session-peer list --output-format json` |
| ファイルからメッセージを読む | `session-peer send --to api-worker -m - < message.txt` |
| オプションのMCPツール / Codexプラグイン | [MCP設定](https://github.com/abruption/session-peer/blob/main/docs/mcp.md) |
| キューに送信したCodexセッションを起動する | [明示的なwake](https://github.com/abruption/session-peer/blob/main/docs/wake.md) |

## インストール方法

`pipx`や`uv`、または有効化した仮想環境で`python -m pip install session-peer`を使えます。
単独実行CLIとエージェントスキルをまとめてインストールするには:

```bash
git clone https://github.com/abruption/session-peer
cd session-peer
./install.sh
# リモートへのインストール: ./install.sh --host worker
```

シェルインストーラーにはPOSIX環境が必要です。ネイティブWindowsではPythonパッケージマネージャーを使ってください。
オプションのMCPツールにはPython 3.10以上と`session-peer[mcp]`が必要です。
[詳細な手順](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#install)を参照してください。

## オプションのv0.9機能

v0.9.0で提供する実験段階の[Antigravity](https://github.com/abruption/session-peer/blob/main/docs/antigravity.md)は、既存TUI内でブリッジを明示的に起動する必要があります。フィルターなしの`list`には稼働中の登録済みブリッジも表示されます。
[デバイスのペアリング・暗号化リレー](https://github.com/abruption/session-peer/blob/main/docs/paired-devices.md)にはUnix、Python 3.11以上、`[relay]`が必要です。デバイスの識別情報を固定し、接続対象は運用者が明示的に許可します。セルフホストのWSSリレーはメッセージを復号できません。NAT越えやホスト済み公開サービスは提供しません。
リレーのベータ版は`pipx install 'session-peer[relay]'`でインストールできます。Antigravityとリレーには追加の運用検証が必要で、公開は長期安定性の保証ではありません。通常のローカル・SSHコマンドは外部依存なしで使えます。

## 送信前の確認

- 正しい接続先アカウントとエージェントのホームを指定してください。独自のCodexホームには検索結果の`codexHome`パスを`--codex-home`で指定します。SSHと受信側の権限が適用されます。
- 通常の送信は停止中のセッションを起動しません。明示的なwakeはエージェントを実行し、利用枠を消費する場合があります。MCPでは別のwake権限が必要です。
- 診断結果を共有する前に、秘密情報・会話・セッションID・個人のパスを伏せてください。

## ドキュメント

- [CLIリファレンス](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md): コマンド、JSON、環境変数、更新、制約、検証履歴
- [診断と返信](https://github.com/abruption/session-peer/blob/main/docs/diagnostics.md) · [複数のCodexホーム](https://github.com/abruption/session-peer/blob/main/docs/multi-home-list.md)
- [cc-peerからの移行](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#moving-from-cc-peer) · [リリース](https://github.com/abruption/session-peer/releases)
- [アダプター開発](https://github.com/abruption/session-peer/blob/main/docs/agent-adapters.md) · [リリース手順](https://github.com/abruption/session-peer/blob/main/RELEASING.md)

4言語のREADMEは同じ入門内容を提供します。詳細な文書は現在英語です。
翻訳を更新する際は、コマンド・要件・動作を英語版に合わせてください。CLIの出力言語は変わりません。

## サポートとセキュリティ

バグや機能の提案は[GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose)、
脆弱性は[非公開の報告フォーム](https://github.com/abruption/session-peer/security/advisories/new)をご利用ください。
[セキュリティポリシー](https://github.com/abruption/session-peer/blob/main/SECURITY.md)もご確認ください。
非公開のご質問や代替の脆弱性報告窓口は、件名に`[session-peer]`を付けて
[support@abruption.dev](mailto:support@abruption.dev)へご連絡ください。
対応期限は保証していません。メールは手動で確認し、公開Issueへ自動変換しません。報告は英語・韓国語で受け付けています。

[MITライセンス](https://github.com/abruption/session-peer/blob/main/LICENSE)。
