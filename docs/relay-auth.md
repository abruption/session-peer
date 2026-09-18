# Private relay control and authentication (RC candidate)

Status: implementation candidate for #69, not a deployed production service.
The control-to-relay contract below is proposed to the Python relay owner and
must be jointly verified before integration. This project adds no listeners,
OAuth accounts, or Node dependency to a normal Python installation.

## Trust boundaries

`control/` is an independent Node 22/24 React/Vite + BetterAuth **1.7.5** service.
GitHub and Google are the only configured login providers. Missing provider
credentials expose no fake login. Password login/signup are disabled. OAuth
account IDs, not email addresses, are explicitly allowlisted. Every control API
call checks the native BetterAuth session, the allowlist, and internal user ID
ownership again; removing an account from policy blocks existing control sessions.
No automatic email-based account linking is permitted. Enabling another provider
with the same email does not silently give it an existing user's devices.

Private operation means operator-owned accounts/devices only. Adding an account
to the allowlist is an explicit operator decision; this implementation does not
open public signup. Allowed OAuth account creation and session creation are also
checked by BetterAuth DB hooks. A rejected OAuth callback may leave a user record
without a permitted account/session; such a record never grants control access.

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

## Candidate control API

JSON bodies only; 16 KiB maximum. Unknown fields are rejected in protocol payloads.
Authenticated API requests have a per-user 60/minute limit. Each user has at most
16 active challenges and 32 total device identities, including revoked tombstones.
Each owner has at most 4096 durable rotation receipts; the limit fails closed
rather than deleting records needed to reconcile ambiguous responses.
Do not retry a potentially accepted native session submission automatically.

| Endpoint | Result / checks |
| --- | --- |
| `GET /api/relay/devices` | Only caller-owned devices; no certificates/secrets |
| `POST /api/relay/challenge` | `{operation: "register" | "admission" | "rotate", payload: …}`; nonce bound to caller/operation/full payload, 60s lifetime |
| `POST /api/relay/devices` | Registration payload plus `challengeId`, `proof` |
| `POST /api/relay/admission` | Admission payload plus `challengeId`, `proof`; short-lived ES256 relay token |
| `POST /api/relay/devices/:principal/rotate` | Owner, exact generation, old/new key proofs and durable operation ID; historical receipt |
| `POST /api/relay/devices/:principal/revoke` | Owner session only; no lost-device key requirement; tombstone persists |

Registration payload:

```
{ principal, certificatePEM, keyGeneration, name }
```

`principal` is a fixed random 64-character lowercase hex identity, separate from
the key. Generation is a positive safe integer <= 2147483647. Names are 1–80
characters with no control characters. Certificate input is exactly one public
PEM certificate, <= 8192 bytes, with a P-256 key and current validity extending
beyond the admission lifetime. Possession is established by the nonce signature;
registration is **not** public-CA verification or a replacement for inner TLS
certificate pinning. Private keys are never submitted.

A repeated registration must have the same owner/generation/certificate and an
active principal. Other-owner takeover, generation rollback and key replacement
through registration are rejected. Existing principals can only renew/rotate via
the explicit dual-proof operation below. Revoked principals cannot be resurrected;
a lost old key requires owner revocation and a new principal, not a login-only
replacement. OAuth login never replaces endpoint E2EE pairing authorization.

### Certificate renewal / key rotation

Generate a UUID v4 `operationId` once and retain it with the exact payload until
its result is known. Challenge operation `rotate` binds:

```json
{
  "principal": "<existing 64 lowercase hex ID>",
  "expectedGeneration": 1,
  "newCertificatePEM": "<new public P-256 certificate>",
  "operationId": "<fixed UUID v4>"
}
```

