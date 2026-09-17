# Security policy

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/abruption/session-peer/security/advisories/new)
for suspected vulnerabilities. Do not disclose them in public issues, pull
requests, or comments.

If you cannot use that form, email [support@abruption.dev](mailto:support@abruption.dev?subject=%5Bsession-peer%5D%20Security)
with `[session-peer] Security` in the subject. Email is an alternative private
contact channel, not an end-to-end encrypted submission mechanism. Start with
a redacted description; do not send live secrets or production data.

Include the affected version or commit, installation method, OS, Python and
agent versions on each endpoint; the affected command or component; required
attacker access; expected and observed behavior; impact; and a minimal
reproduction using dummy accounts, paths, sessions, and messages.

Remove tokens, passwords, private keys, pairing secrets, conversation text,
session/thread identifiers, personal paths, hostnames and addresses from
diagnostics. Use consistent placeholders where relationships matter. Do not
upload complete agent homes, SQLite databases, JSONL transcripts, browser
profiles, or `.env` files. Revoke or rotate exposed secrets through the relevant
provider; deleting a public comment alone does not invalidate them.

## Review and supported versions

Reports are reviewed manually on a best-effort basis; no response or fix
deadline is guaranteed. Reports about any version are welcome. Maintenance
focuses on the latest session-peer release; older versions and the legacy
cc-peer package do not have a guaranteed backport policy.

The maintainer will coordinate investigation and disclosure with the reporter.
Private reports and emails are not automatically converted into public issues.
English and Korean reports are welcome.

For ordinary bugs and feature requests, use the
[public issue templates](https://github.com/abruption/session-peer/issues/new/choose).
