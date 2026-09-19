# 可选 Codex MCP 集成

在 Python 3.10 或更高版本下安装：`pipx install 'session-peer[mcp]'`（或在隔离的 venv 中安装 extra）。仍支持无依赖的 Python 3.9 CLI 和 `install.sh`。shell 安装程序不安装 MCP 依赖项。在 Python 3.9 上，MCP 入口点会报告需要 Python 3.10+。

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

## 工具与权限

- `list_sessions(destination="local", agent=null, include_inactive=false)` 返回 CLI 的结构化列表。Agent 可以是 `claude` 或 `codex`；省略则列出允许的代理。
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` 仅在显式允许 `send` 的情况下提交一次。Target 是 Claude 名称/PID、`codex:<UUID>` 或与配置的主机和主目录完全匹配的 Reply-To URI。

MCP 工具注解将列出标记为只读，将发送标记为非幂等。根据需要配置宿主客户端的工具批准；服务器策略独立限制目的地，且不会绕过沙盒/宿主批准。Reply-To URI 中的 SSH 别名必须与策略完全匹配，即使另一个主机名解析到同一台机器也是如此。否则请使用直接目标和配置的目的地 ID。

响应在 MCP structuredContent 和文本中均保留 CLI JSON 字段。部分列表失败会保留已发现的会话并设置 isError。队列提交并非消费；切勿自动重试结果未知的发送。远程提交后可能会发生取消或传输丢失。不存在 received/status/wait 工具。[显式 wake](wake.md) 除了 `send` 之外还需要单独的 `wake` 功能。启用 wake 时，请将客户端工具超时配置为 150 秒。

共享 MCP 进程无法可靠地识别调用线程。消息标识为 `session-peer MCP (caller session unavailable)` 并省略 Reply-To，而不是将其归因于启动服务器的会话。请勿依赖此标头进行身份验证。消息正文通过 stdin 传递，而非 shell 命令字符串；正常的 CLI 限制仍然适用。

## 验证

在有和没有 MCP extra 的情况下运行 `python -m unittest discover -s tests -v`。可选测试会启动真实的 stdio MCP 服务器，并在没有模型凭据的情况下执行初始化、模式、策略拒绝和 CLI 部分失败测试。同时测试 wheel 和 sdist 安装。实时检查必须记录 Codex 版本、操作系统和宿主批准设置；UDS 访问取决于环境，不是批准绕过承诺。消息请使用专用测试会话。

官方参考：[Codex MCP](https://developers.openai.com/codex/extend/mcp)、[Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)。

### 非交互式客户端批准

Codex `exec` 可能会以“requires approval, but approval policy is never”拒绝发送工具，即使服务器策略允许也是如此。`approval_mode="auto"` 并不是无条件批准。显式授权非交互式集成的操作员可以为该特定 MCP 服务器/工具配置 `mcp_servers.session_peer.tools.send_message.approval_mode="approve"`，同时配合受限的目的地策略。插件不会启用此设置。交互式客户端可以改用其常规的批准提示。测试客户端切勿将此授权复制到不相关的服务器或工具。
