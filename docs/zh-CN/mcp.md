# 可选 Codex MCP 集成

在 Python 3.10 或更高版本下安装：`pipx install 'session-peer[mcp]'`（或在隔离的 venv 中安装 extra）。仍支持无依赖的 Python 3.9 CLI 和 `install.sh`。shell 安装程序不安装 MCP 依赖项。在 Python 3.9 上，MCP 入口点会报告需要 Python 3.10+。

可选extra要求MCP SDK `mcp>=1.30,<2`。这是将依赖版本下限提高到包含上游1.x安全修复的版本，并不表示已在这个仅使用stdio的服务器中确认可利用漏洞。本次变更不启用HTTP传输、OAuth服务器路径或MCP客户端路径。现有环境需要显式升级软件包；仅修改声明不会更新已安装的SDK。

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

## 尚未发布的 v1.4.0 候选版本：目的地发现 (#356)

`list_destinations()` 不接受参数，仅返回操作员策略的元数据：`schemaVersion` 为 1，每个条目包含 `destination`、`transport`、`agents` 和 `capabilities`。它不会启动子进程，也不会发起网络请求。SSH 主机配置值和 Codex 主目录路径会被省略。目的地名称是不可信数据。已配置的功能表示策略权限，不表示原生代理的兼容性。

响应明确列出限制：`callerIdentity="unavailable"`、`readiness="not_checked"`、`submission="not_attempted"`、`consumption="not_checked"` 和 `ack="not_checked"`。目的地超过 64 个、ID 含不可打印字符或 UTF-8 编码超过 128 字节时，此工具拒绝查询。文本与结构化内容合计的 MCP 工具结果不超过 64 KiB，不包括外层 JSON-RPC 信封。这些限制仅适用于查询工具，策略加载及现有工具的行为保持不变。可打印字符的判定遵循运行中 Python 的 Unicode 数据库。默认的仅限本地列表查询的策略保持不变。

## 尚未发布的 v1.4.0 候选版本：发送预检 (#357)

`preflight_send(destination, target, message, wake=false, wake_timeout=30)` 通过现有 CLI dry-run 检查验证普通消息。操作员策略必须使用 `schemaVersion` 2，并为目的地和代理显式授予 `preflight`。版本 1 保留原有的功能集合，不会自动获得新权限；默认策略仍仅允许本地列表查询。预检不需要 `send`，也不能授予发送权限。如需检查唤醒资格，还必须单独具有 `wake`，但不会激活模型或预留唤醒额度。

带有版本的说明会在 SSH 适配器加工结果前，从原生响应中提取允许的事实，并提供固定的拒绝或未知原因及操作员处置建议。它不包含消息内容、原始错误、凭据、主机或主目录路径、原生记录。结果未知或存在意外提交证据时，验证失败并返回 `retryAllowed=false`；切勿自动重发。预检不会提交消息或创建 handoff 授权。不支持设备和 handoff 模式。

现有 dry-run 检查可能启动本地或版本查询进程、建立 SSH 连接；SSH 配置本身也可能执行命令。因此该工具使用 `readOnlyHint=false` 和 `openWorldHint=true`。宿主批准独立于策略权限。通过仅表示检查时点的结果，不代表预留路由、证明有效存储、批准、保证后续发送、消费或 ACK。

## 尚未发布的 v1.4.0 候选版本：有界诊断 (#358)

`diagnose_destination(destination="local", agent=null, active_probe=false)` 要求在 `schemaVersion` 2 策略中显式授予 `diagnostics` 权限。默认模式仅返回策略元数据和声明的代理功能，不启动 CLI 或发现进程，也不发起网络请求。目的地 ID 采用与目的地发现相同的可打印字符及 UTF-8 128 字节限制。版本 1 和默认策略均不授予诊断权限。 默认模式的 `declaredCapabilities` 包含来自适配器声明的布尔值，不证明实际送达或就绪状态。

设置 `active_probe=true` 还需要 `diagnostics_probe`。元数据模式支持所有平台。主动模式目前仅支持 macOS 和 Linux；在 Windows 上返回固定原因 `diagnostics_platform_unsupported`，不启动 CLI 进程或网络请求。检查仅使用配置的目的地、固定的 Codex 主目录和获准的代理。按代理限定范围的 doctor 调用最多检查三个代理，共享 20 秒的执行预算，然后清理进程；这并非严格的实际耗时上限，也不保证清理远程进程。子进程的 stdout 和 stderr 各限 64 KiB。Codex 检查仅访问所选主目录。不进行反向路由探测、消息提交、原生模型激活或自动重试。主动检查可能启动 CLI 进程和 SSH 连接，操作员的 SSH 配置本身也可能执行命令。宿主批准独立于策略权限。由于可选的主动检查能够执行操作员 SSH 配置，组合工具使用 `readOnlyHint=false` 和 `idempotentHint=false`。

