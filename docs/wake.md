# Explicit Codex wake

## Chained wake limits

Before queueing, CLI and MCP read `SESSION_PEER_WAKE_DEPTH` and `SESSION_PEER_WAKE_ORIGIN`. Each wake adds one hop and retains the origin UUID. The default limit is 3 hops; exceeding it returns `wake_depth_exceeded` with nothing submitted. Operators can explicitly lower or raise `--wake-max-depth` or `SESSION_PEER_WAKE_MAX_DEPTH` within 0–16; 0 disables wakes. Invalid or incomplete context returns `invalid_wake_context` before submission. Ordinary queue-only sends remain unchanged.

The owned app-server receives the incremented context. SSH carries typed context without requiring environment forwarding; the destination can lower, not raise, the carried limit. One origin is retained across fanout, but destinations have independent budgets. MCP reads its startup environment, not the calling thread's identity. Wake adds a diagnostic queue-message prefix and, after submission or successful dry-run, a `wakeProvenance` result containing `depth`, `origin`, and `maxDepth`. The prefix counts toward the 32 KiB message limit. Neither prefix nor body grants permission. No queue/history/transcript content is read to recover depth.

Inactive activation also defaults to 3 attempts per canonical home/thread in 60 seconds. Operator-owned `SESSION_PEER_WAKE_TARGET_RATE` accepts 0–16; 0 disables inactive activation. Reservations persist under the existing wake lock. `wake_rate_exceeded` refuses before queueing; unreadable, oversized or malformed state returns `wake_rate_state_invalid`. Failed/interrupted attempts retain slots; clock rollback conservatively keeps reservations. Dry-run and known active writers consume no activation slot. Existing `wake_in_progress` and `already_active` behavior remains. Different targets/hosts have separate budgets; operators or same-user processes can reset cooperative state. This is not a global cost quota or caller authentication.

In the pinned Codex 0.154.0 source, shell `inherit="all"` retains these variables unless exclusion or `include_only` filters them; `inherit="core"` and `inherit="none"` drop them unless explicitly set. Default secret-name exclusions do not match them. Stdio MCP's default whitelist omits them; a new MCP process requires explicit `env_vars` forwarding. Existing/shared MCP processes do not receive a later caller's environment. Static `env` overrides may reset or conflict with context. Filtered/missing context starts a new local origin, so the hop limit cannot guarantee a global chain bound. The local activation rate is a separate backstop. No approval, profile or native environment policy is changed automatically.

