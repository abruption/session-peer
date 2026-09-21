# v1 兼容性契约

本文定义 session-peer 从 1.0.0 起承诺保持兼容的接口。它约束软件包行为，不保证托管
中继的可用性。`tests/fixtures/compatibility-v1.json` 中的机器可读 fixture 是本政策的
可执行依据。

## 兼容性等级

| 等级 | 含义 |
| --- | --- |
| Stable | 在 v1 期间保持现有有效输入和必需输出的含义。可在注明的位置增加字段。 |
| Versioned | 不兼容变更需要新的明确版本。旧版本在文档规定的迁移期内仍可读取。 |
| Migrated | 持久数据只能通过明确的版本化迁移变更。普通启动不会重写旧 schema。 |
| Operator internal | 格式可验证和恢复，但只能由随附工具编辑，不是用户编写的 API。 |
| Experimental | 可在发布说明和迁移指导后变更或删除。 |

“Supported”表示维护 CI 和文档化的生产路径；“Tested”表示发布证据实际运行过的环境；
“Best effort”只有有限诊断，不是发布 gate；“Experimental”在本文升级前不承诺 v1 兼容性。

## CLI 与机器可读结果

命令、文档化选项、选项优先级和退出含义是稳定的。退出`0`表示按文档规定的提交语义完成，
`1`表示命令或传输失败，`2`表示 argparse 使用错误或文档明确的无匹配目标。面向人的文字、
空格、顺序和终端装饰不冻结。

JSON schema version 1 稳定且允许增加字段。每个命令结果保持当前类型的`schemaVersion`、
`ok`、`host`和`command`。单个目标保持一个对象，重复目标保持对象数组。消费者必须忽略未知
字段。v1 内不能删除必需字段或改变其类型。除非存在明确 ACK 字段，提交字段不代表 agent
已消费或回复。参阅 [CLI 参考](cli-reference.md)。

## 回复地址、MCP 与策略

`session-peer://v1/reply` 是版本化格式。生产 URI parser 将字段作为惰性数据读取；未知、
重复或不安全字段会 fail closed。不兼容地址变更需要新的 URI authority version。

MCP 工具结果把 CLI JSON 复用为`structuredContent`，所以 CLI 的新增字段在 MCP 中同样是
新增字段。MCP policy `schemaVersion: 1`和 relay receiver policy 是稳定的严格 allowlist。
未知 policy key 会被拒绝。新增 capability 必须写入文档，并在 operator opt in 前保持拒绝。
参阅 [MCP](mcp.md)和[配对设备](paired-devices.md)。

## 设备状态、备份与操作回执

设备状态和 backup manifest 是版本化的 operator 管理数据，只能通过随附的 backup、restore
和 rotation 命令移动。不能静默重新编号、解释或删除 backup manifest schema 1、稳定 device
principal、key generation、revocation tombstone 和 durable operation receipt。不兼容变更需要
新的 manifest 或 DB schema，以及明确 migration 与 recovery fence。

control/replay DB、public-state snapshot、spent-ticket 文件和 revision high-water 记录属于
operator internal。其不变量稳定，但表和 JSON 布局不是用户可编辑的 public API。请使用
[中继生命周期](relay-lifecycle.md)中的 migration 与 recovery 流程。

## 中继与 endpoint 协议

Endpoint TLS framing、pairing message 与 relay/control HTTP shape 采用版本协商。当前 endpoint
application protocol 是`session-peer-device-v1`，control public state 和 replay state 使用
`schemaVersion: 1`。未知版本 fail closed。blind relay 不得获得明文访问，OAuth 或 relay
admission 不能替代 endpoint pinning 或 receiver policy。

hosted limit、service availability、OAuth provider policy、edge rule 和 operator dashboard 是
deployment behavior，不属于 PyPI v1 可用性承诺。即使 operator 配置变化，security boundary
和 persistent rollback protection 仍是 release gate。

## 支持矩阵

| Surface | v1 支持边界 | Level |
| --- | --- | --- |
| Core CLI | Python 3.9+、macOS、Linux 和 native Windows | Supported |
| MCP adapter | Python 3.10+、macOS、Linux；MCP runtime 支持 stdio 时的 Windows | Supported |
| Paired receiver 与 relay | Python 3.11+、Unix；Windows endpoint 使用文档化 WSL boundary | WSL beta gate 后 Supported |
| Control service | Linux arm64/x64 上的 Node 22 和 24 | Supported |
| Claude Code | CI 与 release validation 运行的 native inbox contract | Tested；不承诺 upstream private schema |
| Codex | CI 运行的 saved-thread discovery 与`codex queue` contract | Tested；未记录 DB variant 为 best effort |
| Antigravity | 明确 bridge protocol | 在后续 contract revision 升级前为 Experimental |

在其他 OS 或 agent version 上一次成功只是 evidence，不是永久支持承诺。release note 必须说明
新测试版本以及 coverage 的减少。

## 变更与 deprecation 规则

Stable surface 在 v1 中以新增方式变更。删除、类型变化、语义复用或更严格拒绝过去有效的
public input，需要新的 versioned surface 或下一个 major release。除非继续该行为不安全，
删除前至少在一个 minor release 的 release note 中标记 deprecation。

Persistent format 使用包含 preflight、backup 和 post-migration verification 的明确 migration。
Experimental surface 可在 prerelease 中变更，但 release note 必须说明变化和替代方案。
[#112](https://github.com/abruption/session-peer/issues/112) 的 source modularization 必须保留这些
fixture 和生成的 standalone CLI behavior。

## 发布检查表

每次 release 都要说明 contract addition、deprecation 和 migration。CI 验证必需 JSON 字段与
类型、退出含义、URI/policy parsing、backup invariant 及 relay protocol version marker。fixture
通过允许文档化的新增字段，但不会把 internal storage 变成 public API。
