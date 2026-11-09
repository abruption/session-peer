# オプションの Codex MCP 統合

2026-11-09の準備確認時点で、最新の公開済みランタイムはv1.4.2であり、以下のv1.4.0ツールとSDK 1のインストール経路を含んでいました。v1.3.3を基にした2026-11-02のソース確認は過去の記録で、[v1.4.0リリースノート](releases/v1.4.0.md)に当時の範囲を保持しています。準備確認時点で、以下のSDK 2互換性は[未公開v1.5.0ソース候補](releases/v1.5.0.md)として準備されたもので、配布済みパッケージのサポート告知ではありませんでした。

Python 3.10 以降でインストールします: `pipx install 'session-peer[mcp]'`（または隔離された venv にエクストラをインストール）。依存関係のない Python 3.9 CLI および `install.sh` は引き続きサポートされます。シェルインストーラーは MCP の依存関係をインストールしません。Python 3.9 では、MCP エントリポイントが Python 3.10+ が必要である旨を報告します。

公開済みv1.4.2の任意エクストラはMCP SDK `mcp>=1.30,<2`を必要とします。上流の1.xセキュリティ修正を含む版まで依存関係の下限を引き上げるもので、stdio専用のこのサーバーで悪用可能な欠陥を確認したという意味ではありません。HTTP転送、OAuthサーバー経路、MCPクライアント経路は今回の変更によって有効化されません。既存環境では明示的なパッケージ更新が必要で、宣言の変更だけではインストール済みSDKは更新されません。

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

<a id="sdk2-compatibility-candidate"></a>
<a id="unreleased-source-candidate-sdk-12-compatibility-389"></a>
<a id="未公開ソース候補sdk-12互換性389"></a>

## v1.5.0準備確認（2026-11-09）：SDK 1/2互換性（#389 / #390）

2026-11-09の準備確認時点で、未公開v1.5.0候補のエクストラは`mcp>=1.30,<3,!=2.0.*,!=2.1.*,!=2.2.*`を使用していました。安定版SDK 1.xの1.30以降を維持し、安定版SDK 2.xの2.3以降を追加しました。候補はサーバー起動時に安定版SDKを強制し、pipの`--pre`で導入されていてもプレリリース・開発版SDKを拒否する実装でした。これは依存関係の解決方法だけに委ねるものではなく、ランタイムの検査です。SDK 2.0–2.2は、サーバーが`subscriptions/listen`を常に公開し、公開APIで無効化できないため除外しました。SDK 2.3+では`MCPServer(subscriptions=False)`でサーバーを生成し、サブスクリプションを無効にしました。

