# 可选 Codex MCP 集成

已发布运行时v1.4.2包含下述v1.4.0工具及SDK 1安装路径。基于v1.3.3的2026-11-02源码检查属于历史记录；[v1.4.0发布说明](releases/v1.4.0.md)保留当时的范围。下方SDK 2兼容性是v1.4.2之后尚未发布的源码候选方案，并非已发布软件包的支持公告。

在 Python 3.10 或更高版本下安装：`pipx install 'session-peer[mcp]'`（或在隔离的 venv 中安装 extra）。仍支持无依赖的 Python 3.9 CLI 和 `install.sh`。shell 安装程序不安装 MCP 依赖项。在 Python 3.9 上，MCP 入口点会报告需要 Python 3.10+。

已发布v1.4.2的可选extra要求MCP SDK `mcp>=1.30,<2`。这是将依赖版本下限提高到包含上游1.x安全修复的版本，并不表示已在这个仅使用stdio的服务器中确认可利用漏洞。本次变更不启用HTTP传输、OAuth服务器路径或MCP客户端路径。现有环境需要显式升级软件包；仅修改声明不会更新已安装的SDK。

启动 `session-peer-mcp --config /absolute/path/policy.json`。在没有策略的情况下，服务器仅允许本地列出，使用启动环境的 Codex 主目录。提供的策略将替换默认值。例如：

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

请使用实际的用户名和 SSH 目的地、已配置的密钥以及 known_hosts。此文件中不得包含密码。每个 Codex 目的地必须固定该目的地上的绝对主目录；为额外的主目录添加单独的目的地 ID。保护策略免受不受信任进程的修改。SSH 配置仍由操作员控制。

使用 `codex mcp add session-peer -- /absolute/path/session-peer-mcp --config /absolute/path/policy.json` 进行注册，或使用仓库的 `plugins/session-peer` 捆绑包：`codex plugin marketplace add /absolute/path/to/session-peer`，然后 `codex plugin add session-peer@session-peer`。该插件从 PATH 启动 `session-peer-mcp`，并在其环境中设置了 `SESSION_PEER_MCP_CONFIG` 时读取该配置。请先安装 Python extra。安装 Python 软件包不会修改现有的 Codex 设置。

<a id="sdk2-compatibility-candidate"></a>

## 尚未发布的源码候选方案：SDK 1/2兼容性（#389）

在2026-11-09源码检查时点，候选extra使用`mcp>=1.30,<3,!=2.0.*,!=2.1.*,!=2.2.*`。它保留稳定版SDK 1.x的1.30及以上版本，并增加稳定版SDK 2.x的2.3及以上版本；不接受SDK预发布版或开发版。SDK 2.0–2.2的服务器始终暴露`subscriptions/listen`，且没有公开API可以关闭，因此不受支持。SDK 2.3+使用`MCPServer(subscriptions=False)`创建服务器，使订阅保持禁用。

