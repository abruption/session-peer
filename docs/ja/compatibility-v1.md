# v1互換性契約

この文書はsession-peerが1.0.0以降で維持するインターフェースを定義します。パッケージの
動作に対する契約であり、ホスト型リレーの可用性契約ではありません。
`tests/fixtures/compatibility-v1.json`の機械可読fixtureがこの方針の実行可能な根拠です。

## 互換性レベル

| レベル | 意味 |
| --- | --- |
| Stable | v1の間、既存の有効な入力と必須出力の意味を維持します。明記した箇所にはフィールドを追加できます。 |
| Versioned | 非互換変更には新しい明示バージョンが必要です。旧版は文書化した移行期間中、読み取り可能です。 |
| Migrated | 永続データは明示的なバージョン付きmigrationだけで変更します。通常起動は旧schemaを書き換えません。 |
| Operator internal | 形式は検証・復旧できますが、同梱ツールだけが編集します。利用者が作成するAPIではありません。 |
| Experimental | release noteと移行案内を示した上で変更または削除できます。 |

「Supported」はCIと文書化した運用経路を維持すること、「Tested」はrelease evidenceで
実行した環境を指します。「Best effort」は限定診断のみでrelease gateではありません。
「Experimental」はここで昇格するまでv1互換性を約束しません。

## CLIと機械可読結果

コマンド、文書化したoption、優先順位、exitの意味はstableです。終了`0`は文書化した
submission semanticsに従って完了、`1`はcommandまたはtransport failure、`2`はargparse
usage failureまたは文書化したno-targetを示します。人向け文言、空白、順序、端末装飾は固定しません。

JSON schema version 1はstableかつadditiveです。各結果は現在の型の`schemaVersion`、
`ok`、`host`、`command`を保持します。単一destinationはobject、複数destinationはobject
arrayです。consumerは未知のfieldを無視しなければなりません。v1内で必須fieldの削除や
型変更はできません。明示ACK fieldがないsubmission fieldはagent consumptionやreplyを
意味しません。[CLIリファレンス](cli-reference.md)を参照してください。

## Reply address、MCP、policy

`session-peer://v1/reply`はversioned形式です。fieldは製品URI parserが不活性なdataとして
読み、未知・重複・危険なfieldはfail closedで拒否します。非互換なaddress変更には新しい
URI authority versionが必要です。

MCP tool resultはCLI JSONを`structuredContent`として再利用するため、CLIのadditive fieldは
MCPでもadditiveです。MCP policy `schemaVersion: 1`とrelay receiver policyはstableな厳格
allowlistです。未知のpolicy keyは拒否します。capability追加は文書化し、operatorがopt in
するまで拒否します。[MCP](mcp.md)と[ペアデバイス](paired-devices.md)を参照してください。

## Device state、backup、operation receipt

Device stateとbackup manifestはversionedなoperator管理dataです。同梱のbackup、restore、
rotation commandでのみ移動します。backup manifest schema 1、stable device principal、key
generation、revocation tombstone、durable operation receiptを暗黙に再番号化、再解釈、削除
できません。非互換変更には新manifestまたはDB schemaと明示migration・recovery fenceが必要です。

control/replay DB、public-state snapshot、spent-ticket file、revision high-water recordはoperator
internalです。不変条件はstableですがtableとJSON layoutは利用者編集用public APIではありません。
[リレーのライフサイクル](relay-lifecycle.md)のmigrationとrecovery手順を使用してください。

## Relayとendpoint protocol

Endpoint TLS framing、pairing message、relay/control HTTP shapeはversion-negotiatedです。現在の
endpoint application protocolは`session-peer-device-v1`、control public stateとreplay stateは
`schemaVersion: 1`です。未知versionはfail closedです。blind relayはplaintextへアクセスできず、
OAuthやrelay admissionはendpoint pinningまたはreceiver policyを置き換えません。

hosted limit、service availability、OAuth provider policy、edge rule、operator dashboardはdeployment
behaviorでありPyPI v1 availability promiseではありません。operator設定が変わってもsecurity
boundaryとpersistent rollback protectionはrelease gateです。

## Support matrix

| Surface | v1のsupport boundary | Level |
| --- | --- | --- |
| Core CLI | Python 3.9+、macOS、Linux、native Windows | Supported |
| MCP adapter | Python 3.10+、macOS、Linux。MCP runtimeがstdioを支援するWindows | Supported |
| Paired receiverとrelay | Python 3.11+、Unix。Windows endpointは文書化したWSL boundaryを使用 | WSL beta gate後にSupported |
| Control service | Linux arm64/x64上のNode 22、24 | Supported |
| Claude Code | CIとrelease validationで実行したnative inbox contract | Tested。upstream private schemaは非保証 |
| Codex | CIで実行したsaved-thread discoveryと`codex queue` contract | Tested。未文書DB variantはbest effort |
| Antigravity | 明示bridge protocol | 後続contract revisionで昇格するまでExperimental |

別OSやagent versionで一度成功した実行はevidenceであり、永続support promiseではありません。
release noteは新たにtestedとなったversionとcoverage低下を明記します。

## 変更とdeprecation rule

Stable surfaceはv1中additiveに変更します。削除、型変更、意味の再利用、以前有効だったpublic
inputの厳格化には新しいversioned surfaceまたは次major releaseが必要です。安全上継続できない
場合を除き、削除前に少なくとも一minor releaseのrelease noteでdeprecationを示します。

Persistent formatはpreflight、backup、post-migration verificationを含む明示migrationを使います。
Experimental surfaceはprereleaseで変更できますがrelease noteに変更とreplacementを記載します。
[#112](https://github.com/abruption/session-peer/issues/112)のsource modularizationはこのfixtureと
生成されたstandalone CLI behaviorを維持しなければなりません。

## Release checklist

各releaseはcontract addition、deprecation、migrationを示します。CIは必須JSON field/type、exit
meaning、URI/policy parsing、backup invariant、relay protocol version markerを検証します。fixtureの
合格は文書化したadditive fieldを許可しますがinternal storageをpublic APIにはしません。
