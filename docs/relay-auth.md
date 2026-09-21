# Private relay control and authentication (RC candidate)

Status: implementation candidate for #69, not a deployed production service.
The control-to-relay contract below incorporates the Python owner's final
interface instruction; actual cross-service integration remains a separate gate. This project adds no listeners,
OAuth accounts, or Node dependency to a normal Python installation.

## Trust boundaries

`control/` is an independent Node 22/24 React/Vite + BetterAuth **1.7.5** service.
GitHub and Google are the only configured login providers. Missing provider
credentials expose no fake login. Password login/signup are disabled. OAuth
account IDs, not email addresses, are the authorization identity. Every control
API call checks the native BetterAuth session, an explicit allowlist or committed
public-signup record, and internal user ID ownership again. Pausing signup does
not evict an already committed public identity.
No automatic email-based account linking is permitted. Enabling another provider
with the same email does not silently give it an existing user's devices.

Allowlist-only operation remains the fail-closed default. Operators may explicitly
enable unrestricted verified public signup. Verified provider callbacks reserve
their identity before BetterAuth creates a user; committed identities remain usable
if the operator later closes new signup. Account and session creation
are also checked by BetterAuth DB hooks. A rejected callback cannot consume a
permanent public slot or grant control access.

Web `/login`, `/device`, `/devices` use HTTP-only secure cookies in production.
The device page displays the code, client and scope, requires a code-match
confirmation and explicit approve/deny, and warns against unexpected requests.
The additional control claim table binds a verified code to the **exact browser
session**, not just the user. BetterAuth's own first-party claim is user-bound;
this wrapper supplies the narrower session restriction.

CLI login uses BetterAuth `deviceAuthorization()` and `bearer()`:

- `POST /api/auth/device/code`, `client_id=session-peer-cli`.
- Open the supplied verification URI; authenticate and check/approve the code.
- Poll `POST /api/auth/device/token` at the advertised interval (5 seconds).
  The grant is `urn:ietf:params:oauth:grant-type:device_code`.
- `access_token` is a **first-party BetterAuth session token**, not an OAuth
  provider access token, an OAuth-protected resource token, or a relay JWT.
- Send it only to this configured control origin as `Authorization: Bearer …`.
  Tokens expire with the BetterAuth session (24 hours); no refresh-token or
  perpetual background sign-in promise is added here. OS credential storage and
  CLI UX are the Python/client owner's integration responsibility.
- Only the browser cookie session may verify/approve/deny; bearer approval is
  rejected. The device code lifetime is 5 minutes; denial, expiry, polling limits
  and one-time redemption use the pinned BetterAuth implementation.

OAuth callbacks (operator app configuration required):

```
https://relay.abruption.dev/api/auth/callback/github
https://relay.abruption.dev/api/auth/callback/google
```

## Final control API (unreleased candidate)

JSON bodies only; 16 KiB maximum. Unknown protocol fields are rejected.
Authenticated API requests are limited to 60/user/minute. Limits are 16 active
challenges, 32 total device identities including tombstones, and 4096 durable
operations per owner. Operation records are never silently deleted to make space;
the limit fails closed, including pending operations.

| Endpoint | Result / checks |
| --- | --- |
| `GET /api/relay/devices` | Only caller-owned devices; no certificates/secrets |
| `POST /api/relay/challenge` | `{operation: "register" | "admission", payload}`; owner/operation/full-payload bound nonce, 60-second window |
| `POST /api/relay/devices` | Initial registration or key renewal; payload + `challengeId`, new-key `proof`, old-key `previousKeyProof` for renewal |
| `GET /api/relay/operations/:id` | Owner-only pending/committed result, for lost-response reconciliation |
| `POST /api/relay/admission` | Admission payload + `challengeId`, `proof`; short-lived ES256 relay JWT |
| `POST /api/relay/devices/:principal/revoke` | Owner session; no lost-device key requirement; permanent tombstone |

### Registration and certificate renewal

```text
{ principal, certificatePEM, keyGeneration, name, operationId, expectedGeneration }
```