バージョンを固定した上流ソース：[SDK 2.0.0サーバー](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/src/mcp/server/mcpserver/server.py)、[SDK 2.2.0サーバー](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/server/mcpserver/server.py)、[SDK 2.3.0サーバー](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/server.py)。[SDK 2.3.0の配布メタデータ](https://pypi.org/pypi/mcp/2.3.0/json)もPython 3.10+を要求し、任意MCPの既存の下限と一致します。

公開ツール名6個、プロジェクト結果データのスキーマバージョン1、ポリシーバージョン1/2、宛先権限、個別のホスト承認、結果・プロセスの制限、結果不明時の扱い、自動再試行の禁止は維持します。サブスクリプション・listen・状態照会・待機のインターフェースは追加しません。SDK 2のPython属性はsnake_caseですが、通信形式ではcamelCaseの別名を使い、モデルのJSONシリアライズには`by_alias=True`を指定します。プロジェクトの結果JSONは変更しませんが、ネゴシエーションされたプロトコルバージョン間でSDK生成のエンベロープや機能フィールドまでバイト単位で同一だとは主張しません。

結果の64 KiB制限は上限であり、それより小さいすべてのデータを受け付ける保証ではありません。SDK 2は旧プロトコルの接続でも新プロトコルのサーバー識別メタデータを含めてサイズを計算するため、上限に近い結果はSDK 1が受け付けても保守的に拒否する場合があります。

2026-11-09の準備確認時点で、公開済みパッケージ向けのインストール・更新コマンドは配布済みSDK 1の経路を選び、このソース候補を提供したりSDK 2サポートを公開したりするものではありませんでした。レビュー済みソースの採用と、運用者が選んだパッケージ管理ツール・インタープリター・エクストラの維持は別の作業であり、定義の変更やサーバーの再起動だけでは導入済みSDKは更新されません。外部依存のないPython 3.9+基本CLIと任意MCPのPython 3.10+下限は変更していませんでした。候補は別途公開済みのスキルv0.5.1、最小0.9.1／文書で案内する全使用手順の基準1.4.0、受信側codexBin下限1.0.1を維持しました。

<a id="未リリースの-v140-候補-宛先メタデータの取得-356"></a>
<a id="unreleased-v140-candidate-destination-discovery-356"></a>

## v1.4.0 ソース: 宛先メタデータの取得 (#356)

`list_destinations()` は引数を取らず、オペレーターのポリシーのメタデータだけを返します。`schemaVersion` は 1 で、各項目には `destination`、`transport`、`agents`、`capabilities` が含まれます。子プロセスの起動やネットワークリクエストは行いません。SSH ホストの値と Codex ホームのパスは省略されます。送信先の名前は信頼できないデータとして扱ってください。設定された権限はポリシー上の権限を示し、ネイティブエージェントとの互換性は示しません。

応答には制約を明示します: `callerIdentity="unavailable"`、`readiness="not_checked"`、`submission="not_attempted"`、`consumption="not_checked"`、`ack="not_checked"`。このツールは宛先が64件を超える場合や、IDに表示できない文字がある場合、UTF-8で128バイトを超える場合に取得を拒否します。テキストと構造化データを合わせたMCPツール結果は64 KiB以内で、外側のJSON-RPCエンベロープは含みません。これは取得ツールの制限であり、ポリシーの読み込みと既存ツールの動作は変わりません。表示可能な文字の判定は、実行中のPythonのUnicodeデータベースに従います。既定のローカル一覧取得専用ポリシーは変わりません。

<a id="未リリースの-v140-候補-送信の事前検証-357"></a>
<a id="unreleased-v140-candidate-send-preflight-357"></a>

## v1.4.0 ソース: 送信の事前検証 (#357)

`preflight_send(destination, target, message, wake=false, wake_timeout=30, preset=null, preset_revision=null)` は、既存の CLI dry-run 検査で通常のメッセージを検証します。オペレーターのポリシーは `schemaVersion` 2 を使用し、送信先とエージェントに対して `preflight` を明示的に許可する必要があります。バージョン 1 の既存の権限には新たな権限を追加せず、既定はローカル一覧取得専用のままです。事前検証に `send` は不要で、送信を許可するものではありません。wake の適格性を調べる場合は別途 `wake` が必要ですが、モデルの起動や wake 予算の予約は行いません。

バージョン付きの説明は、SSH アダプターによる整形前のネイティブ応答から許可された事実だけを抽出し、定められた拒否・不明の理由とオペレーターの対処を示します。メッセージ本文、生のエラー、認証情報、ホスト・ホームのパス、ネイティブの記録は含めません。結果が不明な場合や予期しない投入の証拠がある場合は、`retryAllowed=false` として検証に失敗します。自動再送しないでください。事前検証はメッセージの投入や handoff 権限の作成を行いません。デバイスと handoff のモードには対応しません。

既存の dry-run 検査はローカル・バージョン確認のプロセスや SSH 接続を開始する場合があり、SSH 設定自体がコマンドを実行する場合もあります。このため、このツールは `readOnlyHint=false` と `openWorldHint=true` を使用します。ホストの承認はポリシーの権限とは別です。合格は検査時点の結果であり、経路の予約、有効なストレージの証明、承認、後の送信の保証、消費、ACK を意味しません。

<a id="未リリースの-v140-候補-制限付き診断-358"></a>
<a id="unreleased-v140-candidate-bounded-diagnostics-358"></a>

## v1.4.0 ソース: 制限付き診断 (#358)

`diagnose_destination(destination="local", agent=null, active_probe=false)` には、`schemaVersion` 2 ポリシーで明示的な `diagnostics` 権限が必要です。既定モードはポリシーのメタデータと宣言されたエージェント機能のみを返し、CLI や検出プロセスの起動、ネットワーク要求は行いません。送信先 ID には送信先検出と同じ、表示可能文字と UTF-8 128 バイトの制限が適用されます。バージョン 1 と既定ポリシーは診断権限を付与しません。 既定モードの `declaredCapabilities` はアダプターの宣言に基づくブール値であり、実際の配信や準備状態を証明しません。

`active_probe=true` には、さらに `diagnostics_probe` が必要です。メタデータモードは全プラットフォームで利用できます。能動モードは現在 macOS と Linux のみをサポートし、Windows では CLI プロセスの起動やネットワーク要求を行わず、固定理由 `diagnostics_platform_unsupported` を返します。チェックは設定された送信先、固定された Codex ホームと許可されたエージェントのみを使用します。エージェントごとの doctor 呼び出しは最大 3 エージェントを検査し、20 秒の実行予算を共有した後にプロセスを終了処理します。厳密な経過時間の上限やリモートプロセス終了の保証ではありません。子プロセスの stdout と stderr はそれぞれ 64 KiB に制限されます。Codex のチェックは選択したホームのみを調べます。逆方向経路のプローブ、メッセージ送信、ネイティブモデルの起動、自動再試行は行いません。能動チェックは CLI プロセスや SSH 接続を開始でき、運用者の SSH 設定自体がコマンドを実行する場合もあります。ホストの承認はポリシー権限とは別です。選択的な能動チェックが運用者の SSH 設定を実行できるため、統合ツールは `readOnlyHint=false` と `idempotentHint=false` を使用します。

応答は許可された状態値と診断コードを公開し、生のエラー、ホスト名、ホームパス、認証情報、セッション内容、不明な応答フィールドを除外します。メタデータモードは準備状態を検証しません。能動結果も検査時点の状態であり、消費や ACK の証拠、または送信権限ではありません。テキストと構造化ツール結果の合計は 64 KiB に制限されます。

状態・チェックのフィールドが欠落または不正な場合、一部のチェックが不完全な場合、チェック一覧が切り詰められた場合は、正常とはせず不明・不完全（`diagnostic_incomplete`）として報告します。通信段階 `tcpAccept`、`tls`、`peerAuthentication` はすべて `not_checked` のままで、診断では個別に検証しません。

MCP ラッパーが対応する検査と実行上の影響は、次の範囲に限られます。

| モード / エージェント | 確認する事実 | プロセス / 接続への影響 |
| --- | --- | --- |
| メタデータ | ポリシーとアダプターの宣言 | なし |
| 能動 Claude | 登録記録、プロセス識別メタデータ、ファイルシステム上の受信箱の存在 | 受信箱には接続しない |
| 能動 Codex | 実行ファイルの存在、選択したホームの読み取り専用 SQLite クエリ、制限付き writer 走査 | ネイティブ Codex の実行やバージョン照会はしない |
| 能動 Antigravity | 登録されたブリッジのメタデータ | ブリッジやネイティブへの RPC はしない |
| 能動 SSH | 明示的なプローブ権限を得た後、設定済みの順方向経路のみ | SSH 設定がコマンドを実行する場合がある。逆方向プローブや返信先ホストへの自動接続はしない |

許可されたコードの例は `sessions_dir_missing`、`inbox_present`、`codex_executable_missing`、`state_db_readable`、`unsaved_writer_check_unavailable`、`adapter_failed` です。結果は許可されたエージェントと、エージェントごとに最大 32 件のチェックに限られ、これらのコードが示すのは上記の限定範囲のみです。

`ok` は可用性ではなく、収集と形式の完全性を示します。完全な `missing_home` 結果でも `ok=true` になり得るため、各エージェントの状態は別途確認してください。`diagnosticEvidence` は能動結果では `point_in_time_only`、メタデータモードでは `not_collected` です。個別の対象の準備状態は検査しないため、`readiness` は `not_checked` のままです。`state_db_readable` の合格は読み取り専用 DB クエリの成功だけを意味し、有効なストレージの証明や返信経路の保証ではありません。

`tcpAccept`、`tls`、`peerAuthentication` の段階は `not_checked` のままです。ここでの `peerAuthentication` はペアリングされたデバイスの認証を指し、順方向 SSH 認証とは別です。`sshFailure` は `authentication_failed` や `host_key_failed` など、サニタイズされた順方向 SSH 失敗の分類だけを報告します。TCP、TLS、ペアリングされたデバイス、返信先ホストへのプローブは追加しません。

<a id="未リリースの-v140-候補-mcp-プリセット-359"></a>
<a id="unreleased-v140-candidate-mcp-presets-359"></a>

## v1.4.0 ソース: MCP プリセット (#359)

入力シグネチャ: `list_sessions(destination="local", agent=null, include_inactive=false, preset=null, preset_revision=null)`; `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30, preset=null, preset_revision=null)`; `preflight_send(destination, target, message, wake=false, wake_timeout=30, preset=null, preset_revision=null)`.

`list_presets(destination)` は承認済みの経路メタデータだけを読みます。`schemaVersion` 2 のポリシーで `presets` を明示的に許可し、宛先ごとの `presets` リストに `[a-z][a-z0-9_-]{0,63}` に一致する承認済みの名前を 1 件以上、128 件以下で指定する必要があります。バージョン 1 は新しい権限とフィールドを拒否します。ストアを読む前に権限を確認します。結果には宛先と一致する承認済みの `name`、`agent`、`transport`、`revision` と既存の `dp1:` トークンだけが含まれ、実際のホスト、ホーム、ストアのパスは省略されます。保存済み経路の参照では、セッションの探索、対象の選択、SSH・ネイティブ・バージョン確認のプローブ、データの更新を行いません。バージョン付きのテキストと構造化されたツール結果は、合計 64 KiB に制限されます。

`list_sessions`、`preflight_send`、`send_message` は任意の `preset`、`preset_revision` 入力を受け付けます。選択には既存の操作権限と `presets` の両方が必要です。保存済み経路やリビジョンが権限を与えることはありません。送信には明示的な対象が必要で、実際の送信には現在のリビジョンが必要です。プリセットを wake や Reply-To URI の対象と組み合わせることはできません。macOS/Linux の既存の Claude Code・Codex のローカルまたは SSH 経路だけをサポートし、Windows、デバイス、アドレス帳、handoff、プリセット管理のサポートは追加しません。

アダプターは既存の `XDG_CONFIG_HOME` の選択と安全な読み取り関数を使い、オペレーターの起動環境のストアから検証済みのスナップショットを一度だけ読みます。64 KiB・128 件の制限と、所有者、ACL、シンボリックリンク、マウントの検査を維持し、存在しないストアや安全でないストアを初期化、修復、置換しません。モデルはストアのパスを指定できません。選択した経路は、宛先のホスト、許可されたエージェント、固定された Codex ホームと完全に一致する必要があります。DNS 上の同一性や代替経路への切り替えは認めません。CLI の `--preset` と明示的な経路フラグを組み合わせず、承認済み経路を一つの実行計画に展開し、呼び出し前にポリシーを再確認します。

リビジョンは名前と経路の正確な値を表し、同じ値に戻すと同じトークンを再利用できます。参照時に検査するもので、対象の世代、呼び出し元の身元、ストレージの証明、ACK ではありません。その後の変更によって、すでに展開された呼び出しが遡って取り消されることはありません。プリセットを選択しない場合、既存のツール応答は変わりません。

新しい 64 KiB のツール結果制限は `list_presets` のメタデータ参照だけに適用されます。プリセットは既存の操作の経路選択だけを担い、同じ操作権限とポリシー経路との完全一致を要求します。成功した `list_sessions` と `send_message` の応答では、プリセットのメタデータ、新しいコマンド名、追加のデータ射影を加えず、既存の CLI スキーマとネイティブのペイロードを維持します。既存のネイティブ証拠と通信上の制限を保ち、実際の送信に合計 64 KiB の制限を新設しません。リビジョンは `list_presets` で別途確認してください。選択済みの `preflight_send` に追加できるプリセットのメタデータは、安全な `name`、`agent`、`transport`、`revision` のみです。

承認済みの項目が一つでも欠落しているか、経路がポリシーと一致しない場合、メタデータ参照全体を原子的に拒否します。固定の選択拒否コードには `preset_platform_unsupported`、`preset_route_unsupported`、`preset_revision_mismatch`、`preset_storage_unavailable` があり、管理操作やファイルシステムの修復は行いません。メタデータ参照のエラーは呼び出し前に発生します。呼び出し後の入出力エラーや実際の送信応答のデコード失敗は、送信後に起きる場合もあるため、`outcome_unknown` と `retryAllowed=false` を報告し、自動再試行しないでください。確認済みのネイティブのキュー登録・送信証拠は保持します。

## ツールとパーミッション

以下の二つのシグネチャは既存の基本インターフェースを説明します。v1.4.0ソースのツールと省略可能なプリセット引数は、上の各節と初期化済みMCPの`tools/list`スキーマを確認してください。ツールが表示されても、ポリシー上の権限が付与されるわけではありません。

- `list_sessions(destination="local", agent=null, include_inactive=false)` はCLIの構造化一覧を返します。 エージェントの選択は送信先ポリシーが許可する登録済みアダプター（例：`claude`、`codex`）に制限され、省略時は許可されたエージェントを一覧表示します。
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` は、`send` が明示的に許可されている場所にのみ 1 回送信します。Target は Claude 名/PID、`codex:<UUID>`、または設定されたホストとホームに正確に一致する Reply-To URI です。

MCP ツールのアノテーションは、一覧取得を読み取り専用、送信を非冪等としてマークします。必要に応じてホストクライアントのツール承認を設定してください。サーバーポリシーは宛先を個別に制限し、サンドボックスやホストの承認をバイパスすることはありません。別のホスト名が同じマシンに解決される場合でも、Reply-To URI 内の SSH エイリアスはポリシーと完全に一致する必要があります。そうでない場合は、直接ターゲットと設定済みの宛先 ID を使用してください。

応答は MCP の structuredContent と text の両方で CLI の JSON フィールドを保持します。一覧取得の部分的な失敗では、検出されたセッションを保持し、isError を設定します。キューへの送信は消費ではありません。結果が unknown の送信を自動的に再試行しないでください。リモート送信後にキャンセルやトランスポートの切断が発生する可能性があります。received/status/wait ツールはありません。[明示的な wake](wake.md) には、`send` に加えて個別の `wake` 権限が必要です。wake を有効にする場合は、クライアントツールのタイムアウトを 150 秒に設定してください。

共有 MCP プロセスは、呼び出し元のスレッドを確実には識別できません。サーバーを起動したセッションに帰属させるのではなく、メッセージは `session-peer MCP (caller session unavailable)` と識別し、Reply-To を省略します。認証のためにこのヘッダーに依存しないでください。メッセージ本文はシェルコマンド文字列ではなく stdin 経由で渡されます。通常の CLI の制限が依然として適用されます。

## 検証

MCP エクストラの有無の両方で `python -m unittest discover -s tests -v` を実行します。オプションのテストでは実際の stdio MCP サーバーを起動し、モデルの認証情報なしで初期化、スキーマ、ポリシー拒否、および CLI の部分的な失敗を検証します。wheel と sdist の両方のインストールをテストしてください。実環境チェックでは Codex バージョン、OS、およびホストの承認設定を記録する必要があります。UDS アクセスは環境依存であり、承認のバイパスを約束するものではありません。メッセージには専用のテストセッションを使用してください。

2026-11-09の準備確認時点で、v1.5.0候補のCI設定は、以下の4つのSDKプロファイルをmacOS/LinuxのPython 3.10/3.13/3.14に組み合わせた合計24セルを定義していました。この日付の構成だけで全セルの成功が証明されるわけではありません。正確なHEADの実行と保存されたバージョン・監査レポートを確認してください。

| CIプロファイル | SDKの選択 |
| --- | --- |
| `minimum` | `mcp==1.30.0` |
| `latest1` | `mcp>=1.30,<2` |
| `minimum2` | `mcp==2.3.0` |
| `latest2` | `mcp>=2.3,<3` |

各プロファイルでstdio、ポリシー、タイムアウト、キャンセル、所有する子プロセスの後処理を試験し、解決されたサーバーと試験用クライアントのランタイム依存関係のグラフを個別に監査し、版とレポートを保存します。どちらかの監査に失敗すると、そのCI組み合わせは失敗します。候補の検証には、隔離された異なるメジャーバージョンのSDKクライアントを両方向で使う`2025-11-25`の実stdio初期化と、SDK 2による`2026-07-28`のネゴシエーションが含まれます。旧プロトコルの通信形式検査では、camelCaseの別名、6個のツール名、変更のないプロジェクト内部の結果を確認します。これらのSDK・プロトコル試験は、新たな実エージェント・SSH・ACKの検証ではありません。推移的依存関係は通常の解決に従い、全推移パッケージの最小版を試験するものではありません。固定版のビルド・監査要件はランタイム環境の外にインストールし、監査対象には初期構成用の`pip`/`setuptools`も含めます。既存の最新版解決監査とリリース監査も引き続き必要です。

公式リファレンス: [Codex MCP](https://developers.openai.com/codex/extend/mcp), [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)。 [SDK 1.30.0](https://pypi.org/pypi/mcp/1.30.0/json), [GHSA-84m7-p3x7-pcfv](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv), [GHSA-fmmv-w9g8-j3gc](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-fmmv-w9g8-j3gc).

### 非対話型クライアントの承認

Codex `exec` は、サーバーポリシーが許可している場合でも「requires approval, but approval policy is never」として send ツールを拒否することがあります。`approval_mode="auto"` は無条件の承認ではありません。非対話型統合を明示的に承認するオペレーターは、制限された宛先ポリシーと併せて、その特定の MCP サーバー/ツールに対して `mcp_servers.session_peer.tools.send_message.approval_mode="approve"` を設定できます。プラグインがこの設定を有効にすることはありません。対話型クライアントは、代わりに通常の承認プロンプトを使用できます。テストクライアントがこの承認設定を無関係なサーバーやツールにコピーしてはなりません。

macOS/Linuxでは、MCP CLI呼び出しごとに新しいプロセスグループを作成・管理します。完了、タイムアウト、キャンセルの際は、そのグループのリーダーを回収する前に、TERMを無視する子孫プロセスを含めてグループに対し、時間を制限したTERM→KILLの後処理を行います。キャンセルは引き続き伝播します。意図的に別のセッションへ離脱した子孫プロセスと、SSH先で動くリモートプロセスは、このグループの対象外です。Windowsでは引き続き直接の子プロセスの終了だけを行い、Windowsのプロセスツリー全体の後処理は保証しません。ローカルの後処理は、すでに行ったリモートへの提出を取り消しません。タイムアウト時の結果は `outcome_unknown` のままで、自動再送してはなりません。

呼び出し元セッションが不明であることを示す From ラベルを含め、MCP の本文は宛先 CLI の受信側の枠で引用されます。本文のヘッダーや埋め込まれた Reply-To は権限を与えません。第三者への宛先はセッション所有者に確認してください。共有 MCP プロセスは、認証済み呼び出し元セッションや自動返信経路を引き続き提供できません。最終的な枠もネイティブメッセージの上限に含まれます。
