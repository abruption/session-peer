# Codex steering / instant_interrupt — 2026-10-01

## Verdict

**Experimental native protocol feasibility: PASS. General-use CLI support is
not implemented or accepted.** Issue #247 remains open.

Queue-only default delivery must remain unchanged. An explicit native
`turn/steer` path is technically viable and the default-off feature changes
how promptly an active turn handles that input. No existing session was steered
or interrupted, and no installed package, permissions, global feature config,
hosted service or release was changed.

## Scope and source-grounded findings

- Base: session-peer 90489fccc87fe2588a2546aaaf7f285429d2bcfd.
- Codex CLI/server 0.159.2; source ff6aec96948b70d94983af2641a6b67c94faeff5.
- macOS arm64; Python **3.13.7**, websockets **17.1**.
- Native feature list reports `instant_interrupt` under development, default off.
  A command-local `--enable` override is not a persistent config change.
- Native queue service calls `start_turn_if_idle`; it does not steer busy turns.
- `turn/steer` requires the exact active `expectedTurnId`; no separate user turn
  is created. It is not `turn/interrupt`, which cancels a turn.
- The prototype connects to an operator-selected existing private Unix socket,
  checks advertised native version, exact home, loaded target, active status,
  direct-input capability and a thread-specific feature snapshot. The native
  expected-turn guard handles the final submission, not the dry-run.
- Known RPC refusal vs post-attempt uncertainty are separate; neither is retried
  or silently converted into queue/start/resume/interrupt. Approval requests
  are not answered. Message input has a 64 KiB UTF-8 cap.

## Actual native test, synthetic provider

This used **actual Codex processes**, native WebSocket-over-Unix JSON-RPC,
thread/turn lifecycle and SSE parsing. A local synthetic Responses API emits
fixed text and holds the first streaming response at a gate. It does not invoke
an OpenAI model and its final text is **not an agent-generated ACK**.

Each case had a newly generated private Codex home/cwd and loopback provider,
with no real keys/login files copied or supplied. Child environment was
allowlisted; existing credential-related environment variables were not inherited.
Thread permissions were read-only/on-request. The owner configured the feature
before starting the test thread; the adapter never enabled it.

Inputs were submitted after observing the first native assistant text delta.
Only input-marker booleans were retained from provider requests; original
request bodies, histories, home paths, IDs and credentials are not in this report.

### Pre-registered ordering expectations

For ON steering, the replacement request must arrive before first-stream gate
release within 5 seconds. The other three cases must not issue that request
during a 0.75-second observation window; then the original gate is released.
Queue must use a new turn; steer must keep the initial turn. Each case has a
45-second hard deadline. First scenario assertion failure stops the batch.

An initial four-case native batch passed. Before the confirmation, three
repetitions and additional wrong-home/missing-target controls were specified;
the ordering thresholds/expectations did not change. Final confirmation:

| Mode | Feature | Second request before release | Same turn | n / PASS | Second request after input, ms min–max |
| --- | --- | --- | --- | --- | --- |
| queue | OFF | No | No | 3 / 3 | 809.70–815.18 |
| queue | ON | No | No | 3 / 3 | 792.40–808.92 |
| steer | OFF | No | Yes | 3 / 3 | 780.21–785.17 |
| steer | ON | Yes | Yes | 3 / 3 | 5.20–5.96 |

**12/12 final native cases passed.** Each case made exactly two synthetic model
requests, with the new input present only in the second. Rejected control input
never appeared. Wrong expected turn (-32600), mismatched home, missing target,
and completed/idle-target steering were refused. Disabled-feature refusal for
`--require-instant` was exercised in OFF cases. No input was auto-retried.

The approximately 0.8-second OFF/queue timings include the deliberately imposed
0.75-second gate. They are not typical Codex latency measurements. The ON
5.20–5.96 ms result is a localhost ordering observation, not a real-provider SLA
or guarantee that running tools stop.

## Setup failures, not product findings

Early fixture initialization failed before any scenario input because the
native advertised version prefix depends on the client originator. The first
attempt's teardown also hit macOS EPERM for a zombie-only process group,
skipping `wait()` and producing a subprocess ResourceWarning. Read-only PID
checks subsequently showed that process had exited. These were harness defects,
not product preemption failures.

The accepted known version identifiers were corrected, and teardown now only
tolerates EPERM after verifying every group member is a zombie, then reaps its
leader. Provider cleanup executes independently in `finally`. Final 12-case
execution under `-X dev -W error::ResourceWarning` emitted no warnings/errors.
Expectations were not changed to turn a scenario failure into a pass.

## Other checks and cleanup

- 24 scoped unit tests pass: opt-in, dry-run truth, disabled/unknown feature,
  identity/capability/approval guards, input limits, wrong turn, uncertain
  responses, socket access and pagination bounds.
- Generator `--check` and diff whitespace check pass; runtime diff is zero.
- Artifact-content tests were invoked but **all 3 skipped** because artifacts
  were not supplied. The local environment lacks `build`; no dependencies were
  installed just for this experiment. `pyproject.toml` statically excludes the
  experiment from wheel/sdist; actual artifact verification is left to CI.
- Each final native case reaped its owned process group and verified no live
  group members; temporary fixture homes were removed. Known test-created
  native socket/lock paths were cleaned by exact path, never their shared parent.
- Final checks found no test home directories or Codex cwd/command matching
  the fixture prefix. The unused worktree shell was closed. Other worktrees,
  existing daemons, sessions and account files were preserved.

## Remaining gates before a supported delivery mode

1. Real-provider ON/OFF behavior, real code-mode cell/command yielding and
   remaining external-work semantics; these were reviewed in source, not executed.
2. Safe owner endpoint registration/generation and authorization for existing
   app-hosted sessions; a thread-specific config snapshot is not a guarantee
   of a step's effective preemption settings after a mid-turn config change.
3. Explicit steering capability/policy, sender/untrusted-message framing and
   return-route/ACK behavior. The prototype only forwards operator-authorized
   text and does not provide the canonical envelope or generic completion wait.
4. Genuine turn-replacement interleavings, disconnect/timeout after acceptance,
   SSH, Linux/Windows, MCP/paired exposure and multi-client approval behavior.
5. Stable CLI spelling/schema, regression and independent review. The prototype
   remains excluded from distributions; this is not release/merge approval.

Unlike `turn/start`, which can implicitly steer on an idle-check race, native
`turn/steer` provides an explicit expected-turn guard. It does **not** solve
the `/btw` UI-open vs server-loaded lifetime issue in #245 / Draft #246.

References: [official changelog](https://learn.chatgpt.com/docs/changelog),
[App Server](https://learn.chatgpt.com/docs/app-server).
