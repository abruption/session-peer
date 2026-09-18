# Private relay control and authentication (RC candidate)

Status: implementation candidate for #69, not a deployed production service.
The control-to-relay contract below incorporates the Python owner's final
interface instruction; actual cross-service integration remains a separate gate. This project adds no listeners,
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
known. Initial registration requires an absent principal, `expectedGeneration=0`
and `keyGeneration=1`. Renewal requires the existing active same-owner principal,
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
  "keyGeneration": 2
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

### Atomic public state and contract transition

```text
{ schemaVersion: 1, issuer, audience, issuedAt, expiresAt,
  jwks: { keys: [public signing JWK with kid/alg/use] },
  devices: { principal: { userId, keyFingerprint, generation, revoked } } }
```

No names, emails, certificates, session/OAuth tokens or private keys. User IDs are
pseudonymous ownership metadata. No public HTTP route serves the directory.
Read-only **directory bind**, not a single-file bind, exposes atomic replacements
without granting access to private DB/signing key/ontology/other service files.
Do not broaden a DynamicUser parent directory to expose private siblings.
The writer explicitly sets only the validated public directory to 0755 and
each temporary state file to 0644 even under umask 0077. It sets the file mode
before file fsync, renames within that same directory, then fsyncs the directory.
Never rename/recreate the public directory while a relay directory bind is active;
consumers must reopen state.json to observe each replacement. Private data stays
0700 with DB/signing key files 0600. Initial publication completes synchronously
before the HTTP listener starts, but systemd Type=simple/After is not readiness.
Gate relay launch on validated fresh state and control health, and test coordinated
control/relay restarts separately. File presence alone is not semantic validation.

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
old device fingerprints or operation history. Use a new isolated candidate state
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

## Final contract examples — synthetic only

사용자 확정 계약에 따른 합성 예제다. 토큰/시간/ID는 합성값이며 운영 인증 응답으로 보고하지 않는다. BetterAuth 1.7.5 설치 소스와 기존 실제 fixture 테스트의 API shape를 기준으로 작성했다. 모든 코드·token·시간·ID는 합성값이다. public certificate와 signature만 격리 fixture에서 생성했으며 private key는 삭제했다. 운영 자격, 실제 JWT, OAuth secret을 포함하지 않는다.

모든 issuedAt/expiresAt은 UNIX 초 number다. 초기 expectedGeneration=0/keyGeneration=1; 갱신은 expectedGeneration=current/keyGeneration=current+1. keyGeneration은 서버가 계산/검사한다. 두 경우 operation=register 및 POST /api/relay/devices를 사용한다. operationId는 UUID v4이며 결과 확인까지 고정한다. 갱신 시 previousKeyProof(구키)와 proof(신키)가 동일 서버 proofMessage를 서명한다. 이전 rotate/oldProof/newProof domain API는 최종 계약에서 사용하지 않는다.

### 1. BetterAuth device code

```http
POST /api/auth/device/code
Content-Type: application/json
```

Request:
```json
{
  "client_id": "session-peer-cli"
}
```

Response (200):
```json
{
  "device_code": "SYNTHETIC_DEVICE_CODE_NOT_VALID",
  "user_code": "ABCD-EFGH",
  "verification_uri": "https://relay.abruption.dev/device",
  "verification_uri_complete": "https://relay.abruption.dev/device?user_code=ABCD-EFGH",
  "expires_in": 300,
  "interval": 5
}
```

### 2. CLI poll (browser login/code 확인 후 명시 승인 필요)

```http
POST /api/auth/device/token
Content-Type: application/json
```

Request:
```json
{
  "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
  "device_code": "SYNTHETIC_DEVICE_CODE_NOT_VALID",
  "client_id": "session-peer-cli"
}
```

Response (200):
```json
{
  "access_token": "SYNTHETIC_SESSION_TOKEN_NOT_VALID",
  "token_type": "Bearer",
  "expires_in": 86399,
  "scope": ""
}
```

미승인 poll은 `authorization_pending`, 거절은 `access_denied`, 만료는 `expired_token`; 성공 expires_in은 실제 세션 잔여 초이며 고정86399가 아니다. 반환 access_token은 first-party BetterAuth session token이다.

### 3. 초기 register challenge

```http
POST /api/relay/challenge
Content-Type: application/json
Authorization: Bearer SYNTHETIC_SESSION_TOKEN_NOT_VALID
```

