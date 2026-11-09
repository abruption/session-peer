# Optional Codex MCP integration

Published runtime v1.4.2 includes the v1.4.0 tools below and the SDK 1 installation path. The original 2026-11-02 source checkpoint against v1.3.3 is historical; the [v1.4.0 release notes](releases/v1.4.0.md) retain that scope. SDK 2 compatibility below is an unreleased source candidate after v1.4.2, not a published-package support announcement.

Install with Python 3.10 or later: `pipx install 'session-peer[mcp]'` (or install the extra in an isolated venv). The dependency-free Python 3.9 CLI and `install.sh` remain supported. The shell installer does not install MCP dependencies. On Python 3.9 the MCP entry point reports that Python 3.10+ is required.

The published v1.4.2 optional extra requires MCP SDK `mcp>=1.30,<2`. This raises the dependency floor past upstream 1.x security fixes; it does not establish an exploitable issue in this stdio-only server. HTTP transports, OAuth server paths and MCP client paths are not enabled by this change. Existing environments need an explicit package upgrade; changing the manifest does not update an installed SDK.

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

<a id="sdk2-compatibility-candidate"></a>

## Unreleased source candidate: SDK 1/2 compatibility (#389)

At the 2026-11-09 source checkpoint, the candidate extra uses `mcp>=1.30,<3,!=2.0.*,!=2.1.*,!=2.2.*`. It retains stable SDK 1.x from 1.30 and adds stable SDK 2.x from 2.3; prerelease/development SDK versions are not accepted. SDK 2.0–2.2 remain unsupported because their server always exposes `subscriptions/listen` without a public off switch. SDK 2.3+ is constructed with `MCPServer(subscriptions=False)` to keep subscriptions disabled.