Isolated subprocess fixtures mirror these upstream rules and verify CLI/MCP/SSH context and the app-server stand-in environment. They do not run a credentialed native shell, MCP client or model turn and do not establish wake support beyond 0.154.0. Sources: [pinned shell policy](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/protocol/src/shell_environment.rs), [pinned MCP environment](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/rmcp-client/src/utils.rs), [current configuration reference](https://developers.openai.com/codex/config-reference/).

`session-peer send --to codex:<uuid> --wake --wake-timeout 30 "message"`

Plain send remains queue-only. Wake can incur model usage and modify session history and project files under the target's existing configuration. It requires macOS/Linux and **Codex CLI 0.154.0**, the version whose lifecycle and native writer exclusion have been tested. Other versions fail closed until independently validated. This version boundary applies only to wake.

The operator may select `--codex-home` and an SSH `--host` as usual. The original working directory comes from that home's saved thread record. Missing, archived, uninitialized, unknown-owner and unavailable-directory targets are rejected before enqueue. No state/queue DB is modified directly. A session-peer guard serializes wake requests for the same canonical home and UUID; native Codex's writer lock also protects against unrelated simultaneous resumes.

## Native lifecycle

`codex exec resume UUID` requires a prompt in 0.154.0 and cannot activate a queue without adding input. Wake instead starts native `codex app-server`, initializes its stdio protocol, then calls `thread/resume` with the exact UUID and original cwd. Resume itself consumes pending queue messages; session-peer never calls `turn/start`, copies the message into a prompt, forks the thread, unlocks a writer or changes trust/sandbox/approval configuration. Interactive approval requests fail explicitly. The app-server API is experimental; supporting another CLI version requires repeat validation.

An already-active writer receives one queue submission and no second process is started. For an inactive target, wake waits for one native turn completion within the deadline (default 30 seconds, range 1–60). It then terminates its owned process group. This is **not** a persistent background worker or a promise to drain the whole queue. Long-running turns may be interrupted on timeout; partial work can remain. Existing active processes are never terminated.

The same lifecycle and timeout run on an SSH destination. Connection loss does not prove non-delivery. The remote wake has its own bounded lifetime even if the caller disconnects. Cancellation attempts graceful termination of owned processes, then forced cleanup. No automatic resend occurs.

## Results

The existing submission fields remain: `submitted`, `queueId` (when native queue returns one), `codexHome`, `status`, and `consumptionConfirmed`. A separate `wake` object contains `status`, `reason` and, once resolved, `cwd`.

- `validated`: dry-run only; nothing queued or started.
- `already_active`: message queued; existing writer left running.
- `completed`: native resumed turn completed.
- `refused`: safety/preflight requirement not met.
- `failed`: native transport, resume, approval or turn failure.
- `timed_out`: owned activation exceeded the deadline and cleanup was attempted.
- `unknown`: interrupted or ambiguous activation outcome.

Submission can succeed while wake fails. In that case CLI exit is nonzero and JSON retains the queue ID, `submitted: true` and the failure. **Do not resend automatically.** `completed` is not evidence that a particular queue item was received; `consumptionConfirmed` remains false. A previously queued item or a different concurrent submission can be the completed turn.

For MCP, add both `send` and `wake` to the destination capabilities, then call `send_message(..., wake=true, wake_timeout=30)`. Send permission alone does not grant wake. Configure the client's MCP timeout above the entire queue/SSH/wake budget (for example 150 seconds); a client timeout may otherwise obscure a submitted result.

## Validation evidence

On mac-mini-m4 with CLI 0.154.0, an isolated test thread was initialized, stopped, queued and resumed through app-server without a new prompt. Native turn-start/turn-complete events were observed. A second app-server resume while the first held the same UUID failed with `already has an active writer`. The implemented CLI then returned `submitted: true`, a queue ID, and `wake.status: completed` for another controlled message. No project-trust or approval bypass flags were used.

Automated tests use fixture SQLite databases, real advisory locks and native-process stand-ins. They cover inactive/active/archived/missing targets, default queue-only behavior, deadline and approval failures, process cleanup, concurrent guard refusal, interrupted submissions, remote partial-result preservation and separate MCP permission. Live model/SSH checks are manual; public CI does not receive model credentials.

A real Codex 0.154.0 MCP client subsequently completed local list/send/wake and mac-mini → macbook list/send/wake using the remote Orca custom home. The remote default home had revoked authentication: its queued submission and failed native turn were preserved as a partial failure, without changing authentication or resending. Local and KR SSH Claude-protocol test inboxes also received one message each from the real Codex MCP client. These were dedicated protocol fixtures, not production Claude conversations.

Initial non-interactive Codex tests refused the write tool under their existing approval policy, as expected. Successful tests explicitly set the test client's `mcp_servers.session_peer.tools.send_message.approval_mode="approve"` and granted only the test destinations in server policy. The shipped plugin does not set this approval override. Plugin marketplace registration and installation were validated in a disposable CODEX_HOME; production plugin configuration was untouched. Live wake was tested on macOS; Linux process/lock behavior is covered by CI fixtures, not a credentialed model run.

Cleanup on macOS/Linux escalates TERM to KILL for the owned process group before reaping its leader, including TERM-resistant descendants. The group ID is not reused after cleanup. Escaped sessions and remote processes are outside this group; cleanup never retracts an already submitted request.
