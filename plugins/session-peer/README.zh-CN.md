# session-peer Codex 插件

在 Python 3.10+ 环境下安装 `session-peer[mcp]`，然后在 Codex 主机的 PATH 中提供 `session-peer-mcp`。从仓库检出目录运行 `codex plugin marketplace add /absolute/path/to/session-peer`，然后运行 `codex plugin add session-peer@session-peer`。该检出包含 `.agents/plugins/marketplace.json`。该清单注册了附带的 `.mcp.json` stdio 服务器。

在服务器环境中将 `SESSION_PEER_MCP_CONFIG` 设置为绝对策略文件路径。若无此配置，仅允许本地列出。参见 [MCP 设置与策略](../../docs/zh-CN/mcp.md)。安装此捆绑包不会安装 Python 依赖项，也不会授予发送权限。
