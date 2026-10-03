#!/usr/bin/env python3
"""Download only the attested, already locked release inputs for PyPI."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "session_peer_core"))
from release_verification import (RELEASE_REPOSITORY, ReleaseVerificationError,
                                  release_attest, release_read,
                                  verified_release_download)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir()
    try:
        version = verified_release_download(args.output, tag=args.tag, include_support=True,
                                            event_release=True, expected_commit=args.expected_sha)
        commit = args.expected_sha
        entries = dict((line.split("  ")[1], line.split("  ")[0])
                       for line in (args.output / "SHA256SUMS").read_text().splitlines())
        for name in (f"session_peer-{version}-py3-none-any.whl", f"session_peer-{version}.tar.gz"):
            data = release_read(f"https://github.com/{RELEASE_REPOSITORY}/releases/download/{args.tag}/{name}",
                                32 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != entries[name]:
                raise ReleaseVerificationError("package checksum mismatch: " + name)
            path = args.output / name
            path.write_bytes(data)
            release_attest(path, commit)
    except (ReleaseVerificationError, OSError, ValueError) as error:
        print("release verification failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
