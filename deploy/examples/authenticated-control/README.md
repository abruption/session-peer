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

Do not combine this unit with the static-account relay example. For a complete,
instance-specific reference see [`../../ops/abruption-kr`](../../ops/abruption-kr/README.md).
