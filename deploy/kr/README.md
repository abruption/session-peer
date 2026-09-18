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
private signing key, auth DB and relay replay file are deliberately omitted.
Google provider credentials were enabled separately after these unit copies;
any provider-specific drop-in must use protected LoadCredential files and
`GOOGLE_CLIENT_SECRET_FILE`, with IDs/allowlist in the protected environment file.

Run compiled auth migration and explicit replay initialization only through the
reviewed same-UID/writer-lock procedure on first setup. Regular service startup
must never reset or automatically initialize missing state. Replay state belongs
under the private child directory, not the DynamicUser top-level symlink.
Preserve signing keys, operation receipts, tombstones, revision counter and replay
highwater across restarts, upgrades and rollbacks; never restore an old snapshot
as current state without explicit restore fencing.

The explicit stack uses Upholds plus dependency shutdown and fresh readiness.
The application sends systemd watchdog notifications only while durable state
and listener health pass; Type=notify, NotifyAccess=all, flock --no-fork and the
30-second watchdog were tested together. The relay cannot connect outward and
reads only the directory-bound public auth state. The KR host lacks BPF support:
these units do not claim a kernel restriction to a single listening port.

Use the [validation record](../../docs/validation/69-rc.md) and
[watchdog runbook](../../docs/relay-watchdog.md) for evidence and limitations.
Migration/replay initialization, Caddy changes, boot enablement and fault tests
are explicit operator steps; adding these files does not execute them.
