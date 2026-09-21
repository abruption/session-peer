# Authenticated control example

This directory contains the control-service template for browser OAuth, native
device authorization, managed enrollment and publication of relay verification
state. It is not a complete deployment by itself.

Run the compiled migration explicitly under the same service identity and writer
lock before starting the service. Configure only enabled provider credentials,
the canonical HTTPS origin, protected private state and a dedicated public-state
directory. A compatible relay must consume that directory read-only, retain its
replay/high-water state, fail closed on stale state and participate in an
explicit readiness/recovery topology.

The template reads aggregate Python relay metrics only from
`http://127.0.0.1:3768/metrics`. Configure the managed relay with the matching
`--metrics-port 3768` plus explicit capacity flags. That listener is separate
from the public relay port and must not be reverse-proxied. Only the dedicated
admin listener merges these non-identifying aggregates for the existing
Authelia-protected portal.
Use the bounded sizing procedure in the neighboring
[`static-account` example](../static-account/README.md) before raising any limit.

For every fresh install or upgrade:

1. Stop and fence both the control publisher and relay consumer.
2. Take a protected, consistent snapshot of the control SQLite database, signing
   key, public state and relay replay/high-water state. Keep it as recovery
   evidence; do not automatically restore it over a failed migration.
3. Build the release, then run `node dist/server/migrate.js` as the control
   service identity with the same credentials, environment and exclusive
   `writer.lock` used by the regular unit.
4. Start the service only after the command reports the installed first-party
   schema version. Verify `/healthz`, a fresh public-state revision and relay
   readiness before accepting traffic.
5. If migration fails, leave the stack stopped, retain the database and error
   evidence, and review a fenced recovery. Never delete the ledger, tombstones,
   operation receipts or revision counter to make startup pass.

Normal startup only validates the installed schema. It returns
`migration_required` for an old, partial, future or corrupt schema and never runs
DDL. Do not place migration in `ExecStartPre` or an automatic restart path.

Do not combine this unit with the static-account relay example. For a complete,
instance-specific reference see [`../../ops/abruption-kr`](../../ops/abruption-kr/README.md).
