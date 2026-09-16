# Codex sessions across homes

`session-peer list --json` includes Claude and saved Codex sessions across known
homes. `--agent codex` filters to Codex; `--agent claude` skips Codex inventory.
Without `--codex-home`, candidates on the destination are:

1. Default `~/.codex`.
2. `CODEX_HOME`, if nonempty.
3. Immediate account homes under macOS `~/Library/Application Support/orca/codex-accounts/*/home`.
4. `SESSION_PEER_CODEX_HOMES`, a JSON array of absolute (or `~/`) home paths.

There is no recursive filesystem scan or process/credential inspection. Explicit
`--codex-home PATH` bypasses automatic inventory and unrelated configuration
errors. DBs are opened read-only. Send/wake retain their existing stricter home
resolution; listing does not select an active writer.

## Rows and discovery

Each Codex row includes its canonical `codexHome` and absolute `stateDb` path.
Identity is host + canonical home + UUID: identical UUIDs in different homes
remain separate. Symlink aliases of the same home are deduplicated and their
`sources` merged. Codex rows sort by descending `updatedAt`, then home and UUID.
`--all` includes archived records independently in every home. Human output
shows the home beside each row.

Example (within the existing schemaVersion 1 envelope):

```json
{
  "sessions": [
    {"agent": "codex", "id": "same-uuid", "codexHome": "/home/me/.codex", "stateDb": "/home/me/.codex/state_5.sqlite"},
    {"agent": "codex", "id": "same-uuid", "codexHome": "/home/me/custom", "stateDb": "/home/me/custom/state_5.sqlite"}
  ],
  "discovery": {
    "codex": {
      "status": "ok",
      "homes": [
        {"codexHome": "/home/me/.codex", "stateDb": "/home/me/.codex/state_5.sqlite", "sources": ["default"], "status": "ok", "sessionCount": 1},
        {"codexHome": "/home/me/custom", "stateDb": "/home/me/custom/state_5.sqlite", "sources": ["configured"], "status": "ok", "sessionCount": 1}
      ]
    }
  }
}
```

The legacy top-level `codexHome` remains only when inventory identifies exactly
one candidate home without inventory errors; it is omitted for multiple homes.
Consumers should use the row's home, not infer one from the thread UUID.

Home diagnostics use `status: ok | absent | error`. An absent optional default
or Orca DB is not an error. A missing home explicitly named by `--codex-home`,
`CODEX_HOME`, or `SESSION_PEER_CODEX_HOMES` is an error, even if it aliases an
optional candidate. A successfully read empty DB is `ok` with zero sessions.

Errors carry stable codes: `state_db_missing`, `state_db_not_regular`,
`permission_denied`, or `state_db_read_failed` (including corrupt/incompatible
DBs). Inventory failures appear in `discovery.codex.errors`, with `source`,
`error`, optional `path`, and code `home_resolution_failed`,
`candidate_enumeration_failed`, or `invalid_home_configuration`. Invalid extra-home
configuration is rejected as a whole; default/environment/Orca results survive.

Any failure sets the Codex aggregate to `error` and the command to `ok: false`,
exit 1, retaining other home and Claude rows. With no readable DB and no errors,
automatic discovery reports `not_installed`, empty sessions and exit 0. This is
a change from the previous missing-default-DB error. Successful discovery is
not proof of activity, receipt or queue consumption.

## SSH, send and MCP

The source streamed through SSH enumerates homes on that host using its own
user/environment. Repeated `--host` keeps the existing ordered response array;
one failure yields overall exit 1 without discarding other hosts' results.

Use the home from the selected row explicitly:

```sh
session-peer list --host user@worker --agent codex --json
session-peer send --host user@worker --codex-home '/path/from/selected/row' --to codex:<uuid> 'message'
```

MCP continues passing its configured home explicitly. This CLI default does not
grant MCP access to other homes; create another authorized destination for an
additional home. Python 3.9 standalone dependencies are unchanged.
