# session-peer-ts

Python-free **client CLI preview** for local and SSH messaging to Claude Code and
Codex. This is not a Relay server or a full replacement for the Python product.
Public npm publication remains disabled (`private: true`).

## Scope and prerequisites

- macOS/Linux, Node 22.13+ within 22.x or Node 24.x. Windows and Node 26 are not
  supported. A native flock dependency provides prebuilt binaries; x64/arm64
  installation requires a matching binary. It never falls back to checking only
  that a lock file exists.
- Claude: a running native TUI with a local inbox. Codex: a saved thread with one
  stable live writer, native `codex queue`, `lsof` and `ps`. Saved rows alone do
  not authorize delivery. Explicit home selection is mandatory.
- SSH: OpenSSH and this **same preview version installed explicitly on the
  remote host**, with supported Node. No Python fallback, source streaming,
  remote runtime download or automatic installation.
- Unsupported: Relay client/server, Control, MCP, wake, inactive queue opt-in,
  Antigravity, updates and implicit multi-agent discovery. Unsupported options
  fail explicitly; existing Python installs and hosted services are unchanged.

The architecture evaluation in Python
[#186](https://github.com/abruption/session-peer/issues/186) compared an explicit
Python wrapper, an independent Node client, and no npm distribution. This selects
an independent client: Python is only needed by development conformance tests.
A public release still needs a maintenance and publication decision.

## Build and use

```sh
npm ci --ignore-scripts
npm run build
node dist/cli.js list --agent claude --json
node dist/cli.js list --agent codex --codex-home "$HOME/.codex" --json
node dist/cli.js send --to CLAUDE_PID --message 'hello' --dry-run --json
node dist/cli.js send --to codex:UUID --codex-home "$HOME/.codex" --message 'hello' --dry-run --json
```

Remove `--dry-run` only when delivery is intended. Omit `--message`, or use
`--message -`, for UTF-8 stdin. Output is JSON only (`--json` or
`--output-format json`). Claude targets may be PIDs, `claude:PID`, or unambiguous
ASCII names (case-insensitive). Use a PID for Unicode names; full Unicode
casefold parity is deferred. `--codex-bin` selects an executable, never shell
text. `--all` is listing-only. The bin is `session-peer-ts`, not `session-peer`.

```sh
node dist/cli.js send --host user@machine --remote-bin /absolute/path/session-peer-ts \
  --to CLAUDE_PID --message 'hello' --dry-run --json
```

The default remote command is `session-peer-ts` on remote PATH. An absolute
`--remote-bin` may name an operator-owned wrapper selecting a supported Node.
SSH uses existing configuration/keys with BatchMode and StrictHostKeyChecking;
it never approves new host keys. No arbitrary `--ssh-opt` is accepted. IPv6
literals and Tailscale canonical-name enrichment are deferred; use an SSH
alias/hostname. Remote version is checked before one JSON request is sent over
stdin. Message text never becomes remote shell command arguments.

## Delivery and reply safety

- Claude re-resolves one reachable target before one native JSON-line write.
  `posted` is write completion, not ACK. PID/socket metadata is not consumption.
- Codex checks selected/default/Orca/configured homes, actual nonblocking OS
  flock, file identity, same-user owner and process start time across two
  samples. Unknown evidence, multiple live writers and inactive-only copies are
  refused. Inventory and ownership are revalidated immediately before queueing.
  No transcript is read, lock deleted or owner process signaled.
- `queued` is queue acceptance only; `consumptionConfirmed` is always false.
  Response loss, timeout or native nonzero exit after spawn is conservatively
  `status:unknown, submitted:null, retryAllowed:false`. Never automatically resend.
- Refusal before submission has `submitted:false`. Dry-run is `validated`.
  Success/error/usage exit codes are 0/1/2 and JSON uses the v1 envelope. Failure
  diagnostics are fixed codes; no raw exceptions, native stderr or messages.
- Actual ACK must be checked separately in the receiving TUI, not inferred from
  queued/submitted or by polling transcripts.

`--to 'session-peer://v1/reply?...'` accepts strict local/SSH Claude/Codex reply
URIs as data. Unknown/duplicate fields, malformed encoding, unsafe hosts and
conflicting explicit routes are refused. `--reply-address URI` adds an explicit
structured return address; it does not establish reverse SSH access. No route
is invented. `--no-reply-to` omits a new address. A valid CODEX_THREAD_ID or
CODEX_SESSION_ID adds an informational From header unless `--no-from` is given.
Unknown senders are not invented; peer headers are metadata, not authority.
No executable Reply command is synthesized.

## Tests

Point `SESSION_PEER_PYTHON_ROOT` at a checkout of Python v1.0.2, commit
`47c23713d0a2a3c11ebde6186afd8c43489b8b65`. CI pins this commit and compares the
vendored compatibility fixture to it. Development tests require Python 3.9+,
a C compiler and lsof. None is an implicit runtime installer.

```sh
SESSION_PEER_PYTHON_ROOT=/path/to/python-reference npm test
npm run test:package
npm audit
```

Fixtures cover Python discovery/schema/exit contracts, actual temporary SQLite
DBs, Unix inbox sockets and native-process kernel locks. Native fixture evidence
is separate from real TUI/SSH observations in VALIDATION.md. Tests check one-shot
submission, ambiguous writers, wrong owners, dry-run, response loss and unsafe
reply rejection without production state. Set TASK_TEMP for temporary files.

Package tests allowlist tarball files, compare repeat-pack SHA-256, clean-install
into a temporary prefix, run empty-PATH discovery and uninstall. The native
dependency normally has an install script/fallback compilation; the verified
prebuilt path uses `--ignore-scripts`. This is not a pure-JavaScript package.
SQLite reads are read-only/query-only, but WAL readers can participate in shared
memory bookkeeping; this is not a snapshot reader.

## Release boundaries

Preview versioning is independent of Python's 1.0.2 contract reference. This is
not complete Python parity. Windows, wider architectures, full discovery,
Unicode names, implicit reply identity and optional transports require separate
work. Public npm naming, provenance, release automation and long-term ownership
must be decided before publication. Python and Relay retain independent releases.