Request:
```json
{
  "operation": "register",
  "payload": {
    "principal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "certificatePEM": "-----BEGIN CERTIFICATE-----\nMIIBpzCCAU2gAwIBAgIUKa49Xo+kLwTPu8Br3SJKHOs6tnEwCgYIKoZIzj0EAwIw\nKTEnMCUGA1UEAwwec2Vzc2lvbi1wZWVyLXN5bnRoZXRpYy1maXh0dXJlMB4XDTI2\nMDkxODA2NTIyN1oXDTI2MDkyODA2NTIyN1owKTEnMCUGA1UEAwwec2Vzc2lvbi1w\nZWVyLXN5bnRoZXRpYy1maXh0dXJlMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\n92HBlKOEAbVrDiu11KLa+ogz5Ux1EFs0tVxHGZ8RSTXMZbXogQfp6iSu3CQAT1k6\nrMzvQQEQVfnSFA0Nq2ccj6NTMFEwHQYDVR0OBBYEFA6U04cTyhBfA0KJGiRRo12D\nctKpMB8GA1UdIwQYMBaAFA6U04cTyhBfA0KJGiRRo12DctKpMA8GA1UdEwEB/wQF\nMAMBAf8wCgYIKoZIzj0EAwIDSAAwRQIgO7Or4Jqa2uEdzyJuu7ptCcx1+sjECC7I\n2YJohffcZEkCIQCDjCQ27Sul9tUROKwIe0CgA4sYCRXDc8qVBLpglaJqiA==\n-----END CERTIFICATE-----\n",
    "keyGeneration": 1,
    "name": "fixture-device",
    "operationId": "11111111-1111-4111-8111-111111111111",
    "expectedGeneration": 0
  }
}
```

Response (200):
```json
{
  "challengeId": "22222222-2222-4222-8222-222222222222",
  "nonce": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
  "issuedAt": 1800000000,
  "expiresAt": 1800000060,
  "proofMessage": "session-peer-control-v1:\nhttps://relay.abruption.dev\nregister\n22222222-2222-4222-8222-222222222222\nAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE\n065ac9504e5651509919860a9e9005d6fefd3ac8290bfa5846e3ebbc2757bfab"
}
```

### 4. 초기 register (previousKeyProof 없이)

```http
POST /api/relay/devices
Content-Type: application/json
Authorization: Bearer SYNTHETIC_SESSION_TOKEN_NOT_VALID
```

Request:
```json
{
  "principal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "certificatePEM": "-----BEGIN CERTIFICATE-----\nMIIBpzCCAU2gAwIBAgIUKa49Xo+kLwTPu8Br3SJKHOs6tnEwCgYIKoZIzj0EAwIw\nKTEnMCUGA1UEAwwec2Vzc2lvbi1wZWVyLXN5bnRoZXRpYy1maXh0dXJlMB4XDTI2\nMDkxODA2NTIyN1oXDTI2MDkyODA2NTIyN1owKTEnMCUGA1UEAwwec2Vzc2lvbi1w\nZWVyLXN5bnRoZXRpYy1maXh0dXJlMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\n92HBlKOEAbVrDiu11KLa+ogz5Ux1EFs0tVxHGZ8RSTXMZbXogQfp6iSu3CQAT1k6\nrMzvQQEQVfnSFA0Nq2ccj6NTMFEwHQYDVR0OBBYEFA6U04cTyhBfA0KJGiRRo12D\nctKpMB8GA1UdIwQYMBaAFA6U04cTyhBfA0KJGiRRo12DctKpMA8GA1UdEwEB/wQF\nMAMBAf8wCgYIKoZIzj0EAwIDSAAwRQIgO7Or4Jqa2uEdzyJuu7ptCcx1+sjECC7I\n2YJohffcZEkCIQCDjCQ27Sul9tUROKwIe0CgA4sYCRXDc8qVBLpglaJqiA==\n-----END CERTIFICATE-----\n",
  "keyGeneration": 1,
  "name": "fixture-device",
  "operationId": "11111111-1111-4111-8111-111111111111",
  "expectedGeneration": 0,
  "challengeId": "22222222-2222-4222-8222-222222222222",
  "proof": "MEUCIEoLzPVGLD6C4L4qf3hyF0k08pulV-WpeLw6Gr-ruRrBAiEAgc_eYG7iXI8t65rA6I0WYXlzDaAuhnBh74Xdh3hdmBc"
}
```

