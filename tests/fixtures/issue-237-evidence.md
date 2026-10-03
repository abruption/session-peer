# Issue 237: native message argv evidence

Recorded on 2026-10-03, macOS arm64. These parser checks used synthetic data,
an empty temporary home, and an environment without authentication/session
variables. No message was delivered or queued, and no model or real language
server was used.

## Antigravity 1.2.12

`agy agentapi send-message --help` documents
`[--title=<title>] <recipient_id> <content>` but does not document the delimiter.
An empty-home invocation alone reports `ANTIGRAVITY_LS_ADDRESS is not set`
before argument validation, so that result does **not** prove the argv contract.

The opt-in [native wire probe](agy_wire_probe.py) starts a bounded loopback
HTTP/2 stub, captures the actual native CLI's protobuf request, and closes the
connection without a response. Its recipient is the fixed syntactically invalid
`syntactically-invalid-session-peer-probe`; its environment contains only HOME,
PATH, and the stub's loopback address. It reads no credentials. It is not part
of default test discovery.

Run explicitly with an installed native executable and the appropriate scratch
root for the current workspace:

```sh
python tests/fixtures/agy_wire_probe.py \
  --agy-bin /absolute/path/to/agy --scratch-root /approved/temporary/root
```

Native argv:

```text
agy agentapi send-message --title=session-peer -- syntactically-invalid-session-peer-probe BODY
```

The actual captured fields were:

| BODY | Protobuf field 1 | Protobuf field 2 | Protobuf field 5 |
| --- | --- | --- | --- |
| `hello` | `hello` | invalid recipient above | `session-peer` |
| `-x` | `-x` | invalid recipient above | `session-peer` |
| `--help` | `--help` | invalid recipient above | `session-peer` |
| `- item` | `- item` | invalid recipient above | `session-peer` |
| `--` | `--` | invalid recipient above | `session-peer` |
| `- first\n-- second\n한국어` | exact multiline body | invalid recipient above | `session-peer` |

Ordinary `hello` without the delimiter produced the identical three fields.
Each native invocation exited 1 with empty stderr and this stdout:

```json
{
  "response": {},
  "error": "rpc error: code = Unavailable desc = error reading from server: EOF"
}
```

This verifies actual parser recipient/body/title mapping on 1.2.12, including
ordinary messages. It does not establish live delivery or other native versions.

## Codex 0.159.2

The installed native CLI was run with empty temporary HOME and CODEX_HOME,
without inherited credential/session environment variables, and the nonexistent
UUID `00000000-0000-0000-0000-000000000000`:

```text
codex queue --thread 00000000-0000-0000-0000-000000000000 --message=BODY
```

| BODY | Original `--message BODY` | Fixed `--message=BODY` |
| --- | --- | --- |
| `-x` | exit 2, unexpected argument `-x` | exit 1, no rollout found |
| `--help` | exit 2, message value required | exit 1, no rollout found |
| `- item` | exit 2, unexpected argument `- ` | exit 1, no rollout found |
| `--` | exit 2, message value required | exit 1, no rollout found |
| `- first\n-- second\n한국어` | exit 2, unexpected argument `- ` | exit 1, no rollout found |

All fixed invocations produced empty stdout and this stderr:

```text
Error: failed to queue session message: thread/queue/add failed: failed to read thread: invalid thread-store request: no rollout found for thread id 00000000-0000-0000-0000-000000000000 (code -32603)
```

The synthetic queue database's `queued_items` count was 0. This establishes
parser acceptance on 0.159.2; live queue consumption and older versions were
not exercised. All temporary probe state was disposable.

## Windows native relay

Offline tests pass the relay-produced argv through session-peer's actual
argparse for resolve and send. Existing 32 KiB UTF-8 and NUL validation remain.
Full Windows command length is additionally checked before native launch with
`subprocess.list2cmdline`, counting UTF-16 units plus the terminating NUL against
32,767. ASCII, quoting/backslash expansion, Unicode executable paths, and
multibyte message boundaries are covered. Oversized commands return structured
`status: refused`, `submitted: false`, and
`reason: native_windows_command_too_long` before starting a process.

Native Windows/WSL execution and delivery have not been exercised. The length
guard is conservative; Python's standard Windows serialization is used to
bound the complete invocation, including the interpreter and every option.
