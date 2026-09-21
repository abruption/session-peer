# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

**English** · [한국어](https://github.com/abruption/session-peer/blob/main/README.ko.md) · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · [简体中文](https://github.com/abruption/session-peer/blob/main/README.zh-CN.md)

**Find and message Claude Code and Codex sessions, locally or over SSH, from one CLI.**

Ask a session on another machine to review a change, report progress, or pick up
a task. session-peer uses native agent inboxes and queues; the receiving agent
controls how incoming messages are handled.

## Quick start

Python 3.9+. The core CLI has no third-party Python dependencies.

```bash
pipx install session-peer
# Alternative: uv tool install session-peer

session-peer list
session-peer list --host worker
session-peer send --to api-worker --message "Report progress"
session-peer send --host worker --to 'codex:<full-thread-uuid>' --message "Review the change"
```

Replace `worker` with your SSH host or alias, `api-worker` with a discovered
session name, and `<full-thread-uuid>` with the full ID from the destination's
listing. The destination needs Python and the target agent's inbox or queue;
session-peer itself need not be installed there for SSH list/send.

**`posted` / `queued` means submitted, not read or completed.** Saved Codex
threads may be inactive. Ask for an explicit reply when completion matters.

## Common tasks

| Task | Command / guide |
|---|---|
| Filter by agent | `session-peer list --agent codex` |
| Inspect connectivity and agent setup | `session-peer doctor --host worker` |
| Resolve without sending | `session-peer send --to api-worker --dry-run -m "hello"` |
| Get JSON results | `session-peer list --output-format json` |
| Read a message from a file | `session-peer send --to api-worker -m - < message.txt` |
| Optional MCP tools / Codex plugin | [MCP setup](https://github.com/abruption/session-peer/blob/main/docs/mcp.md) |
| Activate a queued Codex session | [Opt-in wake](https://github.com/abruption/session-peer/blob/main/docs/wake.md) |

## Installation options

Install the Python CLI with `pipx` or `uv`, or run
`python -m pip install session-peer` in an activated virtual environment.
Install the agent skill separately for Claude Code and Codex:

```bash
npx -y skills@latest add abruption/session-peer \
  --skill session-peer --global \
  --agent claude-code --agent codex --copy --yes
```

This writes `SKILL.md` to both `~/.claude/skills/session-peer/` and
`~/.agents/skills/session-peer/`. Update it independently with
`npx -y skills@latest update session-peer --global --yes`. The currently
verified `skills@1.7.0` requires Node.js 22.20 or newer.

For a standalone POSIX installation without the skills CLI:

```bash
git clone https://github.com/abruption/session-peer
cd session-peer
./install.sh
# Remote installation: ./install.sh --host worker
```

The shell installer requires POSIX; on native Windows use a Python package
manager. Optional MCP tools require Python 3.10+ and `session-peer[mcp]`.
See [installation details](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#install).

## Optional v0.9 features

The v0.9 candidate adds [Antigravity](https://github.com/abruption/session-peer/blob/main/docs/antigravity.md) through a bridge explicitly started inside an existing TUI; unfiltered `list` also includes live registered bridges.
[Paired devices / encrypted relay](https://github.com/abruption/session-peer/blob/main/docs/paired-devices.md) require Unix, Python 3.11+ and the `[relay]` extra. Device identities are pinned and targets need explicit operator authorization. The self-hosted WSS relay cannot decrypt application messages; no NAT traversal or hosted public service is provided.
These features are not in PyPI v0.8.0: use a reviewed candidate wheel as described in the guides until published. Ordinary local/SSH commands remain dependency-free.

## Before you send

- Use the correct destination account and agent home. SSH access and receiver permissions still apply.
- Plain sends do not activate inactive sessions. Explicit wake can start a turn and consume usage.
- Redact secrets, conversation text, session IDs, and personal paths before sharing diagnostics.

## Documentation

- [CLI reference](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md): commands, JSON, environment variables, updates, limits, and validation history.
- [Diagnostics and replies](https://github.com/abruption/session-peer/blob/main/docs/diagnostics.md) · [Multiple Codex homes](https://github.com/abruption/session-peer/blob/main/docs/multi-home-list.md)
- [Moving from cc-peer](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#moving-from-cc-peer) · [Releases](https://github.com/abruption/session-peer/releases)
- [Adapter development](https://github.com/abruption/session-peer/blob/main/docs/agent-adapters.md) · [Release process](https://github.com/abruption/session-peer/blob/main/RELEASING.md)

The four README editions cover the same quick start. Detailed docs are currently
in English. Keep translated commands, requirements, and behavior aligned with
the English README. These translations do not change the CLI output language.

## Support and security

[GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose) for
bugs and features; [private reporting](https://github.com/abruption/session-peer/security/advisories/new)
for vulnerabilities ([security policy](https://github.com/abruption/session-peer/blob/main/SECURITY.md)).
For private questions or an alternative security contact, email
[support@abruption.dev](mailto:support@abruption.dev) with `[session-peer]` in the subject.
Support is best effort. Emails are reviewed manually and never automatically
published as issues. English and Korean reports are welcome.

[MIT license](https://github.com/abruption/session-peer/blob/main/LICENSE).
