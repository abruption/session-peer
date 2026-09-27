# session-peer CLI reference

[Back to the overview](../README.md)

Detailed command behavior, installation options, transport limits, and historical validation follow below.
Machine consumers should also follow the [v1 compatibility contract](compatibility-v1.md).

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/pypi/pyversions/session-peer)](https://pypi.org/project/session-peer/)

Message **Claude Code and Codex sessions**, locally or over SSH, from one CLI.
Claude targets use their native inbox socket/pipe; Codex targets use `codex queue`.
SSH runs the same Python script on the destination, so session-peer need not be
installed there to receive a send or list request.

This project continues cc-peer with its Git history and issue numbers preserved.
session-peer releases are published on [PyPI](https://pypi.org/project/session-peer/)
and [GitHub](https://github.com/abruption/session-peer/releases); the old PyPI
cc-peer project is archived after its final 0.5.1 release.
See [Moving from cc-peer](#moving-from-cc-peer) for explicit migration steps.

## Support and security

- **Bugs and feature requests:** use the [issue templates](https://github.com/abruption/session-peer/issues/new/choose). Search existing issues first.
- **Security vulnerabilities:** [report privately](https://github.com/abruption/session-peer/security/advisories/new). See [SECURITY.md](../SECURITY.md).
- **Private questions:** email [support@abruption.dev](mailto:support@abruption.dev?subject=%5Bsession-peer%5D%20Support) with `[session-peer]` in the subject. Email is also an alternative if you cannot use private vulnerability reporting.

Public issues are visible to everyone. Share minimal, redacted reproductions;
do not attach conversation histories, session databases, authentication files,
tokens, or private keys. Emails are reviewed manually and are not automatically
published as issues. Support is best effort with no guaranteed response time.
English and Korean reports are welcome.

## Quick start

Install the CLI with `pipx install session-peer` or `uv tool install session-peer`.
For the standalone CLI plus Claude skill, see [Install](#install).

```bash
session-peer list                              # Claude, Codex + registered Antigravity
session-peer list --agent claude                # Claude-only filter
session-peer list --agent codex                 # saved Codex threads
session-peer list --agent codex --host worker   # saved threads on an SSH host

session-peer send --to api-worker --message "message"     # Claude name or PID
session-peer send --to 'codex:<full-thread-uuid>' --message "message" --output-format json
session-peer send --host worker --to 'codex:<full-thread-uuid>' --dry-run -m "message"
```

Replace `<full-thread-uuid>` with a full ID from the destination's Codex listing.
`list` includes all registered adapters by default. Antigravity lists only live,
explicitly registered bridges. **Use
`--agent codex` to filter, not `--codex`**: `--codex` is not a supported flag and is ambiguous
with `--codex-home` and `--codex-bin`. `send` selects the agent from its target,
not a `--agent` flag.

**Posted/queued is not acknowledged.** Saved Codex threads are not necessarily
running. Plain send does not activate a session; [explicit `--wake`](wake.md)
is opt-in and does not confirm consumption or a reply.

### Optional paired devices and Antigravity (v0.9)

These features are available starting with PyPI v0.9.0. Antigravity remains
experimental and the paired transport remains beta; operational validation
is still required. Install the extra with `pipx install 'session-peer[relay]'`.
The `[relay]` extra (Unix, Python 3.11+) enables authenticated paired-device
delivery directly or through a self-hosted WSS relay. Pairing pins device
identities; a separate operator policy permits individual agent targets and
operations. The blind relay cannot decrypt application messages. Follow the
[paired-device setup and operations guide](paired-devices.md) before exposing
an endpoint. The beta does not provide NAT traversal or a hosted public service.

Antigravity requires an explicitly started bridge inside the existing TUI; see
[Antigravity setup](antigravity.md). It is opt-in and does not change
Claude/Codex discovery; live Antigravity registrations also appear in unfiltered
listing. Normal local and SSH commands retain their standard-library-only
installation path. See the [v0.9 release notes](releases/v0.9.0.md).

### Message input and result output

`--message TEXT` (short form `-m`) names the text sent to the destination.
`--output-format text|json` selects the command result format, not the message
format. It is available on `list`, `send`, `doctor`, and `update`; the default is
`text`. The existing `--json` is retained as an alias for `--output-format json`.

```bash
session-peer send --to worker --message "Report progress" --output-format json
session-peer send --to worker -m - --output-format json < message.txt
session-peer list --output-format json
```

Legacy positional messages and omitted-message stdin input continue to work.
Use either a positional message or `--message`, not both. `--message -` reads
stdin; an explicit empty message is still rejected. To send text beginning with
a dash, use `--message='--literal text'` or stdin. Internal SSH `--b64` input
cannot be combined with either public message form.

`--json --output-format json` is valid; combining `--json` with
`--output-format text` is an error in either order. Invalid/contradictory output
options are argparse usage errors (stderr, exit 2); message-source conflicts
are ordinary command errors (JSON when requested, exit 1). No messages are
submitted in either case. JSON results still describe submission rather than
receipt; these flags introduce no structured JSON message-input protocol.

## Install

Python 3.9+, standard library only — no external dependencies.

### pip

In an activated virtual environment:

```bash
python -m pip install session-peer
```

Or with [pipx](https://pipx.pypa.io/) for an isolated install:

```bash
pipx install session-peer
```

Alternatively, use `uv tool install session-peer`.
Package managers install the `session-peer` command but not the [agent skill](#the-skill).
Install the skill for Claude Code, Codex, and Antigravity from its dedicated repository:

```bash
npx -y skills@latest add abruption/session-peer-skill \
  --skill session-peer --global \
  --agent claude-code --agent codex --agent antigravity \
  --copy --yes
```

### install.sh

Installs both the command and the skill in one step. Use this for air-gapped
hosts or remote deployment over SSH:

```bash
git clone https://github.com/abruption/session-peer && cd session-peer

./install.sh                          # this machine
./install.sh --host build-server      # a remote machine, over SSH
./install.sh --host web-01 --host db  # several at once
```

That places `session_peer.py` in `~/.local/share/session-peer/`, installs a
compatibility copy of the [session-peer skill](https://github.com/abruption/session-peer-skill/blob/main/session-peer/SKILL.md) in both `~/.claude/skills/session-peer/` and `~/.agents/skills/session-peer/`,
and links `~/.local/bin/session-peer`. Skills already installed by another manager,
including symlinks, and existing cc-peer files are preserved. Remove installer-owned
files with `./install.sh --uninstall [--host ...]`; unmarked legacy skills remain.

`session-peer update` refreshes a standalone program from the latest GitHub release.
`./install.sh --host <host>` pushes this checkout's program and skill over SSH.
`session-peer update --host <host>` pushes only the program when the installed
version differs or is absent; add `--check` to report without changing anything.
See [Updating](#updating) for package-managed installs and remote limitations.

**Remote installs push the files over the SSH connection itself**, so the target needs
no internet access. Installing the standalone files requires `python3` and SSH
access. Messaging also requires the selected agent's native inbox or queue on
the destination.

Or skip the installer entirely and copy the one file:

```bash
curl -O https://raw.githubusercontent.com/abruption/session-peer/main/session_peer.py
chmod +x session_peer.py
```

### The skill

The published skill is maintained in the [session-peer-skill repository](https://github.com/abruption/session-peer-skill).
The standalone installer retains a compatibility copy for air-gapped and SSH
installations and places it in `~/.claude/skills/session-peer/SKILL.md` for Claude
Code and `~/.agents/skills/session-peer/SKILL.md` for Codex. Claude placement
respects `CLAUDE_CONFIG_DIR`, then `ANTHROPIC_CONFIG_DIR`, before the default.
It does not overwrite separately managed skills or remove them on uninstall.
For normal global installation across Claude Code, Codex, and Antigravity, use the
Skills CLI command above. The skill guides target and message selection while the
Python program performs discovery and transport. Installing it does not change an
agent's permissions or inbound settings.

## Usage

```bash
session-peer list                                  # Claude + Codex on this machine
session-peer list --host web-01                    # Claude + Codex over there
session-peer list --host web-01 --all              # Claude stale records / no inbox
session-peer list --agent codex --all              # include archived Codex threads
session-peer doctor                                # local inbox/tool/home diagnostics
session-peer doctor --host web-01                  # run the same checks there
session-peer doctor --host web-01 --check-return-route  # also test SSH back here

session-peer send --to api-worker "message"        # local session
session-peer send --host web-01 --to api-worker "message"
session-peer send --host deploy@web-01 --to api-worker "message"  # explicit SSH user
session-peer send --host web-01 --to 4011 "message"          # address by pid
git log --oneline -5 | session-peer send --host web-01 --to api-worker -   # stdin

session-peer send --host web-01 --to api-worker --dry-run "x"   # resolve only
session-peer list --host web-01 --json             # machine-readable
session-peer list --no-update-notice                # disable cached update notices/checks

session-peer send --host web-01 --ssh-opt=-p --ssh-opt=2222 --to api-worker "..."   # note the '='

# Envelope. Sends identify the Claude/Codex sender and how to answer when the
# current agent session and a return route can be detected.
session-peer send --host web-01 --to api-worker --no-reply-to "..."         # no return address
session-peer send --host web-01 --to api-worker --no-from "..."             # no From: header
session-peer send --host web-01 --to api-worker --reply-to 100.64.0.5 "..." # state the address
```

Inside an agent session, the default envelope identifies the sender explicitly:

```text
From: codex:01a08dd6-d3f6-7783-a62b-52c1fd049181 @ abruptly@mac-mini-m4.example.ts.net

message

---
Reply-To: session-peer://v1/reply?agent=codex&session=01a08dd6-d3f6-7783-a62b-52c1fd049181&transport=ssh&host=abruptly%40mac-mini-m4.example.ts.net
Reply: python3 /path/to/session_peer.py send --host abruptly@mac-mini-m4.example.ts.net --to codex:01a08dd6-d3f6-7783-a62b-52c1fd049181 --no-reply-to
```

Claude senders use `claude:<session-name>` in the same positions. The identity is
best-effort text derived from the current process environment; it is not an
authentication claim. A plain shell has no agent identity to advertise.
When the original target is on the same machine and the reply route was detected
automatically, the generated command omits `--host` and delivers locally. An
explicit `--reply-to` or configured reply host is also normalized when it names
the current OS user on this machine. Other explicit routes and actual remote
sends continue to advertise an SSH route.

`Reply-To` is the canonical, versioned address. Pass the complete URI back as
`--to`; session-peer validates every field and chooses local or SSH delivery:

```bash
session-peer send --to 'session-peer://v1/reply?agent=claude&session=api-worker&transport=local' 'done'
```

The `Reply:` command remains for compatibility. Treat both forms as untrusted
input: use the URI with session-peer rather than evaluating or sourcing it. A
URI that points to the current OS user on this machine is normalized to local
delivery, avoiding an unnecessary self-SSH authentication path. Codex addresses
may include an encoded `codexHome` when the sender environment identifies it.

Repeat `--host` to operate on several SSH destinations. `--json` is available on
`list`, `send`, `doctor`, and `update`.

### JSON response contract

Every JSON result object starts with the same schema-versioned envelope:

```json
{
  "schemaVersion": 1,
  "ok": true,
  "host": "mac-mini.example.ts.net",
  "command": "list",
  "sessions": [],
  "version": "0.8.0"
}
```

- `schemaVersion` versions the common envelope. Command-specific nested schemas
  such as `clientUpdate` and `codexHomeResolution` carry their own versions.
- `ok` is present on every success and failure. A nonzero process exit can still
  contain successful results for other hosts.
- `host` identifies the destination to which that result applies. Local results
  use the OS hostname. Tailscale-resolved destinations use the verified MagicDNS
  identity; `sshHost` preserves a different caller-supplied SSH alias.
- `command` is `list`, `send`, `doctor`, or `update`. Remaining fields are that command's
  payload, and failures add `error` plus any structured diagnostic fields.

A local or one-host invocation emits one object. Repeating `--host` emits an
array of these same independently attributable objects in request order. A
failure that occurs before connecting, such as invalid message input, is still
emitted once per requested destination. This cardinality is shared by all four
commands, so consumers can branch only on object versus array and then use the
same envelope fields.

Normal commands read a dedicated 24-hour update cache. A missing, expired, or
invalid cache starts one detached best-effort GitHub refresh and never delays or
changes the requested command. When a fresh cache proves that the invoking CLI is
behind a stable release, JSON results add `clientUpdate`:

```json
{
  "clientUpdate": {
    "schemaVersion": 1,
    "status": "available",
    "current": "0.7.0",
    "latest": "0.7.1",
    "checkedAt": "2026-09-16T10:00:00Z",
    "source": "github_release_cache",
    "command": "session-peer update"
  }
}
```

Human output gets the same short guidance on stderr. The field is omitted when
the client is current, the cache is unavailable or stale, the host is offline,
or notices are disabled, so absence alone does not prove the client is current.
For multi-host commands the fact remains scoped to the one invoking CLI and is
copied into each result object; destination `remoteVersion` fields keep
their separate meaning. Remote subprocesses do not perform their own refresh.

When local `tailscale status --json` identifies a `--host` by device hostname,
short MagicDNS name, full MagicDNS name, or Tailscale IP, session-peer verifies and
reports the current MagicDNS FQDN as `host`. SSH still receives the supplied value
as its destination alias, reported separately as `sshHost` when different, while a
`HostName` override routes the connection to that FQDN and `HostKeyAlias` retains
the existing host-key lookup. This preserves matching `Host`, `User`, `Port`, and
`IdentityFile` settings. A known peer reported offline fails before SSH. Hosts
absent from the tailnet map remain normal SSH destinations.

Host identity does not supply a login account: `known_hosts`, Tailscale peers,
and MagicDNS names identify a machine, not its OS users. Specify the account as
`--host USER@HOST`, or configure it for the original alias:

```sshconfig
Host web-01
    User deploy
```

An explicit `USER@HOST` takes precedence. Otherwise session-peer runs `ssh -G`
with the same alias and options to report the effective OpenSSH configuration or
local-user default. It never guesses from another machine or retries a failed
login under different usernames.

Successful remote results and SSH connection failures add `sshUser` and
`sshUserSource`; the source is `explicit`, `ssh_config_or_local_default`, or
`unknown` when `ssh -G` cannot resolve it. Connection failures also add
`sshFailure`, classified as `authentication_failed`, `host_key_failed`, `timeout`,
or `transport_failed`. Authentication errors direct the caller to
`--host USER@HOST` or the original alias's SSH `User` setting and are never
retried.

Exit codes: `0` successful command (including listing or dry-run), `1` operational
error, `2` CLI usage error or an unresolved target reported as no-target, and
`130` interrupted (Ctrl-C). A Codex queue rejection, including a missing rollout,
is an operational error (`1`); a missing saved thread during dry-run returns `2`.
Exit `0` on send does not confirm consumption or a reply.

### Updating

For package-managed installs, use the same manager that installed the command:

```bash
pipx upgrade session-peer
# or: uv tool upgrade session-peer
# or, in its virtual environment: python -m pip install --upgrade session-peer
```

For these installs, local `session-peer update` prints package-manager guidance
without replacing package-owned files. `session-peer update --check` checks the
latest stable GitHub release, refreshes the shared cache, and reports the exact
upgrade command, but still does not replace those files.

For standalone programs:

```bash
session-peer update --check                       # check the latest GitHub release
session-peer update                               # update the local program
session-peer update --host web-01 --check         # inspect the remote standalone copy
session-peer update --host web-01                 # push this program if versions differ
```

Remote update compares against the **local program's version**, not the latest
GitHub release. It pushes even if the remote version is newer; check first and
update the local program before distributing it. The remote copy does not fetch
from GitHub. Remote version probes inspect only
`~/.local/share/session-peer/session_peer.py`, not pip/pipx/uv installations;
remote update installs that standalone path and its CLI link. For a
package-managed remote CLI, upgrade it with its own manager on that host instead.

Neither local nor remote `update` refreshes the Claude skill. Re-run `install.sh`
from the desired release checkout to refresh both standalone program and skill.
Local `session-peer update --check` and `session-peer update` also populate the
same cache used by automatic notices.

### Environment variables

| Variable | Effect |
| :-- | :-- |
| `SESSION_PEER_REPLY_HOST` | Override the advertised reply host: `--reply-to` → `SESSION_PEER_REPLY_HOST` → `CC_PEER_REPLY_HOST` → auto-detected Tailscale MagicDNS name or IP. A detectable Claude or Codex sender session is still required for a reply line. |
| `CC_PEER_REPLY_HOST` | Legacy fallback; prefer `SESSION_PEER_REPLY_HOST` for new configuration. |
| `CLAUDE_CONFIG_DIR` | Where Claude Code keeps its config (default `~/.claude`). Respected by `session-peer list` for session discovery and by `install.sh` for skill placement. |
| `ANTHROPIC_CONFIG_DIR` | Fallback if `CLAUDE_CONFIG_DIR` is unset. |
| `CODEX_HOME` | Codex discovery/queue home (default `~/.codex`); overridden by `--codex-home`. |
| `SESSION_PEER_CODEX_HOMES` | Additional destination homes to check for duplicate thread UUIDs and stable live writers before an implicit send/dry-run. JSON array of absolute paths (or `~/…`), not a shell command or a path-separated list. It does not merge listings; an unambiguous active writer may change the implicit send home. |
| `SESSION_PEER_NO_UPDATE_NOTICE` | Set to `1`, `true`, `yes`, or `on` to disable automatic cached update notices and background refreshes. The per-command equivalent is `--no-update-notice`. Explicit `session-peer update --check` still checks. |
| `XDG_CACHE_HOME` | Base directory for the update cache; otherwise `~/.cache/session-peer/update.json` is used. |

With `--host`, discovery uses the destination's environment; local environment
variables are not automatically forwarded. `--codex-home` and `--codex-bin`
explicitly select paths on that destination.

## Codex sessions

Codex discovery reads `state_5.sqlite` using a read-only SQLite connection.
This internal schema is experimental, tested with Codex CLI 0.154.0 on macOS;
cross-platform fixture tests are not a claim of live Codex verification on all OSes.
Saved sessions are not necessarily active. `--all` includes archived threads.

`--codex-home` overrides the destination's `CODEX_HOME` (default `~/.codex`).
`--codex-bin` overrides its PATH lookup of `codex` for sending. On SSH these are
remote paths. Sending requires a Codex executable with the `queue` command and
the appropriate saved thread/rollout in that home; a listing alone does not
prove the queue can accept it.

### Orca and multiple Codex homes

An Orca-launched session can use a per-account home while a separate terminal
or SSH command uses `~/.codex`. The same UUID can exist in both. A successful
queue submission to one copy does not establish that the intended session is
using that home.

An explicit destination home remains the strongest selection. For example, replace
`<account-id>` and `<full-thread-uuid>` with the intended account and thread:

```bash
session-peer list --host mac --agent codex \
  --codex-home '~/Library/Application Support/orca/codex-accounts/<account-id>/home' --json
session-peer send --host mac --to 'codex:<full-thread-uuid>' \
  --codex-home '~/Library/Application Support/orca/codex-accounts/<account-id>/home' \
  --dry-run --json "message"
```

Omit `--host mac` for local use. Remove `--dry-run` only when ready to submit.
Quoting `~` keeps expansion on the destination; an absolute remote path also
works. Current releases treat `--codex-home` as a destination constraint and
still validate every matching known home's writer evidence. Older releases
accept the explicit-home syntax but do not provide this safety guarantee.

The duplicate-home rejection baseline shipped in v0.6.1. The active-writer
selection, revalidation, and detailed `codexHomeResolution` evidence described
below ship in v0.6.2; v0.6.1 requires an explicit `--codex-home` when the same
thread UUID exists in more than one known home.

Without `--codex-home`, selection still uses destination `CODEX_HOME`, then
`~/.codex`. Before send or dry-run, the ambiguity guard checks a bounded inventory:

- The selected home and the default `~/.codex` when its state DB exists.
- On macOS only, existing state DBs immediately under
  `~/Library/Application Support/orca/codex-accounts/*/home`.
- Additional homes from destination `SESSION_PEER_CODEX_HOMES`, for example:

```bash
export SESSION_PEER_CODEX_HOMES='["/srv/codex/account-a", "/srv/codex/account-b"]'
```

Configure this in the destination command's environment; a local export is not
forwarded by `--host`. On Windows, use absolute Windows paths with backslashes
escaped as required by JSON. Empty configuration arrays are allowed; malformed
configuration is an error for implicit sends.

For every send and dry-run, session-peer finds every known home that saves the
UUID and examines its exact `thread-writer-locks/<uuid>.lock`. This includes a
single candidate and an explicit `--codex-home`. It independently probes the
kernel advisory lock and correlates the opener through two stable `lsof`
observations. An implicit send selects the only stable, same-user Codex writer.
An explicit home must be that writer; if another home owns the only live writer,
the command returns a structured conflict and never changes the home silently.
The selected PID, process start time, and held lock are checked again immediately
before queue submission. A free or stale lock does not win merely because its
file exists.

Unknown evidence, multiple live writers, missing `lsof`, permission failures,
changing PIDs/start times/inodes, and conflicting evidence fail closed before
queueing. Archived saved copies still count. Unreadable or incompatible known
databases and missing configured databases also prevent submission. If every
saved copy is inactive, intentionally queueing for a future resume requires an
explicit `--codex-home` together with `--allow-inactive-codex-home`; `--wake`
already serves as the explicit activation opt-in. The inactive flag without an
explicit home is rejected. Resolved symlink aliases and repeated paths count as
one home.

`list` aggregates known homes unless `--codex-home` selects exactly one. There
is no general filesystem scan or process environment inspection, and process
arguments are not exposed. Activity inspection runs on the destination machine,
including over SSH. Platforms without POSIX `flock` or `lsof` cannot establish
live-writer ownership and fail closed when that evidence is required.
Unconfigured/custom layouts and copies created after the check can still be
missed. Use `session-peer doctor` to inspect the selected home, bounded
candidates, executable, and supported state DB schema without submitting.

### Submission and JSON results

Submission uses `codex queue`, never direct database writes. `queued` means the
CLI accepted the submission, not that a turn consumed it or acknowledged it.
session-peer does not wake or resume sessions. Queue DB writes and Claude socket
connections may require approval in the caller's execution environment; the tool
does not change sandbox or inbound policies. A queue timeout (30 seconds) has an
unknown submission outcome: inspect the destination before retrying. It is not
a timeout for waiting on a reply, and session-peer does not automatically retry.

Codex messages are limited to 32 KiB of UTF-8 including sender/reply headers, as a
session-peer portability policy rather than a measured Codex server limit. NUL
characters cannot be passed as CLI arguments. `--dry-run` verifies the executable
and saved target without queueing but cannot guarantee a later submission will succeed.

Local Codex list JSON uses the common response envelope and includes `sessions`,
`version`, and per-home diagnostics in `discovery.codex.homes`. Each session entry has
`agent`, `id`, `name` (first line, at most 120 characters), `cwd`, `updatedAt`
(Unix seconds), `archived`, canonical `codexHome`, and `stateDb`. Top-level
`codexHome` is retained only for a single candidate home without inventory errors.
Each successful remote result includes the same fields and an optional `remoteVersion` for an
installed standalone copy. One remote host returns an object; repeated hosts
return an array.

Within the common envelope, Codex send JSON includes `target: {agent, id}`,
`status: queued` (or `validated` under dry-run), `chars`, `dryRun`, and optional
`queueId`. It also includes:

- `codexHome`: the resolved absolute destination home, not a sender-side guess.
- `codexHomeResolution`: schema-versioned `status`, `selected`, `reason`, and
  bounded candidate evidence. Status is `explicit`, `selected`, `ambiguous`, or
  `unknown`; candidates expose saved-thread, writer-lock, stable owner PID and
  process start-time facts without process arguments or environment values.
- `submitted`: `true` only after successful queue CLI completion, `false` for dry-run.
- `consumptionConfirmed`: always `false`; neither queued nor validated establishes consumption.

Errors set the common envelope's `ok` to `false`, add `error`, and include
`codexHomeResolution` when home evidence caused the failure.
A timeout has an unknown submission outcome; missing `submitted` on an error
must not be interpreted as proof that nothing was queued. Listing results do
not describe a submission and have no submission/consumption fields.

For every command, one remote host returns a flat object and multiple hosts
return an array. When `CODEX_THREAD_ID` (or the compatibility
fallback `CODEX_SESSION_ID`) is present, the message envelope and reply command
identify the originating Codex thread.

### Diagnostics and reply observation

`doctor` performs read-only checks on the machine that owns the sessions. It
reports Claude's configured sessions directory and inbox availability, Codex's
executable and bounded home/state DB candidates, unsupported DB schemas, and
permission or unknown failures as distinct codes. It does not connect to an
inbox, write a queue, scan arbitrary directories, or alter agent/SSH settings.

Reverse SSH is checked only with `--check-return-route`. The destination runs a
fixed `ssh ... true` probe with prompts, password authentication, host-key
enrollment, and config mutation disabled. Forward SSH success is never reused as
proof that the reverse path works. Use `--reply-to USER@HOST` when automatic
Tailscale detection cannot identify the origin. JSON details and status values
are documented in [docs/diagnostics.md](diagnostics.md).

There is deliberately no general `--wait`. Claude Code has a native
same-machine `notify_when_idle` facility, but it does not cover remote sessions,
subagents, or Codex, and a successful socket/queue submission is not an
acknowledgement. session-peer therefore reports
`capabilities.replyObservation.status: unsupported` instead of tailing mutable
transcripts and risking a false match. Ask the target to send an explicit reply
to the supplied `Reply-To` address when completion matters. Optional wake remains
tracked in [#46](https://github.com/abruption/session-peer/issues/46).

## Moving from cc-peer

The repository rename and package transition are complete:
[session-peer 0.6.0](https://pypi.org/project/session-peer/0.6.0/) is published and
[cc-peer 0.5.1](https://pypi.org/project/cc-peer/0.5.1/) is the final Claude-only
compatibility release. **The old PyPI cc-peer project is archived; the GitHub
session-peer repository remains active.** Existing legacy distributions remain
downloadable and are not yanked for migration. See the completed [transition
issue #48](https://github.com/abruption/session-peer/issues/48).

Install the new product explicitly with `pipx install session-peer`,
`uv tool install session-peer`, or the [standalone installer](#installsh).
No `cc-peer` command alias is installed. Both products can coexist.
After checking your workflows, remove the old package with the same manager that
installed it, e.g. `pipx uninstall cc-peer`. For a script installation, use the
`install.sh --uninstall` from the pinned cc-peer v0.5.1 tag; check its paths and
back up local customizations before running it. New uninstall only removes
session-peer files.

Update scripts and agent instructions to call `session-peer` and use the new
standalone program path `~/.local/share/session-peer/session_peer.py`, not the old
`~/.claude/skills/cc-peer/cc_peer.py`. The new Claude skill lives separately in
`~/.claude/skills/session-peer/`. Claude/Codex configuration, session data and old
installations are not migrated or removed automatically. Replace
`CC_PEER_REPLY_HOST` with `SESSION_PEER_REPLY_HOST` when convenient; the old
variable remains a fallback.

The final cc-peer release is not an ongoing feature or security-maintenance
promise. The frozen root `cc_peer.py` is retained in tags for old self-update
URLs but is excluded from the new wheel and sdist. Its local update command
directs users here instead of installing a different product.

## Claude Code sessions

### Use the official feature first

For Claude-to-Claude workflows, consider Claude Code's built-in
[cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
and [Remote Control](https://code.claude.com/docs/en/remote-control) first.
session-peer provides a shell-driven local/SSH path when that workflow is not
available or suitable, and a common CLI for Claude and Codex targets. The
Claude-specific guidance in this section is not a prerequisite for Codex queues.

### How the inbox transport works

Claude Code's [session inbox socket](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket)
accepts a JSON line:

```json
{"type":"user","message":{"role":"user","content":"your message"}}
```

session-peer connects on the machine that owns that inbox. For SSH sends, it
pipes its source to remote `python3 -` and makes the connection there, rather
than forwarding the Unix socket. Native Windows targets use a named pipe and
the auth line from the session's `.key` file instead.

Session records normally live in `~/.claude/sessions/<pid>.json` and carry the
socket path in `messagingSocketPath`. Never guess `/tmp/cc-socks/`: previous
tests found both that layout and `/run/user/1001/cc-socks/`. A live PID without
a bound inbox is treated as unreachable. The record schema is an internal
interface and may change; use `session-peer list --all` to inspect stale or
inbox-less records. A record or socket's existence does not guarantee that the
caller has permission to write to it.

### The receiving side decides what happens next

**"Posted" is not "delivered."** Writing to the socket succeeds; whether Claude ever reads the message is up to that session's [inbound controls](https://code.claude.com/docs/en/cross-session-messaging#control-inbound-messages).

Messages can be held for approval or refused. In the legacy verification, a
bypass-mode receiver held script-originated messages until approved. Do not
infer receipt from a successful socket write or change permission modes to
make a test pass.

If you deliberately want a worker to accept incoming messages unattended,
configure that receiver explicitly:

```json
{ "crossSessionInbound": "accept" }
```

Scope this with project settings or `--settings` if it is intended for one worker;
user settings affect other sessions for that OS user too. Accepting messages can
start receiving turns and consume usage. session-peer never applies this setting
for you, and the receiver's own tool permissions still apply.

### Why not `tmux send-keys`?

Terminal keystrokes can land in a running subprocess or permission prompt, not
the intended chat input. session-peer uses the agent's inbox/queue boundary
instead. Claude treats an inbox message as peer text, subject to its
[receiving-session rules](https://code.claude.com/docs/en/cross-session-messaging#how-a-session-treats-an-incoming-message),
not as the user typing approval.

## Limits

- **Sender identity is best-effort.** When running inside a detectable Claude or
  Codex session, session-peer adds an agent-qualified textual `From:` header.
  Outside that context, it may omit it. This is not an authenticated identity
  protocol; environment variables and session registries are local hints.
- **Advertised replies need a working return path.** When an agent sender and
  reply host can be determined, `Reply-To` and a compatibility `Reply:` line
  describe a return route. Forward SSH success does not prove reverse SSH
  access; use the opt-in doctor check. The address grants no access and
  session-peer does not correlate or wait for a reply.
- **Tailscale status is a local routing hint.** A known online peer is addressed
  by its current MagicDNS name and a known offline peer is rejected before SSH.
  An unknown destination remains ordinary SSH; session-peer does not claim that
  every SSH host belongs to the tailnet.
- **No discovery across a bastion.** `--host` is a single SSH hop; chain it yourself with an SSH config `ProxyJump`.
- **Destination user and execution permissions matter.** Claude inboxes and
  Codex state/queues belong to the destination account. Use the correct account
  and home. A `known_hosts` entry does not store that account. A caller's sandbox
  may still deny access; session-peer does not bypass either agent's permissions
  or quota.
- **`--host` and `--ssh-opt` are as trusted as your ssh config.** They are handed to `ssh`, so whoever controls them controls where you connect. Values that would make ssh run a local command (`ProxyCommand` and friends) are refused, and a `--host` starting with `-` is rejected outright — but if you allowlist `session-peer` for an agent, treat it as granting SSH, not just messaging. Message bodies and session names carry no such risk: they are quoted before they reach any shell.
- **Windows support.** Claude's named pipe transport is supported.
  `install.sh` and the standalone remote installer/updater use POSIX shell;
  use a Python package manager on native Windows. Live Codex verification
  remains macOS-only; the Codex home, Reply-To, doctor, and JSON fixtures run in
  Windows CI.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The default suite needs no live agent, SSH server or network. It includes legacy
compatibility tests, shared CLI helpers, fixture-based Codex discovery and queue
subprocess tests, and isolated standalone installation/coexistence checks.
Codex coverage includes argv/payload handling, destination home selection,
real advisory-lock probing, stable owner evidence, dry-run without dispatch,
failure/timeout semantics and remote option forwarding.
Multi-home fixtures reproduce duplicate UUIDs across the default and Orca/configured
homes, unique/multiple/changing writer evidence, fail-closed inventory errors,
explicit selection, alias deduplication, single-home compatibility and structured
home/submission metadata. They never infer a live writer from a saved row or
submit messages to real sessions.
Update-notice coverage checks freshness and expiry, strict stable versions,
atomic private writes, single-flight background refresh, opt-out behavior,
package-manager guidance, multi-host scope, and failure isolation.

CI runs tests on Ubuntu/macOS with Python 3.9 and 3.13, and Windows with Python
3.13 (POSIX installer tests are skipped there). Separate jobs check shell syntax
with `shellcheck`, standalone install/reinstall/uninstall, and wheel/sdist
contents and installation. This is not full transport coverage: Claude discovery
fixtures, real UDS payload checks and broader exit-code/remote-command regression
tests remain tracked in [#28](https://github.com/abruption/session-peer/issues/28).

## Verified

### session-peer v0.8.0 candidate (2026-09-16)

- Integrates unified Claude/Codex listing, optional MCP tools and a Codex plugin,
  explicit bounded Codex wake, multi-home Codex listing, and named message and output
  formatting options from #76, #77, #78, #80, and #82.
- See [v0.8.0 release notes](releases/v0.8.0.md) for JSON compatibility,
  optional dependencies, the Codex 0.154.0 wake boundary, and validation limits.
- 301 local tests passed with the MCP SDK; standalone runs skip two optional
  SDK tests. Wheel and sdist installed independently and report v0.8.0.
- Release preparation does not publish a GitHub release or upload to PyPI.

### session-peer v0.7.0 (2026-09-16)

- 240 local tests passed for cached update notices, the shared JSON envelope,
  read-only diagnostics, structured Reply-To parsing/routing, same-machine
  normalization, and opt-in reverse-route classification.
- CI covers Ubuntu and macOS with Python 3.9/3.13, Windows with Python 3.13,
  package build and isolated installs, standalone install smoke tests, shellcheck,
  and secret scanning.
- Wheel and sdist contents were inspected and installed independently. Both
  artifacts report v0.7.0 and exclude the frozen legacy `cc_peer.py`.
- A real SSH doctor run found Claude inboxes and bounded default/Orca Codex homes.
  Its opt-in reverse probe reported authentication failure independently of the
  successful forward connection. No live message was submitted.

### session-peer v0.6.2 (2026-09-15)

- 198 local tests and the release build checks passed for UUID-specific Codex
  writer validation, same-machine reply localization, SSH destination-user
  resolution, and structured connection-failure diagnostics.
- Wheel and sdist contents were inspected and installed independently. Both
  artifacts report v0.6.2 and exclude the frozen legacy `cc_peer.py`.
- No live message was submitted during release preparation. Queue acceptance,
  consumption, acknowledgements, and reverse SSH reachability remain distinct
  outcomes.

### session-peer v0.6.1 (2026-09-15)

- 174 local tests and the release CI checks passed after integrating the v0.6.0
  Codex adapter with duplicate-home protection, sender-agent envelopes, and
  MagicDNS SSH routing. Wheel/sdist builds and isolated installs were checked.
- A local Codex listing and explicit-home dry-run succeeded without submission.
  A read-only SSH listing supplied by Tailscale IP connected through the current
  MagicDNS `HostName` and retained the original value as `sshHost`/`HostKeyAlias`.
- No live message was submitted as part of release preparation. Queue acceptance,
  message consumption, acknowledgements, and reverse SSH reachability remain
  distinct outcomes.

### session-peer v0.6.0 transition (2026-09-10)

- 134 local tests and the release CI checks passed. Wheel/sdist builds and
  isolated installs, actual PyPI installs, package-manager update protection,
  and coexistence/removal of the legacy CLI were checked.
- With Codex CLI **0.154.0 on two macOS machines**, local/SSH saved-session
  discovery, dry-run and actual queue submission worked. The submitted bodies
  matched the queue records. Those checks established **queued**, not consumed
  or acknowledged, and did not establish a reliable active-session indicator.
- Claude local/SSH inbox writes through the new CLI succeeded. A weekly usage
  limit prevented fresh receiving-turn/reply verification; those writes are
  not claimed as completed round trips.
- Standalone CLI/Claude skill migration was checked on two macOS hosts and two
  Ubuntu hosts. Installation and read-only discovery checks did not start agent
  turns or change inbound settings.

See [RELEASING.md](../RELEASING.md) and [#48](https://github.com/abruption/session-peer/issues/48)
for the release sequence and verification limits.

### Historical cc-peer Claude transport verification

Before the rename, Claude Code **v2.1.263** was exercised across five machines
over SSH on a Tailscale network: two macOS 26 (Apple silicon), two Ubuntu 24.04
(arm64, Oracle Ampere A1 in separate regions), and one Windows 10 22H2.
These historical observations are not a claim that every test was repeated
with session-peer v0.6.0:

- Posting from macOS to Linux sessions in two regions; each landed in the receiving transcript as
  `type: user` with `origin.kind: "peer"`.
- Payload integrity — quotes, backticks, `$HOME`, and emoji arrive byte-for-byte.
- The held path: a bypass-mode session raised an approval dialog, then logged
  `Released 1 held cross-session message` once approved.
- Both socket layouts in the wild: `/tmp/cc-socks/` on one Ubuntu host, `/run/user/1001/cc-socks/`
  on another running the same build.
- Windows named pipe transport (`\\.\pipe\LOCAL\cc-msg-<hash>`) with mandatory auth line read from
  the session's `.key` file. `list`, `send`, and `--host` all verified on the Windows machine.

Both agents' discovery formats can change between upstream releases. A previous
successful transport test does not guarantee discovery or delivery in a newer
agent build.

## License

MIT

### Combined session discovery

Default `list` and `list --json` query Claude and Codex together. Use
`--agent claude` to retain the previous Claude-only default, or `--agent codex`
for Codex only. Every session row includes `agent: "claude" | "codex"`;
agent-specific fields such as PID and thread UUID remain unchanged. Combined
human output includes an AGENT column. Claude rows precede Codex rows, preserving
Claude discovery ordering; Codex rows sort by descending update time, then home and UUID.

List responses include `discovery`, keyed by each requested agent, with
`status: "ok" | "not_installed" | "error"` (the middle state is Codex-only)
and an `error` explanation for failed sources.
Any discovery failure returns `ok: false`, a top-level error summary, and exit
code 1 while retaining successfully discovered sessions. No automatically discovered
Codex installation is a normal empty result (`not_installed`, exit 0); a missing
explicitly configured home is an error. A missing Claude sessions directory is an empty result.
Neither is evidence of a running Codex process. Malformed individual Claude
records continue to be skipped as before.

These semantics apply locally and over SSH. Repeated hosts retain independent
results in the existing ordered array; any failure makes the overall exit code 1.
Codex listing includes default, environment-selected, Orca, and configured homes.
Use `--codex-home PATH` to inspect only that home.
`--all` retains Claude stale/no-inbox records and includes archived Codex threads.

### Optional MCP / Codex plugin

For structured, destination-restricted `list_sessions` and `send_message` tools,
install `session-peer[mcp]` with Python 3.10+ and follow [MCP setup](mcp.md).
The default policy permits local listing only. The standalone CLI and shell
installer retain their existing dependency requirements.

For opt-in activation of queued Codex sessions, see [explicit wake](wake.md).

See [multi-home Codex listing](multi-home-list.md) for candidate sources,
per-home errors, duplicate UUIDs, and selecting the exact home for send.

### Internal extension architecture

Agent adapters and local/SSH execution share an internal versioned contract while
retaining the single-file CLI. See [adapter development](agent-adapters.md)
and the [architecture decision](architecture/agent-transports.md). External
plugin loading is not available. `doctor.capabilities.agents` describes implemented
list/send/wake/wait/ack support; it does not grant permission or prove readiness.
