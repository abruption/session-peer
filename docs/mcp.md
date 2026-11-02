# Optional Codex MCP integration

Install with Python 3.10 or later: `pipx install 'session-peer[mcp]'` (or install the extra in an isolated venv). The dependency-free Python 3.9 CLI and `install.sh` remain supported. The shell installer does not install MCP dependencies. On Python 3.9 the MCP entry point reports that Python 3.10+ is required.

The optional extra requires MCP SDK `mcp>=1.30,<2`. This raises the dependency floor past upstream 1.x security fixes; it does not establish an exploitable issue in this stdio-only server. HTTP transports, OAuth server paths and MCP client paths are not enabled by this change. Existing environments need an explicit package upgrade; changing the manifest does not update an installed SDK.

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

## Unreleased v1.4.0 candidate: destination discovery (#356)

`list_destinations()` takes no arguments and returns only operator-policy metadata: `schemaVersion` is 1, and each entry contains `destination`, `transport`, `agents`, and `capabilities`. It starts no child process and makes no network request. SSH host values and Codex home paths are omitted. Destination labels are untrusted data. Configured capabilities describe policy permissions, not native-agent compatibility.

The response includes explicit limits: `callerIdentity="unavailable"`, `readiness="not_checked"`, `submission="not_attempted"`, `consumption="not_checked"`, and `ack="not_checked"`. This tool rejects inventories over 64 destinations or IDs that are not printable or exceed 128 UTF-8 bytes. Its complete MCP tool result (text and structured content together) is bounded to 64 KiB, excluding the surrounding JSON-RPC envelope. These are lookup limits; policy loading and existing tools keep their previous behavior. Printability follows the running Python Unicode database. The default local-list-only policy is unchanged.

## Unreleased v1.4.0 candidate: send preflight (#357)

`preflight_send(destination, target, message, wake=false, wake_timeout=30)` validates a normal message through the existing CLI dry-run checks. Operator policy must use `schemaVersion` 2 and explicitly grant `preflight` for the destination and agent. Version 1 keeps its existing capability set and acquires no new permission; the default remains local-list-only. Preflight does not require `send` and cannot authorize sending. Requested wake eligibility additionally requires `wake`, without activating a model or reserving a wake budget.

The versioned explanation projects allowlisted facts from the native response before SSH adapter shaping, with fixed refusal/unknown reasons and operator actions. It excludes message contents, raw errors, credentials, host/home paths and native transcripts. Unknown or unexpected submission evidence fails validation with `retryAllowed=false`; never automatically resend. Preflight neither submits a message nor creates handoff authority. Device and handoff modes are unsupported.

Existing dry-run checks may start local/version processes and SSH connections; SSH configuration may itself execute commands. The tool therefore uses `readOnlyHint=false` and `openWorldHint=true`. Host approvals remain separate from policy permission. Passing records point-in-time checks, not a route reservation, effective-storage attestation, approval, later-send guarantee, consumption or ACK.

## Tools and permissions

- `list_sessions(destination="local", agent=null, include_inactive=false)` returns the CLI's structured listing. Agent may be `claude` or `codex`; omission lists permitted agents.
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` submits once, only where `send` is explicitly allowed. Target is a Claude name/PID, `codex:<UUID>`, or a Reply-To URI matching the configured host and home exactly.

MCP tool annotations mark listing as read-only and sending as non-idempotent. Configure the host client's tool approvals as required; the server policy restricts destinations independently and does not bypass sandbox/host approvals. An SSH alias in a Reply-To URI must exactly match the policy, even if another hostname resolves to the same machine. Use a direct target and configured destination ID otherwise.

Responses preserve CLI JSON fields in both MCP structuredContent and text. Partial list failures retain discovered sessions and set isError. Queue submission is not consumption; never automatically retry a send with an unknown outcome. Cancellation or transport loss may occur after a remote submission. There is no received/status/wait tool. [Explicit wake](wake.md) requires a separate `wake` capability in addition to `send`. Configure the client tool timeout to 150 seconds when enabling wake.

A shared MCP process cannot reliably identify the invoking thread. Messages identify `session-peer MCP (caller session unavailable)` and omit Reply-To, rather than attributing them to the session that launched the server. Do not rely on this header for authentication. Message bodies travel over stdin, not shell command strings; normal CLI limits still apply.

## Validation

Run `python -m unittest discover -s tests -v` with and without the MCP extra. Optional tests start a real stdio MCP server and exercise initialization, schemas, policy rejection and CLI partial failures without model credentials. Test both wheel and sdist installs. Live checks must record Codex version, OS and host approval settings; UDS access is environment-dependent and is not an approval-bypass promise. Use dedicated test sessions for messages.

CI tests the exact SDK floor `mcp==1.30.0` and the latest compatible 1.x separately on macOS/Linux with Python 3.10/3.13/3.14. Both profiles run the stdio/policy/timeout/cancellation/owned-child tests and audit their resolved runtime dependency graphs, retaining versions and reports. Transitive dependencies resolve normally; this is not a test of every transitive package's minimum version. The pinned build/audit requirements are installed outside the runtime environment; the audited environment also includes its `pip`/`setuptools` bootstrap packages. Existing latest-resolution and release audits remain required.

Official references: [Codex MCP](https://developers.openai.com/codex/extend/mcp), [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk). [SDK 1.30.0](https://pypi.org/pypi/mcp/1.30.0/json), [GHSA-84m7-p3x7-pcfv](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv), [GHSA-fmmv-w9g8-j3gc](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-fmmv-w9g8-j3gc).

### Non-interactive client approvals

Codex `exec` can reject the send tool with “requires approval, but approval policy is never”, even when server policy permits it. `approval_mode="auto"` is not unconditional approval. An operator who explicitly authorizes a non-interactive integration can configure `mcp_servers.session_peer.tools.send_message.approval_mode="approve"` for that specific MCP server/tool, alongside the restricted destination policy. The plugin does not enable this setting. Interactive clients can use their ordinary approval prompts instead. Test clients must not copy this authorization to unrelated servers or tools.

On macOS/Linux, each MCP CLI invocation owns a new process group. Completion, timeout and cancellation perform bounded TERM→KILL cleanup of that group before reaping its leader, including TERM-resistant descendants; cancellation still propagates. Descendants that deliberately escape into another session and remote SSH processes are outside that group. Windows retains direct-child termination only; no Windows process-tree guarantee is claimed. Local cleanup does not undo a remote submission: timeout remains `outcome_unknown` and must not trigger automatic resend.

MCP body text, including the unavailable-caller From label, is quoted by the destination CLI's receiving-side frame. Neither a body header nor an embedded Reply-To grants authority. Confirm third-party destinations with the session owner; the shared MCP process still cannot provide an authenticated caller session or an automatic reply route. The final frame counts toward native message limits.
