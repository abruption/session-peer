# session-peer Codex 插件

在 Python 3.10+ 环境下安装 `session-peer[mcp]`，然后确保在 Codex 主机的 PATH 中能够找到 `session-peer-mcp`。在仓库检出目录中运行 `codex plugin marketplace add /absolute/path/to/session-peer`，接着运行 `codex plugin add session-peer@session-peer`。检出目录中包含 `.agents/plugins/marketplace.json`。插件清单会注册随附的 `.mcp.json` stdio 服务器。

在服务器环境中将 `SESSION_PEER_MCP_CONFIG` 设置为策略文件的绝对路径。若未配置，则仅允许列出本地会话。参见 [MCP 设置与策略](../../docs/zh-CN/mcp.md)。安装此捆绑包不会安装 Python 依赖项，也不会授予发送权限。
