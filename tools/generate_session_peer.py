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
    "target_generation.py",
    "replies.py",
    "ssh.py",
    "output.py",
    "diagnostics.py",
    "adapters.py",
    "antigravity.py",
    "registry.py",
    "commands.py",
    "messages.py",
    "release_verification.py",
    "updates.py",
    "handoff_stdin.py",
    "handoff.py",
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
    # Keep the installer's pre-execution trust gate identical to the runtime.
    installer = ROOT / "install.sh"
    # Source distributions deliberately omit the installer, but retain this tool.
    if installer.is_file():
        text = installer.read_text(encoding="utf-8")
        start_marker = "    python3 - \"$1\" <<'SESSION_PEER_RELEASE_VERIFIER'\n"
        end_marker = "\ntry:\n    print(verified_release_download(Path(sys.argv[1]), include_support=True))"
        start = text.index(start_marker) + len(start_marker)
        end = text.index(end_marker, start)
        verifier = (SOURCE_DIRECTORY / "release_verification.py").read_text(encoding="utf-8").rstrip()
        expected_installer = text[:start] + verifier + "\n" + text[end:]
        if args.check and text != expected_installer:
            print("install.sh verifier is stale; run: python3 tools/generate_session_peer.py", file=sys.stderr)
            return 1
        if not args.check and text != expected_installer:
            write_atomic(installer, expected_installer.encode("utf-8"))
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
