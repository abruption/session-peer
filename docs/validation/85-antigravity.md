# #85 Antigravity adapter development validation

2026-09-17; local branch `feat/85-antigravity-adapter`, isolated worktree
`/tmp/session-peer-85`, based on #47 `993d04d`. No relay dependency, release,
remote push or PR. Version remains 0.8.0 as development metadata; this feature
is not in the published 0.8.0 distribution. Issue: https://github.com/abruption/session-peer/issues/85

## Implemented

Opt-in registered-session adapter in the standalone source, local/SSH list and
send, doctor capabilities, exact UUID/home/process identity and generation checks,
private same-UID framed socket, bounded requests/lifetime/native subprocess,
in-generation request deduplication/conflict handling, signal cleanup and stale
restart. Sender detection requires a unique registered ancestor. MCP listing
preserves explicit agent allowlists when a third built-in adapter is added.

## Evidence

- macOS Python 3.14: 332 tests pass with optional MCP SDK installed (including
  real MCP stdio tests). Without SDK: 332 tests, two optional skips.
- KR Ubuntu Python 3.12: 17 adapter tests pass; real Unix socket, fake native
  executable, SIGTERM cleanup and stale restart fixture, no model calls.
- Wheel/sdist built and independently installed in isolated virtual environments;
  CLI bridge help and registered-only listing smoke tested. No global install.
- Real KR agy 1.2.4 TUI: user launched the bounded bridge through its tool runner.
  Source-streamed SSH `list` found the correct ubuntu home despite the workspace
  being under another user's directory. Two distinct integration markers each
  produced one SYSTEM receive record and one exact MODEL ACK. Duplicate requests
  were suppressed; changed body with the same ID and old generation were rejected.
  Dry-run invoked no native delivery. Structured `consumptionConfirmed` stayed
  false, while independent transcript observation confirmed these test ACKs.
- Explicit bridge stop removed socket and registration; subsequent SSH list
  returned no registered sessions. User TUI remained alive in the original cwd.
  Remote test source/tests were removed. One empty lock file intentionally remains
  in the private per-UID runtime directory to avoid split-lock races; no active
  bridge/socket/registration remains.

Detailed sanitized evidence is local at `/tmp/session-peer-85-evidence/`:
`list.json`, `send.json`, `observation.json`, `cleanup.json`, `linux-tests.log`,
`full-tests.log`. The first live test's transcript markers are retained alongside
second-test markers in `cleanup.json`; `send.json` contains the second run.
No raw environment, token, credentials or unrelated transcript was collected.

## Limits / next steps

This is an experimental explicit-registration workflow. No CLI sidecar autostart,
headless writer substitution, unattended registration, durable outbox, automatic
ACK/wait/wake, cross-UID access or exactly-once claim. Native sender is the TUI's
agentapi identity; a descriptive From header is not cryptographic sender proof.
The new implementation's live native test is Linux; macOS has protocol/lifecycle
fixtures plus the earlier native PoC, not a live native test of this branch.
Windows bridge is unsupported; Windows CI and Python 3.9 execution were not run
locally. SIGKILL cannot clean up synchronously; restart removes stale entries only
after taking the exclusive lock. PID polling cannot eliminate every process-exit
race between verification and agentapi invocation.

The earlier KR PoC demonstrated busy delivery, SSH disconnect, bridge and TUI
restart with seven messages. Those results informed this implementation but are
not counted as live executions of this branch. Product-level reconnect durability,
long-running operation and pairing/relay integration remain separate v0.9/RC work.
