"""Owned fake SSH: execute the actual streamed source, never open a network.

This tests Python/source/argv/wire integration, not SSH authentication or a
physical remote host. Its inherited HOME/config are private fixture paths.
"""
import os
from pathlib import Path
import shlex
import subprocess
import sys


if sys.argv[1:2] == ["-G"]:
    print("user fixture-user\nhostname owned-fixture\nport 22")
    raise SystemExit(0)

if len(sys.argv) != 3 or sys.argv[1] != "owned-fixture":
    raise SystemExit(2)
command = shlex.split(sys.argv[2])
if command[:2] != ["python3", "-"]:
    raise SystemExit(2)
source = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
if not source or len(source) > 4 * 1024 * 1024:
    raise SystemExit(2)
counter = Path(os.environ["SESSION_PEER_TEST_SSH_COUNTER"])
counter.write_text(str(int(counter.read_text(encoding="ascii")) + 1), encoding="ascii")
completed = subprocess.run([sys.executable, "-I", "-", *command[2:]], input=source,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
sys.stdout.buffer.write(completed.stdout)
sys.stderr.buffer.write(completed.stderr)
raise SystemExit(completed.returncode)
