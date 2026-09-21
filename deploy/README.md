# Deployment material

Deployment files are separated by purpose so an example cannot be mistaken for
the live Abruption topology.

## Reusable examples

- [`examples/static-account`](examples/static-account/README.md) runs only the
  blind relay with operator-provisioned hashed bearer accounts. It has no OAuth,
  browser UI, control database, public-state publisher or managed revocation.
- [`examples/authenticated-control`](examples/authenticated-control/README.md)
  is the control-service half of a managed deployment. It requires an explicit
  migration, provider credentials, a compatible managed relay, readiness and
  recovery policy. It must not be combined with the static-account relay unit.

These files are templates. Copying a unit is not installation or validation.
Review paths, service identity, credentials, resource limits, network policy and
backup scope for the target host before enabling anything.

## Instance-specific operations

[`ops/abruption-kr`](ops/abruption-kr/README.md) preserves secret-free copies of
the deployed KR service contracts and recovery helper. Those files document one
reviewed installation; their paths, users, runtime and Authelia/Caddy topology
are not reusable defaults.
