# #69 paired-device relay laboratory

Experimental, fixture-only code based on local #47 commit `993d04d`. **Not a
production receiver, plugin, or installed CLI command.** The ordinary package,
local/SSH behavior, and installed version are unchanged. No native Claude/Codex
sessions, inboxes, queues, model credentials or quota are used.

## Reproduce locally

Python 3.11+ and OpenSSL with TLS 1.3 are required. The exercised environments
were macOS Python 3.14/3.13 and Ubuntu arm64 Python 3.12.

```sh
python3 -m venv /tmp/session-peer-relay-lab
/tmp/session-peer-relay-lab/bin/pip install -r experiments/relay69/requirements.txt
/tmp/session-peer-relay-lab/bin/python -m unittest tests.test_relay69 -v
```

Tests use loopback TCP, real TLS, a local WebSocket relay and disposable state.
Without the optional dependencies, ordinary unittest discovery skips this module.
The experiment isn't included in wheel or sdist. No import starts a listener.

## Components and boundaries

- `identity.py`: locally generated P-256 private keys and short-lived self-signed
  certificates. Keys/state are 0600/0700, never placed in invitations or copied
  to the relay. This is filesystem protection, not a production OS keychain.
- `wire.py`: TLS 1.3/ALPN over either TCP or binary WebSocket frames using
  Python/OpenSSL MemoryBIO. The client explicitly trusts and pins the invited
  certificate. Paired receivers require a recognized client certificate before
  list/send. Unknown unauthenticated clients can only attempt one invitation
  reservation per connection. Public relay URLs require WSS; plaintext WS is
  restricted to loopback tests. HTTP and WS redirects are rejected.
- `store.py`: ten-minute, single-use invitation reservation; pending/paired/
  revoked device states; an execution journal independent of agent databases.
  Pairing commits only after mutual TLS proves the proposed key. A pending
  initiator can reconcile a lost commit response with the same key. Revocation
  closes live channels; rotation is revoke plus a new pairing, not seamless renewal.
- `relay.py`: role/room-scoped admission credentials issue 120-second HttpOnly
  session cookies. Authentication happens before upgrade. The relay only forwards
  ciphertext and holds no endpoint key. It sees routing/role, IP, time, lengths
  and ciphertext. Cloudflare/Caddy see outer TLS metadata **and admission
  credentials/cookies**, but not inner-TLS plaintext or keys. Outer authentication
  is not end-to-end identity and doesn't replace peer TLS verification.
- `app.py`: all received operations go through the #47 `LocalTransport` and one
  explicitly instantiated deterministic fixture adapter. Wire operations are
  probe/list/send/status; no arbitrary command, path, native adapter, or wake is
  available. Requests bind version, both identities, UUID, expiry, operation and
  body; the TLS channel supplies record integrity and replay protection.

The journal commits pending intent before invoking the fixture adapter. The same
peer+message ID with the same body returns the stored result; another body is
rejected. A crash between adapter invocation and result commit remains unknown
and is never automatically reexecuted. This favors at-most-once attempts over
liveness. It is **not** exactly-once native delivery. `submitted` is separate from
`consumptionConfirmed`, which remains false. `relayAttached` describes carrier
attachment; only an authenticated endpoint probe establishes receiver readiness.

An automatic route races authenticated direct and relay probes, prioritizing
direct if both complete in the same selection cycle. The message goes to one
winner only. Failure after submission does not switch routes or resend. When
checking an unknown outcome, use status with the original message ID.

## Explicit commands

Run from the worktree root with the experiment venv:

```sh
python -m experiments.relay69 init --state /private/test/receiver
python -m experiments.relay69 invite --state /private/test/receiver \
  --out /private/test/invitation.json --direct 127.0.0.1:3769
python -m experiments.relay69 serve --state /private/test/receiver \
  --bind 127.0.0.1 --port 3769 --seconds 1800
python -m experiments.relay69 pair --state /private/test/client \
  --invite /private/test/invitation.json --route direct
python -m experiments.relay69 request --state /private/test/client \
  --peer RECEIVER_FINGERPRINT --route direct --op send --message fixture-only
```

Compare the invitation's certificate fingerprint with the receiver's `init`
output through a separately trusted management path before pairing. The lab used
existing SSH for public invitation material and a private file for the one-time
secret. Never paste invitations, admission secrets or cookies into logs or URLs.
`request --op status --message ORIGINAL_MESSAGE_ID` reconciles an uncertain result.
`revoke --state RECEIVER_STATE --peer CLIENT_FINGERPRINT` revokes that test client.

For relay mode, provision two random 256-bit admission credentials outside git,
one per role. The relay `--accounts` file is a JSON array of
`{hash: SHA256(credential), room: test-room, role: receiver|client}`. Endpoints
receive only their own credential in a 0600 `--admission-file`; they never receive
the other's private TLS key. Add `--relay wss://HOST/v1/connect` to both invite and
serve, and use `pair --route relay`. Receiver and client both connect outbound.
The relay command accepts `--bind`, `--port`, `--accounts`, and `--seconds`.

The public trial used a dedicated hostname, existing CF/KR TLS termination and a
KR-to-US tailnet upstream. Public configuration is infrastructure-specific and is
not automatically provisioned by this repository. No deployed trial remains.

## Operational limits

The relay allows 10 connections, 20 HTTP admission/upgrade requests per second,
100 live cookies, 256 KiB frames, a four-frame receive watermark, 32 KiB transport
write watermark, a two-second forwarding deadline and 32 MiB total forwarded
bytes. TLS JSON messages are bounded to 64 KiB and message bodies to 32 KiB.
The receiver limits connections to eight and requests per connection to 100;
its journal stops at 10,000 records rather than silently evicting deduplication
history. These limits are test budgets, not tuned product guarantees.

The service lifetime is at most 30 minutes. The public backend also used an
independent systemd runtime limit, DynamicUser, no capabilities, read-only code,
ProtectHome, explicit forbidden directories, private tmp/devices, 256 MiB memory,
50% CPU and 64 tasks. Cgroup IP rules admitted only KR to the US backend. The
sandbox preflight asserted that other homes and product directories were
unreadable. No new firewall rule, DNS record, persistent account or global Python
package was installed. Mac fixture clients used separate state/venvs; they were
not claimed to have the Linux sandbox's OS isolation.

A real application would need stronger device lifecycle/UX, origin-bound
admission configuration, per-device quotas, offline recovery, dependency and
protocol review, and platform service/key storage design. The receipt contract
must continue distinguishing relay attachment, endpoint acceptance and native
submission. See [the measured report](REPORT.md).
