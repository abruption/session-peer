# Issue #69 technical validation — 2026-09-16

## Decision

Device pairing, authenticated direct transport, and an opaque public WebSocket
relay are feasible with the #47 adapter/transport separation. This experiment is
an isolated prototype, not a production implementation or a recommendation to
deploy the current code. It uses a deterministic fixture adapter exclusively;
no real Claude/Codex session, queue, credential, or model quota was involved.

The worktree is based on local commit `993d04d`. Product CLI, dependencies,
packaging, and version remain unchanged. No remote push, PR, or release is part
of this trial. See [README](README.md) for reproduction and protocol boundaries.

## Actual topology and measurements

Direct: Mac mini → MacBook over tailnet TCP. Relay: each Mac independently makes
an outbound WSS connection → Cloudflare → KR Caddy → US tailnet backend. Inner
TLS 1.3 terminates only at the two Macs. This is application E2EE over WebSocket,
not a newly deployed WireGuard tunnel or a NAT traversal implementation.

The temporary public hostname was `relay-test.abruption.dev`. The public trial
ran from **21:13:09 to 21:20:33 KST on 2026-09-16**. Routes to Cloudflare used
ordinary network interfaces (mini: en1; MacBook: en7), rather than Tailscale.
Tailscale remained available for management/direct traffic; a mobile device with
VPN disabled was not tested.

| Measurement | Samples | Median | Maximum |
| --- | ---: | ---: | ---: |
| Cold direct fixture send | 10/10 successful | 46.955 ms | 53.62 ms |
| Cold public relay fixture send | 10/10 successful | 3363.5 ms | 3473.93 ms |
| Existing direct TLS connection, list | 10 successful | 9.495 ms | 18.6 ms |
| Existing relay TLS connection, list | 10 successful | 439.42 ms | 460.17 ms |

Cold relay measurements include admission HTTP, WebSocket connection, inner TLS,
authenticated readiness probe, and submission. Warm measurements use **list**,
not send; they demonstrate connection reuse potential, not an equivalent send
benchmark. These small sequential samples are not a throughput or load study.
Sanitized observations are in [results.json](results.json).

Public pairing, direct preference, relay fallback with an unavailable direct
route, lost-response status reconciliation, and cross-route duplicate suppression
all passed. The fixture recorded 23 effects, zero duplicates, and zero pending
entries. Revoking a paired public client prevented subsequent use. Backend
restart was followed by successful fresh admission and ten warm relay requests,
but an immediate request during restart failed: uninterrupted recovery was not
demonstrated.

## Verification

- 20 lab integration tests passed on macOS Python 3.14/OpenSSL 3.6 and Ubuntu
  arm64 Python 3.12/OpenSSL 3.0. The real MacBook ran Python 3.13/OpenSSL 3.0.
- The combined repository suite passed **335 tests** in 7.751 seconds, including
  the optional MCP and lab dependencies. Ubuntu lab tests passed in 4.701 seconds.
- Tests exercise real loopback TLS/WebSocket traffic, certificate substitution,
  TLS tampering/replay, pairing expiry/reuse, lost commit responses, revocation,
  crash ambiguity, duplicate IDs, request bounds, relay authentication, resource
  limits, slow forwarding, redirect rejection, and key file permissions.
- Captured local relay frames did not contain sentinel plaintext, invitation
  secrets, or private keys. Public relay payload capture was disabled; this is
  not a full audit of edge/proxy observability.
- Wheel and sdist build successfully and exclude the experiment. Optional lab
  imports do not add dependencies or listeners to the installed product.

The intent journal supports at-most-once execution attempts. A crash after an
effect but before receipt commit leaves an unknown result and prevents automatic
reexecution. This deliberately does not claim exactly-once native delivery.
`submitted` and `consumptionConfirmed` remain separate.

## Findings during the trial

1. The first direct pairing attempt timed out before a later TCP probe and retry
   succeeded. No peer had been committed. The cause was not conclusively
   established; startup/readiness diagnostics need improvement.
2. MacBook Python's default CA file/directory paths did not exist. Setting
   `SSL_CERT_FILE=/etc/ssl/cert.pem` for the test process enabled outer HTTPS
   verification. Verification was never disabled; no global setting changed.
3. The default urllib user agent received Cloudflare HTTP 403. An explicit
   `session-peer-relay69-lab/1.0` user agent succeeded, as did a curl comparison.
   The specific Cloudflare rule was not identified and no WAF policy changed.
4. A client request immediately after backend restart failed; later requests
   succeeded. Production work needs bounded reconnect/backoff, readiness, and
   useful typed errors without exposing credentials.
5. Cold public relay setup dominates latency. Persistent authenticated channels
   deserve measurement before integrating a one-shot CLI workflow.

## Isolation, resources, and cleanup

The US process used a temporary systemd unit with DynamicUser, no capabilities,
read-only code, restricted directories, private tmp/devices, a 30-minute runtime
limit, MemoryMax 256 MiB, CPUQuota 50%, and TasksMax 64. A preflight verified that
other homes and selected product directories were unreadable. Cgroup IP policy
allowed KR access to this backend. Mac fixtures used private temporary state,
not the Linux service's OS sandbox.

Observed US peak memory was 26,189,824 bytes (about 25 MiB), one task, and about
1.002 CPU seconds across two backend processes. These low-volume observations do
not validate the limits under hostile sustained load.

The trial added only an exact-host Caddy block under the existing Cloudflare
ingress. No DNS record, global firewall rule, persistent account, or global Python
package was added. A timed rollback was prepared before the change. Caddy reload
could affect existing WebSocket clients; full user-session impact was not measured.
The existing chat health endpoint returned HTTP 200 before, during, and after.

Cleanup stopped the MacBook receiver and US relay, verified no trial listener,
removed remote code/state/credentials, removed the exact Caddy block, and stopped
the rollback timer. Caddy remained active and its original SHA-256 was restored:
`60ae35627b82d65724ceac89421e1f92ba475b675fd146b4036129f352197ebb`.
The test hostname returned its original HTTP 301 redirect afterward. Local trial
keys and credentials are deleted after retaining only sanitized measurements.

## Remaining boundaries and next steps

Outer admission uses provisioned room/role bearer credentials and short-lived
cookies; it is not a device-bound proof. Cloudflare/Caddy can see these outer
credentials and metadata. Inner pinned mutual TLS authenticates peers and
protects application payloads. Production work needs origin-bound admission
configuration, credential rotation, per-device quotas, and protocol review.

Invitation transfer used trusted management paths and private files. There is no
mobile QR/SAS UX, hardware key storage, seamless certificate renewal, offline
queue, production receiver lifecycle, or native agent authorization integration.
Filesystem permissions alone are not a keychain. Certificates in this lab are
short-lived, and rotation requires revocation and pairing again.

Direct success means tailnet TCP, not public peer-to-peer NAT traversal. Windows,
mobile VPN-off clients, IPv6 origin policy, current OCI API firewall state,
large-scale denial-of-service behavior, and independent security review remain
unverified. A direct public-origin probe timed out from one vantage point only.

Recommended next scope: define stable device/receipt schemas and lifecycle;
measure connection reuse and reconnect behavior; strengthen outer admission and
key storage; then review the protocol before any real agent adapter is enabled.
Keep this lab optional and isolated while those decisions are made.
