# Antigravity startup and receiver-bridge evidence (#307)

Status: **historical investigation record**. Issue:
https://github.com/abruption/session-peer/issues/307

This directory curates observations made on **2026-10-13** in an isolated,
owned macOS session. Nothing here is a new test, and nothing here is a live
test of the v1.1.2 runtime on `main`. It does not promote any Antigravity
behavior to stable CLI support, does not claim first-input (pre-input)
delivery support, and does not change runtime code, hooks, settings or
permission policy. `experiments/` is excluded from the wheel and sdist.

The existing owner bridge (started from the receiving TUI's own tool runner,
#85) and a hypothetical new startup/autostart feature are different things.
Evidence for the first is not evidence for the second.

Mac/Linux validation of CLI 1.3.3 after explicit registration is tracked
separately in #304 / PR #305 (`docs/validation/85-antigravity.md`) and is not
repeated here.

## Sources and evidence classes

| Source | What it is |
| --- | --- |
| Issue #307 comment, 2026-10-13 | Operator summary of the first (unpinned) run |
| Local experiment report, 2026-10-13 | Uncommitted operator report from the original experiment worktree; this README is a curated, sanitized restatement of it |
| `hook_probe.py`, `native_probe.py`, `execution_probe.py` | Probe scaffolding copied byte-for-byte from that worktree (no personal paths or identifiers embedded) |

The Hooks and Sidecars links below are historical references cited by the
2026-10-13 reports. Neither page was newly checked for current availability by
this archive-only change.

Evidence classes used below:

- **Reported result**: structured fields (exit code, `status`, `submitted`,
  `consumptionConfirmed`, ...) as recorded in the operator report. Raw native
  or send stdout/stderr is **not** in this repository. For the receiver-side
  send, the message/input binding was kept privately as a **reconstruction**
  from the executed command and a private manifest, explicitly not labeled raw
  send stdout. For the first run, only a reduced result was retained.
- **On-screen observation**: text the operator saw in the owned TUI's PTY
  output. This is a test receipt, not a structured receipt;
  `consumptionConfirmed` stayed `false` in every send.
- **Body-free metadata**: hook-event records containing only event name,
  process/parent IDs, validated owner PID/start time, conversation ID and
  timestamps and owner-validation booleans (`execution_probe.py`), plus `lsof` presence-FD checks. No message
  bodies, hook payloads, environment values, credentials or transcripts were
  recorded. The private records themselves are not committed.
  The private bridge manifest additionally stores bridge PID, generation and
  local absolute paths; it must not be committed either.

The private collaborator manifest explicitly identifies an initial probe as
deleted and later reconstructed from the recorded command, with no original
source hash. It separately identifies the joint sender probe as the exact source
used in that joint run. Copying these three files unchanged from the review
worktree establishes snapshot equality, not their identity with every historical
execution. The execution observer was also revised during the receiver-side
control (see below); not every record came from the committed version.

## Versions

| Item | Value |
| --- | --- |
| Host | macOS 27.0.1, arm64 (only platform tested) |
| Python | 3.15.0 |
| session-peer runtime under test | published v1.1.1, `b48144bdf2ad1569031562136f5a60e33780020e`, unchanged |
| Model shown by TUI | Gemini 3.8 Flash (High) |
| First run, TUI display | **1.3.3** at startup and at exit |
| First run, post-test `agy --version` | **1.3.4**, same installed executable path |
| Follow-ups, pinned private copy | 1.3.4, SHA-256 `9da414c0624c27aa2969a86030a070b5341c0657700512eba70b21725ce253f5` |

**Version confound (first run).** The TUI displayed 1.3.3, but the installed
executable reported 1.3.4 after the test. The experiment did not invoke an
update. The reason and replacement time are not established, and the
`agentapi` wrapper executes that path, so the delegate version during the
first-run send is **unknown**. The first-run send is not an exact-version 1.3.3
or 1.3.4 result.

The follow-ups ran the owned TUI and direct `agentapi` probes from a private
copy of the public native executable (basename `agy`); the installed wrapper and
home were not changed. For the receiver-side control, the pinned TUI binary and
the installed binary used by the unchanged `agentapi` wrapper had matching 1.3.4
hashes immediately before and after the send. Even so, each result below is one
observation on one host, not a version-wide guarantee.

## Findings

### (a) Pre-input: no externally observable conversation ID or hook

With a temporary workspace-local `.agents/hooks.json` (SessionStart) in a
trusted, dedicated test folder, the TUI reached its first idle prompt with no
user input and the probe's result file did not exist. In the pinned follow-up
the result was still absent at two idle checkpoints, 05:22:11 UTC and 05:22:34
UTC (23 seconds apart).

This only shows that **no conversation ID or hook execution was externally
observable at those idle checkpoints**. It does not show that the TUI has no
internal conversation ID before input, and it is not a universal timing
guarantee or a long-duration idle test.

### (b) SessionStart was observed after the first input

After one harmless first prompt (requesting a fixed `READY` marker, no tools),
SessionStart ran and supplied a valid conversation ID. The hook started the
unchanged runtime bridge without asking the model to run a tool; its native
ancestor/presence checks passed, it returned `ready: true`, and the
registration was discoverable exactly once. The TUI visibly returned the
`READY` marker.

In this historical run, the hook started the bridge **after the first input**.
The upstream wording
quoted in the 2026-10-13 report, "before first model invocation"
([Hooks](https://antigravity.google/docs/hooks/)) does not mean "before first
user input". A listening bridge is not proof of delivery authority.
The probes did not independently timestamp model invocation start; invocation
ordering here is the upstream contract quoted in that historical report.

### (c) The hook lacks the normal language-server context

Only boolean availability of four context variable names was retained (no
values):

| Variable | In hook (first run and pinned follow-up) | In native tool runner (pinned control) |
| --- | --- | --- |
| `ANTIGRAVITY_CONVERSATION_ID` | present | present |
| `ANTIGRAVITY_TRAJECTORY_ID` | absent | present |
| `ANTIGRAVITY_LS_ADDRESS` | absent | present |
| `ANTIGRAVITY_CSRF_TOKEN` | absent | present |

These are the retained booleans, not raw values. `hook_probe.py` checks whether a
value is nonempty; `native_probe.py` checks whether the name exists. Empty-value
state is not available from the native probe, so the two criteria must not be
treated as identical authority checks.

Reported send outcomes:

- **First run (unpinned)**: one generation-pinned bridge send from the hook-
  started bridge returned exit 1, `status: unknown`, `submitted: false`,
  `consumptionConfirmed: false`, `retryAllowed: false`. No ACK was visible
  during bounded observation. The legacy `submitted: false` on an unknown
  outcome is not proof of no effect. No retry, new conversation or fallback.
  The bridge discards native diagnostics and the reduced result did not keep
  the exit-code/timeout discriminator, so the cause is **unclassified** for
  this run.
- **Pinned 1.3.4, from the hook** (`native_probe.py --phase hook`): exit 1, no
  timeout, fixed `ANTIGRAVITY_LS_ADDRESS` variable-name diagnostic matched (a
  name match, not the exact error sentence).
- **Pinned 1.3.4, read-only ordinary-shell control**: an own-conversation
  metadata query exited 1 with the exact fixed text `ANTIGRAVITY_LS_ADDRESS is
  not set`.
- **Pinned 1.3.4, native tool-runner positive control**
  (`native_probe.py --phase tool`, approved once via the normal permission
  prompt, not always-allow; distinct marker, not a retry): exit 0, no timeout.
  The model visibly referred to the new marker afterward, but **no final exact
  ACK** was obtained before the bounded test was interrupted (the operator
  prompt and the injected message also asked for conflicting output; this is a
  test limitation). This is a direct-native control, not a full session-peer
  bridge round trip.

Together these identify an observed environment/context boundary: the hook did
not provide the working native-send context observed in the tool runner. They do **not**
establish the internal authentication protocol, and they do not authorize
copying or manufacturing the missing context. SessionStart cannot be described
as a working first-input listener on this evidence.

### (d) Positive: receiver-started bridge delivered to the owner

A separate owned receiver B was started with the pinned 1.3.4 binary. From B's
legitimate native tool runner, one approved command (`execution_probe.py
--start-bridge`) started the unchanged v1.1.1 receiver bridge; it returned
ready and B returned to idle. An external shell then made exactly one ordinary,
generation-pinned session-peer send to that bridge.

- Reported result: exit 0, `status: submitted`, `submitted: true`,
  `nativeExitCode: 0`, `consumptionConfirmed: false`.
- On-screen observation: B visibly answered the exact fresh test marker, in its
  owned PTY output and again in its exit redraw (no transcript file was read).
  This is an on-screen ACK, not a structured receipt; the CLI's
  `consumptionConfirmed` contract is unchanged and no automatic return message
  exists.
- Body-free metadata: the post-send PreInvocation/PostInvocation/Stop records
  had B as parent and as the validated native owner, with B's conversation ID;
  a separate `lsof` check confirmed B's presence FD and working directory. This
  places execution in B, not merely a native exit zero.

Observer revision: between B's setup and the send, the observer was refined.
Initial records used successful owner validation without an `ownerVerified`
field; later records include it, and a failed owner validation no longer
suppresses read-only event observations (bridge setup still requires
validation). The committed `execution_probe.py` matches the later observer
SHA-256 `64a393ff372fe8c54cf62d268d6bb89c6b25c90593c37edaf35a3eb6d220631c`;
do not attribute the initial records to this exact source.

This is one macOS receiver-side round trip from the explicit-registration path,
not a startup feature and not a Linux/Windows or long-term stability claim.

### (e) Counterexample: the direct agentapi invocation was parented by the caller

A fresh receiver B2 was left idle with no bridge. A separate cooperating sender
A invoked direct `agentapi send-message` from **A's** tool runner against B2's
exact conversation ID. Sender-side reported result: one native send, exit 0, no
timeout. (An earlier, different marker was declined at the approval prompt
before execution and was not retried.)

- Body-free metadata: B2's workspace hook recorded PreInvocation,
  PostInvocation and Stop for B2's conversation, but all three had **A's process
  as parent**, and native owner validation failed for them. Concurrent `lsof`
  checks showed B2 still held its own presence FD while A held its own and not
  B2's. Process start times and executable paths were cross-checked against
  private manifests. A separate observation of A holding other handles whose
  paths contained B2's ID at a different instant does not establish persistent
  storage overlap.
- On-screen observation: B2 stayed idle for 93.88 seconds. One later operator
  query asked whether a new marker had arrived, without supplying or resending
  it; B2 answered `NONE`, and that query's hook events were parented by B2.

So a matching conversation ID plus native exit zero does not prove execution in
the already-open TUI. No target-owner receipt was observed within the bounded
test; the invocation was parented by the caller's process. The later query
returned `NONE`, which does not rule out unobserved late delivery or history
effects. Native persistence, store-conflict and resume behavior were **not established**; no
database or history was modified directly. Creating a new agentapi execution in
another process, or a new conversation, is not a substitute for reaching the
owner of the target TUI. The [Sidecars](https://antigravity.google/docs/sidecars/)
page cited in the historical report described Antigravity 2.0 availability;
that was not CLI sidecar-autostart evidence.

## Not established / unverified

- Delivery to an idle TUI before its first user input.
- Any legitimate way for SessionStart (or another hook) to obtain agentapi
  authority; the internal authentication protocol.
- Cause of the first-run unknown send (unclassified), and the delegate version
  at that time.
- A complete session-peer bridge round trip on 1.3.4 started from a hook.
- Structured receipt: all ACKs above are on-screen observations;
  `consumptionConfirmed` was always `false`.
- Linux, Windows, later native versions, the v1.1.2 runtime, automatic
  bridge recovery, long idle periods and long-term stability.
- Exact initial-execution source custody for reconstructed probes; no missing
  original hash is inferred from a later snapshot comparison.

## Probe scaffolding

These scripts are reproduction scaffolding, not automated tests, not a
production transport and not a general-purpose runner. Nothing in the test
suite executes them. Running them requires an owned TUI, an explicitly approved
workspace and an operator; do not install them as global hooks.

These historical scripts are not a reviewed future-run recipe. In particular,
native markers are fixed rather than fresh nonces, native output capture has no
byte cap, and bridge readiness/cleanup and output-file handling are not hardened
against every partial-output, symlink or same-user race. Do not rerun them to
infer a fresh receipt without a separately reviewed, bounded harness and new
operator authorization. No rerun was performed for this documentation change.

| Script | Role | Notes |
| --- | --- | --- |
| `hook_probe.py` | SessionStart hook: records context-variable booleans and starts the unchanged bridge (TTL 120 s, 2 requests) | `--output-dir PRIVATE_SCRATCH --runtime ABSOLUTE_SCRIPT`; scratch must be owner-only (mode 0700); result file mode 0600 |
| `native_probe.py` | One direct native `agentapi send-message`, keeping only a fixed diagnostic class and exit code | `--phase hook` or `tool`; 15 s deadline but no byte cap on native output; expects a private `agy` copy in the scratch dir |
| `execution_probe.py` | Body-free hook-event observer and receiver-side bridge setup (`--start-bridge`, TTL 600 s, 2 requests) | Appends to a private mode-0600 JSONL file |

The private results contain owned conversation and process IDs that are needed
only for exact-target testing and cleanup and must never be committed. The
request cap is not permission to retry an unknown result. Production ancestor,
UID, presence and start-time checks are used unchanged. Legitimate context is
inherited by the native child; availability checks retain booleans, not token
values. This is not a claim that subprocess environment inheritance transfers no
authority. Credential values are not intentionally logged, exported or persisted.

## Cleanup recorded in the source report

The source reports cleanup of the owned bridges (`stopped: true` where reported),
TUIs and disposable workspaces/hooks/executable copies, with owned PIDs checked
absent at that time. Selected private metadata, manifests and reconstructed
evidence were retained for review, not committed here; this is not a claim that
all private records were deleted or that current processes were rechecked.
Native conversation history and unrelated sessions were preserved. Any temporary
workspace-trust change was reported restored; this documentation work did not
change global settings or the installed wrapper.

## Next gates (from #307)

A follow-up must pin TUI and delegate versions, keep bounded non-secret native
outcome classification, and separately establish startup timing, legitimate
hook authority and actual receipt, without copying credentials or weakening
owner checks. Issue #307 stays open until those acceptance gates are met.
