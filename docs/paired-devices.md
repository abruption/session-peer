# Paired devices and private relay (v0.9 beta)

This optional Unix/Python 3.11+ transport carries requests to operator-defined
Claude, Codex or registered Antigravity endpoints. The usual local/SSH commands
stay dependency-free. This is an explicit CLI workflow; no mobile application,
NAT traversal, WireGuard tunnel or automatic public service is installed.

## Install

Install session-peer v0.9.0 or later from PyPI in an isolated environment on both devices:

```sh
python3 -m venv ~/.local/share/session-peer-relay/venv
~/.local/share/session-peer-relay/venv/bin/pip install 'session-peer[relay]'
```

The relay extra is available on PyPI starting with v0.9.0 and remains beta;
publication does not establish long-term operational stability. Use the installed
`session-peer` executable below. Management commands (`device`/`relay`) emit JSON.
Do not mix Python environments with different package versions.

## Identity, policy and pairing

On each endpoint:

```sh
session-peer device init --state /private/device-state
```

The returned `device` is its public certificate fingerprint. Each device retains
its own private key; never copy that key to the relay or the other endpoint.
Use new private state directories (0700). Existing insecure files/directories are
rejected instead of silently chmodding user data. This database is session-peer's
own device journal; it is not a Codex conversation DB or ontology vault DB.

On the receiving machine create a 0600 policy file. Replace the client fingerprint,
agent target and home with independently discovered values. For example:

```json
{
  "targets": {
    "review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/home/alice/.codex"
    }
  },
  "peers": {
    "CLIENT-64-HEX-FINGERPRINT": {
      "capabilities": ["list", "send"],
      "targets": ["review"]
    }
  }
}
```

Claude bindings use `agent: claude` and an exact session name/PID without a home.
Antigravity bindings use `agent: antigravity`, `target: antigravity:UUID` and
`antigravityHome`; first register the TUI using [its bridge procedure](antigravity.md).
The receiver runs as the account that owns these agent sessions. Do not run the
receiver as root merely to reach another user's session.

Pairing proves possession of the device key. **It does not grant native agent
access**: the receiving policy must separately allow the fingerprint, operation
and target alias. Peers cannot supply an executable, home, wake flag, SSH destination
or arbitrary native command arguments. Policy changes take effect after restarting
the receiver. Limits: eight configured targets and 128 policy devices.

## WSL receiver for native Windows Codex

Run the receiver in WSL2 when the Codex session and CLI run natively on the same
Windows workstation. The operator policy, rather than the paired peer, fixes both
the mounted state home and executable:

```json
{
  "targets": {
    "windows-review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/mnt/c/Users/alice/.codex",
      "codexBin": "/mnt/c/Users/alice/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe",
      "codexPython": "/mnt/c/Python313/python.exe"
    }
  },
  "peers": {
    "CLIENT-64-HEX-FINGERPRINT": {
      "capabilities": ["list", "send"],
      "targets": ["windows-review"]
    }
  }
}
```

`codexHome` must be an absolute WSL path on a mounted local Windows drive and
`codexBin` must be an absolute, executable regular file named `codex.exe`.
`codexPython` is also required: select an installed native Windows Python 3.9+
interpreter named `python.exe`, not a Microsoft Store execution alias. Both
executables must be non-symlink files controlled by the operator.

The receiver uses fixed `/usr/bin/wslpath` arguments and streams its standalone
core into that native interpreter, without constructing a shell command. Native
Python reads the Windows SQLite/WAL state and verifies the native writer lock,
unique owner, same-user SID, process creation time and Codex executable identity.
It does not open that database through Linux SQLite or bypass writer checks.
Inactive, ambiguous or uninspectable writers fail closed. Existing WSL bindings
must add `codexPython`; missing or invalid interpreters are rejected with
`native_windows_python_required` or `invalid_codex_python`.

Linux/macOS targets omit both executable fields. Native Windows clients continue
to use the ordinary local CLI; this adapter is for a WSL receiver targeting
Windows Codex. Successful submission reports `consumptionConfirmed: false`;
only an independently observed reply proves consumption. Never retry an unknown
send automatically, including after a policy or receiver upgrade.

Native local CLI support does not imply support for every native Windows SSH
shell. Source-streamed SSH requires working python3 and a POSIX-compatible
remote shell; a Windows Store execution alias is insufficient. Use the native
CLI locally or a WSL SSH endpoint with Python installed.

Start a direct receiver (loopback by default; choose a reachable private interface
for another machine):

```sh
session-peer device serve --state /private/device-state \
  --policy /private/receiver-policy.json --bind PRIVATE-IP --port 3770 --seconds 3600
session-peer device invite --state /private/device-state \
  --direct PRIVATE-IP:3770 --out /private/invitation.json
```

Transfer the invitation through a trusted channel into a private file on the
client, then run within ten minutes:

```sh
session-peer device pair --state /private/client-state \
  --invite /private/invitation.json --route direct
```

An invitation has a one-use secret and a pinned receiver certificate. A pending
pair can reconcile a lost commit response by proving the same device key. Certificate
substitution fails. Delete invitation files after pairing; they contain a secret.
IPv6 direct addresses use `[address]:port`. Direct access requires TCP reachability;
there is no automatic router, firewall, VPN or NAT configuration.

## Provision a private relay

On a trusted administration machine:

```sh
session-peer relay provision --out /private/new-room --room personal
```

This creates `accounts.json` (admission hashes), `receiver.token`, and `client.token`.
Keep each token in a 0600 file. Only hashes are installed on the relay server.
Distribute the receiver/client admission tokens separately from private device
identity keys. Tokens control relay admission; inner pinned TLS independently
controls pairing and native access. The relay never gets endpoint private keys.

