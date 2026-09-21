# KR relay deployment reference

These secret-free files preserve the service units and readiness helper reviewed
and deployed for backend `428575a11799e4eb15b43e86aa6ceebe648dd7d4`.
They are operational reference files, not an automatic installation script.
The top-level legacy static-account relay template is a separate deployment mode.

The control runtime is a root-owned regular Node 24.16.0 executable outside home
directories. Build each release on its target platform. Install the helper at
`/opt/session-peer-infra/check-control-ready.py`. Explicitly configure the origin,
release links and protected credential/environment paths before installation.
Actual `control.env`, OAuth client secrets, Better Auth secret, provider allowlist,
public signup switch,
private signing key, auth DB and relay replay file are deliberately omitted.
Google provider credentials were enabled separately after these unit copies;
any provider-specific drop-in must use protected LoadCredential files and
`GOOGLE_CLIENT_SECRET_FILE`, with IDs/allowlist/signup switch in the protected environment file.

The reviewed relay unit explicitly retains the Alpha-compatible safety defaults:
20 handshakes/second, 100 pending admission sessions, 10 global connections, 8
per user, 4 per device and 32 MiB forwarded per connection direction. Ten live
sockets plus the public and metrics listeners remain below `LimitNOFILE=256`,
`TasksMax=64` and the measured `MemoryMax=256M` envelope; these settings are not
a user-count or concurrency guarantee. Change them only after a bounded load
result and a unit/resource review.

For sizing, begin with these limits, run a bounded loopback mix at the expected
frame size, record peak RSS/file descriptors/tasks/latency and all rejection
counters, verify that connections and waiting rooms return to zero, and retain
headroom for Caddy, control and host agents. Change one bound at a time and repeat
both saturation and recovery before applying it to the installed unit.

Port 3768 is a dedicated loopback-only aggregate metrics listener. The control
service reads it with `SESSION_PEER_RELAY_METRICS_URL`; Caddy never routes that
port or `/metrics` on the public relay host. The separate 3771 control listener
merges current connection/session pressure, rejection counters, traffic,
uptime and configured capacity for the Authelia-protected admin portal. The
payload contains no user, room, principal, ticket, proof, address or message.

Run compiled auth migration and explicit replay initialization only through the
reviewed same-UID/writer-lock procedure on first setup and every schema-bearing
upgrade. Stop and fence the stack, run the protected snapshot helper, verify its
`controlSchemaVersion`, signing-key/JWKS match and public/replay revisions, then
run `current/dist/server/migrate.js` with the root-owned regular Node runtime as
the control DynamicUser while its UID is held and the same `writer.lock`,
LoadCredential inputs and protected environment are active. Inspect the reported
schema version before starting the regular stack. Regular service startup
must never reset or automatically initialize missing state. Replay state belongs
under the private child directory, not the DynamicUser top-level symlink.
Preserve signing keys, operation receipts, tombstones, revision counter and replay
highwater across restarts, upgrades and rollbacks; never restore an old snapshot
as current state without explicit restore fencing.

Migration is not an `ExecStartPre` dependency. On failure, keep the stack stopped,
retain the snapshot, live database and journal evidence, and investigate under a
new fenced recovery plan. Do not make an old snapshot current, clear the migration
ledger, reset the revision, or delete a tombstone/receipt. A normal start against
an old, partial, future or damaged schema must fail with `migration_required`.

`session-peer-backup-snapshot.py` creates the state input for the KR encrypted
Restic job. Run it as root. It stops relay, readiness and control explicitly,
backs up SQLite through its online backup API while the writers are stopped,
copies the signing key, provider configuration, public state and replay
high-water into a root-only snapshot, verifies the signing key against the
published JWKS, and restarts only a stack that was active before the snapshot.
The regular DR job must fail closed if this helper fails and include all of:

- `/var/lib/session-peer-backup/snapshots`
- `/etc/session-peer-control` and the four session-peer systemd units
- `/opt/session-peer-control`, `/opt/session-peer-relay` and
  `/opt/session-peer-infra`
- `/usr/local/sbin/session-peer-backup-snapshot.py`

Do not restore those paths over a running service. Restore the encrypted
snapshot to a root-only staging directory first, verify `manifest.json`, SQLite
integrity and table counts, signing-key/JWKS identity, state/replay revisions,
spent-ticket count and runtime symlinks, then perform a separately reviewed
fenced recovery with the stack stopped. Historical Restic data is recovery
evidence, not an automatically current authority.

The explicit stack uses Upholds plus dependency shutdown and fresh readiness.
The application sends systemd watchdog notifications only while durable state
and listener health pass; Type=notify, NotifyAccess=all, flock --no-fork and the
30-second watchdog were tested together. The relay cannot connect outward and
reads only the directory-bound public auth state. The KR host lacks BPF support:
these units do not claim a kernel restriction to a single listening port.

Use the [validation record](../../docs/validation/69-rc.md) and
[watchdog runbook](../../docs/relay-watchdog.md) for evidence and limitations.
Migration/replay initialization, Caddy changes and fault tests are explicit
operator steps; adding these files does not execute them. Production boot uses
only `session-peer-stack.target` as the enabled entry point. Control and relay
remain disabled as direct boot entries, and migration/replay initialization
remain inactive manual one-shots. This policy passed an actual KR reboot on
2026-09-19; see the validation record for timings and existing-infrastructure
checks.
### Operator metrics entry point

Keep `admin.abruption.dev` as the existing Authelia-protected administration
portal. It already owns its root page and `/api/*`; do not replace those routes
with session-peer. The exact `/session-peer` page and
`/session-peer/api/metrics` route use the portal's existing Authelia session as
the sole browser login. The API proxies only to the control service's dedicated
`127.0.0.1:3771` listener; never expose that listener through the relay host or
bind it publicly. Public RC signups never inherit portal access. The default
response contains control and relay aggregate counts. Allowlisted drill-down queries may return
operator-useful names, email addresses, providers, operation IDs and shortened
principal hints. They never return provider account IDs, internal user IDs, full
principals, tokens, cookies, proofs, request hashes, certificates or keys.

`admin-session-peer.caddy` is the reviewed insertion block for the existing
`(b_admin)` snippet. Place it before that snippet's catch-all `handle`, adapt and
validate the complete Caddy configuration, then reload with a live-file CAS.
The block uses explicit `route` wrappers so Caddy preserves `forward_auth`
before serving the page or proxying the aggregate API. Install
`session-peer-admin.html` as `/srv/www/home/session-peer.html`. Do not import the
block at the global level or use it to replace the existing admin site.
