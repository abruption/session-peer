#!/usr/bin/env python3
"""Build or verify the dependency-free session_peer.py artifact."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = ROOT / "session_peer_core"
DEFAULT_OUTPUT = ROOT / "session_peer.py"
SEGMENTS = (
    "common.py",
    "codex.py",
    "claude.py",
    "replies.py",
    "ssh.py",
    "output.py",
    "diagnostics.py",
    "adapters.py",
    "antigravity.py",
    "registry.py",
    "commands.py",
    "messages.py",
    "updates.py",
    "sending.py",
    "relay.py",
    "cli.py",
)


def render() -> bytes:
    """Return the standalone artifact without timestamps or host-specific data."""
    segments = [
        (SOURCE_DIRECTORY / name).read_bytes().strip(b"\n")
        for name in SEGMENTS
    ]
    return b"\n\n\n".join(segments) + b"\n"


def validate(source: bytes) -> None:
    if not source.startswith(b"#!/usr/bin/env python3\n"):
        raise ValueError("generated artifact must retain its Python shebang")
    if source.count(b"from __future__ import annotations") != 1:
        raise ValueError("generated artifact must contain one future import")
    compile(source, str(DEFAULT_OUTPUT), "exec")


def write_atomic(output: Path, source: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = output.stat().st_mode & 0o777 if output.exists() else 0o644
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(output.parent), prefix=".session_peer.", suffix=".tmp", delete=False
        ) as temporary:
            temporary.write(source)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, output)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the output differs instead of rewriting it",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output.resolve()
    source = render()
    validate(source)
    if args.check:
        try:
            current = output.read_bytes()
        except FileNotFoundError:
            current = None
        if current != source:
            print(
                "{} is stale; run: python3 tools/generate_session_peer.py".format(output),
                file=sys.stderr,
            )
            return 1
        return 0
    write_atomic(output, source)
    print("wrote {}".format(output.relative_to(ROOT) if output.is_relative_to(ROOT) else output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
