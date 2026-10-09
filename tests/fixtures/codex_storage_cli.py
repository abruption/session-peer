#!/usr/bin/env python3
"""Synthetic storage-environment recorder; never invokes a native agent."""
import json
import os
from pathlib import Path
import sys

assert sys.argv[1] == "queue"
root = Path(os.environ["CODEX_HOME"])
(root / "fixture-environment.json").write_text(json.dumps({
    "home": os.environ["CODEX_HOME"],
    "sqliteOverridePresent": "CODEX_SQLITE_HOME" in os.environ,
}), encoding="utf-8")
thread = sys.argv[sys.argv.index("--thread") + 1]
print("Queued message fixture-storage for thread " + thread + ".")
