#!/usr/bin/env python3
"""Create a cold, internally consistent session-peer recovery snapshot."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time


BASE = Path("/var/lib/session-peer-backup/snapshots")
STACK = "session-peer-stack.target"
CONTROL_DB = Path("/var/lib/private/session-peer-control/private/control.sqlite")
FILES = (
    Path("/var/lib/private/session-peer-control/private/signing-key.pem"),
    Path("/var/lib/private/session-peer-control/private/google-account-discovery.json"),
    Path("/var/lib/private/session-peer-control/relay-public/state.json"),
    Path("/var/lib/private/session-peer-relay/private/spent-tickets.json"),
)
CONFIG = Path("/etc/session-peer-control")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def copy_regular(source: Path, root: Path) -> dict[str, object]:
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"not_regular:{source}")
    relative = Path(str(source).lstrip("/"))
    target = root / relative
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(source, target, follow_symlinks=False)
    os.chmod(target, stat.S_IMODE(info.st_mode))
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    return {
        "source": str(source),
        "snapshot": str(relative),
        "mode": oct(stat.S_IMODE(info.st_mode)),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "size": info.st_size,
        "sha256": digest(target),
    }


def database_snapshot(root: Path) -> tuple[dict[str, object], dict[str, int]]:
    relative = Path(str(CONTROL_DB).lstrip("/"))
    target = root / relative
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{CONTROL_DB}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("control_db_integrity")
        tables = {
            name: destination.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for (name,) in destination.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        }
    finally:
        destination.close()
        source.close()
    os.chmod(target, 0o600)
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    info = CONTROL_DB.stat()
    return ({
        "source": str(CONTROL_DB),
        "snapshot": str(relative),
        "mode": "0o600",
        "uid": info.st_uid,
        "gid": info.st_gid,
        "size": target.stat().st_size,
        "sha256": digest(target),
        "integrity": "ok",
    }, tables)


def signing_kid(root: Path) -> str:
    key = root / str(FILES[0]).lstrip("/")
    result = subprocess.run(
        ["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"],
        check=True, capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def wait_ready() -> None:
    deadline = time.monotonic() + 45
    units = ("session-peer-control.service", "session-peer-control-ready.service", "session-peer-relay.service")
    while time.monotonic() < deadline:
        if all(run("systemctl", "is-active", unit, check=False).returncode == 0 for unit in units):
            health = run(
                "curl", "-fsS", "-H", "Host: relay.abruption.dev",
                "http://127.0.0.1:3770/healthz", check=False,
            )
            if health.returncode == 0:
                return
        time.sleep(1)
    raise RuntimeError("stack_not_ready_after_snapshot")


def stop_stack() -> None:
    units = (
        "session-peer-relay.service",
        "session-peer-control-ready.service",
        "session-peer-control.service",
        STACK,
    )
    run("systemctl", "stop", *units)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if all(run("systemctl", "is-active", unit, check=False).returncode != 0 for unit in units):
            return
        time.sleep(0.25)
    raise RuntimeError("stack_stop_timeout")


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("root_required")
    os.umask(0o077)
    BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(BASE.parent, 0o700)
    os.chmod(BASE, 0o700)
    was_active = run("systemctl", "is-active", STACK, check=False).returncode == 0
    temporary: Path | None = None
    finalized: Path | None = None
    try:
        if was_active:
            stop_stack()
        for unit in ("session-peer-control.service", "session-peer-relay.service"):
            if run("systemctl", "is-active", unit, check=False).returncode == 0:
                raise RuntimeError(f"unit_still_active:{unit}")

        temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=BASE))
        os.chmod(temporary, 0o700)
        records: list[dict[str, object]] = []
        database, tables = database_snapshot(temporary)
        records.append(database)
        for source in FILES:
            if source.exists():
                records.append(copy_regular(source, temporary))
        for source in sorted(CONFIG.iterdir()):
            if source.is_file() and not source.is_symlink():
                records.append(copy_regular(source, temporary))

        public_state = json.loads((temporary / str(FILES[2]).lstrip("/")).read_text())
        replay_state = json.loads((temporary / str(FILES[3]).lstrip("/")).read_text())
        kid = signing_kid(temporary)
        state_kids = [key.get("kid") for key in public_state["jwks"]["keys"]]
        if kid not in state_kids:
            raise RuntimeError("signing_key_state_mismatch")
        manifest = {
            "schemaVersion": 1,
            "createdAt": int(time.time()),
            "databaseIntegrity": "ok",
            "tableCounts": tables,
            "publicStateRevision": public_state.get("revision"),
            "publicDeviceCount": len(public_state.get("devices", {})),
            "replayRevision": replay_state.get("revision"),
            "replaySpentCount": len(replay_state.get("spent", {})),
            "replayDigestPresent": bool(replay_state.get("digest")),
            "signingKid": kid,
            "files": records,
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.chmod(manifest_path, 0o600)
        with manifest_path.open("rb") as stream:
            os.fsync(stream.fileno())
        fsync_dir(temporary)
        finalized = BASE / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        os.rename(temporary, finalized)
        temporary = None
        fsync_dir(BASE)
        snapshots = sorted(path for path in BASE.iterdir() if path.is_dir() and not path.name.startswith("."))
        for old in snapshots[:-3]:
            shutil.rmtree(old)
        print(json.dumps({
            "ok": True,
            "snapshot": str(finalized),
            "publicStateRevision": manifest["publicStateRevision"],
            "replayRevision": manifest["replayRevision"],
            "replaySpentCount": manifest["replaySpentCount"],
            "databaseIntegrity": "ok",
            "tableCounts": tables,
            "signingKeyMatchesState": True,
        }, sort_keys=True))
        return 0
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)
        if was_active:
            run("systemctl", "start", STACK, check=False)
            wait_ready()


if __name__ == "__main__":
    raise SystemExit(main())
