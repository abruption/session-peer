# Optional Codex MCP integration

Install with Python 3.10 or later: `pipx install 'session-peer[mcp]'` (or install the extra in an isolated venv). The dependency-free Python 3.9 CLI and `install.sh` remain supported. The shell installer does not install MCP dependencies. On Python 3.9 the MCP entry point reports that Python 3.10+ is required.

Start `session-peer-mcp --config /absolute/path/policy.json`. Without a policy the server allows only local listing, using the launching environment's Codex home. A supplied policy replaces defaults. Example:

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

Use the actual username and SSH destination, configured keys and known_hosts. No passwords belong in this file. Every Codex destination must pin an absolute home on that destination; add separate destination IDs for additional homes. Protect the policy from modification by untrusted processes. SSH configuration remains operator-controlled.

Register using `codex mcp add session-peer -- /absolute/path/session-peer-mcp --config /absolute/path/policy.json`, or use the repository's `plugins/session-peer` bundle: `codex plugin marketplace add /absolute/path/to/session-peer`, then `codex plugin add session-peer@session-peer`. The plugin launches `session-peer-mcp` from PATH and reads `SESSION_PEER_MCP_CONFIG` when set in its environment. Install the Python extra first. Existing Codex settings are not modified by installing the Python package.

## Tools and permissions

- `list_sessions(destination="local", agent=null, include_inactive=false)` returns the CLI's structured listing. Agent may be `claude` or `codex`; omission lists permitted agents.
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` submits once, only where `send` is explicitly allowed. Target is a Claude name/PID, `codex:<UUID>`, or a Reply-To URI matching the configured host and home exactly.

MCP tool annotations mark listing as read-only and sending as non-idempotent. Configure the host client's tool approvals as required; the server policy restricts destinations independently and does not bypass sandbox/host approvals. An SSH alias in a Reply-To URI must exactly match the policy, even if another hostname resolves to the same machine. Use a direct target and configured destination ID otherwise.

Responses preserve CLI JSON fields in both MCP structuredContent and text. Partial list failures retain discovered sessions and set isError. Queue submission is not consumption; never automatically retry a send with an unknown outcome. Cancellation or transport loss may occur after a remote submission. There is no received/status/wait tool. [Explicit wake](wake.md) requires a separate `wake` capability in addition to `send`. Configure the client tool timeout to 150 seconds when enabling wake.

A shared MCP process cannot reliably identify the invoking thread. Messages identify `session-peer MCP (caller session unavailable)` and omit Reply-To, rather than attributing them to the session that launched the server. Do not rely on this header for authentication. Message bodies travel over stdin, not shell command strings; normal CLI limits still apply.

## Validation

Run `python -m unittest discover -s tests -v` with and without the MCP extra. Optional tests start a real stdio MCP server and exercise initialization, schemas, policy rejection and CLI partial failures without model credentials. Test both wheel and sdist installs. Live checks must record Codex version, OS and host approval settings; UDS access is environment-dependent and is not an approval-bypass promise. Use dedicated test sessions for messages.

Official references: [Codex MCP](https://developers.openai.com/codex/extend/mcp), [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).

### Non-interactive client approvals

Codex `exec` can reject the send tool with “requires approval, but approval policy is never”, even when server policy permits it. `approval_mode="auto"` is not unconditional approval. An operator who explicitly authorizes a non-interactive integration can configure `mcp_servers.session_peer.tools.send_message.approval_mode="approve"` for that specific MCP server/tool, alongside the restricted destination policy. The plugin does not enable this setting. Interactive clients can use their ordinary approval prompts instead. Test clients must not copy this authorization to unrelated servers or tools.
