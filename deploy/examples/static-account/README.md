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