`principal` is a fixed random 64-character lowercase hex device identity, separate
from the certificate. `operationId` is a UUID v4 retained until the result is
known. Initial registration requires a principal equal to the initial certificate DER
SHA256, an absent device, `keyGeneration=0`,
and omission of `expectedGeneration`. Renewal requires the existing active same-owner principal,
`expectedGeneration=current generation` and `keyGeneration=expectedGeneration+1`.
The server computes/checks the increment; clients cannot choose a jump or rollback.
Maximum generation is 2147483647. Owner, principal and existing name are preserved
on renewal; `name` is used for initial registration (send the existing name when
renewing). Names are 1–80 characters with no control characters.

Certificate input is exactly one public PEM certificate, <=8192 bytes, with a
P-256 key and current validity extending beyond 60 seconds. New certificates
must differ from the stored certificate. Same-key certificate renewal is allowed.
Possession is established by signature, not public-CA verification; registration
never replaces endpoint E2EE pairing/pin authorization. Never submit a private key.

Both initial registration and renewal use challenge operation **register**, then
`POST /api/relay/devices`. New-key `proof` signs the exact returned `proofMessage`.
Renewal additionally requires old-key `previousKeyProof` over the **same message**.
No login-only replacement is allowed. Only possession of the stored old key ignores
old certificate validity dates, permitting renewal of an expired certificate;
new certificate validity and ordinary admission validity remain enforced. A lost
old key requires owner revocation and a new principal. Revoked identities never
revive via registration, renewal or retries.

Mutation, challenge consumption and committed receipt are one SQLite transaction.
Renewal invalidates outstanding owner challenges, republishes state immediately,
and rejects admission signing that spans a generation change.

### Operation result / retry boundaries

A registration challenge durably reserves owner/operationId/payload digest before
returning. Owner lookup before mutation returns:

```json
{ "operationId": "<fixed UUID v4>", "committed": false }
```

Completed registration and `GET /api/relay/operations/:id` return:

```json
{
  "operationId": "<fixed UUID v4>",
  "committed": true,
  "principal": "<unchanged ID>",
  "keyFingerprint": "<SHA256 certificate DER>",
  "keyGeneration": 1
}
```

Unknown IDs and another owner's IDs both return 404. Pending reservations persist
after challenge expiry. Identical completed owner/payload/operationId retries
return the stored historical receipt without another mutation or proof execution,
even if the challenge expired or the device was later revoked. Changed-payload
or different-owner operationId reuse is rejected. A receipt is **not current device
status**; use the device list for current generation/revocation. A revoked receipt
retry cannot resurrect a device. Publication failure rolls back the mutation and
leaves its operation uncommitted, while health blocks admission until publication
recovers. Retain the ID and query status on lost responses; do not create a new
operation or automatically retry a potentially accepted native agent submission.

### Challenge proof and time units

Response: `{challengeId, nonce, issuedAt, expiresAt, proofMessage}`. All control
API and public-state `issuedAt`/`expiresAt` values are UNIX **seconds** numbers.
BetterAuth's native auth API retains its installed SDK shape; `expires_in` and
`interval` are relative seconds. Clients sign the exact returned UTF-8 message
with P-256 ECDSA/SHA256, DER signature encoded as unpadded base64url:

```text
session-peer-control-v1:
<origin>
<operation>
<challengeId>
<nonce>
<SHA256 of server-canonical payload JSON>
```

Clients require the `session-peer-control-v1:` prefix, then sign the exact
returned string without parsing/rebuilding the remainder. No final newline. Server canonicalization binds every registration field,
including operationId/expectedGeneration; clients need no JSON canonicalization.
Admission proof uses the registered certificate's current key. Register proof
uses the submitted certificate; renewal's previousKeyProof uses the stored old key.

`keyFingerprint` is lowercase **SHA256(certificate DER)**, matching the existing
Python fingerprint/keyId meaning. `cnf.jwk` is extracted from that certificate's
public key. It is **not SHA256(SPKI DER)**. JWK alone cannot reconstruct certificate
DER; the relay compares the signed certificate fingerprint with current state and
trusts the authenticated control issuer's signed binding to cnf, then verifies
possession using cnf. Do not compute a JWK/SPKI hash and compare it to this field.
Signing `kid` identifies the separate control signing key (currently SPKI hash);
it is not the device certificate fingerprint.

