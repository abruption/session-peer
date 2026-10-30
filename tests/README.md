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

The CI matrix includes standard CPython 3.9/3.13/3.14 core fixture cells on
macOS/Linux and retains Windows CPython 3.13. The 3.14 core cells run the
generated-standalone, core, adapter, Codex and distribution-source checks.
Separate macOS/Linux
3.14 package cells build wheel/sdist, verify their full contents and install
each independently in fresh environments, checking the installed import origin,
exact CLI version, help and dependency consistency. The existing Linux 3.13
package cell is retained.

The MCP CI matrix tests Python 3.10/3.13/3.14 on macOS/Linux with both the exact SDK
floor (`.github/requirements/mcp-minimum.txt`) and latest compatible 1.x.
Transitive dependencies resolve normally, not at their individual minima.
Both runtime graphs (including pip/setuptools bootstrap packages) are audited
separately from the pinned build/audit requirements and retained
as CI artifacts. Existing latest-resolution and release audits remain required.

Relay fixtures also run on macOS/Linux with Python 3.11/3.13/3.14. All core,
package, MCP and Relay cells are required by the existing release gate. These
are fixture/package checks, not new live native-agent, SSH, Windows 3.14 or
free-threaded Python acceptance. Python floors remain core 3.9, MCP 3.10 and
Relay 3.11. CI outcomes must be recorded at the exact reviewed source before
expanding supported-version metadata.

After building exactly one wheel and one sdist, validate the full distribution
contract with:

```bash
SESSION_PEER_DIST_DIR=dist \
  python -m unittest discover -s tests/distribution -t . -v
```

The distribution contract compares complete archive contents, not a sentinel
subset, and rejects legacy compatibility code, tests, prototypes, operational
state, credentials, private keys, and local databases.
