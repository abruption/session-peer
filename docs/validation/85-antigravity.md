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

## 2026-10-13: CLI 1.3.3 acceptance campaign (#304)

This update is separate from the historical 2026-09-17 branch evidence above.
Baseline: published session-peer 1.1.1, commit b48144bdf2ad1569031562136f5a60e33780020e.
Both native CLIs were 1.3.3; the dedicated TUIs used Gemini 3.8 Flash (Low).
The adapter remains experimental. This campaign does not publish a release or
establish general supported-version, Windows, sidecar-autostart or availability guarantees.

### Observed evidence

- macOS 27.0.1 arm64 / Python 3.15.0 and Ubuntu 24.04.5 arm64 / Python 3.12.3:
  23 Antigravity adapter tests passed on each. Owner/native mocks and real Unix
  socket/child-process fixtures are not native-model integration tests.
- Installed CLI parser probe: seven cases passed on each platform, including
  leading dashes, a delimiter, multiline Korean text and recipient/title preservation.
  Empty HOME, a minimal environment and a bounded loopback stub ensured no
  credentials or successful native delivery were used by this probe.
- Dedicated owner TUIs registered the bounded bridge through their normal terminal
  tool. macOS local, Linux local and macOS-to-Linux source-streamed SSH submissions
  returned native exit zero; distinct exact reply markers were observed in the TUIs.
- Additional sends were made while each TUI displayed a working state on a bounded
  synthetic response. Their distinct replies were observed after that response.
  This is a dated UI observation, not a scheduling/latency or all-busy-states guarantee.
- macOS dry-run returned without native submission. Repeating the original ID/body
  returned a cached duplicate; changed content with that ID was refused. An unrelated
  generation on the SSH route was refused before native invocation.
- Explicit bridge stop on both machines removed the registrations from discovery.
  Re-registering from both still-live TUIs produced new generations; requests pinned
  to the original generations were refused on local and SSH routes.
  The fixture additionally exercises SIGTERM, SIGINT and SIGHUP cleanup, changed
  generations on restart, and retention of the same lock inode.
- JSON consumption confirmation stayed false throughout. An observed TUI reply is
  separate evidence for that test message, not a new automatic ACK/wait facility.

### Failures and remaining promotion gates

An initial shell-background launch on macOS exited with the required-ancestor
registration refusal. A foreground long-running terminal-tool invocation registered
successfully. Do not detach a shell and assume the bridge preserves TUI ancestry.
The first Linux fixture transfer omitted the MCP module and failed one import;
after transferring that tracked source file, all 23 tests passed. This was test
setup failure, not evidence of a product fix.

The added tests cover cached launch failure without retry and the exact 32 KiB
UTF-8 boundary. They do not establish durable deduplication or prove no effect
from an unknown outcome; automatic resubmission remains forbidden.
Long-duration soak, native TUI restart/owner-death and forced-crash acceptance,
real transport-disconnect outcomes and bidirectional CLI return routing remain
unexecuted promotion gates. Full Claude/Codex/Antigravity interoperability and
paired Relay delivery were not rerun in this campaign.
The official sidecar documentation describes managed startup, but compatibility
with this ancestor-bound bridge must be investigated separately; no global
sidecar configuration, authentication copying or production deployment was performed.
