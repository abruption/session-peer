# Codex live side-session experiment (#245)

Not installed or exposed by the canonical `session-peer` CLI. Existing package
rules exclude `experiments/`. No relay, SSH, native queue, generated runtime,
installation or policy changes are made by this prototype.

This local Unix-domain-socket adapter connects only to an existing owning
Codex app-server. It never starts/resumes/forks a target. A private socket
directory and explicit experimental flag are required. The adapter uses
WebSocket-over-Unix sockets (including Codex's owned rendezvous symlink),
requires `websockets` (tested with 17.1), and gates server version to 0.159.2.
The required absolute `--expected-home` must match the canonical `codexHome`
reported by that server before inventory or input. This metadata comparison
does not establish a server generation, atomic storage identity or side-UI lifetime.
`list` reports loaded
ephemeral threads as **unclassified**, not necessarily `/btw` conversations.
For a real `/btw` test, establish its origin separately using the dedicated TUI.

Malformed RPC envelopes, error fields, deeply nested JSON and invalid discovery
metadata are rejected with fixed diagnostics. Once `turn/start` has been
attempted, an invalid response is `unknown`, with no automatic retry. An ordinary
connection-close error preserves an already validated submission or the original
unknown outcome; it does not establish non-submission. These boundaries are
covered by offline fake-transport tests, not a new native-version acceptance run.

Example (dummy paths/UUID):

```sh
python3 experiments/codex_side_session/side_session.py \
  --experimental-side-session --socket /private-test/app.sock \
  --expected-home /private-test/home list
python3 experiments/codex_side_session/side_session.py \
  --experimental-side-session --socket /private-test/app.sock \
  --expected-home /private-test/home send \
  --to codex:00000000-0000-4000-8000-000000000001 \
  --exclusive-test-session --dry-run --message 'test input'
```

## Critical limitation

**Use only a dedicated test session with a single input producer.** Codex
0.159.2 `turn/start` calls `start_or_steer_turn`; an idle preflight is not an
atomic idle-only guard. Concurrent input can turn a intended new turn into
steering. `--exclusive-test-session` acknowledges this restriction; it does
not enforce exclusivity against other native clients. General use remains
blocked until safe native semantics or a cooperating owner can enforce it.

**Loaded is not UI-open.** After the native TUI dismisses `/btw`, app-server
may retain the ephemeral thread as loaded and idle during its unload grace
period. The live test reproduced this: a dry-run remained validated after the
side UI closed. No further input was sent. A future integration needs an
owner-provided active registration/generation, not merely a loaded-ID check.

No automatic steering, retries, parent fallback, approval responses, permission
overrides, or persistence of a side transcript. Acceptance is not ACK. The
dedicated live test may read its own TUI output to verify an exact response,
but this does not implement general wait/completion detection.

## Review-ready experiment scope

The offline suite runs explicitly in the Linux/macOS Python 3.13 CI jobs. It
uses fake filesystem and RPC responses, including private-endpoint, server-home,
version, approval-request and idle/start rejection cases. It never launches Codex
or sends a model request. The historical native evidence in `RESULTS.md` predates
the required home comparison and is not a rerun of the current adapter.

Ready for code review means this bounded experiment can be reviewed with those
limitations visible. General `/btw` support still requires the atomic submission
and owner-lifecycle contracts described above; issue #245 remains open.

Source review: session-peer base 90489fc; Codex CLI 0.159.2/upstream ff6aec9.
See [RESULTS.md](RESULTS.md) for actual roundtrip evidence and unmet gates.

Unit tests:

```sh
python3 -m unittest discover -s experiments/codex_side_session -v
```
