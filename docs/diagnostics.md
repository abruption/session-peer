# Diagnostics and reply-address contract

`session-peer doctor` inspects the machine that owns the target sessions. With
`--host`, the same standard-library script runs on that host over SSH, so paths,
users, processes, sockets, and databases are evaluated in the correct security
boundary.

The command is read-only. It does not connect to a Claude inbox, submit a Codex
queue item, scan arbitrary filesystem roots, change permissions, enroll an SSH
host key, or alter agent settings.

## JSON model

Doctor uses the common response envelope. `ok` says whether the diagnostic
command ran; it does not mean every optional agent is installed or available.
Use the nested statuses for that:

```json
{
  "schemaVersion": 1,
  "ok": true,
  "host": "worker.example.ts.net",
  "command": "doctor",
  "status": "partial",
  "claude": {
    "status": "inbox_unavailable",
    "sessionsDir": "/home/alice/.claude/sessions",
    "records": 1,
    "invalidRecords": 0,
    "aliveSessions": 1,
    "availableInboxes": 0,
    "checks": [
      {"status": "warning", "code": "inbox_unavailable", "message": "..."}
    ]
  },
  "codex": {
    "status": "available",
    "selectedHome": "/home/alice/.codex",
    "homeSource": "default",
    "executable": "/home/alice/.local/bin/codex",
    "homes": [
      {
        "codexHome": "/home/alice/.codex",
        "stateDb": "/home/alice/.codex/state_5.sqlite",
        "status": "available",
        "code": "state_db_readable",
        "sessionCount": 12
      }
    ],
    "checks": []
  },
  "capabilities": {
    "replyObservation": {
      "status": "unsupported",
      "reason": "no_cross_agent_acknowledgement_api",
      "claudeLocalIdleNotice": "native_claude_only",
      "automatedWait": false
    }
  }
}
```

Top-level `status` is `healthy` when both agent transports are available,
`partial` when one is available, and `issues_found` when neither is. Agent
statuses include:

| Status | Meaning |
| --- | --- |
| `available` | Required local evidence is readable and present. Claude inbox verification is filesystem-only until a real send. |
| `unavailable` | No live usable session was found. |
| `inbox_unavailable` | A live Claude process is recorded but no inbox is available. |
| `missing_tool` | The Codex executable is not available on the destination. |
| `missing_home` | The configured sessions directory or Codex state DB is absent. |
| `wrong_home` | The configured path has the wrong file type. |
| `permission_denied` | The destination OS user cannot inspect the required path or record. |
| `unsupported` | A known file exists but its schema is not supported. |
| `unknown` | Inspection could not prove a more specific state. |

Code values are stable machine-readable reasons. Messages are for people and
may become more specific without a schema change.

## Return-route check

`doctor --host worker --check-return-route` asks `worker` to test an SSH command
back to the detected origin. `--reply-to USER@HOST` overrides that detected
address. The check uses a fixed `true` command with batch mode, password and
keyboard-interactive authentication disabled, strict host-key checking, and
host-key updates disabled. It never retries with credentials or relaxed policy.

```json
{
  "returnRoute": {
    "status": "failed",
    "transport": "ssh",
    "host": "alice@origin.example.ts.net",
    "reason": "authentication_failed",
    "sshUser": "alice",
    "sshUserSource": "explicit"
  }
}
```

Return status is `verified` or `failed`. Failure reasons include
`return_host_unavailable`, `ssh_executable_missing`, `authentication_failed`,
`host_key_failed`, `timeout`, `transport_failed`, and `remote_command_failed`.
A return address for the current user on the current machine is normalized to a
verified local route and never starts SSH.

## Structured Reply-To

Messages now carry an inert, versioned URI followed by the legacy command:

```text
Reply-To: session-peer://v1/reply?agent=claude&session=api-worker&transport=ssh&host=alice%40origin
Reply: python3 /path/to/session_peer.py send --host alice@origin --to api-worker --no-reply-to
```

The URI can be passed as `send --to URI`. Version, field names, duplicate fields,
agent, transport, UUID, host, control characters, and conflicting CLI routing
flags are validated before discovery or dispatch. Its contents are never parsed
as shell syntax. The fields are:

| Field | Requirement |
| --- | --- |
| `agent` | Required: `claude` or `codex`. |
| `session` | Required session name/PID, or full Codex UUID. |
| `transport` | Required: `local` or `ssh`. |
| `host` | Required only for `ssh`; includes the SSH user when known. |
| `codexHome` | Optional for Codex when the sender can identify its active configured home. |

Send JSON includes `replyRoute` for the route placed in the outgoing message.
Local routes are `verified`; SSH routes are `unverified` with reason
`reverse_ssh_not_checked` until the opt-in doctor probe succeeds. When `--to`
uses a structured address, `addressResolution` records its selected transport
and any `ssh_self` normalization.

## Why there is no general wait

Claude Code documents a native one-shot `notify_when_idle` subscription for a
main Claude conversation watching another local Claude session. The same
documentation limits it to sessions on that machine and excludes subagents,
agent-team teammates, and sessions beyond that machine. Codex queue submission
also exposes no cross-agent acknowledgement through session-peer.

Consequently, a portable `--wait` would need to infer completion from mutable
transcripts. A new transcript event could belong to another request, and a
missing event could mean held input, an offline session, a changed storage
format, or an unfinished turn. session-peer reports the capability as
`unsupported` instead of returning a false acknowledgement. For completion
workflow, put the requirement and correlation token in the message and ask the
target to send a fresh message to its `Reply-To` URI.

References: [Claude Code message delivery](https://code.claude.com/docs/en/cross-session-messaging#message-delivery),
[idle notices](https://code.claude.com/docs/en/cross-session-messaging#get-a-notice-when-another-session-goes-idle),
and [the session inbox socket](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket).

## List discovery outcomes

`list` defaults to both agents; `--agent claude|codex` selects one.
The `discovery` object reports each requested agent. Claude retains `ok`/`error`;
Codex reports `ok`, `not_installed`, or `error` plus per-home diagnostics.
Failures preserve successful rows but set `ok=false`, a top-level error summary,
and exit code 1. No automatic Codex installation is `not_installed`, an empty
result with exit code 0. Missing explicitly configured homes remain errors.
A missing Claude session directory is an empty result; an unreadable directory
is an error. SSH preserves partial results and repeated-host envelopes.
Every row has an `agent` discriminator. See [multi-home listing](multi-home-list.md)
for candidate discovery, metadata and permission boundaries.
