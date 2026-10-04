# Opt-in Codex steering experiment (#247)

This is an **unreleased local experiment**, not a new installed CLI mode.
Existing package rules exclude `experiments/`. Canonical queue/send/wake,
generated runtime, Relay/SSH, and the Side Session experiment (#245/#246)
are unchanged.

## Technical review

Codex 0.159.0 introduced default-off `instant_interrupt`, still under development
in 0.159.2. It makes current-turn user input preempt sampling and yield
foreground code-mode observations. It does not terminate all external work,
undo earlier side effects, or convert durable queue submissions into steering.

Native queued-item dispatch uses `start_turn_if_idle`. The prototype instead
connects to the **existing owner** via private Unix-domain WebSocket and calls
`turn/steer` with exact `threadId` and nonempty `expectedTurnId`. It never uses
`turn/start`, `turn/interrupt`, resume, fallback, auto-approval or resend.

Operator opt-in and exact server/home/target are required. The owning thread's
feature snapshot is read using `experimentalFeature/list(threadId=...)`;
`--require-instant` refuses disabled/unknown snapshots. This read is not a
promise that every pending step reflects a recently changed feature or that
latency meets a deadline. The operator must configure the destination; the
sender never enables the feature. Target permission overrides are not accepted.

Dry-run verifies metadata but does **not** claim native validation of the
expected turn ID; that atomic guard is enforced during actual `turn/steer`.
Accepted is not consumed/ACK/completed. RPC uncertainty is never auto-retried.

## Pre-registered native experiment

Actual Codex 0.159.2 executes against a **loopback synthetic Responses API**.
No real account credentials or model calls are used. No existing session or
home is loaded. The first response emits an initial text delta then waits at
a controlled gate. Input is submitted only after that delta is observed.

| Mode | `instant_interrupt` | Expected second model request before first gate release |
| --- | --- | --- |
| queue | OFF | No |
| queue | ON | No |
| steer | OFF | No |
| steer | ON | Yes |

ON steering must produce the second request within 5 seconds while the first
gate stays closed; other cases must not produce it during a 0.75-second window.
After gate release, all four cases must include the new input in the next
request and finish. Steering must retain the same turn; queue must start a new
turn. These are deterministic synthetic protocol observations, not model ACKs
or a real-provider latency SLA. Each case has a 45-second deadline, first
scenario assertion failure stops the batch. Failed gates are findings, not
redefined expectations. Fixture/setup defects may be corrected separately.

After the first four-case batch passed, a three-repeat confirmation batch was
specified with unchanged ordering windows and new wrong-home/missing-target
negative controls, before executing that confirmation. Native scenario results
and setup failures are recorded separately in `RESULTS.md`.

The version-gated native harness covers SSE response preemption. Actual
code-mode cell yielding, real model/SSH/Windows/remote listeners, simultaneous
senders, and hosted permission/allowlist integration remain follow-up gates.

## Usage (dummy values)

Requires Python 3.11+ and websockets 17.1 for this experiment only.

```sh
python3 experiments/codex_steering/steer.py --experimental-steering \
  --socket /private-test/app.sock --expected-home /private-test/home \
  --to codex:00000000-0000-4000-8000-000000000001 \
  --expected-turn-id turn-example --require-instant --dry-run \
  --message 'Change the review focus'
python3 -m unittest discover -s experiments/codex_steering -v
```

Native fixture execution is a separate opt-in command documented with its
results. It never silently changes a feature/config in an existing daemon.

```sh
python3 experiments/codex_steering/native_fixture.py --run-native-fixture \
  --temp-root /approved-private-scratch --repetitions 3
```

References (reviewed 2026-10-01):
[changelog](https://learn.chatgpt.com/docs/changelog),
[App Server](https://learn.chatgpt.com/docs/app-server).
Pinned source: openai/codex ff6aec96948b70d94983af2641a6b67c94faeff5
(`rust-v0.159.2`), particularly `features/src/lib.rs`,
`core/src/session/input_queue.rs`, `core/src/session/turn.rs`,
`ext/queue/src/service.rs`, and `app-server/.../turn_processor.rs`.
