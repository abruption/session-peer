# オプションの Codex MCP 統合

Python 3.10 以降でインストールします: `pipx install 'session-peer[mcp]'`（または隔離された venv にエクストラをインストール）。依存関係のない Python 3.9 CLI および `install.sh` は引き続きサポートされます。シェルインストーラーは MCP の依存関係をインストールしません。Python 3.9 では、MCP エントリポイントが Python 3.10+ が必要である旨を報告します。

任意のエクストラはMCP SDK `mcp>=1.30,<2`を必要とします。上流の1.xセキュリティ修正を含む版まで依存関係の下限を引き上げるもので、stdio専用のこのサーバーで悪用可能な欠陥を確認したという意味ではありません。HTTP転送、OAuthサーバー経路、MCPクライアント経路は有効にしません。既存環境では明示的なパッケージ更新が必要で、宣言の変更だけではインストール済みSDKは更新されません。

`session-peer-mcp --config /absolute/path/policy.json` を起動します。ポリシーがない場合、サーバーは起動環境の Codex ホームを使用して、ローカルの一覧取得のみを許可します。ポリシーを指定するとデフォルトが置き換えられます。例:

```json
{
  "schemaVersion": 1,
  "destinations": {
    "local": {
      "agents": ["claude", "codex"],
      "capabilities": ["list"],
      "codexHome": "/Users/me/.codex"
    },
    "worker": {
      "host": "ubuntu@worker.example.ts.net",
      "agents": ["claude", "codex"],
      "capabilities": ["list", "send"],
      "codexHome": "/home/ubuntu/.codex"
    }
  }
}
```

実際のユーザー名と SSH 送信先、設定済みの鍵、および known_hosts を使用してください。このファイルにパスワードを含めてはなりません。すべての Codex 送信先は、その送信先での絶対パスのホームを固定する必要があります。ホームを追加する場合は、個別の送信先 ID を追加してください。信頼できないプロセスによる変更からポリシーを保護してください。SSH 設定はオペレーターが管理する状態を維持します。

`codex mcp add session-peer -- /absolute/path/session-peer-mcp --config /absolute/path/policy.json` を使用して登録するか、リポジトリの `plugins/session-peer` バンドルを使用します: `codex plugin marketplace add /absolute/path/to/session-peer`、続いて `codex plugin add session-peer@session-peer`。このプラグインは PATH から `session-peer-mcp` を起動し、環境変数に設定されている場合は `SESSION_PEER_MCP_CONFIG` を読み取ります。最初に Python エクストラをインストールしてください。Python パッケージをインストールしても、既存の Codex 設定が変更されることはありません。

## 未リリースの v1.4.0 候補: 宛先メタデータの取得 (#356)

`list_destinations()` は引数を取らず、オペレーターのポリシーのメタデータだけを返します。`schemaVersion` は 1 で、各項目には `destination`、`transport`、`agents`、`capabilities` が含まれます。子プロセスの起動やネットワークリクエストは行いません。SSH ホストの値と Codex ホームのパスは省略されます。送信先の名前は信頼できないデータとして扱ってください。設定されたケーパビリティはポリシー上の権限を示し、ネイティブエージェントとの互換性は示しません。

応答には制約を明示します: `callerIdentity="unavailable"`、`readiness="not_checked"`、`submission="not_attempted"`、`consumption="not_checked"`、`ack="not_checked"`。このツールは宛先が64件を超える場合や、IDに表示できない文字がある場合、UTF-8で128バイトを超える場合に取得を拒否します。テキストと構造化データを合わせたMCPツール結果は64 KiB以内で、外側のJSON-RPCエンベロープは含みません。これは取得ツールの制限であり、ポリシーの読み込みと既存ツールの動作は変わりません。表示可能な文字の判定は、実行中のPythonのUnicodeデータベースに従います。既定のローカル一覧取得専用ポリシーは変わりません。

## 未リリースの v1.4.0 候補: 送信の事前検証 (#357)

`preflight_send(destination, target, message, wake=false, wake_timeout=30)` は、既存の CLI dry-run 検査で通常のメッセージを検証します。オペレーターのポリシーは `schemaVersion` 2 を使用し、送信先とエージェントに対して `preflight` を明示的に許可する必要があります。バージョン 1 の既存のケーパビリティには新たな権限を追加せず、既定はローカル一覧取得専用のままです。事前検証に `send` は不要で、送信を許可するものではありません。wake の適格性を調べる場合は別途 `wake` が必要ですが、モデルの起動や wake 予算の予約は行いません。

バージョン付きの説明は、SSH アダプターによる整形前のネイティブ応答から許可された事実だけを抽出し、定められた拒否・不明の理由とオペレーターの対処を示します。メッセージ本文、生のエラー、認証情報、ホスト・ホームのパス、ネイティブの記録は含めません。結果が不明な場合や予期しない投入の証拠がある場合は、`retryAllowed=false` として検証に失敗します。自動再送しないでください。事前検証はメッセージの投入や handoff 権限の作成を行いません。デバイスと handoff のモードには対応しません。

既存の dry-run 検査はローカル・バージョン確認のプロセスや SSH 接続を開始する場合があり、SSH 設定自体がコマンドを実行する場合もあります。このため、このツールは `readOnlyHint=false` と `openWorldHint=true` を使用します。ホストの承認はポリシーの権限とは別です。合格は検査時点の結果であり、経路の予約、有効なストレージの証明、承認、後の送信の保証、消費、ACK を意味しません。

