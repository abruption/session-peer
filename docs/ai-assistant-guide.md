# AI-assisted setup and operation

[Back to the overview](../README.md)

This guide is concise input for a coding agent or AI assistant. It helps the
assistant choose the smallest session-peer setup, perform the work, validate the
result, and report any remaining limits. It does not grant new permissions or
turn a submitted message into proof that the receiving agent read it.

## Copy this request

Replace the bracketed values and give the whole block to the assistant. Let the
assistant inspect the current machine and repository before asking you questions.

```text
Read AGENTS.md if it exists, then read docs/ai-assistant-guide.md and every guide it links that is relevant to this goal.

Goal: [install session-peer / connect an SSH host / configure MCP / configure Antigravity / configure paired devices / diagnose a failure]
Environment: [operating system, local or remote, SSH alias if any]
Target agents: [Claude Code / Codex / Antigravity]

Work through the goal to a verified result. Reuse authorization already given in this conversation. Before account changes, OAuth consent, DNS or firewall changes, service deployment, reboot, payment, merge, release, or publication, confirm that the action is explicitly authorized. Never ask me to paste secrets into chat; use an existing credential manager or protected file. Start with read-only discovery, use dry-run where available, preserve unknown message outcomes, and do not retry a send merely to turn an unknown result into success.

At the end report: outcome, files or systems changed, commands and tests run, message acknowledgement evidence, remaining limitations, and any rollback instructions. Redact tokens, cookies, session IDs, private paths, conversation text, and private keys.
```

## Choose the smallest scope

- For sessions on the same machine or an SSH host, install only the core CLI.
- Configure an optional adapter only when the target agent requires it.
- Add MCP only when an MCP client needs session-peer tools.
- Use paired devices or the encrypted relay only when SSH is unsuitable and an
  operator accepts the additional identity, recovery, and service work.

Do not deploy a relay merely because the repository contains relay code. The
core local and SSH workflow is simpler, has fewer dependencies, and should stay
the default for ordinary use.

## Required workflow

1. Identify the operating system, Python version, installation method, current
   user, destination account, agent homes, and whether the target is local, SSH,
   MCP, or a paired device.
2. Read the relevant linked guide and inspect the installed version before
   changing files. Do not assume the default agent home when discovery reports a
   different one.
3. Run read-only discovery first. Use doctor, list, and dry-run to resolve the
   exact target and transport before sending a real message.
4. Make the smallest reversible change. Preserve existing configuration and
   record a rollback before changing a shared service or remote host.
5. Keep credentials out of commands, logs, source control, issue comments, and
   chat. Use protected files, system credential facilities, or the user's
   credential manager.
6. Validate the installed path and the actual requested transport. A local unit
   test does not prove SSH, OAuth, public WSS, or a receiving model worked.
7. Report facts with their limits. Submitted, posted, or queued is not an
   acknowledgement; request and observe an explicit reply when completion
   matters.

## Baseline commands

Prefer an isolated tool installation. On native Windows, use a Python package
manager rather than the POSIX shell installer.

```bash
python3 --version
pipx install session-peer
# Alternative: uv tool install session-peer

session-peer --version
session-peer doctor
session-peer list --output-format json
```

Resolve a target without delivering a message. Add the SSH host option only for
a remote destination.

```bash
session-peer doctor --host SSH_ALIAS
session-peer list --host SSH_ALIAS --output-format json
session-peer send --host SSH_ALIAS --to TARGET --dry-run --message "hello" --output-format json
```

After dry-run resolves one intended session, send a new message once. Do not
reuse the fictional names or identifiers from the README.

```bash
session-peer send --host SSH_ALIAS --to TARGET --message "Reply with: SESSION-PEER-ACK-UNIQUE-MARKER" --output-format json
```

## Security and approval boundaries

- Treat agent databases, inboxes, transcripts, cookies, OAuth tokens, device
  state, private keys, replay state, and credential files as private.
- Do not copy browser profiles or credentials between machines. Use the browser
  that already owns the user's authenticated session when interactive consent is
  required.
- Do not weaken host-key checks, authentication, firewall rules, browser
  integrity protection, or service sandboxing to make a test pass.
- A request to install or diagnose does not by itself authorize account changes,
  public exposure, payment, destructive cleanup, reboot, merge, tag, release, or
  package publication.
- If an action is already explicitly authorized, complete the reversible
  preparation and validation without repeatedly asking for the same permission.
- Preserve request and operation identifiers after timeouts or lost responses.
  Reconcile status instead of creating a duplicate operation.

## Completion report

The assistant should leave a short report in this shape:

```text
Outcome:
Changes:
Validation:
Acknowledgement evidence:
Remaining limitations:
Rollback:
```

Installation is complete only when the intended command runs from a clean shell.
Transport setup is complete only when the requested local, SSH, MCP, or paired
path is exercised. A relay deployment additionally needs service health,
persistent-state, restart, backup and restore checks. Never describe an excluded
or interrupted test as passed.

## Related guides

- [CLI reference](cli-reference.md)
- [Diagnostics and replies](diagnostics.md)
- [MCP setup](mcp.md)
- [Agent adapters](agent-adapters.md)
- [Antigravity](antigravity.md)
- [Wake behavior](wake.md)
- [Paired devices and encrypted relay](paired-devices.md)
- [Security policy](../SECURITY.md)
