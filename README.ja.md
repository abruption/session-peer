# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![PyPIの週間ダウンロード](https://api.pepy.tech/badge/session-peer/week)](https://pepy.tech/projects/session-peer)
[![PyPIの月間ダウンロード](https://api.pepy.tech/badge/session-peer/month)](https://pepy.tech/projects/session-peer)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

[English](https://github.com/abruption/session-peer/blob/main/README.md) · [한국어](https://github.com/abruption/session-peer/blob/main/README.ko.md) · **日本語** · [简体中文](https://github.com/abruption/session-peer/blob/main/README.zh-CN.md)

**ひとつのCLIでローカルやSSH接続先のClaude Code・Codexセッションを検索し、メッセージを送れます。**

別のセッションに変更のレビュー、進捗報告、作業の引き継ぎを依頼できます。
標準の受信箱やキューを利用し、応答方法は受信側のエージェントが決定します。

<a id="see-it-in-action"></a>

## デモ

![CodexがClaude Codeに依頼を送り、明示的なACKを受け取るデモ](https://raw.githubusercontent.com/abruption/session-peer/main/docs/assets/session-peer-live-codex-claude.gif)

session-peer 1.0.2による実際のローカル通信です。CodexがClaude Codeに依頼を送り、
`ACK DEMO-READY`を受け取ります。CLI出力とメッセージの抜粋を匿名化して再描画した
約22秒のアニメーションで、画面録画ではありません。送信成功だけではACKを意味しません。

## クイックスタート

<a id="installation-options"></a>

### インストール

Python 3.9以上が必要です。基本のローカル・SSH CLIに外部Python依存パッケージはありません。
現在の安定版：**1.0.2**。

```bash
pipx install session-peer
session-peer --version
session-peer list
```

uvを使う場合は `uv tool install session-peer` を選べます。ネイティブWindows、
仮想環境のpip、単独スクリプト・SSHのインストール方法は
[インストールガイド](https://github.com/abruption/session-peer/blob/main/docs/ja/cli-reference.md#install)を参照してください。

SSH検索では、例のホスト `worker` を実際のホストまたはエイリアスに置き換えてください。
その後、架空のセッション名と完全なUUIDを検索結果の接続先に置き換えてください。

```bash
session-peer list --host worker
session-peer send --to api-worker --message "進捗を教えてください"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "変更をレビューしてください"
```

SSH接続先にはPythonと対象エージェントの標準受信箱・キューが必要ですが、
session-peer CLIのインストールは不要です。独自のCodexホームは検索結果の
`codexHome` を `--codex-home` で指定し、`--dry-run` で送信せずに検証できます。
セッションを所有する接続先アカウントを使ってください（`--host USER@HOST`）。
SSHと受信側の権限が適用されます。

**`posted` / `queued` は受信箱・キューへの提出の確認であり、消費・ACK・作業完了の確認ではありません。**
必要なら明示的な返信を依頼してください。通常の送信は停止中のCodex接続先をデフォルトで拒否し、
起動もしません。結果が不確かな送信を自動で再試行しないでください。

オプションの [エージェントスキル](https://github.com/abruption/session-peer-skill) はランタイムとは
別にインストールします。Skills CLIのコマンドはインストールガイドを参照してください。

### 更新

ランタイムをインストールした管理ツールで更新してください。

```bash
pipx upgrade session-peer
# または: uv tool upgrade session-peer
# または、対象の仮想環境内で: python -m pip install --upgrade session-peer
```

ローカルのインストールでは、`session-peer update` は単独スクリプトのランタイムファイルを置き換えます。
パッケージ版には更新方法を案内します。このコマンドはスキルを更新しません。
元のインストールツール（Skills CLI、または同梱コピーの `install.sh`）を使ってください。
[更新の詳細とリモートでの制約](https://github.com/abruption/session-peer/blob/main/docs/ja/cli-reference.md#updating)を参照してください。

<a id="documentation"></a>

## ドキュメント

- [文書マップ](https://github.com/abruption/session-peer/blob/main/docs/ja/README.md)：ユーザー、統合、運用、開発ガイド
- [CLIリファレンス](https://github.com/abruption/session-peer/blob/main/docs/ja/cli-reference.md)：オプション、JSON、インストール方法、移行
- [診断と返信](https://github.com/abruption/session-peer/blob/main/docs/ja/diagnostics.md) · [複数のCodexホーム](https://github.com/abruption/session-peer/blob/main/docs/ja/multi-home-list.md)
- [AIを利用したセットアップ](https://github.com/abruption/session-peer/blob/main/docs/ja/ai-assistant-guide.md) · [プロジェクトサイト](https://abruption.dev/projects/session-peer/) · [リリースノート](https://github.com/abruption/session-peer/releases)
- [リリース手順](https://github.com/abruption/session-peer/blob/main/RELEASING.ja.md)

[デバイスのペアリング・暗号化Relay](https://github.com/abruption/session-peer/blob/main/docs/ja/paired-devices.md)には
Unix、Python 3.11以上、`session-peer[relay]`、固定した識別情報と明示的な受信ポリシーが必要です。
パッケージの公開はホスト型サービスの可用性を保証しません。
ブラインドRelayはアプリケーションのメッセージ内容を復号できません。
[MCP・Codexプラグイン](https://github.com/abruption/session-peer/blob/main/docs/ja/mcp.md)にはPython 3.10以上と
`session-peer[mcp]` が必要で、MCP wakeには `send` と `wake` の両方の権限が必要です。
[Wake](https://github.com/abruption/session-peer/blob/main/docs/ja/wake.md)は明示的に依頼した場合だけ実行し、
ターンの開始、利用枠の消費、プロジェクトファイルの変更を伴う場合があります。
[Antigravityブリッジ](https://github.com/abruption/session-peer/blob/main/docs/ja/antigravity.md)は実験段階です。

英語が正本で、韓国語、日本語、簡体字中国語のガイドとの整合性を保ちます。
翻訳はCLIの出力言語を変更しません。

## ライセンス

[MIT](https://github.com/abruption/session-peer/blob/main/LICENSE)。

## サポートとセキュリティ

バグや機能の提案は [GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose) をご利用ください。
脆弱性は公開Issueではなく [非公開の報告フォーム](https://github.com/abruption/session-peer/security/advisories/new) から報告し、
[セキュリティポリシー](https://github.com/abruption/session-peer/blob/main/SECURITY.ja.md)に従ってください。
共有する診断結果から秘密情報、会話、セッションID、個人のパスを伏せてください。

非公開のご質問や代替のセキュリティ窓口には、件名に `[session-peer]` を付けて
[support@abruption.dev](mailto:support@abruption.dev)へご連絡ください。
できる限り対応しますが、対応期限は保証しません。メールは手動で確認し、公開Issueへ自動投稿しません。
英語・韓国語での報告を受け付けています。
