# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![PyPI downloads per week](https://api.pepy.tech/badge/session-peer/week)](https://pepy.tech/projects/session-peer)
[![PyPI downloads per month](https://api.pepy.tech/badge/session-peer/month)](https://pepy.tech/projects/session-peer)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

**English** · [한국어](https://github.com/abruption/session-peer/blob/main/README.ko.md) · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · [简体中文](https://github.com/abruption/session-peer/blob/main/README.zh-CN.md)

**Find and message Claude Code and Codex sessions from one CLI, locally or over SSH.**

Ask another session to review a change, report progress, or pick up a task.
session-peer uses native agent inboxes and queues; the receiving agent decides how to respond.

<a id="see-it-in-action"></a>

## Demo

![Codex sends a request to Claude Code and receives an explicit ACK](https://raw.githubusercontent.com/abruption/session-peer/main/docs/assets/session-peer-live-codex-claude.gif)

A real local request and reply using session-peer 1.0.2: Codex contacts Claude Code
and receives `ACK DEMO-READY`. CLI and message excerpts are anonymized and re-rendered
in this ~22-second animation, not a screen recording; send success alone is not an ACK.

## Quick Start

<a id="installation-options"></a>

### Install

Python 3.9+. The core local/SSH CLI has no third-party Python dependencies.
Current stable release: **1.0.3**.

```bash
pipx install session-peer
session-peer --version
session-peer list
```

Use `uv tool install session-peer` instead if you prefer uv. Native Windows,
virtual-environment pip, and standalone/SSH installation variants are in the
[installation guide](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#install).

For SSH discovery, replace the example host `worker` with your host or alias.
Then replace the fictional session name and full UUID with the listed destination:

```bash
session-peer list --host worker
session-peer send --to api-worker --message "Report progress"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "Review the change"
```

The SSH destination needs Python and the target agent's native inbox or queue,
but not an installed session-peer CLI. For a custom Codex home, pass the listed
`codexHome` with `--codex-home`; use `--dry-run` to validate without sending.
Use the destination account that owns the session (`--host USER@HOST`).
SSH access and receiver permissions still apply.

**`posted` / `queued` confirms submission, not consumption, ACK, or completion.**
Ask for an explicit reply when needed. Ordinary sends refuse inactive Codex destinations
by default and do not start them. Never automatically retry an uncertain send.

The optional [agent skill](https://github.com/abruption/session-peer-skill) is installed separately
from the runtime; see the installation guide for its Skills CLI command.

### Update

Use the same manager that installed the runtime:

```bash
pipx upgrade session-peer
# or: uv tool upgrade session-peer
# or, in its virtual environment: python -m pip install --upgrade session-peer
```

For local installations, `session-peer update` replaces standalone runtime files;
package-managed installs receive upgrade guidance instead. It never updates agent skills:
use their original installer (Skills CLI, or `install.sh` for its bundled copy).
See [update details and remote limitations](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#updating).

<a id="documentation"></a>

## Docs

- [Documentation map](https://github.com/abruption/session-peer/blob/main/docs/README.md): user, integration, operator, and development guides.
- [CLI reference](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md): options, JSON, installation variants, and migration.
- [Diagnostics and replies](https://github.com/abruption/session-peer/blob/main/docs/diagnostics.md) · [Multiple Codex homes](https://github.com/abruption/session-peer/blob/main/docs/multi-home-list.md).
- [AI-assisted setup](https://github.com/abruption/session-peer/blob/main/docs/ai-assistant-guide.md) · [Project site](https://abruption.dev/projects/session-peer/) · [Release notes](https://github.com/abruption/session-peer/releases).
- [Release process](https://github.com/abruption/session-peer/blob/main/RELEASING.md).

[Paired devices / encrypted Relay](https://github.com/abruption/session-peer/blob/main/docs/paired-devices.md)
require Unix, Python 3.11+, and `session-peer[relay]`, with pinned identities and
explicit receiver policy. Package publication does not guarantee hosted-service availability.
The blind Relay cannot decrypt application message content.
[MCP / Codex plugin](https://github.com/abruption/session-peer/blob/main/docs/mcp.md) requires Python 3.10+
and `session-peer[mcp]`; MCP wake requires both `send` and `wake` capabilities.
[Wake](https://github.com/abruption/session-peer/blob/main/docs/wake.md) runs only when explicitly requested
and can start a turn, consume usage, and change project files.
The [Antigravity bridge](https://github.com/abruption/session-peer/blob/main/docs/antigravity.md) remains experimental.

English is canonical; Korean, Japanese, and Simplified Chinese guides are kept aligned.
Translations do not change the CLI output language.

## License

[MIT](https://github.com/abruption/session-peer/blob/main/LICENSE).

## Support and security

Use [GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose) for bugs and features.
Report vulnerabilities [privately](https://github.com/abruption/session-peer/security/advisories/new)
under the [security policy](https://github.com/abruption/session-peer/blob/main/SECURITY.md), not in public issues.
Redact secrets, conversation text, session IDs, and personal paths from shared diagnostics.

For private questions or an alternative security contact, email
[support@abruption.dev](mailto:support@abruption.dev) with `[session-peer]` in the subject.
Support is best effort, with no guaranteed response time. Emails are reviewed manually, never automatically published as issues.
English and Korean reports are welcome.