Response (201):
```json
{
  "operationId": "11111111-1111-4111-8111-111111111111",
  "committed": true,
  "principal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "keyFingerprint": "7c9d073898577eb39a163275f7c227aa24e0fb0dab478fd8f3f1d17bdc8dbdae",
  "keyGeneration": 1
}
```

### 5. owner operation 조회

```http
GET /api/relay/operations/11111111-1111-4111-8111-111111111111
Content-Type: application/json
Authorization: Bearer SYNTHETIC_SESSION_TOKEN_NOT_VALID
```

Response (200):
```json
{
  "operationId": "11111111-1111-4111-8111-111111111111",
  "committed": true,
  "principal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "keyFingerprint": "7c9d073898577eb39a163275f7c227aa24e0fb0dab478fd8f3f1d17bdc8dbdae",
  "keyGeneration": 1
}
```

challenge가 등록한 owner operation의 mutation 전 조회는 `{operationId, committed:false}`다. 없는 ID와 타인의 ID는 모두404다. `committed:true` receipt는 과거 결과이며 현재 폐기/세대는 GET devices로 확인한다. 동일ID 다른payload는409 operation_conflict, tombstone은 부활하지 않는다.

### 6. same principal key 갱신 challenge

```http
POST /api/relay/challenge
Content-Type: application/json
Authorization: Bearer SYNTHETIC_SESSION_TOKEN_NOT_VALID
```

Request:
```json
{
  "operation": "register",
  "payload": {
    "principal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "certificatePEM": "-----BEGIN CERTIFICATE-----\nMIIBpjCCAU2gAwIBAgIUKQc0iqYoQiyaCmoNO6Qux5zGAvkwCgYIKoZIzj0EAwIw\nKTEnMCUGA1UEAwwec2Vzc2lvbi1wZWVyLXN5bnRoZXRpYy1maXh0dXJlMB4XDTI2\nMDkxODA2NTIyN1oXDTI2MDkyODA2NTIyN1owKTEnMCUGA1UEAwwec2Vzc2lvbi1w\nZWVyLXN5bnRoZXRpYy1maXh0dXJlMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\nV3dkiUlLJLKl/AKNG50R5UgwFj0RDisR7IA2uNClrZxZbKud8Fi8Dt2HaHyycY9E\ntJTrcXsmmk6YfxrgLRWRGqNTMFEwHQYDVR0OBBYEFD+pnfUEswoSaYfpeRSt+bqE\nl4z8MB8GA1UdIwQYMBaAFD+pnfUEswoSaYfpeRSt+bqEl4z8MA8GA1UdEwEB/wQF\nMAMBAf8wCgYIKoZIzj0EAwIDRwAwRAIgYd388lDAsfqrP2MwvyeSHSTgJOlTC52o\nWxd/XSw4l2QCIECk7pesSkht4ULje415Yv48oMjp7Gx5VJnydjW6tHrd\n-----END CERTIFICATE-----\n",
    "keyGeneration": 2,
    "name": "fixture-device",
    "operationId": "33333333-3333-4333-8333-333333333333",
    "expectedGeneration": 1
  }
}
```

Response (200):
```json
{
  "challengeId": "44444444-4444-4444-8444-444444444444",
  "nonce": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
  "issuedAt": 1800000000,
  "expiresAt": 1800000060,
  "proofMessage": "session-peer-control-v1:\nhttps://relay.abruption.dev\nregister\n44444444-4444-4444-8444-444444444444\nAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE\n21a005eb78a3bf35c35c5c38e60214e6c9d9ecfd810f6c5b9ae03784a614463b"
}
```

### 7. same message에 구키·신키 proof 제출

```http
POST /api/relay/devices
Content-Type: application/json
Authorization: Bearer SYNTHETIC_SESSION_TOKEN_NOT_VALID
```