## ツールとパーミッション

- `list_sessions(destination="local", agent=null, include_inactive=false)` は CLI の構造化された一覧を返します。Agent は `claude` または `codex` です。省略した場合は許可されたエージェントを一覧表示します。
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` は、`send` が明示的に許可されている場所にのみ 1 回送信します。Target は Claude 名/PID、`codex:<UUID>`、または設定されたホストとホームに正確に一致する Reply-To URI です。

MCP ツールのアノテーションは、一覧取得を読み取り専用、送信を非冪等としてマークします。必要に応じてホストクライアントのツール承認を設定してください。サーバーポリシーは宛先を個別に制限し、サンドボックスやホストの承認をバイパスすることはありません。別のホスト名が同じマシンに解決される場合でも、Reply-To URI 内の SSH エイリアスはポリシーと完全に一致する必要があります。そうでない場合は、直接ターゲットと設定済みの宛先 ID を使用してください。

応答は MCP の structuredContent と text の両方で CLI の JSON フィールドを保持します。一覧取得の部分的な失敗では、検出されたセッションを保持し、isError を設定します。キューへの送信は消費ではありません。結果が unknown の送信を自動的に再試行しないでください。リモート送信後にキャンセルやトランスポートの切断が発生する可能性があります。received/status/wait ツールはありません。[明示的な wake](wake.md) には、`send` に加えて個別の `wake` ケーパビリティが必要です。wake を有効にする場合は、クライアントツールのタイムアウトを 150 秒に設定してください。

共有 MCP プロセスは、呼び出し元のスレッドを確実には識別できません。サーバーを起動したセッションに帰属させるのではなく、メッセージは `session-peer MCP (caller session unavailable)` と識別し、Reply-To を省略します。認証のためにこのヘッダーに依存しないでください。メッセージ本文はシェルコマンド文字列ではなく stdin 経由で渡されます。通常の CLI の制限が依然として適用されます。

## 検証

MCP エクストラの有無の両方で `python -m unittest discover -s tests -v` を実行します。オプションのテストでは実際の stdio MCP サーバーを起動し、モデルの認証情報なしで初期化、スキーマ、ポリシー拒否、および CLI の部分的な失敗を検証します。wheel と sdist の両方のインストールをテストしてください。実環境チェックでは Codex バージョン、OS、およびホストの承認設定を記録する必要があります。UDS アクセスは環境依存であり、承認のバイパスを約束するものではありません。メッセージには専用のテストセッションを使用してください。

CIではmacOS/LinuxのPython 3.10/3.13/3.14で、SDK下限の`mcp==1.30.0`と最新の互換1.xを別々に試験します。両プロファイルでstdio・ポリシー・タイムアウト・キャンセル・所有する子プロセスの終了処理を試験し、解決されたランタイム依存関係を監査して、版とレポートを保存します。推移的依存関係の版は通常の依存関係解決に従って選択されます。すべての推移的パッケージの最小版を試験するものではありません。版を固定したビルド・監査用要件はランタイム環境の外にインストールし、監査対象には初期構成用の`pip`/`setuptools`パッケージも含めます。既存の最新版解決監査とリリース監査も引き続き必須です。

公式リファレンス: [Codex MCP](https://developers.openai.com/codex/extend/mcp), [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)。 [SDK 1.30.0](https://pypi.org/pypi/mcp/1.30.0/json), [GHSA-84m7-p3x7-pcfv](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv), [GHSA-fmmv-w9g8-j3gc](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-fmmv-w9g8-j3gc).

### 非対話型クライアントの承認

Codex `exec` は、サーバーポリシーが許可している場合でも「requires approval, but approval policy is never」として send ツールを拒否することがあります。`approval_mode="auto"` は無条件の承認ではありません。非対話型統合を明示的に承認するオペレーターは、制限された宛先ポリシーと併せて、その特定の MCP サーバー/ツールに対して `mcp_servers.session_peer.tools.send_message.approval_mode="approve"` を設定できます。プラグインがこの設定を有効にすることはありません。対話型クライアントは、代わりに通常の承認プロンプトを使用できます。テストクライアントがこの承認設定を無関係なサーバーやツールにコピーしてはなりません。

macOS/LinuxではMCP CLI呼び出しごとに新しいプロセスグループを所有します。完了・timeout・取消時はleaderの回収前に制限時間付きのTERM→KILLでTERMを無視する子も整理し、キャンセルは引き続き伝播します。別sessionへ離脱した子やSSH先のプロセスは対象外です。Windowsは直接の子の終了のみで、ツリー終了は保証しません。ローカル終了で遠隔送信は取り消せません。timeoutは `outcome_unknown` のままで自動再送は禁止です。

呼び出し元セッションが不明であることを示す From ラベルを含め、MCP の本文は宛先 CLI の受信側の枠で引用されます。本文のヘッダーや埋め込まれた Reply-To は権限を与えません。第三者への宛先はセッション所有者に確認してください。共有 MCP プロセスは、認証済み呼び出し元セッションや自動返信経路を引き続き提供できません。最終的な枠もネイティブメッセージの上限に含まれます。
