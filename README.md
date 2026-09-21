# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![PyPI downloads per week](https://api.pepy.tech/badge/session-peer/week)](https://pepy.tech/projects/session-peer)
[![PyPI downloads per month](https://api.pepy.tech/badge/session-peer/month)](https://pepy.tech/projects/session-peer)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

**English** · [한국어](https://github.com/abruption/session-peer/blob/main/README.ko.md) · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · [简体中文](https://github.com/abruption/session-peer/blob/main/README.zh-CN.md)

**Find and message Claude Code and Codex sessions, locally or over SSH, from one CLI.**

Ask a session on another machine to review a change, report progress, or pick up
a task. For example, ask `api-worker` on SSH host `worker` to review a change.
session-peer uses native agent inboxes and queues; the receiving agent controls
how incoming messages are handled.

## See it in action

This 26-second recording uses live Codex and Claude Code sessions over the local
transport—there is no mocked output.

1. Codex discovers the exact Claude Code session.
2. Codex posts a review request to the session's native inbox.
3. Claude Code follows the structured reply address and sends a response.
4. Codex receives the explicit reply in its own session.

```mermaid
sequenceDiagram
    participant C as Codex session
    participant P as session-peer CLI
    participant I as Claude Code native inbox
    participant H as Claude Code session
    C->>P: list (discover exact session)
    P-->>C: host + session ID
    C->>P: send (request + reply address)
    P->>I: write via local or SSH transport
    I-->>H: deliver request
    H->>P: send explicit reply
    P-->>C: deliver to Codex native inbox
```

[![Live Codex-to-Claude Code messaging demo](docs/assets/session-peer-live-codex-claude-poster.png)](docs/assets/session-peer-live-codex-claude.mp4)

[Watch the 26-second demo video](docs/assets/session-peer-live-codex-claude.mp4).
A successful post confirms only the inbox write. The explicit reply at the end
confirms that the receiving session consumed the request and responded.

## Quick start

Python 3.9+. The core CLI has no third-party Python dependencies.

```bash
pipx install session-peer
# Alternative: uv tool install session-peer

session-peer list
session-peer list --host worker
```

## Send your first message

The names and UUID below are fictional examples. Discover your destination first,
then replace them with a session from its listing.

```bash
session-peer send --to api-worker --message "Report progress"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "Review the change"
```

Replace `worker` with your SSH host or alias, `api-worker` with a discovered
session name, and the example UUID with the full ID from the destination's listing.
The destination needs Python and the target agent's inbox or queue;
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

Install the runtime with `pipx` or `uv`, or run `python -m pip install session-peer`
in an activated virtual environment. Install the agent skill separately from its
[dedicated repository](https://github.com/abruption/session-peer-skill):

```bash
npx -y skills@latest add abruption/session-peer-skill \
  --skill session-peer --global \
  --agent claude-code --agent codex --agent antigravity \
  --copy --yes
```

For air-gapped or SSH deployment, the POSIX `./install.sh [--host worker]` path
continues to bundle a compatibility copy of the skill. On native Windows use a
Python package manager for the runtime. Optional MCP tools require Python 3.10+
and `session-peer[mcp]`. See [installation details](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#install).

## Let an AI assistant help

If you would rather describe the goal than work through every document, give your
coding agent the [AI-assisted setup and operation guide](https://github.com/abruption/session-peer/blob/main/docs/ai-assistant-guide.md).
It provides a reusable request, approval and secret-handling boundaries,
validation steps, and a completion-report format. You remain in control of
account changes, public exposure, payments, reboots, merges, releases, and
publication.

## Optional 1.0 beta features

The opt-in `1.0.0b1` prerelease advances the authenticated public relay and keeps the v0.9 experimental [Antigravity](https://github.com/abruption/session-peer/blob/main/docs/antigravity.md) bridge. Unfiltered `list` also includes live registered bridges.
[Paired devices / encrypted relay](https://github.com/abruption/session-peer/blob/main/docs/paired-devices.md) require Unix, Python 3.11+ and the `[relay]` extra. Device identities are pinned and targets need explicit authorization on the receiving endpoint. The blind WSS relay cannot decrypt application messages; hosted-service availability remains separate from the package.
Install the beta explicitly with `pipx install 'session-peer[relay]==1.0.0b1'`; normal upgrades do not select prereleases. Start with the [session-peer project page](https://abruption.dev/projects/session-peer/) and the paired-device guide above. Beta publication does not imply long-term stability. Ordinary local/SSH commands remain dependency-free.

## Before you send

- Use the correct destination account and agent home; for custom Codex homes, pass the listed `codexHome` path with `--codex-home`. SSH access and receiver permissions still apply.
- Plain sends do not activate inactive sessions. Explicit wake can start a turn and consume usage; MCP requires separate wake permission.
- Redact secrets, conversation text, session IDs, and personal paths before sharing diagnostics.

## Documentation

- [Project site](https://abruption.dev/projects/session-peer/): a curated overview, quick start, and documentation entry point.
- [Repository documentation map](https://github.com/abruption/session-peer/blob/main/docs/README.md): user, integration, operator, development, and historical references.
- [CLI reference](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md): commands, JSON, environment variables, updates, limits, and validation history.
- [Diagnostics and replies](https://github.com/abruption/session-peer/blob/main/docs/diagnostics.md) · [Multiple Codex homes](https://github.com/abruption/session-peer/blob/main/docs/multi-home-list.md)
- [Moving from cc-peer](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#moving-from-cc-peer) · [Releases](https://github.com/abruption/session-peer/releases)
- [Adapter development](https://github.com/abruption/session-peer/blob/main/docs/agent-adapters.md) · [Release process](https://github.com/abruption/session-peer/blob/main/RELEASING.md)

The README and detailed documentation are available in English, Korean, Japanese,
and Simplified Chinese. English is canonical; CI checks that translated files,
commands, requirements, and behavior stay aligned. These translations do not
change the CLI output language.

## Support and security

[GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose) for
bugs and features; [private reporting](https://github.com/abruption/session-peer/security/advisories/new)
for vulnerabilities ([security policy](https://github.com/abruption/session-peer/blob/main/SECURITY.md)).
For private questions or an alternative security contact, email
[support@abruption.dev](mailto:support@abruption.dev) with `[session-peer]` in the subject.
Support is best effort. Emails are reviewed manually and never automatically
published as issues. English and Korean reports are welcome.

[MIT license](https://github.com/abruption/session-peer/blob/main/LICENSE).
