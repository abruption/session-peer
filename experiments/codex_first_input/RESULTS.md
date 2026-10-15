# Codex first-input App Server experiment — 2026-10-13

## Result

This is a historical report, not a validation of the current harness. The
account-home row count below was an observed diagnostic, not proof of the
running server's effective SQLite location. Later review found that relocated
storage can invalidate that inference. The harness now uses server-reported
turn snapshots instead; those new guards have not had a fresh native run.

For the subsequent **already-open ordinary TUI** negative/positive controls,
see [ORDINARY_TUI.md](ORDINARY_TUI.md). An embedded blank TUI was unreachable
through the external queue path, while a plain TUI already connected to a shared
server received the external request and replied. Neither establishes arbitrary
in-process TUI attachment or shipped session-peer support.

**PASS for one dedicated macOS App Server and its fresh TUI.** Before any user
prompt, the thread was loaded in memory but had **zero matching rows** in the
selected Codex home's state database. One `thread/queue/add` request was accepted.
The native TUI then displayed the request and its independently generated reply:

```text
ACK CODEX-FIRST-INPUT-306-QUEUE
```

The TUI reported three seconds of work at 14:17 KST. This establishes a feasible
first-input transport; it does not make the public `session-peer send` support it.

## Setup and observations

- macOS arm64; installed Codex CLI/server 0.162.1; TUI-selected GPT-6-Astra medium.
- A dedicated `codex app-server --listen unix://…` process and a fresh
  `codex --remote unix://… --no-alt-screen` TUI shared one private endpoint.
  The working directory was an already approved temporary test folder.
- The server inherited the normal account home and authentication. Credentials
  were not copied; no user configuration, existing daemon, permission setting,
  or unrelated session was changed.
- `thread/loaded/list` contained exactly one ID before submission.
  `thread/read` with `includeTurns:false` reported that same thread as idle,
  non-ephemeral and able to accept direct input. Its cwd matched the owned TUI.
- Read-only SQLite lookup for that exact ID found zero `threads` rows. This was
  checked both during inspection and immediately before the single submission.
- `thread/queue/add` returned `queuedSubmission`; the harness kept
  `consumptionConfirmed:false`. Actual receipt evidence came separately from the
  owned TUI's displayed response, not from queue deletion or turn completion.
- No `turn/start`, `thread/resume`, direct database write, fallback or resend was
  used. The message requested only the fixed reply and no tools or file changes.

## Reproduction harness

`probe.py` requires Python with websockets 17.x and an **exclusively owned** fresh
server/TUI. It does not launch or discover an arbitrary server. Operators supply
the private socket, the same account home used to launch that server, and the
exact approved TUI cwd. The current harness no longer opens local SQLite or
uses account-home row counts. Both modes require
`--allow-server-history-db-init`: even a non-submitting server history lookup
can initialize or migrate the server's history database. `--mode inspect`
reports an empty server-visible-turn snapshot without queuing; `--mode queue`
rechecks the server metadata/turns after checking its pending queue, then sends
once. These are non-atomic snapshots, not storage identity or never-used-thread
attestations. Do not run it against an existing working conversation. Run
without Python optimization because its experimental preconditions use assertions.

The endpoint may be a native-created symlink to a shorter physical Unix socket;
the harness checks both the logical and resolved private directories and socket
ownership. The first harness inspection rejected this symlink before any RPC;
the ownership-preserving resolution was then added. No retry of a send occurred.

The public output excludes IDs, paths and native response bodies. Native error
text is omitted. This harness is excluded from release artifacts under the
existing `experiments/` packaging rule.

## Limits and cleanup

- This is dedicated-server topology, not proof that ordinary daemon, Orca-hosted,
  `--no-daemon`, SSH, Linux or Windows targets can be discovered safely.
- An optional post-reply inspection stopped at the exclusive single-loaded-ID
  assertion. The cause of the changed inventory was not investigated; no
  additional submission was attempted and no post-reply row-count claim is made.
- A product adapter still needs explicit endpoint ownership and generation
  binding, version/capability checks, bounded body-free discovery and approval
  routing. A queue response alone must never become a generic receipt ACK.
- The dedicated server and TUI exited with status zero. The native socket and
  logical link disappeared; the empty owned scratch directory was removed.
  The test conversation remains in the native account's normal history; no
  existing history or credentials were deleted.
- Runtime source, canonical CLI, package metadata and operations were unchanged.

Related issue: [#306](https://github.com/abruption/session-peer/issues/306).
Protocol reference: [Codex App Server](https://learn.chatgpt.com/docs/app-server).