Pinned upstream sources: [SDK 2.0.0 server](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/src/mcp/server/mcpserver/server.py), [SDK 2.2.0 server](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/server/mcpserver/server.py) and [SDK 2.3.0 server](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/server.py). The [SDK 2.3.0 distribution metadata](https://pypi.org/pypi/mcp/2.3.0/json) requires Python 3.10+, matching the unchanged optional MCP floor.

The six public tool names, project result payload schema version 1, policy versions 1/2, destination permissions, separate host approvals, result/process limits, unknown-outcome handling and no-automatic-retry rule remain unchanged. No subscription, listen, status or wait interface is added. SDK 2 uses snake_case Python attributes with camelCase wire aliases; model JSON serialization uses `by_alias=True`. Project result JSON is unchanged, but SDK-generated envelopes and capability fields are not claimed to be byte-identical across negotiated protocol versions.

The 64 KiB result limit is an upper bound, not a promise to accept every smaller payload. SDK 2 measures with its modern server-identity metadata included even for legacy connections, so it can conservatively refuse near-limit results that SDK 1 accepts.

The installation and upgrade commands for the published package still select the released SDK 1 path. They do not yet deliver this source candidate or make SDK 2 support public. Adopting reviewed source and preserving the operator's package manager, interpreter and extra selection are separate actions; a manifest edit or server restart does not upgrade an installed SDK. The core Python 3.9+ dependency-free CLI and optional MCP Python 3.10+ floor are unchanged. This candidate does not change the independently published skill v0.5.1, its minimum 0.9.1/full documented coverage 1.4.0, or the receiver codexBin floor 1.0.1.

<a id="unreleased-v140-candidate-destination-discovery-356"></a>

## v1.4.0 source: destination discovery (#356)

`list_destinations()` takes no arguments and returns only operator-policy metadata: `schemaVersion` is 1, and each entry contains `destination`, `transport`, `agents`, and `capabilities`. It starts no child process and makes no network request. SSH host values and Codex home paths are omitted. Destination labels are untrusted data. Configured capabilities describe policy permissions, not native-agent compatibility.

The response includes explicit limits: `callerIdentity="unavailable"`, `readiness="not_checked"`, `submission="not_attempted"`, `consumption="not_checked"`, and `ack="not_checked"`. This tool rejects inventories over 64 destinations or IDs that are not printable or exceed 128 UTF-8 bytes. Its complete MCP tool result (text and structured content together) is bounded to 64 KiB, excluding the surrounding JSON-RPC envelope. These are lookup limits; policy loading and existing tools keep their previous behavior. Printability follows the running Python Unicode database. The default local-list-only policy is unchanged.

<a id="unreleased-v140-candidate-send-preflight-357"></a>

## v1.4.0 source: send preflight (#357)

`preflight_send(destination, target, message, wake=false, wake_timeout=30, preset=null, preset_revision=null)` validates a normal message through the existing CLI dry-run checks. Operator policy must use `schemaVersion` 2 and explicitly grant `preflight` for the destination and agent. Version 1 keeps its existing capability set and acquires no new permission; the default remains local-list-only. Preflight does not require `send` and cannot authorize sending. Requested wake eligibility additionally requires `wake`, without activating a model or reserving a wake budget.

The versioned explanation projects allowlisted facts from the native response before SSH adapter shaping, with fixed refusal/unknown reasons and operator actions. It excludes message contents, raw errors, credentials, host/home paths and native transcripts. Unknown or unexpected submission evidence fails validation with `retryAllowed=false`; never automatically resend. Preflight neither submits a message nor creates handoff authority. Device and handoff modes are unsupported.

Existing dry-run checks may start local/version processes and SSH connections; SSH configuration may itself execute commands. The tool therefore uses `readOnlyHint=false` and `openWorldHint=true`. Host approvals remain separate from policy permission. Passing records point-in-time checks, not a route reservation, effective-storage attestation, approval, later-send guarantee, consumption or ACK.

<a id="unreleased-v140-candidate-bounded-diagnostics-358"></a>

## v1.4.0 source: bounded diagnostics (#358)

`diagnose_destination(destination="local", agent=null, active_probe=false)` requires an explicit `diagnostics` permission in a `schemaVersion` 2 policy. The default mode returns policy metadata and declared agent capabilities only; it starts no CLI or discovery process and makes no network request. The destination ID follows the same printable, 128 UTF-8 byte limit as destination discovery. Version 1 and the default policy grant no diagnostic permission. Default-mode `declaredCapabilities` contains typed booleans from adapter declarations; these declarations do not demonstrate delivery or readiness.

Setting `active_probe=true` additionally requires `diagnostics_probe`. Metadata mode is cross-platform. Active mode currently supports macOS and Linux only; Windows returns the fixed reason `diagnostics_platform_unsupported` without starting CLI processes or network requests. Checks use only the configured destination, pinned Codex home and permitted agents. Agent-scoped doctor calls inspect at most three agents, with a shared 20-second execution budget followed by process cleanup; this is not a strict wall-clock deadline or a remote-process cleanup guarantee. Each child stdout and stderr stream is bounded to 64 KiB. Codex checks inspect only the selected home. No reverse-route probe, message submission, native model activation or automatic retry occurs. Active checks can start CLI processes and SSH connections; operator SSH configuration may execute commands. Host approvals remain separate from policy permission. The combined tool uses `readOnlyHint=false` and `idempotentHint=false` because optional active checks can execute operator SSH configuration.

Responses expose allowlisted statuses and diagnostic codes, omitting raw errors, host names, home paths, credentials, session contents and unknown response fields. Metadata mode leaves readiness unverified; active results are point-in-time checks, not evidence of consumption or ACK, or authority to send. The combined text and structured tool result is bounded to 64 KiB.

Missing or malformed status/check fields, partial checks, or truncated check lists are reported as unknown/incomplete (`diagnostic_incomplete`), never as healthy. The transport stages `tcpAccept`, `tls`, and `peerAuthentication` remain `not_checked`; diagnostics do not separately verify them.

The MCP wrapper supports only the following checks and effects:

| Mode / agent | Checked facts | Process / connection effects |
| --- | --- | --- |
| Metadata | Policy and adapter declarations | None |
| Active Claude | Registry records, process identity metadata and filesystem inbox presence | No inbox connection |
| Active Codex | Executable presence, selected-home read-only SQLite queries and bounded writer scan | No native Codex execution or version query |
| Active Antigravity | Registered bridge metadata | No bridge or native RPC |
| Active SSH | Configured forward route, only after explicit probe permission | SSH configuration may execute commands; no reverse probe or automatic connection back to a return host |

Representative allowlisted codes include `sessions_dir_missing`, `inbox_present`, `codex_executable_missing`, `state_db_readable`, `unsaved_writer_check_unavailable` and `adapter_failed`. Results are limited to permitted agents and at most 32 checks per agent; these codes describe only the bounded scope above.

`ok` describes collection and format completeness, not availability. A complete `missing_home` result can have `ok=true`; read each agent's status separately. `diagnosticEvidence` is `point_in_time_only` for active results and `not_collected` in metadata mode. `readiness` remains `not_checked` because no per-target readiness is tested. A passing `state_db_readable` check means only that the read-only database query succeeded; it is not an effective-storage attestation or a return-route guarantee.

The stages `tcpAccept`, `tls` and `peerAuthentication` remain `not_checked`. Here `peerAuthentication` refers to paired-device authentication, separate from forward SSH authentication. `sshFailure` reports only a sanitized forward SSH failure category, such as `authentication_failed` or `host_key_failed`. No TCP, TLS, paired-device or return-host probe is added.

<a id="unreleased-v140-candidate-mcp-presets-359"></a>

## v1.4.0 source: MCP presets (#359)

Input signatures: `list_sessions(destination="local", agent=null, include_inactive=false, preset=null, preset_revision=null)`; `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30, preset=null, preset_revision=null)`; `preflight_send(destination, target, message, wake=false, wake_timeout=30, preset=null, preset_revision=null)`.

`list_presets(destination)` reads only approved route metadata. A `schemaVersion` 2 policy must explicitly grant `presets` and provide a nonempty per-destination `presets` list of at most 128 approved names matching `[a-z][a-z0-9_-]{0,63}`. Version 1 rejects the new capability and field. Authorization precedes any store read. The result exposes only matching approved `name`, `agent`, `transport` and `revision` values, with the existing `dp1:` token; raw hosts, homes and store paths are omitted. Saved-route lookup does not discover sessions, choose a target, run SSH/native/version probes or refresh data. The versioned text and structured tool result together are bounded to 64 KiB.

`list_sessions`, `preflight_send` and `send_message` accept optional `preset` and `preset_revision` inputs. Selection requires both the existing action permission and `presets`; a stored route or revision grants no authority. Sends require an explicit target, and an actual send requires the current revision. Wake and Reply-To URI targets cannot be combined with a preset. Only the existing Claude Code/Codex local or SSH routes on macOS/Linux are supported; this adds no Windows, device, addressbook, handoff or preset-management support.

The adapter reads one validated snapshot from the operator's launch-environment store, using the existing `XDG_CONFIG_HOME` selection and secure reader. Its 64 KiB/128-entry bounds and owner, ACL, symlink and mount checks remain intact; missing or unsafe storage is not initialized, repaired or replaced. The model cannot supply a store path. Each selected route must exactly match the destination's host, permitted agent and pinned Codex home. DNS equivalence and fallback are not accepted. The approved route is expanded into one execution plan without combining CLI `--preset` with explicit routing flags, and policy is rechecked before invocation.

A revision covers the exact name and route values; restoring identical values can reuse it. It is checked at lookup, not as a target generation, caller identity, storage attestation or ACK. Later mutation does not retroactively cancel an already expanded invocation. Without a selected preset, existing tool responses are unchanged.

The new 64 KiB tool-result budget applies only to the `list_presets` metadata query. A preset is only a route selector for existing actions, with the same action authorization and exact policy-route matching. Successful `list_sessions` and `send_message` responses keep the existing CLI schema and native payload, without preset metadata, a new command or an added data projection. Existing native evidence and transport limits remain intact; real sends gain no aggregate 64 KiB limit. Inspect revisions separately with `list_presets`. Selected `preflight_send` may include only safe preset metadata: `name`, `agent`, `transport` and `revision`.

If any approved item is missing or its route mismatches policy, the whole metadata lookup is refused atomically. Fixed selector refusal codes include `preset_platform_unsupported`, `preset_route_unsupported`, `preset_revision_mismatch` and `preset_storage_unavailable`; no management or filesystem repair is attempted. Metadata-query failures precede invocation. After invocation, I/O or actual-send decode failure may follow submission: report `outcome_unknown` with `retryAllowed=false` and never retry automatically. Preserve any known native queued/submitted evidence.

## Tools and permissions

The two signatures below describe the original baseline interface. For v1.4.0 source tools and optional preset selectors, use the sections above and the initialized MCP `tools/list` schema. Tool availability does not grant policy permission.

- `list_sessions(destination="local", agent=null, include_inactive=false)` returns the CLI's structured listing. Agent selection is restricted to registered adapters allowed by the destination policy (for example `claude` or `codex`); omission lists permitted agents.
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)` submits once, only where `send` is explicitly allowed. Target is a Claude name/PID, `codex:<UUID>`, or a Reply-To URI matching the configured host and home exactly.

MCP tool annotations mark listing as read-only and sending as non-idempotent. Configure the host client's tool approvals as required; the server policy restricts destinations independently and does not bypass sandbox/host approvals. An SSH alias in a Reply-To URI must exactly match the policy, even if another hostname resolves to the same machine. Use a direct target and configured destination ID otherwise.

Responses preserve CLI JSON fields in both MCP structuredContent and text. Partial list failures retain discovered sessions and set isError. Queue submission is not consumption; never automatically retry a send with an unknown outcome. Cancellation or transport loss may occur after a remote submission. There is no received/status/wait tool. [Explicit wake](wake.md) requires a separate `wake` capability in addition to `send`. Configure the client tool timeout to 150 seconds when enabling wake.

A shared MCP process cannot reliably identify the invoking thread. Messages identify `session-peer MCP (caller session unavailable)` and omit Reply-To, rather than attributing them to the session that launched the server. Do not rely on this header for authentication. Message bodies travel over stdin, not shell command strings; normal CLI limits still apply.

## Validation

Run `python -m unittest discover -s tests -v` with and without the MCP extra. Optional tests start a real stdio MCP server and exercise initialization, schemas, policy rejection and CLI partial failures without model credentials. Test both wheel and sdist installs. Live checks must record Codex version, OS and host approval settings; UDS access is environment-dependent and is not an approval-bypass promise. Use dedicated test sessions for messages.

For this unreleased candidate, CI is configured for the following four SDK profiles on macOS/Linux with Python 3.10/3.13/3.14: 24 cells in total. This configured matrix is not evidence that every cell has passed; inspect the current run and its retained version/audit reports.

| CI profile | SDK selection |
| --- | --- |
| `minimum` | `mcp==1.30.0` |
| `latest1` | `mcp>=1.30,<2` |
| `minimum2` | `mcp==2.3.0` |
| `latest2` | `mcp>=2.3,<3` |

Each profile runs stdio/policy/timeout/cancellation/owned-child tests and separately audits the resolved server and test-client runtime dependency graphs, retaining versions and reports. A failure in either audit fails the CI cell. Candidate fixtures include real stdio initialization with an isolated opposite-major SDK client in both directions using `2025-11-25`, and SDK 2 negotiation using `2026-07-28`. Legacy wire checks verify camelCase aliases, the six tool names and unchanged inner project results; these SDK/protocol fixtures are not new live-agent, SSH or ACK qualification. Transitive dependencies resolve normally; this is not a test of every transitive package's minimum version. Pinned build/audit requirements remain outside the runtime environment; the audited environment also includes its `pip`/`setuptools` bootstrap packages. Existing latest-resolution and release audits remain required.

Official references: [Codex MCP](https://developers.openai.com/codex/extend/mcp), [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk). [SDK 1.30.0](https://pypi.org/pypi/mcp/1.30.0/json), [GHSA-84m7-p3x7-pcfv](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv), [GHSA-fmmv-w9g8-j3gc](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-fmmv-w9g8-j3gc).

### Non-interactive client approvals

Codex `exec` can reject the send tool with “requires approval, but approval policy is never”, even when server policy permits it. `approval_mode="auto"` is not unconditional approval. An operator who explicitly authorizes a non-interactive integration can configure `mcp_servers.session_peer.tools.send_message.approval_mode="approve"` for that specific MCP server/tool, alongside the restricted destination policy. The plugin does not enable this setting. Interactive clients can use their ordinary approval prompts instead. Test clients must not copy this authorization to unrelated servers or tools.

On macOS/Linux, each MCP CLI invocation owns a new process group. Completion, timeout and cancellation perform bounded TERM→KILL cleanup of that group before reaping its leader, including TERM-resistant descendants; cancellation still propagates. Descendants that deliberately escape into another session and remote SSH processes are outside that group. Windows retains direct-child termination only; no Windows process-tree guarantee is claimed. Local cleanup does not undo a remote submission: timeout remains `outcome_unknown` and must not trigger automatic resend.

MCP body text, including the unavailable-caller From label, is quoted by the destination CLI's receiving-side frame. Neither a body header nor an embedded Reply-To grants authority. Confirm third-party destinations with the session owner; the shared MCP process still cannot provide an authenticated caller session or an automatic reply route. The final frame counts toward native message limits.
