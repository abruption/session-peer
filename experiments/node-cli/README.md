# Node CLI experiment — issue #186

**Unpublished, read-only prototype. Not a replacement for session-peer.**
The stable Python CLI and hosted Relay remain unchanged. This directory is
excluded from the Python source distribution (`/experiments` in `pyproject.toml`).
No separate repository, npm name reservation or public release is made here.

## Architecture decision

| Option | Benefit | Cost / decision |
| --- | --- | --- |
| npm adapter calling Python | Reuses mature messaging and safety implementation | Still requires an explicitly installed Python CLI; not Python-free. Not selected for this experiment. |
| Independent TypeScript CLI | A Node-only installation can serve npm users | Must independently preserve identity, queue, transport and uncertain-outcome contracts. Selected **only for a bounded discovery prototype**. |
| No npm package | No second runtime to secure and maintain | Remains the default distribution decision until the gates below pass. |

The long-term candidate is a **client CLI**, never a TypeScript replacement for
the Relay server or Control service. Relay **client** support is also absent in
this first slice; it is not silently routed through Python.

This deliberately starts narrower than a messaging MVP. Codex submission needs
kernel advisory-lock probing, process owner/start-time evidence, cross-home
ambiguity checks and revalidation immediately before queueing. `lsof`, a PID,
or a saved SQLite row alone is not equivalent. No such shortcut is implemented.
Even `send --dry-run` fails explicitly until those checks exist.

## Run locally

Prerequisites: Node **22.13+ within 22.x, or 24.x**, macOS/Linux. The Node
`node:sqlite` API may print an experimental warning on stderr; stdout remains
one JSON result. Windows is explicitly rejected because Claude PID creation-time
and named-pipe handling have not been ported. Linux is a CI target, not a claim
of live-agent interoperability. No platform has a production support promise.

```sh
cd experiments/node-cli
npm ci --ignore-scripts
npm run build
node dist/cli.js list --agent claude --json
node dist/cli.js list --agent codex --codex-home "$HOME/.codex" --json
```

- Only `list`, `--agent claude|codex`, `--json` (or `--output-format json`),
  `--all`, and the applicable `--codex-home` are supported. `--help`, `--version`
  and `--no-update-notice` are available. Updates are never checked or installed.
- Agent selection is mandatory; Codex also requires an explicit home. Implicit
  default/Orca/configured multi-home inventory is deferred, not partially emulated.
- Claude reads the same config-directory precedence and actual socket path in
  each record. `reachable` is only PID/socket metadata, **not** a connection,
  target validation, message consumption or ACK.
- Codex opens `state_5.sqlite` read-only/query-only and discovers saved threads.
  It does not read rollout contents, touch writer locks, or claim execution state.
  SQLite WAL readers can participate in SQLite shared-memory bookkeeping; this
  is not a snapshot reader and does not copy or modify application DB contents.
- `send`, reply, wake, SSH, paired devices, Relay, MCP, doctor, update, human text
  output and Antigravity are unsupported. Unknown options are rejected before
  discovery. No network or child process is used by the CLI.
- A refusal always has `submitted:false`, `consumptionConfirmed:false`, exit 2
  for usage/unsupported operations or exit 1 for discovery failures. There is no
  retry path. Exception strings and unknown argument values are not echoed.
- Successful discovery naturally includes local names, paths and thread IDs,
  just like Python; do not publish raw inventory. Failure diagnostics use fixed
  codes and never include raw database contents or message arguments.

The prototype package version (`0.0.0`) is independent from its Python contract
reference (`1.0.2`). JSON uses schema version 1; it does **not** advertise itself
as the full Python 1.0.2 implementation. `private:true` prevents npm publication;
the nonconflicting bin name is `session-peer-ts-prototype`. No lifecycle installer,
postinstall hook, Python fallback, skills installation or service setup exists.

## Contract tests and packaging

```sh
npm test                         # Python 3.9+ needed only for the test oracle
npm run test:package             # repeatable pack, clean install and uninstall
npm pack --ignore-scripts        # build first; never publish this prototype
```

Tests consume `tests/fixtures/compatibility-v1.json` and invoke the repository's
generated Python CLI against the **same temporary fixtures**, with update checks
disabled. They compare exit codes, the v1 envelope, session rows, ordering,
Unicode truncation, archived filtering and successful Codex discovery metadata.
Error wording and package version are deliberately not byte-identical. The
prototype also rejects unsupported row types conservatively.

An actual Unix socket proves metadata discovery without making a connection;
real SQLite fixtures prove the read path and preserve the DB bytes. Malformed
DB/schema/rows, missing files and unsupported operations fail closed. No real
user messages, credential reads, agent queue submissions or ACKs occur. **These
are not real Claude inbox/Codex queue interoperability tests.** Python-free
execution is tested with an empty PATH. CI covers Node 22/24 on macOS/Linux.

The package contains compiled JS plus this README, MIT license and package metadata. Build
dependencies are exact-version locked; there are no runtime npm dependencies.
The package smoke test compares two tarball SHA-256 hashes, installs into a fresh
temporary prefix, tests the installed bin with an empty PATH, then uninstalls it.
A release decision still needs cross-builder reproducibility/provenance review
and an approved final package name.

## Next gates (keep #186 open)

1. Review this architecture/scope and decide if a second runtime is worth owning.
2. Add full discovery inventory and cross-runtime error/capability contracts.
3. Port target resolution and dry-run with native lock/owner identity evidence;
   test ambiguous homes, PID reuse, races, permissions and unsupported platforms.
4. Port local submission with envelope/reply URI validation, uncertain-outcome
   handling and no automatic resend. Run explicitly authorized real native
   inbox/queue tests; queued must never become consumption/ACK confirmation.
5. Choose SSH prerequisites explicitly: Python currently streams the standalone
   script to remote Python. A Node implementation must not silently require
   remote Python or download remote Node. Relay client/MCP are separate gates.
6. Only after contract/platform gates pass: decide repo split, npm ownership,
   version mapping, supported Node matrix, publication/provenance and maintenance.

References: [#186](https://github.com/abruption/session-peer/issues/186),
[adapter architecture](../../docs/architecture/agent-transports.md),
[v1 compatibility](../../docs/compatibility-v1.md),
[Node SQLite](https://nodejs.org/docs/latest-v22.x/api/sqlite.html).
