# session-peer Codex plugin

Install `session-peer[mcp]` with Python 3.10+, then make `session-peer-mcp` available on the Codex host's PATH. From a repository checkout, run `codex plugin marketplace add /absolute/path/to/session-peer`, then `codex plugin add session-peer@session-peer`. The checkout includes `.agents/plugins/marketplace.json`. The manifest registers the bundled `.mcp.json` stdio server.

Set `SESSION_PEER_MCP_CONFIG` in the server environment to an absolute policy file. Without it only local listing is permitted. See [MCP setup and policy](../../docs/mcp.md). Installing this bundle does not install Python dependencies or grant send permissions.
