# Developing an internal agent adapter

This is a source-extension guide, not an external plugin installation interface.
See the [architecture decision](architecture/agent-transports.md) for contract
versioning, compatibility, result semantics and trust boundaries.

An adapter subclasses `AgentAdapter`, declares a unique lowercase `name`, and
implements `list(context)` and `submit(context, text)`. Register it explicitly
with `AGENTS.register(...)` before `main()` executes. Keep its implementation in
the standalone source if it must work over SSH. No CLI router or SSH dispatcher
change is needed for a basic new adapter.

Minimal deterministic example (test use only):

```python
class ExampleAdapter(AgentAdapter):
    name = "example"
    capabilities = AgentCapabilities()  # list/send; no wake/wait/ack

    def list(self, context):
        return {"sessions": [{"agent": self.name, "id": "one", "status": "idle"}],
                "discovery": {"status": "ok"}}

    def submit(self, context, text):
        target = self.identity(context.options.to, context)
        return {"ok": True, "target": {"id": target.identifier},
                "status": "validated" if context.options.dry_run else "submitted",
                "submitted": not context.options.dry_run,
                "consumptionConfirmed": False}

AGENTS.register(ExampleAdapter())
```

The example has no real inbox; never ship it as an actual delivery adapter.
The test-only `tests/fixtures/agent_adapter.py` supplies the executable example
used in contract tests and is excluded from published distributions.

- `list` returns `sessions` and a `discovery` object with `status` equal to `ok`,
  `error` (with `error` text), or `not_installed`. Every row identifies its agent.
  Preserve native identity fields. Implement `display_row`/`render` for different
  row layouts. Codex additionally preserves existing top-level home metadata.
- `submit` receives the already-validated, wrapped message exactly once. Honor
  dry-run before native side effects. Return native submission facts; do not
  infer acknowledgement from socket/queue acceptance. Native failures after a
  known submission must retain its ID and partial outcome.
- `identity` and `target` translate native identity and CLI/Reply-To targets.
  The default is `name:identifier`; Claude preserves unprefixed names/PIDs.
- `diagnose`, `diagnostic_text`, `listing_notes`, `submission_text`,
  `remote_submission` and `remote_options` specialize evidence and existing
  output compatibility without changing common routing. Argument options must
  still be explicitly declared in the parser; agents cannot inject shell code.
- Feature booleans report implementation support only. False capabilities fail
  before submission. Advertising wake does not skip native runtime checks or MCP
  authorization; wait/ack have no CLI implementation in this version.

MCP permits only explicitly authorized destinations and agents. Source
registration alone never grants remote/send privileges. Optional dependencies
must stay outside core import paths; adding a backend dependency requires a
separate packaging decision. Public external loading and installation are not
implemented.

Run the existing suite and the shared contract tests both without and with the
optional MCP SDK. Also build/install wheel and sdist independently and run the
isolated standalone installer tests. Use fixture transports for new contract
coverage, not production sessions.