### Admission token and relay exchange

Admission payload:

```text
{ role: "client" | "receiver", devicePrincipal, receiverPrincipal }
```

Both principals must be active and owned by the same internal user ID; receiver
role must identify itself. Room = SHA256(UTF8(userId + NUL + receiverPrincipal)),
without a domain prefix. Callers cannot set room/user/issuer/audience/TTL.

JWT uses **ES256**, recognized signing `kid`, `typ=JWT`. Claims are `iss`/`aud` =
configured relay origin, `sub` = internal opaque user ID, `devicePrincipal`,
`receiverPrincipal`, `keyFingerprint`, `keyGeneration`, `role`, `room`, `iat`,
`exp` (iat+60 seconds), `jti`, `cnf.jwk` (public EC P-256 only, no private material).
Response `{token, expiresAt, room}` uses UNIX-second expiry. Neither provider
access tokens nor first-party session tokens go to the Python relay.

Relay exchange:

```http
Authorization: Bearer <JWT>
X-Session-Peer-Proof: <unpadded base64url DER ECDSA signature>
```

The device signs exact UTF-8 `session-peer-admission-v1:` + the **whole JWT**, with
P-256 ECDSA/SHA256 and no final newline. This is separate from the control nonce
proof. Python must verify signature/issuer/audience/time/lifetime<=60/recognizedkid,
public P256 cnf, current state/owner/generation/fingerprint/role/receiver/room and
possession before atomic single-use jti consumption and cookie issuance. Failed
proof must not burn another device's jti. Replay storage must be verified across
restart/multiple workers through JWT expiration. These are Python integration gates;
control format tests do not establish that the Python receiver implements them.
OAuth login/registration does not replace endpoint E2EE pairing/pin policy.

## Operator metrics

`GET /api/admin/metrics` is a browser-session-only operator endpoint. An
operator is an authenticated user with at least one provider identity explicitly
listed in `SESSION_PEER_ALLOWED_ACCOUNTS`; public signup never grants this role.
The response contains aggregate service health, signup status and counts, device counts,
operation counts and the current public-state revision. It never returns email,
provider account ID, internal user ID, device principal, certificate, token or
secret. The React route is `/admin/metrics` and refreshes the aggregate view every
30 seconds.

`admin.abruption.dev` remains the existing Authelia administration portal. Its
root and `/api/*` routes are already owned by the authentication console. Integrate
session-peer with the exact `/session-peer` portal page and protect both that page
and `/session-peer/api/metrics` with Authelia. The aggregate API is served on a
separate `127.0.0.1:3771` listener and must never be routed through the public
relay host. This makes Authelia the sole browser login while keeping the public
relay from trusting forwarded identity headers. The original relay
`/admin/metrics` route and `/api/admin/metrics` retain their provider-operator
authorization for direct relay access. The Authelia portal can request bounded
drill-down lists for users, public signups, devices and operations. Those lists
may include names, email addresses, providers, operation IDs, status, generation
and shortened principal hints. They never include provider account IDs, internal
user IDs, full principals, tokens, cookies, proofs, request hashes, certificates
or keys, and each response is limited to 100 rows.

### Atomic public state and contract transition

```text
{ schemaVersion: 1, revision, issuer, audience, issuedAt, expiresAt,
  jwks: { keys: [public signing JWK with kid/alg/use] },
  devices: { principal: { userId, keyFingerprint, generation, revoked } } }
```

No names, emails, certificates, session/OAuth tokens or private keys. User IDs are
pseudonymous ownership metadata. No public HTTP route serves the directory.
Read-only **directory bind**, not a single-file bind, exposes atomic replacements
without granting access to private DB/signing key/ontology/other service files.
Do not broaden a DynamicUser parent directory to expose private siblings.

Every publication durably reserves a new safe-integer `revision` in the control
SQLite database before any device mutation transaction or file replacement.
Reservations survive mutation rollback; gaps are allowed, reuse is not. SQLite
uses WAL with synchronous FULL. Startup refuses a counter older than the existing
public file. Python additionally persists its highest revision and content hash.
A complete host rollback still needs external recovery fencing; waiting for a
restored counter to catch up must never be used to revive revoked devices.

