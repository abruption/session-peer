---
name: Bug report
about: Something doesn't work as described
title: ''
labels: bug
---

## What happened

> This issue is public. Report vulnerabilities privately at
> https://github.com/abruption/session-peer/security/advisories/new.
> Private questions: support@abruption.dev (subject: [session-peer]).

<!-- Include a minimal reproduction, command, exit code and redacted output.
     Replace paths, hosts, addresses and session IDs with consistent placeholders.
     Do not attach tokens, private keys, pairing secrets, conversation text,
     agent homes, JSONL transcripts, SQLite databases, browser profiles or .env files. -->

```
$ session-peer ...
```

## What you expected

## Environment

- session-peer version: <!-- session-peer --version -->
- Installation method (pipx / uv / pip / standalone / other):
- Agent name and version on **both** ends:
- Python version on **both** ends:
- Connection (local / SSH / other):
- OS on both ends: <!-- e.g. macOS 26 (arm64) → Ubuntu 24.04 (arm64) -->

## Discovery output

<!-- Optional: include only relevant, redacted listing lines.
     Select the agent supported by your installed version. A saved session is
     not necessarily running; queued/posted does not prove consumption. -->

```
$ session-peer list --agent <agent> --host <target> --all
```

## Checked

- [ ] I searched existing issues.
- [ ] I removed sensitive information from the text and attachments.
- [ ] For SSH connections, I checked whether `ssh <host> true` succeeds independently.
- [ ] I checked discovery and existing inbound approval settings without weakening them.