Request:
```json
{
  "principal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "certificatePEM": "-----BEGIN CERTIFICATE-----\nMIIBpjCCAU2gAwIBAgIUKQc0iqYoQiyaCmoNO6Qux5zGAvkwCgYIKoZIzj0EAwIw\nKTEnMCUGA1UEAwwec2Vzc2lvbi1wZWVyLXN5bnRoZXRpYy1maXh0dXJlMB4XDTI2\nMDkxODA2NTIyN1oXDTI2MDkyODA2NTIyN1owKTEnMCUGA1UEAwwec2Vzc2lvbi1w\nZWVyLXN5bnRoZXRpYy1maXh0dXJlMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\nV3dkiUlLJLKl/AKNG50R5UgwFj0RDisR7IA2uNClrZxZbKud8Fi8Dt2HaHyycY9E\ntJTrcXsmmk6YfxrgLRWRGqNTMFEwHQYDVR0OBBYEFD+pnfUEswoSaYfpeRSt+bqE\nl4z8MB8GA1UdIwQYMBaAFD+pnfUEswoSaYfpeRSt+bqEl4z8MA8GA1UdEwEB/wQF\nMAMBAf8wCgYIKoZIzj0EAwIDRwAwRAIgYd388lDAsfqrP2MwvyeSHSTgJOlTC52o\nWxd/XSw4l2QCIECk7pesSkht4ULje415Yv48oMjp7Gx5VJnydjW6tHrd\n-----END CERTIFICATE-----\n",
  "keyGeneration": 2,
  "name": "fixture-device",
  "operationId": "33333333-3333-4333-8333-333333333333",
  "expectedGeneration": 1,
  "challengeId": "44444444-4444-4444-8444-444444444444",
  "previousKeyProof": "MEQCIA5Zy17iMSNDbkyMOO4bBePq5C8iDjNk_Eok604QM3imAiAFjrGDCTd0HPmmZrRaiJ05EaWm4TtMa_E12Z7lQMlr1w",
  "proof": "MEUCIFzIQwVYkOvqVP8PGf2dJrapd3uXpIqCKpzt-Xq0ixhpAiEA8fq_jf3DTllk43eR3GS-cYlfV4jDKle5e1yf0wBWq30"
}
```

Response (201):
```json
{
  "operationId": "33333333-3333-4333-8333-333333333333",
  "committed": true,
  "principal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "keyFingerprint": "3b2bde1e4f2c4b605850afad06655e7619402feb71fa3c28d739bc02f89aed8d",
  "keyGeneration": 2
}
```

### 8. admission challenge

```http
POST /api/relay/challenge
Content-Type: application/json
Authorization: Bearer SYNTHETIC_SESSION_TOKEN_NOT_VALID
```

Request:
```json
{
  "operation": "admission",
  "payload": {
    "role": "receiver",
    "devicePrincipal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "receiverPrincipal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
}
```

Response (200):
```json
{
  "challengeId": "55555555-5555-4555-8555-555555555555",
  "nonce": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
  "issuedAt": 1800000000,
  "expiresAt": 1800000060,
  "proofMessage": "session-peer-control-v1:\nhttps://relay.abruption.dev\nadmission\n55555555-5555-4555-8555-555555555555\nAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE\nd9816e1974bfdff446236e3db7c6b305be75a17978f58c0cb3873267eb83f789"
}
```

### 9. admission JWT 발급

```http
POST /api/relay/admission
Content-Type: application/json
Authorization: Bearer SYNTHETIC_SESSION_TOKEN_NOT_VALID
```

Request:
```json
{
  "role": "receiver",
  "devicePrincipal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "receiverPrincipal": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "challengeId": "55555555-5555-4555-8555-555555555555",
  "proof": "MEUCIFjtvXtaIzRSp71RB5N31qV1HDQ7cb7yu_d6W-kUzedYAiEA9r-3Xq1qzucZuneFEJkRaeUCkIcb4GmANffMVNOcgZc"
}
```

Response (200):
```json
{
  "token": "SYNTHETIC_JWT_NOT_VALID",
  "expiresAt": 1800000060,
  "room": "f8f3367b6f76880e8101074990ee03a28af5e301a202ffa5f61f779f3192038d"
}
```

JWT 실제본문은 예제/로그로 출력하지 않는다. claims: iss/aud=origin, sub=내부userID, devicePrincipal/receiverPrincipal, keyFingerprint=SHA256(certificate DER), keyGeneration, role, room, iat, exp<=iat+60, jti, cnf.jwk=certificate public EC P256 key. Signing kid는 별도 signing public key 식별자다.

Relay exchange: Bearer JWT + X-Session-Peer-Proof=ECDSA/SHA256 DER base64url of exact UTF8 `session-peer-admission-v1:`+JWT. 이 proof는 control nonce proof와 별개다.

State: schemaVersion1/issuer/audience/jwks/devices 구조 유지. issuedAt UNIX 초, expiresAt=issuedAt+180; 60초마다 atomic 재발행하고 mutation 즉시 발행. Python은 issuedAt>now+5 / expired / malformed / missing을 fail-closed하고 기존 socket을1초마다 재검사한다.