The public directory is explicitly 0755, even under umask 0077. Each new state
file is fchmod 0644 before fsync/rename/directory fsync; its private parent and
private database/signing material remain protected. Directory bind mounts see
atomic file replacement without a directory replacement.

State republishes every **60 seconds**, expires at **issuedAt+180 seconds**, and
publishes immediately on mutation. Python fails closed for missing/malformed/
expired state or issuedAt>now+5 seconds. It rereads every admission and rechecks
existing connections every second, closing revoked/rotated sessions. JWT TTL
alone is not active-session revocation. Actual connection/clock/restart behavior
requires Python/staging verification. Publication failures roll back DB mutations
and mark health failed; SQLite and a file are not a distributed atomic transaction.
A publication followed by DB commit failure can temporarily deny access; never
report that failed operation as success or bypass stale-state checks.

The final contract supersedes unpublished candidates 55ff3bb/6815e1e/fae9029
(SPKI device hash, millisecond challenges, distinct-domain rotate endpoint, 2s/10s
state). Do not mix old artifacts/clients with this verifier. Startup refuses stored
SPKI device rows with `contract_migration_required`; it never silently reinterprets
old device fingerprints or operation history. A registration schema marker also
refuses older populated candidate databases without renumbering generations or
discarding receipts. Use a new isolated candidate state
or plan an explicit operator-reviewed migration preserving old state. No automatic
credential/device-state deletion is performed here.

## Build, secrets and operation

From `control/`:

```
npm ci
npm run typecheck
npm test
npm run build
```

Production must explicitly configure one HTTPS origin (no wildcard trusted
origins), a >=32-character random BetterAuth secret, an optional break-glass
provider account-ID allowlist, an explicit public-signup switch and the enabled
operator-owned OAuth apps. Example **non-secret** values:

```
NODE_ENV=production
SESSION_PEER_CONTROL_ORIGIN=https://relay.abruption.dev
SESSION_PEER_ALLOWED_ACCOUNTS=[{"provider":"github","accountId":"REPLACE_WITH_NUMERIC_PROVIDER_ID"}]
SESSION_PEER_PUBLIC_SIGNUP=true
SESSION_PEER_CONTROL_DATA=/var/lib/session-peer-control/private
SESSION_PEER_RELAY_PUBLIC=/var/lib/session-peer-control/relay-public
GITHUB_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
GOOGLE_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
```

Missing allowlist defaults to deny all unless the operator explicitly sets
`SESSION_PEER_PUBLIC_SIGNUP=true`. Public signup has no invitation list or user
count cap. Setting it back to `false` closes new registration while previously
committed public identities and explicit allowlist entries remain usable.
Provider verification creates a pending identity reservation for at most ten
minutes, and a SQLite `IMMEDIATE` transaction prevents concurrent callbacks from
racing the same identity. OAuth secrets and the BetterAuth secret
come from `*_SECRET_FILE`/`BETTER_AUTH_SECRET_FILE` and systemd LoadCredential;
never commit them or copy browser credentials. Raw env values are also supported
for operator-controlled local/test environments; never print environment dumps.
For enabled GitHub/Google providers add LoadCredential entries and corresponding
`GITHUB_CLIENT_SECRET_FILE`/`GOOGLE_CLIENT_SECRET_FILE` paths in the deployment
override. Missing half-configured credentials refuse startup. Disabled providers
must have neither client ID nor secret file configured.

Use the same protected config when running `npm run db:migrate`, then run
`npm start`. Migration is explicit; production does not silently rewrite the
auth schema on every startup. Local development permits HTTP only on localhost
or 127.0.0.1 and must not use production secrets. State must be outside source and
outside iCloud. The private signing key is generated once, mode0600, and survives
restart. All private DB/state parents are owner-only; backups must include the
control SQLite consistent snapshot, signing key and OAuth policy as separate
protected resources. This is **not** the central ontology SQLite.

