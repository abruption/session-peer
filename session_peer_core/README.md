# Core source composition

The Python files in this directory are the canonical source for the default
session-peer runtime. They are ordered functional segments, not independently
importable modules. `tools/generate_session_peer.py` concatenates them into the
root `session_peer.py` artifact.

This flat composition is intentional. The generated program retains one global
namespace, preserving existing imports, monkey-patching contracts, CLI and JSON
behavior while allowing maintainers to work in bounded source files. The root
artifact remains standard-library-only, directly executable, streamable to
`python3 -` over SSH, and installable by itself.

After editing a segment, regenerate and verify the artifact:

```bash
python3 tools/generate_session_peer.py
python3 tools/generate_session_peer.py --check
```

The deterministic segment order is declared in the generator. CI rejects a
stale artifact. Wheels contain only the generated runtime; source distributions
also contain these canonical segments and the generator. The frozen legacy
`cc_peer.py` is outside this composition and must not be changed.