固定版本的上游源码：[SDK 2.0.0服务器](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/src/mcp/server/mcpserver/server.py)、[SDK 2.2.0服务器](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/server/mcpserver/server.py)和[SDK 2.3.0服务器](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/server.py)。[SDK 2.3.0发行元数据](https://pypi.org/pypi/mcp/2.3.0/json)同样要求Python 3.10+，与可选MCP现有下限一致。

公开工具名称6个、项目结果数据模式版本1、策略版本1/2、目的地权限、独立的宿主批准、结果及进程限制、未知结果处理和禁止自动重试的规则均保持不变。不增加订阅、listen、状态查询或等待接口。SDK 2的Python属性使用snake_case，但线上传输使用camelCase别名，模型JSON序列化使用`by_alias=True`。项目结果JSON不变，但不宣称不同协商协议版本下由SDK生成的封装及能力字段也逐字节相同。

结果的64 KiB限制是上限，并不保证接受所有小于该值的数据。SDK 2即使在旧协议连接中也将新协议的服务器身份元数据计入大小，因此可能保守地拒绝SDK 1能够接受的接近上限的结果。

已发布软件包的安装、升级命令仍选择已发布的SDK 1路径，尚不提供此源码候选方案，也不表示SDK 2支持已经发布。采用经过审查的源码与保留运维选择的软件包管理器、解释器和extra是独立操作；仅修改声明或重启服务器不会升级已安装的SDK。无外部依赖的Python 3.9+基本CLI及可选MCP的Python 3.10+下限不变。此候选方案不会更改独立发布的技能v0.5.1、最低0.9.1／文档所述全部使用流程的覆盖基准1.4.0，或接收端codexBin下限1.0.1。

<a id="尚未发布的-v140-候选版本目的地发现-356"></a>
<a id="unreleased-v140-candidate-destination-discovery-356"></a>

## v1.4.0 源码：目的地发现 (#356)

`list_destinations()` 不接受参数，仅返回操作员策略的元数据：`schemaVersion` 为 1，每个条目包含 `destination`、`transport`、`agents` 和 `capabilities`。它不会启动子进程，也不会发起网络请求。SSH 主机配置值和 Codex 主目录路径会被省略。目的地名称是不可信数据。已配置的权限表示策略授权范围，不表示原生代理的兼容性。

响应明确列出限制：`callerIdentity="unavailable"`、`readiness="not_checked"`、`submission="not_attempted"`、`consumption="not_checked"` 和 `ack="not_checked"`。目的地超过 64 个、ID 含不可打印字符或 UTF-8 编码超过 128 字节时，此工具拒绝查询。文本与结构化内容合计的 MCP 工具结果不超过 64 KiB，不包括外层 JSON-RPC 信封。这些限制仅适用于查询工具，策略加载及现有工具的行为保持不变。可打印字符的判定遵循运行中 Python 的 Unicode 数据库。默认的仅限本地列表查询的策略保持不变。

<a id="尚未发布的-v140-候选版本发送预检-357"></a>
<a id="unreleased-v140-candidate-send-preflight-357"></a>

## v1.4.0 源码：发送预检 (#357)

`preflight_send(destination, target, message, wake=false, wake_timeout=30, preset=null, preset_revision=null)` 通过现有 CLI dry-run 检查验证普通消息。操作员策略必须使用 `schemaVersion` 2，并为目的地和代理显式授予 `preflight`。版本 1 保留原有的权限集合，不会自动获得新权限；默认策略仍仅允许本地列表查询。预检不需要 `send`，也不能授予发送权限。如需检查唤醒资格，还必须单独具有 `wake`，但不会激活模型或预留唤醒额度。

带有版本的说明会在 SSH 适配器加工结果前，从原生响应中提取允许的事实，并提供固定的拒绝或未知原因及操作员处置建议。它不包含消息内容、原始错误、凭据、主机或主目录路径、原生记录。结果未知或存在意外提交证据时，验证失败并返回 `retryAllowed=false`；切勿自动重发。预检不会提交消息或创建 handoff 授权。不支持设备和 handoff 模式。

现有 dry-run 检查可能启动本地或版本查询进程、建立 SSH 连接；SSH 配置本身也可能执行命令。因此该工具使用 `readOnlyHint=false` 和 `openWorldHint=true`。宿主批准独立于策略权限。通过仅表示检查时点的结果，不代表预留路由、证明有效存储、批准、保证后续发送、消费或 ACK。

<a id="尚未发布的-v140-候选版本有界诊断-358"></a>
<a id="unreleased-v140-candidate-bounded-diagnostics-358"></a>

## v1.4.0 源码：有界诊断 (#358)

`diagnose_destination(destination="local", agent=null, active_probe=false)` 要求在 `schemaVersion` 2 策略中显式授予 `diagnostics` 权限。默认模式仅返回策略元数据和声明的代理支持能力，不启动 CLI 或发现进程，也不发起网络请求。目的地 ID 采用与目的地发现相同的可打印字符及 UTF-8 128 字节限制。版本 1 和默认策略均不授予诊断权限。 默认模式的 `declaredCapabilities` 包含来自适配器声明的布尔值，不证明实际送达或就绪状态。

设置 `active_probe=true` 还需要 `diagnostics_probe`。元数据模式支持所有平台。主动模式目前仅支持 macOS 和 Linux；在 Windows 上返回固定原因 `diagnostics_platform_unsupported`，不启动 CLI 进程或网络请求。检查仅使用配置的目的地、固定的 Codex 主目录和获准的代理。按代理限定范围的 doctor 调用最多检查三个代理，共享 20 秒的执行预算，然后清理进程；这并非严格的实际耗时上限，也不保证清理远程进程。子进程的 stdout 和 stderr 各限 64 KiB。Codex 检查仅访问所选主目录。不进行反向路由探测、消息提交、原生模型激活或自动重试。主动检查可能启动 CLI 进程和 SSH 连接，操作员的 SSH 配置本身也可能执行命令。宿主批准独立于策略权限。由于可选的主动检查能够执行操作员 SSH 配置，组合工具使用 `readOnlyHint=false` 和 `idempotentHint=false`。

响应仅公开允许列表中的状态和诊断代码，省略原始错误、主机名、主目录路径、凭据、会话内容和未知响应字段。元数据模式不验证就绪状态；主动检查结果也仅代表检查时点，不是消费或 ACK 的证据，也不授予发送权限。文本与结构化工具结果的合计大小限于 64 KiB。

状态或检查字段缺失、格式错误、检查不完整或检查列表被截断时，结果报告为未知或不完整（`diagnostic_incomplete`），不会报告为健康。传输阶段 `tcpAccept`、`tls` 和 `peerAuthentication` 均保持 `not_checked`；诊断不会单独验证这些阶段。

MCP 包装层仅支持以下检查及执行效果：

| 模式 / 代理 | 检查的事实 | 进程 / 连接效果 |
| --- | --- | --- |
| 元数据 | 策略与适配器声明 | 无 |
| 主动 Claude | 注册记录、进程身份元数据和文件系统中的收件箱存在情况 | 不连接收件箱 |
| 主动 Codex | 可执行文件是否存在、所选主目录的只读 SQLite 查询和有界 writer 扫描 | 不执行原生 Codex，也不查询版本 |
| 主动 Antigravity | 已注册桥接的元数据 | 不调用桥接或原生 RPC |
| 主动 SSH | 获得显式探测权限后，仅检查配置的正向路由 | SSH 配置可能执行命令；不反向探测，也不自动连接回回复主机 |

允许的代码示例包括 `sessions_dir_missing`、`inbox_present`、`codex_executable_missing`、`state_db_readable`、`unsaved_writer_check_unavailable` 和 `adapter_failed`。结果仅涉及获准的代理，每个代理最多 32 项检查；这些代码仅描述上表的有界范围。

`ok` 表示收集和格式的完整性，而非可用性。完整的 `missing_home` 结果也可能返回 `ok=true`，应另行查看每个代理的状态。主动结果中的 `diagnosticEvidence` 为 `point_in_time_only`，元数据模式中则为 `not_collected`。由于不检查特定目标的就绪情况，`readiness` 保持 `not_checked`。`state_db_readable` 检查通过仅表示只读数据库查询成功，不证明有效存储，也不保证回复路由可用。

`tcpAccept`、`tls` 和 `peerAuthentication` 阶段保持 `not_checked`。这里的 `peerAuthentication` 指配对设备身份验证，与正向 SSH 身份验证不同。`sshFailure` 仅报告经过脱敏的正向 SSH 失败类别，例如 `authentication_failed` 或 `host_key_failed`。不会新增 TCP、TLS、配对设备或回复主机探测。

<a id="尚未发布的-v140-候选版本mcp-预设-359"></a>
<a id="unreleased-v140-candidate-mcp-presets-359"></a>

## v1.4.0 源码：MCP 预设 (#359)

输入签名: `list_sessions(destination="local", agent=null, include_inactive=false, preset=null, preset_revision=null)`; `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30, preset=null, preset_revision=null)`; `preflight_send(destination, target, message, wake=false, wake_timeout=30, preset=null, preset_revision=null)`.

`list_presets(destination)` 仅读取已批准的路径元数据。`schemaVersion` 2 策略必须显式授予 `presets`，并在每个目的地的 `presets` 列表中提供 1 至 128 个符合 `[a-z][a-z0-9_-]{0,63}` 的已批准名称。版本 1 拒绝新增功能和字段。任何存储读取之前都先检查授权。结果仅公开与目的地匹配的已批准 `name`、`agent`、`transport` 和 `revision` 值及现有 `dp1:` 令牌，省略实际主机、主目录和存储路径。查询已保存的路径不会发现会话、选择目标、执行 SSH/原生/版本探测或刷新数据。带版本的文本与结构化工具结果合计限制为 64 KiB。

`list_sessions`、`preflight_send` 和 `send_message` 接受可选的 `preset`、`preset_revision` 输入。选择预设既需要现有操作权限，也需要 `presets`；保存的路径或修订令牌不会授予权限。发送必须指定明确目标，实际发送还必须提供当前修订令牌。预设不能与 wake 或 Reply-To URI 目标组合使用。仅支持 macOS/Linux 上现有的 Claude Code/Codex 本地或 SSH 路径；不新增 Windows、设备、地址簿、handoff 或预设管理支持。

适配器使用现有 `XDG_CONFIG_HOME` 选择规则和安全读取函数，从操作员启动环境中的存储读取一次经过验证的快照。64 KiB/128 条目的限制以及所有者、ACL、符号链接和挂载检查保持不变；不会初始化、修复或替换缺失或不安全的存储。模型不能指定存储路径。所选路径必须与目的地的主机、允许的代理和固定的 Codex 主目录完全匹配。不接受 DNS 等价性，也不会回退到其他路径。适配器将已批准的路径展开为单个执行计划，不将 CLI `--preset` 与显式路由选项组合，并在调用前重新检查策略。

修订令牌涵盖名称和路径的精确值；恢复相同值时可再次使用相同令牌。令牌在查询时检查，不是目标代次、调用者身份、存储证明或 ACK。之后的修改不会追溯取消已经展开的调用。未选择预设时，现有工具响应保持不变。

新增的 64 KiB 工具结果限制仅适用于 `list_presets` 元数据查询。预设仅作为现有操作的路由选择器，仍要求相同的操作授权及与策略路由完全匹配。成功的 `list_sessions` 和 `send_message` 响应保留现有 CLI 模式与原生载荷，不增加预设元数据、新命令名或额外的数据投影。现有原生证据和传输限制保持不变，实际发送不会新增合计 64 KiB 的限制。请通过 `list_presets` 单独检查修订令牌。选择预设的 `preflight_send` 只能额外包含安全的预设元数据：`name`、`agent`、`transport` 和 `revision`。

任一已批准项缺失或其路由与策略不匹配时，整个元数据查询都会被原子拒绝。固定的选择拒绝代码包括 `preset_platform_unsupported`、`preset_route_unsupported`、`preset_revision_mismatch` 和 `preset_storage_unavailable`；不会尝试管理操作或文件系统修复。元数据查询错误发生在调用之前。调用后的 I/O 错误或实际发送响应的解码失败可能发生在提交之后，因此必须报告 `outcome_unknown` 和 `retryAllowed=false`，切勿自动重试。已确认的原生排队或提交证据必须保留。

## 工具与权限

以下两个签名说明原有的基本接口。v1.4.0源码工具及可选预设参数请参阅上文各节和初始化后的MCP `tools/list`模式。工具可见并不授予策略权限。

- `list_sessions(destination="local", agent=null, include_inactive=false)` 返回CLI结构化列表。 智能体选择仅限目的地策略允许的已注册适配器（如 `claude` 或 `codex`）；省略时列出允许的智能体。
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` 仅在显式允许 `send` 的情况下提交一次。Target 是 Claude 名称/PID、`codex:<UUID>` 或与配置的主机和主目录完全匹配的 Reply-To URI。

MCP 工具注解将列出标记为只读，将发送标记为非幂等。根据需要配置宿主客户端的工具批准；服务器策略独立限制目的地，且不会绕过沙盒/宿主批准。Reply-To URI 中的 SSH 别名必须与策略完全匹配，即使另一个主机名解析到同一台机器也是如此。否则请使用直接目标和配置的目的地 ID。

响应在 MCP structuredContent 和文本中均保留 CLI JSON 字段。部分列表失败会保留已发现的会话并设置 isError。队列提交并非消费；切勿自动重试结果未知的发送。远程提交后可能会发生取消或传输丢失。不存在 received/status/wait 工具。[显式 wake](wake.md) 除了 `send` 之外还需要单独的 `wake` 权限。启用 wake 时，请将客户端工具超时配置为 150 秒。

共享 MCP 进程无法可靠地识别调用线程。消息标识为 `session-peer MCP (caller session unavailable)` 并省略 Reply-To，而不是将其归因于启动服务器的会话。请勿依赖此标头进行身份验证。消息正文通过 stdin 传递，而非 shell 命令字符串；正常的 CLI 限制仍然适用。

## 验证

在有和没有 MCP extra 的情况下运行 `python -m unittest discover -s tests -v`。可选测试会启动真实的 stdio MCP 服务器，并在没有模型凭据的情况下执行初始化、模式、策略拒绝和 CLI 部分失败测试。同时测试 wheel 和 sdist 安装。实时检查必须记录 Codex 版本、操作系统和宿主批准设置；UDS 访问取决于环境，不是批准绕过承诺。消息请使用专用测试会话。

此未发布候选方案的CI在macOS/Linux与Python 3.10/3.13/3.14上配置以下四种SDK组合，共24个单元。矩阵已配置并不证明所有单元都已通过；请查看当前运行及保留的版本、审计报告。

| CI配置 | SDK选择 |
| --- | --- |
| `minimum` | `mcp==1.30.0` |
| `latest1` | `mcp>=1.30,<2` |
| `minimum2` | `mcp==2.3.0` |
| `latest2` | `mcp>=2.3,<3` |

各配置运行stdio、策略、超时、取消及所属子进程清理测试，并分别审计解析得到的服务器和测试客户端运行时依赖图，保留版本及报告。任何一项审计失败都会使该CI组合失败。候选测试包含使用隔离的另一SDK主版本客户端，双向进行`2025-11-25`真实stdio初始化，以及SDK 2的`2026-07-28`协商。旧协议传输格式检查会核对camelCase别名、6个工具名称和不变的项目内部结果；这些SDK／协议测试不代表新的真实代理、SSH或ACK验证。传递依赖按常规方式解析，并非测试所有传递依赖包的最低版本。固定版本的构建、审计依赖仍安装在运行时环境之外；审计范围也包括初始配置用的`pip`/`setuptools`。现有的最新版本解析审计和发布审计仍为必需。

官方参考：[Codex MCP](https://developers.openai.com/codex/extend/mcp)、[Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)。 [SDK 1.30.0](https://pypi.org/pypi/mcp/1.30.0/json), [GHSA-84m7-p3x7-pcfv](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv), [GHSA-fmmv-w9g8-j3gc](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-fmmv-w9g8-j3gc).

### 非交互式客户端批准

Codex `exec` 可能会以“requires approval, but approval policy is never”拒绝发送工具，即使服务器策略允许也是如此。`approval_mode="auto"` 并不是无条件批准。显式授权非交互式集成的操作员可以为该特定 MCP 服务器/工具配置 `mcp_servers.session_peer.tools.send_message.approval_mode="approve"`，同时配合受限的目的地策略。插件不会启用此设置。交互式客户端可以改用其常规的批准提示。测试客户端切勿将此授权复制到不相关的服务器或工具。

macOS/Linux上的每次MCP CLI调用拥有独立进程组。完成、超时或取消时，在回收leader前通过有时间限制的TERM→KILL清理该组，包括忽略TERM的子进程；取消仍会传播。主动逃离到新session的子进程和SSH远端进程不在范围内。Windows仍仅终止直接子进程，不保证整个进程树。清理本地进程不撤销远端提交；超时仍为 `outcome_unknown`，不可自动重发。

MCP 正文，包括表示调用会话不可用的 From 标签，都会被目标 CLI 的接收侧消息框架引用。正文头部或嵌入的 Reply-To 均不授予权限。请向会话所有者确认第三方目的地；共享 MCP 进程仍不能提供已认证的调用会话或自动回复路由。最终消息框架也计入原生消息限制。