```sh
session-peer relay serve --accounts /private/accounts.json \
  --bind 127.0.0.1 --port 3769 --seconds 3600
```

For persistent Linux hosting, install the wheel into `/opt/session-peer-relay/venv`,
store hashes in `/etc/session-peer-relay/accounts.json`, and adapt the reviewed
[systemd template](../deploy/examples/static-account/session-peer-relay.service). Validate it with
`systemd-analyze verify` before enabling. The template runs with a dynamic user,
no capabilities, inaccessible homes, read-only system, private temporary directory
and explicit resource limits. It is for the **blind relay**, not the native receiver;
the latter needs its agent-owned runtime paths and sockets.

Put the loopback relay behind an HTTPS/WSS reverse proxy on a dedicated hostname:

```caddyfile
relay.example.com {
    reverse_proxy 127.0.0.1:3769
}
```

This example is not an instruction to reload an existing production Caddyfile.
Use the deployment's existing certificate/DNS policy, validate the exact diff,
check existing WebSocket users, and plan rollback. Reloads/edge updates can close
connections. No token belongs in a URL/query. Avoid header/body debug logs.
A proxy sees IP, hostname and admission metadata, while application messages and
pairing secrets remain inside endpoint TLS1.3. Do not disable outer TLS validation.

Start the receiver with `--relay wss://relay.example.com/v1/connect` and
`--admission-file /private/receiver.token`, then create an invitation with that
`--relay` URL (and optionally `--direct`). The client can pair using `--route relay`
and `--admission-file /private/client.token`. Cleartext `ws://` is restricted to
loopback for isolated testing. Receiver readiness output confirms its local listener;
`relayReadyConfirmed: false` intentionally does not claim end-to-end relay readiness.

## List, send and reconcile

```sh
session-peer list --device RECEIVER-FINGERPRINT --device-state /private/client-state \
  --relay-admission-file /private/client.token --json
session-peer send --device RECEIVER-FINGERPRINT --device-state /private/client-state \
  --relay-admission-file /private/client.token --device-route auto \
  --to review --message 'Please inspect the proposed change' --json
```

`--to` is the allowed target alias from the receiving policy, not an arbitrary native
UUID or shell command. `--agent` filters allowed list results. Device routing is
exclusive with `--host`; native-home/binary/SSH options belong in the receiving
policy and are rejected on paired requests. `--wake` and explicit SSH Reply-To are
unsupported here. The descriptive From header is retained, but no automatic paired
Reply-To route is advertised. MCP device destinations are not implemented in this
beta; its existing local/SSH policy remains unchanged.

Auto routing races authenticated readiness probes, preferring direct if both finish
together. It sends the application request on **one** chosen connection. It never
fails over and resends after an uncertain submission. Set `--device-route direct`
or `relay` to force a path. Messages are limited to 32 KiB UTF-8 after the envelope.
`--dry-run` resolves the configured native target without native submission.

`submitted`/`queued` remains distinct from consumption. `consumptionConfirmed` is
always false; a model ACK must be independently observed. Native operations run in
bounded subprocesses so they cannot block admission/revocation. A durable request
intent is committed before the native effect. Same request ID and canonical target
binding/body returns its recorded outcome; changing the target/body conflicts.

Use `--request-id UUID` to preserve an attempt identifier. After a lost response,
query the original ID instead of generating a new one:

```sh
session-peer device status --state /private/client-state --peer RECEIVER-FINGERPRINT \
  --request-id ORIGINAL-UUID --admission-file /private/client.token
```

`unknown` (including receiver/worker crash) never permits automatic reexecution.
This is at-most-once execution attempts, not exactly-once consumption. The journal
caps at 10,000 requests and refuses further new submissions when full. Do not delete
pending entries or clear the journal to retry unknowns. Retention/rotation and
long-running fleet management remain RC hardening work.

## Revoke, restart and recover

```sh
session-peer device peers --state /private/device-state
session-peer device revoke --state /private/device-state --peer CLIENT-FINGERPRINT
```

Revocation prevents new authorized work and closes tracked channels. A native call
already accepted may finish; reconcile its ID. Receiver restart preserves identity,
pairing and journal. Relay restart drops connections; endpoints reconnect and acquire
fresh admission. Readiness probes must succeed before a new submission. Relay tickets
are short-lived and single-use; connections and frames are bounded. There is no queue
of plaintext/offline native requests on the relay.

Default foreground service lifetime is one hour; `--seconds 0` explicitly selects
persistent operation for a service manager. Stop with SIGTERM and wait for bounded
native shutdown before cleanup. Back up private state using a consistent SQLite
snapshot plus identity files, protect that backup, and never copy an active DB
independently of its WAL. Identity certificates last one year; expiry requires
planned new identity/re-pairing, not silently replacing a device pin.

The isolated live validation uses loopback/SSH tunnels; it does not establish VPN-off
public WSS readiness. Public pilot, restart/soak testing, and release gates are tracked
in [the active development plan](relay-development-plan.md).

### Updating a paired route

Keep the pinned identity and delivery journal when a paired device changes its
address. This replaces the saved routes; include every route you want to retain.

```sh
session-peer device routes --state ./client-state --peer RECEIVER_FINGERPRINT \
  --relay wss://relay.example.com/v1/connect
```

A route change does not authorize a new identity or revive a revoked device.
See [public pilot evidence](relay-public-pilot-2026-09-17.md) for the bounded live
Antigravity test and remaining release gates.
