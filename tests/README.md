# Test suites

The default test command stays dependency-free and offline:

```bash
python -m unittest discover -s tests -v
```

It discovers every suite below. Tests that require the optional relay or MCP
dependencies report a skip when those extras are not installed. No default test
uses a provider login, model call, public relay, or production mutation.

| Suite | Stable command | Ownership |
| --- | --- | --- |
| Core | `python -m unittest discover -s tests/core -t . -v` | CLI, messaging, SSH, diagnostics, compatibility |
| Adapters | `python -m unittest discover -s tests/adapters -t . -v` | Adapter registry and Antigravity bridge |
| Codex | `python -m unittest discover -s tests/codex -t . -v` | Queueing, home selection, writer evidence, wake |
| Relay | `python -m unittest discover -s tests/relay -t . -v` | Native transport, protocol, auth, lifecycle, capacity |
| Control integration | `python -m unittest discover -s tests/control_integration -t . -v` | Node/Python contract and backup snapshots |
| MCP integration | `python -m unittest discover -s tests/mcp_integration -t . -v` | MCP policy and stdio protocol |
| Distribution | `python -m unittest discover -s tests/distribution -t . -v` | Installer and exact wheel/sdist contents |
| Documentation | `python -m unittest discover -s tests/docs -t . -v` | Translation and repository-link contracts |

Install `.[relay,mcp]` before running the complete relay and MCP suites. The
control integration suite additionally requires `npm ci` in `control/` and
`SESSION_PEER_CONTROL_INTEGRATION=1`; without that explicit opt-in, the live
Node/Python fixture is skipped.

After building exactly one wheel and one sdist, validate the full distribution
contract with:

```bash
SESSION_PEER_DIST_DIR=dist \
  python -m unittest discover -s tests/distribution -t . -v
```

The distribution contract compares complete archive contents, not a sentinel
subset, and rejects legacy compatibility code, tests, prototypes, operational
state, credentials, private keys, and local databases.
