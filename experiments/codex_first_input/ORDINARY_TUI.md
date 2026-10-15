# Already-open ordinary blank TUI investigation

Date: 2026-10-13. Platform: macOS arm64. Installed Codex: 0.162.1.
Runtime reference: session-peer v1.1.1, b48144bdf2ad1569031562136f5a60e33780020e.

## Ordinary in-process TUI: negative result

An operator-owned `codex --no-alt-screen` was launched without a prompt, remote
endpoint, daemon override, or approval/sandbox override in an already approved
test folder. It reached its idle composer. No user message was entered.

The account's effective `daemon_auto_start` feature was false. Before and after
launch, `codex app-server daemon version` could not connect because the control
socket did not exist. The owned TUI held an exact UUID-named writer lock, but a
read-only lookup of that UUID in `state_5.sqlite` found zero matching thread rows.
The owned process's Unix sockets were unnamed socket pairs, not a discoverable
named external App Server endpoint.

Exactly one external official `codex queue --thread <owned UUID> --message
<fresh harmless ACK request>` was attempted. It returned exit 1 and RPC code
-32603: `failed to read thread: invalid thread-store request: no rollout found
for thread id ...`. The native TUI remained blank; no ACK was observed. There
was no resend, thread resume/start, or database mutation by the harness. The
TUI exited via `/quit` with exit zero and its owned PID was confirmed absent.

This refutes a general claim that an arbitrary already-open blank TUI can be
reached through the external App Server protocol in this tested configuration.
The UUID exists in memory and the writer lock, so failure is not proof that an
internal conversation identity does not exist. Nor is it a platform-wide
impossibility proof.

The earlier dedicated server/remote TUI experiment in RESULTS.md is a different
topology. Its positive result must not be relabeled as this ordinary-TUI test.

## Scope and safety

Only the owned native TUI was inspected and targeted. No credentials, environment
values, unrelated transcript bodies, global configuration, permissions, product
code, GitHub state, releases, or operating services were modified. Normal native
startup/queue shutdown may create native account metadata. Existing user sessions
were not terminated. Private UUID/PID evidence is not included in this report.

Official protocol reference: https://learn.chatgpt.com/docs/app-server

## Already-open ordinary TUI on a shared server: positive result

For a separate control, an exclusively owned foreground
`codex app-server --listen unix://<default-control-socket>` was started before
another ordinary `codex --no-alt-screen`. This second TUI had no `--remote`
argument, no initial prompt, and no feature/permission overrides. It attached to
the existing server and reached its idle composer. This does **not** retrofit the
first in-process TUI or move a running conversation between servers.

An independent external WebSocket client connected after the second TUI was
already open. The server had exactly one loaded thread; `thread/read` with
`includeTurns:false` (no turn-body read)
showed the expected cwd, idle status, and ability to accept direct input. A
read-only lookup immediately before submission still found zero stored rows for
the exact loaded UUID. The queue operation used that same ID, without
`thread/start`, `thread/resume`, or `turn/start`.
Only selected metadata was reported. This is not a claim that the general
`thread/read` API never returns preview text; this target was the owned blank
thread, and no unrelated conversation or transcript was read.

One `thread/queue/add` was accepted with `queuedSubmission`. The existing native
TUI displayed the external request and then the exact independently generated
reply `ACK CODEX-SHARED-EMPTY-306-8C2F`, reporting four seconds of work. This proves
first-input receipt in that already-open, shared-server-connected TUI. Queue
acceptance itself was not labeled consumption or ACK; receipt was a separate
direct PTY observation. It does not implement this transport in session-peer.

An initial read-only stdio-proxy probe timed out before initialization, with no
queue attempt. It was discarded; the successful inspection/submission used the
existing Unix-WebSocket harness with websockets 17.0 in a temporary isolated
environment. At that live-test stage the harness only gained an optional bounded
ASCII test marker; subsequent review-driven guards are described below.
No uncertain effect was retried.

Both test TUIs and the foreground server exited zero; their PIDs were checked
absent and the created logical/physical sockets disappeared. Server shutdown
logged a best-effort MCP session-delete HTTP failure; this was not silently
reported as an error-free shutdown. No managed daemon installation or updater
was started, and the pre-existing startup lock was preserved.

## Implementation evidence and conclusion

Read-only independent review of the exact upstream rust-v0.162.1 source supports
the observed distinction:

- [In-process client](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server-client/src/lib.rs#L317): async mpsc worker, no external
  process boundary; [in-process server](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server/src/in_process.rs#L515): InProcess transport and no
  remote-control handle.
- [TUI startup](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/tui/src/startup_orchestration.rs#L311): chooses a shared socket at startup when one
  exists, otherwise uses the applicable embedded/managed startup path.
- [Queue command](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/tui/src/session_queue_commands.rs#L95) accepts a UUID without saved name lookup,
  but submits through its selected server. [Queue processor](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server/src/request_processors/thread_queue_processor.rs#L253)
  requires that server's loaded thread or persisted history.

Thus, **an already shared-server-connected blank TUI can receive; an arbitrary
embedded blank TUI cannot be claimed reachable externally after startup**. A
safe product feature would require explicit shared-endpoint/owner/target binding
and must refuse unavailable embedded targets, not create a substitute session.
No Linux/Windows, remote machine, arbitrary Orca TUI, restart recovery, or general
production support is established by these macOS tests.

The harness's exclusive-server assumption, UUID/cwd/status checks and assertions
are experiment preconditions, not production PID/start-time/generation binding.
Its generic JSON decoding is not a substitute for session-peer's strict wire
validation. Do not run it with Python optimization or against a shared server
containing unrelated user work. The WebSocket dependency is test-only and is not
added to the Python core runtime. `experiments/` remains excluded from release
artifacts by the existing packaging rules.

## Review-driven harness guards

The supplied Codex home is now canonicalized before SQLite URI construction and
must match the absolute `codexHome` returned by `initialize` before any thread
lookup or database inspection. Missing or mismatched server-home evidence
refuses the probe without queuing. A queue RPC rejection returns exit 1; malformed
error objects, non-integer codes or missing/non-string messages yield an unknown outcome once queue submission
has been attempted, without reflecting native error text or retrying. Timeout,
invalid JSON, invalid results, and transport failures after that boundary also
report `accepted:null`, `outcome:unknown`, and `retryAllowed:false`; after a queue
attempt, a validated RPC rejection alone supplies `accepted:false`. Runtime
preflight failures report `accepted:false`, `outcome:not_attempted`; argparse
usage errors retain exit 2 and usage output. An interrupted probe returns exit 130 while preserving the
same effect boundary. Queue mode requires explicit `ephemeral:false` before
database inspection or submission: a previously used ephemeral conversation may
still have no database row. True, null and missing values cannot establish this
precondition. Inspection mode may report boolean/null metadata without queuing;
that does not prove the conversation is unused. Arbitrary result keys and native
error details are not reflected. The version guard remains
exactly 0.162.1, and Python optimization is refused up front.

Ten synthetic WebSocket/temporary-database tests cover these boundaries,
including relative home paths, complete error validation on both RPC paths,
ephemeral/missing/null refusal and exactly one queue attempt on rejection.
These are harness regression tests, not new native delivery, receipt, platform,
or production-support evidence. None of these review-driven guards were exercised
by another live native run. SQLite handles are explicitly closed. A failure during
connection cleanup may return a nonzero exit while preserving an already observed
acceptance or rejection; it never authorizes retry.
