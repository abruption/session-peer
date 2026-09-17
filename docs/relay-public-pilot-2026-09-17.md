# Public WSS pilot — 2026-09-17

User-approved temporary KR pilot, completed and removed. This is a bounded
integration check, not a production deployment or a sustained-operation result.

## Path and isolation

Mac client → public Cloudflare HTTPS/WSS → KR Caddy exact test hostname →
127.0.0.1:3769 blind relay → authenticated receiver → existing Antigravity bridge.
The application TLS 1.3 channel pins device certificates inside WebSocket; public
TLS termination does not receive application plaintext. Native access was limited
to one explicitly allowed peer and the existing `agy-kr` session alias.

The prior SSH forwarding process was stopped before testing. Public destination
routing used en1 / the local internet gateway, not a Tailscale interface. SSH was
used separately for management and read-only transcript observation. This does
not establish a phone-with-VPN-disabled test or raw TCP NAT traversal.

The relay ran with DynamicUser, ProtectHome, ProtectSystem=strict,
NoNewPrivileges, 256 MiB memory, 50% CPU, 64 tasks, a 10-connection application
limit and a 30-minute runtime ceiling. An independent 30-minute systemd cleanup
timer was armed before the Caddy change. No DNS or firewall changes were made.

## Observations

- Public unauthenticated admission: HTTP 401.
- Authenticated paired `list`: existing Antigravity session returned.
- Public send marker: `SP090_PUBLIC_e037d3d2d993`.
- Request ID: `e037d3d2-d993-4fae-8c03-dbc66619967c`.
- Native result: submitted, `consumptionConfirmed=false`.
- Independently observed MODEL transcript: `ACK_SP090_PUBLIC_e037d3d2d993`.
- Same request ID/body repeated: persisted receipt with `duplicate=true` and
  the same native request ID. No second native submission was requested.

This independently observed ACK strengthens the evidence for this particular
message. It does not change the general send contract to delivery confirmation
or establish exactly-once delivery under crashes.

## Cleanup

The exact temporary Caddy block was removed while preserving other configuration.
Validation/reload succeeded. Caddy SHA256 returned to the pre-test value
`60ae35627b82d65724ceac89421e1f92ba475b675fd146b4036129f352197ebb`.
The public test hostname returned its original HTTP 301 response. Relay service
was stopped and loopback port 3769 was closed. The cleanup timer was disarmed only
after successful rollback. The temporary receiver and native bridge were stopped;
the user's Antigravity TUI remained running. Test credentials and temporary
service installation were removed afterward.

## Remaining release gates

Main-target integration/release PR and CI, package revalidation after final edits,
release merge/tag/PyPI verification, and sustained real-device operation remain.
The live agent coverage here is Antigravity; Claude socket fixtures and other
unit tests are not live Claude/Codex model evidence.
