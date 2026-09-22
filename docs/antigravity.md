# Antigravity CLI adapter (experimental)

This experimental opt-in adapter is available in session-peer v0.9.0.
Install it with `pipx install session-peer` or `uv tool install session-peer`.
Release availability does not establish long-term operational stability.
It uses the internal adapter/transport refactor (#47), and can be authorized as
a target for paired-device delivery (#69). Antigravity itself is never installed
automatically. Unfiltered listing includes live bridge registrations.

It delivers to an **existing TUI** using a user-started local bridge and the
[official agentapi interface](https://antigravity.google/docs/sidecars/).
Mac and Linux CLI 1.2.4 experiments demonstrated idle delivery. A later macOS
CLI 1.2.7 RC run passed both direct and public-relay delivery after aligning the
documented `agentapi send-message` positionals. A CLI sidecar autostart mechanism
has **not** been established. `agy -p` and starting another
writer with `--conversation` are not delivery substitutes. Windows bridge
operation is unsupported; other adapters remain available there.

## Register from the receiving TUI

Ask the receiving agy TUI to execute this command through its normal tool runner:

```sh
session-peer antigravity-bridge serve --thread FULL-CONVERSATION-UUID
```

Run as the account that owns the TUI. A workspace directory owned by another user
does not identify the CLI's home. Default home is `~/.gemini/antigravity-cli`;
use `--antigravity-home /absolute/path` for a custom home. Registration verifies
an ancestor `agy` process, UID, start time, and an open presence file for that
exact home and conversation. Linux uses `/proc`; macOS uses `ps` and `lsof`.
On macOS, process start time is read with a fixed C locale so a bridge started
from a localized TUI remains discoverable by relay workers using another locale.
An open presence FD is identity evidence, **not proof of a held kernel lock**.
Multiple matching ancestor registrations are not used to infer a sender.

The bridge inherits the authenticated tool environment and invokes
`<home>/bin/agentapi send-message`. It never extracts process environments or
copies tokens. Do not run it from an unrelated SSH shell, invent credentials,
or bypass a tool permission denial. A plain SSH process cannot create this
registration on behalf of a TUI. Start it as a long-running command; ready JSON
means the local endpoint is listening, not that the model has consumed anything.

Defaults: lifetime 3,600 seconds (maximum 86,400), at most 1,000 unique requests
(maximum 10,000). `--ttl` and `--max-requests` lower or raise these explicit bounds.
No daemon, global sidecar configuration or automatic restart is installed.

## Discover and send

```sh
session-peer list --agent antigravity --host ubuntu@worker --json
session-peer send --host ubuntu@worker --to antigravity:FULL-CONVERSATION-UUID \
  --antigravity-home /home/ubuntu/.gemini/antigravity-cli \
  --antigravity-generation GENERATION-FROM-LIST \
  --message 'Please review the proposed change' --json
```

Omit `--host` for local delivery. The ordinary SSH transport streams the standalone
source to the destination; no remote package installation is required for send.
The receiving bridge must already be running. Registered sessions also appear in
unfiltered `list`, with `agent: antigravity`, `antigravityHome`, `ownerPid`,
`ownerStart`, `generation`, and `status: registered`. This status does not mean idle.
Discovery scope is `registered_bridges`: historical or unregistered TUI sessions
are not enumerated, even with `--all`. `not_installed` with reason
`no_live_registration` means no live bridge, not proof that agy is uninstalled.

`--antigravity-home` filters known registrations on the destination. Two live
homes for the same UUID fail with `ambiguous_home` unless filtered. Generation
pinning prevents delivery through a replaced registration. `--dry-run` validates
the registration without invoking agentapi. Bodies are limited to 32 KiB UTF-8.
Native sender identity is the receiving TUI's agentapi identity; a `From:` header
is descriptive, not cryptographic authentication of a remote agent.

## Result contract

- `status: submitted`, `ok: true`, `submitted: true` means agentapi exited zero.
- `consumptionConfirmed: false` remains false; no automated ACK/wait facility is
  offered. `--wake` is unsupported. Verify a reply separately when needed.
- Timeout, launch failure, nonzero native exit, or a lost bridge response returns
  `status: unknown`, `ok: false`, `retryAllowed: false`; do not automatically resend.
- Request validation errors are refused before native invocation. Inspect
  `reason` and `error`. Remote transport failure before a structured response can
  also leave the outcome unknown.
- `requestId` and `generation` identify this attempt. Optional `--request-id UUID`
  requires `--antigravity-generation UUID`. Same ID/body within the **same bridge
  generation** returns the cached result with `duplicateSuppressed: true`.
  Changed content with that ID is rejected. There is no durable outbox, replay
  across restarts, or exactly-once guarantee. Do not change IDs to retry unknowns.

The bridge has a same-UID check and private `/tmp/session-peer-agy-UID` directory
(0700), registration and socket (0600), bounded framed JSON reads, and a
15-second native invocation timeout. Native stdout/stderr are discarded; secrets
are not included in errors. Message bodies passed to agentapi are native process
arguments and can be visible to sufficiently privileged process inspection.
Other programs running as the same OS user are within the same trust boundary.

## Stop and re-register

```sh
session-peer antigravity-bridge stop --thread FULL-CONVERSATION-UUID
```

Run on the receiving machine/account with the same home option if customized.
Stop, TTL, owner death, SIGINT/SIGTERM/SIGHUP remove the socket and registration.
An active native request can delay cleanup by its 15-second deadline. SIGKILL or
machine failure cannot run cleanup; next serve holds an exclusive lock before
removing stale files and uses a new generation. Small lock files intentionally
remain to prevent split-lock races. Do not unlink a live lock file.

After TUI restart, explicitly register again from that TUI. Discovery checks the
owner again, so a stale path or reused PID alone is insufficient. Permission or
inspection failures cannot make a session sendable. `doctor` reports Antigravity
as `disabled` when no live bridge exists; this optional feature does not degrade
an otherwise healthy Claude/Codex setup.

MCP needs explicit destination `agents: ["antigravity"]` and `send` permission;
source registration grants no send permission. MCP currently cannot pin a custom
Antigravity home/generation; use CLI for that control. Multiple homes remain
ambiguous and fail closed. A Reply-To URI carries agent/UUID, not a home pin.

## Validation

`python3 -m unittest discover -s tests/adapters -t . -v` covers fragmented/invalid/oversized
frames, exact-target/generation checks, PID reuse, permissions, request conflicts,
timeouts, dry-run, SSH structured outcomes, sender identity and MCP allowlists.
A real Unix socket + child-process fixture tests SIGTERM cleanup and stale restart
without model credentials. See [development validation](validation/85-antigravity.md)
for the live-test boundaries and remaining work.