The response also supplies `oldProofMessage` and `newProofMessage`. They are the
base `proofMessage` followed by `\nold-key` and `\nnew-key`, respectively,
without a trailing newline. Sign each **exact returned string** with the respective
old/new P-256 key (ECDSA SHA256 DER, unpadded base64url). Submit the payload plus
`challengeId`, `oldProof`, `newProof` to
`POST /api/relay/devices/:principal/rotate`; path and payload principal must match.
A browser/CLI owner session alone is insufficient. The existing device must be
active, same owner, and at the expected generation. New generation is computed by
the server as `expectedGeneration + 1`. Owner, principal and name are preserved.
The new certificate must be valid for more than 60 seconds and differ from the
stored certificate; same-key certificate renewal is allowed with both proof domains.
Only the **stored old certificate's possession check** ignores certificate dates,
so expired certificates can be renewed if the old private key remains available.
New certificates and normal admission continue to enforce validity.

Mutation, consumed challenges and receipt journal are one SQLite transaction.
Outstanding owner challenges are invalidated, public state is republished, and
admission signing that spans a generation change fails rather than returning an
old-generation token. The result is a historical receipt:

```json
{
  "operationId": "<fixed UUID v4>",
  "principal": "<unchanged ID>",
  "keyFingerprint": "<new SHA256 SPKI DER>",
  "keyGeneration": 2,
  "completed": true
}
```

An authenticated same-owner retry of the **identical payload/operationId** returns
the saved receipt even if its challenge expired or its device was subsequently
revoked. It does not reverify consumed proofs or perform a second mutation. Reuse
with a changed payload or another owner is rejected. The receipt is **not current
device status**; query `GET /api/relay/devices` for that. No retry can revive a
revoked tombstone. New rotations of revoked devices fail. Do not discard the ID
or automatically create a new operation on timeout/unknown outcome.

Python must check the current generation/fingerprint at admission and while
connections remain active. Control login/rotation does not approve a new peer
certificate pin; endpoints still apply their independent E2EE pairing/pin policy.

Admission payload:

```
{ role: "client" | "receiver", devicePrincipal, receiverPrincipal }
```

Both devices must be active and owned by the same **internal user ID**. A receiver
must identify itself. The server computes the room; callers cannot supply an
arbitrary room/user/issuer/audience/expiry. Room = SHA256 UTF-8 of
internal user ID + `\0` + receiver principal (no domain prefix).

### Device proof

Challenge response includes `{challengeId, nonce, expiresAt, proofMessage}`.
`expiresAt` is UNIX milliseconds. The client signs the **exact returned UTF-8
proofMessage**, with ECDSA P-256 / SHA-256, encoded as a DER signature in unpadded
base64url. No client JSON-canonicalization implementation is necessary.

```
session-peer-control-v1
<origin>
<operation>
<challengeId>
<nonce>
<SHA256 of server-canonical payload JSON>
```

No trailing newline. The control server compares the submitted payload with the
stored normalized JSON, checks owner/operation/expiry, verifies the signature,
and deletes the challenge transactionally. Replayed, altered or cross-user
requests fail. Register proof uses the submitted certificate; admission proof
uses the registered current certificate. Name/payload strings are data only.

`keyFingerprint` is lowercase **SHA256(SPKI DER)**. Existing Python
`identity.fingerprint()` uses certificate DER; these are different values.
Control stores a separate private `certificateFingerprint` for exact registration
matching. Python integration must agree on the SPKI meaning before using the
new claim; do not relabel an existing certificate fingerprint as a key hash.

### Admission token and state

JWT algorithm is pinned **ES256**; `kid` identifies the persisted control signing
public key. Claims: `iss` and `aud` = configured relay origin, `sub` = internal
opaque user ID, `devicePrincipal`, `receiverPrincipal`, `keyFingerprint`, `keyGeneration`, `role`,
server-computed `room`, `iat`, `exp` (60 seconds), `jti`, `cnf.jwk` (device public
P-256 key only). Neither OAuth provider tokens nor the first-party session token
are forwarded to the relay. API response includes `{token, expiresAt, room}`;
this `expiresAt` is UNIX **seconds**, consistent with JWT expiry.

