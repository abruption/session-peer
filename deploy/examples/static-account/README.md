# Static-account blind relay example

This example runs `session-peer relay serve --accounts ...` with a private JSON
file containing only hashed bearer admission values, rooms and roles. It does
not run the browser control service and cannot provide OAuth login, managed
device enrollment, operation receipts or immediate managed revocation.

Adapt the paths and supply `accounts.json` through systemd credentials. Keep the
listener on loopback behind a reviewed TLS reverse proxy. The service limits are
initial safety bounds rather than a capacity guarantee. Validate the final unit
with `systemd-analyze verify` and a loopback authentication test before enabling
it.

The example spells out the compatible defaults: 20 handshakes/second, 100
pending sessions, 10 global connections, 8 per user, 4 per device and 32 MiB per
connection direction. Static accounts do not carry managed user/device IDs, so
only the global limit applies to their live sockets. Every limit has validated
bounds and cross-limit checks; an invalid combination refuses startup. Keep the
connection ceiling below the unit's file-descriptor, task and measured memory
budget. These are overload controls, not a supported-user-count claim.

`--metrics-port` is intentionally absent here. Enable that loopback-only listener
only when an authenticated operator service consumes it; never proxy it from the
public relay hostname.

Initial sizing is an operator exercise:

1. Start with the documented defaults and the final systemd resource limits.
2. Run a bounded loopback load using the expected frame size and connection mix.
3. Record peak RSS, file descriptors, tasks, latency, rejection counters and
   cleanup back to zero after saturation.
4. Keep explicit headroom for the control service, proxy and host agents.
5. Change one limit at a time, repeat saturation/recovery, and revert if cleanup,
   latency or resource headroom regresses.
