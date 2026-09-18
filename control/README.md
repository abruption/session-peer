# session-peer control (private RC candidate)

Independent optional Node project. It does not change the dependency-free Python
CLI. It is not installed, exposed, or enabled by installing session-peer.

Requires Node 22.13+ or Node 24, npm, and a C/C++ build toolchain if the
better-sqlite3 prebuilt binary is unavailable. OpenSSL is required for test-only
certificate fixtures. BetterAuth is pinned to 1.7.5; use `npm ci`.

```
npm ci
npm run typecheck
npm test
npm run build
```

Read [relay-auth](../docs/relay-auth.md) for policy, API, secrets, migration,
isolation, and the unverified integration gates. Never point this project's
SQLite adapter at the ontology vault or store credentials in this repository.
