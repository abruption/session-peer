# Relay lifecycle hardening (development)

These changes are under development for #69. They are not a published RC and
have not passed the 24-hour operating gate or live OAuth-provider verification.

## Stable devices and explicit rotation

The initial certificate fingerprint remains the logical device ID. Public key
versions have separate fingerprints and generations. Policies, routes and request
receipts stay attached to the logical ID, including across receiver key changes.
The additive SQLite migration preserves existing v0.9 identities and receipts.

Stop the device receiver and other commands using its state before rotating:

```sh
session-peer device rotate --state /private/device-state \
  --operation-id REPLACE-WITH-A-FULL-UUID --route direct
session-peer device rotation-status --state /private/device-state
```

Keep the operation ID when recovering from a lost response. Never start a fresh
rotation to resolve an unknown result. Every paired peer must have an explicitly
configured reachable receiver route and support `identity-rotation-v1`. Update
routes with the existing `device routes` command. A receiver cannot transparently
rotate its pin on an offline client; bring that client receiver online first.

Prepare proves the old key over pinned TLS and verifies a signature made by the
new key. Commit requires a new-key TLS connection. During transition, pending and
retired keys have only probe, receipt-status and rotation-reconciliation access.
An old committed key has a ten-minute recovery window and cannot submit messages.
Revocation overrides this window. New requests and conflicts cannot create a
second rotation for the same generation. Local activation occurs only after all
recorded peers commit. Failed attempts retain the same proposal and private key.

A device state lock excludes rotation/backup while ordinary commands or a receiver
hold the state. A separate receiver lock prevents two local receiver processes
from using the same state. These are local filesystem locks, not a distributed
lease: copying a live identity to a second machine is unsupported.

## Journal limits and recovery

```sh
session-peer device diagnostics --state /private/device-state
session-peer device backup --state /private/device-state \
  --policy /private/policy.json --out /private/new-snapshot
session-peer device restore --state /private/new-restored-state \
  --backup /private/new-snapshot
```

Diagnostics reports the global 10,000-request limit, remaining rows, pending
unknown outcomes, SQLite/WAL sizes and free disk space. Notice, warning and
critical thresholds are 70%, 85% and 95%. At capacity, new submissions are refused;
existing receipts and administration remain available. Receipt evidence is never
pruned to create room. Capacity reservation and receipt creation are transactional.

Backup requires an exclusive state lock and includes identity versions, policy,
a consistent SQLite snapshot and a manifest. The output is a private **unencrypted
staging directory** containing keys; use the approved encrypted backup system for
retention. Do not publish or move the directory through source control. Backing up
state does not copy keys to the relay or to the OAuth control service.

Restore creates a new directory and sets a persistent recovery marker. Existing
receipts remain queryable; a missing receipt returns unknown rather than proving
non-execution. New sends and key-rotation changes remain blocked. There is no
one-command override that clears this safeguard. Reconcile post-snapshot native
effects and revoke/fence the old identity before planning recovery. This development
implementation does not yet provide a complete lost-key recovery workflow.

## Optional control-service admission

The standalone static-token relay remains available. A control-managed relay uses:

```sh
session-peer relay serve --auth-state /run/session-peer-auth/state.json \
  --auth-issuer https://relay.example.com \
  --auth-replay-state /private/relay-state/spent-tickets.json --bind 127.0.0.1 --port 3769 --seconds 0
```

`--auth-state` and `--accounts` are mutually exclusive. The read-only state contains
verification public keys and minimal device ownership/revocation records. Endpoint
private keys, login-session tokens and OAuth provider secrets are absent.

Admission requires a short-lived ES256 ticket and a signature by the enrolled
P-256 device key. Audience, issuer, generation, owner, receiver and room are checked.
A ticket is consumed once before issuing the existing one-use WebSocket cookie.
Missing/invalid state fails closed; existing connections recheck revocation every
second. Control-service issuance and CLI browser login are being integrated in a
separate worktree. Token verification tests alone do not establish live login.

## Browser login (integration candidate)

```sh
session-peer device login --state /private/device-state --server https://relay.example.com
session-peer device enroll --state /private/device-state --name laptop --operation-id FULL-UUID
session-peer device pair --state /private/device-state --invite /private/invite.json --route relay --login
session-peer list --device DEVICE-ID --device-state /private/device-state --relay-login --output-format json
```

Headless login uses `--no-browser`: open the printed URL in a separate browser and
confirm its user code. The private device code and resulting session token are not
printed. The login is stored in the explicit device directory as a private 0600
file. Expired login requires another explicit login. Core local/SSH commands do
not start a login or contact this service.

The control service uses Better Auth with GitHub/Google, and is independently
owned under `control/`. The Python client and service API are still undergoing
cross-language integration. Provider credentials and live OAuth validation are
pending; successful unit tests must not be reported as a working public login.

For control-managed rotation add `--login` to `device rotate`. It registers the
staged public key with the control service using old/new-key proof and the stable
operation ID, then uses that new key for outer admission while completing the
independent pinned endpoint transition. Reuse the same operation ID after failure.

The relay commits spent JWT IDs before issuing cookies and preserves this small
replay file across restarts. It does not persist payloads. The control public state
refreshes every 60 seconds and expires within 180 seconds; missing, expired or
invalid state rejects admissions and closes existing managed connections.

Managed admission also limits one user to eight open relay connections and one
device to four, within the existing global ten-connection limit. Public state
carries a persistent increasing revision; the relay remembers its highest revision
and rejects rollback or conflicting content at the same revision, even after a
restart. This high-water mark is retained with the spent-ticket file and must not
be discarded during control-state recovery.