The relay must independently verify algorithm/signature, issuer/audience, exact
claim shape and lifetime, JTI/proof replay protection, device key possession,
owner/generation/fingerprint/current revocation state, both members' ownership,
and room derivation before exchanging for its existing short-lived cookie.
For the Python relay's admission exchange (not the control API), send:

```http
Authorization: Bearer <JWT>
X-Session-Peer-Proof: <unpadded base64url DER ECDSA signature>
```

The device signs exact UTF-8 `session-peer-admission-v1:` + the **entire JWT**, with
P-256 ECDSA/SHA256; no final newline. This is a separate signature from the control
challenge proof. The relay checks its signature against `cnf.jwk`, which must
contain only a public EC P-256 key matching the current device SPKI fingerprint.
It validates `receiverPrincipal`/role/ownership and room derivation independently.
Pin ES256 and a recognized signing `kid`; require `exp - iat <= 60` seconds and
valid issue/expiry time bounds. Do not consume a JTI until all checks and device
proof succeed. Atomic single-use JTI consumption precedes cookie issuance and
must survive process restart/multiple workers through at least JWT expiration;
failed device proof must not burn somebody else's JTI. The Python owner must
validate those concurrency/durability gates in the actual receiver.

The agreed room derivation supersedes the unpublished 55ff3bb/6815e1e control
candidates, which used a domain prefix and omitted the receiver claim. Do not mix
those older artifacts with the new Python verifier. Control issuing a token and
its local proof-format checks do not demonstrate Python gates are implemented.
E2EE payload remains inside pinned inner TLS, not the control API.

Atomic `relay-public/state.json` contains:

```
{ schemaVersion: 1, issuer, audience, issuedAt, expiresAt,
  jwks: { keys: [public signing JWK with kid/alg/use] },
  devices: { principal: { userId, keyFingerprint, generation, revoked } } }
```

No emails, names, certificates, session/OAuth tokens or private keys are exported.
User IDs are pseudonymous ownership identifiers, not an assertion that the file
has no privacy-sensitive metadata. No public HTTP endpoint serves this directory.
The relay receives a **read-only directory bind**, not an individual-file bind,
so atomic rename updates are visible. Its service must not read the private DB,
signing key, ontology DB or other homes/services. With a DynamicUser parent
0700 directory, mount the `relay-public` directory inside the relay namespace;
do not broaden parent permissions to expose the private sibling.

State refreshes every 2 seconds with 10-second freshness. The Python reader must
fail closed on missing, malformed or stale state and reopen after replacement.
Successful revocation publishes a tombstone before returning. Active websocket
connections use the Python owner's proposed 1-second state recheck/closure;
JWT TTL alone is **not immediate active-session revocation**. No such integration
claim is made by these control tests. Publication failure rolls back the DB
mutation, marks health failed and blocks admissions until a successful refresh.
An already-issued token can only be judged against the relay's current state.
SQLite and filesystem do not form a distributed atomic transaction: a file
published before a DB commit failure may temporarily deny access, but the failed
operation is never reported as successful. Stale-state denial remains required.

## Build, secrets and operation

From `control/`:

```
npm ci
npm run typecheck
npm test
npm run build
```

Production must explicitly configure one HTTPS origin (no wildcard trusted
origins), a >=32-character random BetterAuth secret, immutable provider account-ID
allowlist and the enabled operator-owned OAuth apps. Example **non-secret** values:

```
NODE_ENV=production
SESSION_PEER_CONTROL_ORIGIN=https://relay.abruption.dev
SESSION_PEER_ALLOWED_ACCOUNTS=[{"provider":"github","accountId":"REPLACE_WITH_NUMERIC_PROVIDER_ID"}]
SESSION_PEER_CONTROL_DATA=/var/lib/session-peer-control/private
SESSION_PEER_RELAY_PUBLIC=/var/lib/session-peer-control/relay-public
GITHUB_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
GOOGLE_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
```

Missing allowlist defaults to deny all. OAuth secrets and the BetterAuth secret
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

`deploy/session-peer-control.service` is an installation template, not an enabled
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
replacement denial, dual-key rotation, generation races, durable receipt retry,
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
