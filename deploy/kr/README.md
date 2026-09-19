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

Run compiled auth migration and explicit replay initialization only through the
reviewed same-UID/writer-lock procedure on first setup. Regular service startup
must never reset or automatically initialize missing state. Replay state belongs
under the private child directory, not the DynamicUser top-level symlink.
Preserve signing keys, operation receipts, tombstones, revision counter and replay
highwater across restarts, upgrades and rollbacks; never restore an old snapshot
as current state without explicit restore fencing.

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
with session-peer. The safe integration is an exact `/session-peer` portal link
or redirect to `https://relay.abruption.dev/admin/metrics`. The relay page and
`/api/admin/metrics` apply a second authorization check: only provider identities
present in `SESSION_PEER_ALLOWED_ACCOUNTS` are operators. Public RC signups never
inherit this role. The metrics response contains aggregate counts only, with no
email, provider account ID, user ID, principal, token, or certificate.

`admin-session-peer.caddy` is the reviewed insertion block for the existing
`(b_admin)` snippet. Place it before that snippet's catch-all `handle`, adapt and
validate the complete Caddy configuration, then reload with a live-file CAS.
The block uses an explicit `route` so Caddy preserves `forward_auth` before the
redirect; ordinary directive sorting would otherwise run `redir` first. The
destination independently requires the relay operator's provider allowlist. Do not
import the block at the global level or use it to replace the existing admin site.