响应仅公开允许列表中的状态和诊断代码，省略原始错误、主机名、主目录路径、凭据、会话内容和未知响应字段。元数据模式不验证就绪状态；主动检查结果也仅代表检查时点，不是消费或 ACK 的证据，也不授予发送权限。文本与结构化工具结果的合计大小限于 64 KiB。

状态或检查字段缺失、格式错误、检查不完整或检查列表被截断时，结果报告为未知或不完整（`diagnostic_incomplete`），不会报告为健康。传输阶段 `tcpAccept`、`tls` 和 `peerAuthentication` 均保持 `not_checked`；诊断不会单独验证这些阶段。

## 工具与权限

- `list_sessions(destination="local", agent=null, include_inactive=false)` 返回 CLI 的结构化列表。Agent 可以是 `claude` 或 `codex`；省略则列出允许的代理。
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` 仅在显式允许 `send` 的情况下提交一次。Target 是 Claude 名称/PID、`codex:<UUID>` 或与配置的主机和主目录完全匹配的 Reply-To URI。

MCP 工具注解将列出标记为只读，将发送标记为非幂等。根据需要配置宿主客户端的工具批准；服务器策略独立限制目的地，且不会绕过沙盒/宿主批准。Reply-To URI 中的 SSH 别名必须与策略完全匹配，即使另一个主机名解析到同一台机器也是如此。否则请使用直接目标和配置的目的地 ID。

响应在 MCP structuredContent 和文本中均保留 CLI JSON 字段。部分列表失败会保留已发现的会话并设置 isError。队列提交并非消费；切勿自动重试结果未知的发送。远程提交后可能会发生取消或传输丢失。不存在 received/status/wait 工具。[显式 wake](wake.md) 除了 `send` 之外还需要单独的 `wake` 功能。启用 wake 时，请将客户端工具超时配置为 150 秒。

共享 MCP 进程无法可靠地识别调用线程。消息标识为 `session-peer MCP (caller session unavailable)` 并省略 Reply-To，而不是将其归因于启动服务器的会话。请勿依赖此标头进行身份验证。消息正文通过 stdin 传递，而非 shell 命令字符串；正常的 CLI 限制仍然适用。

## 验证

在有和没有 MCP extra 的情况下运行 `python -m unittest discover -s tests -v`。可选测试会启动真实的 stdio MCP 服务器，并在没有模型凭据的情况下执行初始化、模式、策略拒绝和 CLI 部分失败测试。同时测试 wheel 和 sdist 安装。实时检查必须记录 Codex 版本、操作系统和宿主批准设置；UDS 访问取决于环境，不是批准绕过承诺。消息请使用专用测试会话。

CI在macOS/Linux的Python 3.10/3.13/3.14上分别测试SDK下限`mcp==1.30.0`及最新兼容1.x。两个配置均运行stdio、策略、超时、取消及所属子进程清理测试，并审计解析得到的运行时依赖图，保留版本和报告。传递依赖按常规方式解析；这不是对所有传递依赖包的最低版本进行测试。固定版本的构建与审计依赖安装在运行时环境之外；被审计的环境也包含用于初始配置的`pip`/`setuptools`包。现有的最新版本解析审计和发布审计仍为必需。

官方参考：[Codex MCP](https://developers.openai.com/codex/extend/mcp)、[Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)。 [SDK 1.30.0](https://pypi.org/pypi/mcp/1.30.0/json), [GHSA-84m7-p3x7-pcfv](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv), [GHSA-fmmv-w9g8-j3gc](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-fmmv-w9g8-j3gc).

### 非交互式客户端批准

Codex `exec` 可能会以“requires approval, but approval policy is never”拒绝发送工具，即使服务器策略允许也是如此。`approval_mode="auto"` 并不是无条件批准。显式授权非交互式集成的操作员可以为该特定 MCP 服务器/工具配置 `mcp_servers.session_peer.tools.send_message.approval_mode="approve"`，同时配合受限的目的地策略。插件不会启用此设置。交互式客户端可以改用其常规的批准提示。测试客户端切勿将此授权复制到不相关的服务器或工具。

macOS/Linux上的每次MCP CLI调用拥有独立进程组。完成、超时或取消时，在回收leader前通过有时间限制的TERM→KILL清理该组，包括忽略TERM的子进程；取消仍向上传播。主动逃离到新session的子进程和SSH远端进程不在范围内。Windows仍仅终止直接子进程，不保证整个进程树。清理本地进程不撤销远端提交；超时仍为 `outcome_unknown`，不可自动重发。

MCP 正文，包括表示调用会话不可用的 From 标签，都会被目标 CLI 的接收侧消息框架引用。正文头部或嵌入的 Reply-To 均不授予权限。请向会话所有者确认第三方目的地；共享 MCP 进程仍不能提供已认证的调用会话或自动回复路由。最终消息框架也计入原生消息限制。