`deploy/examples/authenticated-control/session-peer-control.service` is an installation template, not an enabled
unit: loopback3770, DynamicUser, exclusive flock writer lock, private persistent
state, protected homes/system/kernel, an isolated `/opt` mount exposing only its
read-only control tree, inaccessible other-service data/config/log paths, no
capabilities, 256MiB/50% CPU/64 tasks.
Deployment must provide supported Node at `/usr/bin/node`, install the built
control tree, migrate auth schema in the service's private state and set provider
credentials/policy. The launch lock prevents simultaneous systemd control writers;
manual launches must use the same lock. Check lock ownership/state paths during
installation. Node memory/runtime behavior still needs staging observation.

Caddy integration should split `/api/control/*`, `/api/auth/*`, `/api/relay/*` and
web pages/assets to3770 from the existing Python relay websocket/admission paths.
Do not reload Caddy or open the hostname until integrated artifacts and resource
isolation have been reviewed with the staging owner. Unknown paths return404;
`.env` and source/state files are not static assets. Security headers include
no-store, strict CSP, anti-framing and no-referrer. The HTTP server trusts neither
X-Forwarded-Host nor arbitrary Host values. Proxy must preserve the configured
origin Host. The server overwrites its auth IP header from the loopback socket; untrusted
X-Forwarded-For cannot evade the auth limiter. This conservative candidate shares
auth endpoint limits across the local proxy, so multi-user capacity still needs
staging measurement. Multiple Set-Cookie headers are preserved separately.
No request URL/headers/body/token logging is enabled; diagnostic
messages contain only fixed operational error codes.

## Verification boundaries

Local tests use real BetterAuth/SQLite/device-code endpoints, generated fixture
P-256 certificates and crypto, plus the compiled HTTP server on loopback. Auth
fixtures seed test users/accounts/sessions in a private temporary control DB.
Separate callback tests mock only outbound GitHub/Google transport, with fixture
credentials and signed fixture Google tokens; they run the pinned native OAuth
state/PKCE/callback/allowlist/account-linking paths. No provider request is sent.
There is **no production fake OAuth endpoint or auth bypass**. OpenSSL is test-only.
Tests cover owner isolation, policy revocation, CSRF, exact browser-session claim,
code approval/denial/expiry/redemption, challenge expiry/replay/alteration, key
replacement denial, dual-key rotation, generation races, same-message previousKeyProof, owner-only durable operation
lookup/pending/committed/reopened-DB retry,
expired-certificate renewal, revoked tombstones, atomic state publication failure
and non-secret state,
loopback/static/Host/body-limit behavior, rejected forged Google ID tokens and
unallowlisted/same-email different provider identities. These are not credentialed provider
OAuth, Mac user-browser, Python JWT integration, 24h operating or real Claude
quota-recovery tests. Record each of those separately before RC PR. No merge,
release tag, publication or remote push is authorized by this implementation.

Official references (implementation verified against installed 1.7.5 source):
- https://better-auth.com/docs/plugins/device-authorization
- https://better-auth.com/docs/plugins/bearer
- https://better-auth.com/docs/concepts/users-accounts

## Registration examples

These abbreviated shapes are illustrative. Obtain a fresh challenge and sign its
exact returned `proofMessage`; certificate, signature and challenge placeholders
are not runnable credentials.

Initial challenge payload (`operation: "register"`):

```json
{
  "principal": "<initial certificate DER SHA256>",
  "certificatePEM": "<device certificate>",
  "keyGeneration": 0,
  "name": "laptop",
  "operationId": "11111111-1111-4111-8111-111111111111"
}
```

Send that payload plus `challengeId` and new-key `proof` to
`POST /api/relay/devices`. To rotate for the first time, keep the same principal,
set `expectedGeneration: 0` and `keyGeneration: 1`, supply the replacement
certificate and a new, stable rotation operation UUID. Add `previousKeyProof`
from the old key over the same challenge message. Preserve that operation ID
through uncertain responses and query its owner-only historical receipt with
`GET /api/relay/operations/<operationId>`.

Initial registration must omit `expectedGeneration`; it is required for rotation.
Do not infer or silently convert the generation used by older candidates.
The executable Node/Python fixture in `tests/test_control_integration.py` covers
registration, admission, revoked credentials, cross-owner rejection and rotation
with response loss. Seeded fixture sessions are not evidence of actual OAuth.
