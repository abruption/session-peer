#!/usr/bin/env python3
"""session-peer — message Claude Code and Codex sessions locally or over SSH.

Claude uses its native inbox socket/pipe; Codex uses its queue CLI. SSH runs the
same standard-library-only script on the destination, without a remote install.
Successful submission is not evidence of consumption or acknowledgement.
"""

# Generated into session_peer.py by tools/generate_session_peer.py. Edit the
# canonical segments in session_peer_core/, then regenerate the standalone file.

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
from datetime import datetime, timezone
import errno
import getpass
from importlib import metadata
import json
import os
import re
import selectors
import signal
import shlex
import socket
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NamedTuple, TypedDict

try:
    import fcntl
except ImportError:  # Native Windows uses its own read-only writer inspection.
    fcntl = None

__version__ = "1.0.0rc3"
GITHUB_REPO = "abruption/session-peer"

# Claude Code refuses a same-machine message once its serialized form passes
# about a million characters, so fail here rather than at the far end.
MAX_MESSAGE_CHARS = 1_000_000

# Over SSH the message travels as a command-line argument, so it meets Linux's
# MAX_ARG_STRLEN (128 KB per argument) long before the cap above. base64 costs
# 4/3, and the rest of the command needs room, so keep well under it.
MAX_REMOTE_MESSAGE_CHARS = 90_000
CONNECT_TIMEOUT = 10.0
DRAIN_TIMEOUT = 2.0
DETECT_TIMEOUT = 3.0
CODEX_QUEUE_TIMEOUT = 30.0
MAX_CODEX_MESSAGE_BYTES = 32 * 1024
CODEX_HOME_STABILITY_SECONDS = 0.25
UPDATE_CACHE_SCHEMA_VERSION = 1
UPDATE_CACHE_TTL_SECONDS = 24 * 60 * 60
UPDATE_REFRESH_LOCK_SECONDS = 5 * 60
UPDATE_CACHE_MAX_BYTES = 4096
UPDATE_NOTICE_ENV = "SESSION_PEER_NO_UPDATE_NOTICE"
UPDATE_REFRESH_ARG = "--_refresh-update-cache"
REPLY_ADDRESS_SCHEME = "session-peer"
REPLY_ADDRESS_VERSION = "v1"
MAX_REPLY_ADDRESS_CHARS = 4096

# Tailscale hands out addresses from the CGNAT range, 100.64.0.0/10. Matching on
# "100." alone would also catch ordinary public addresses like 100.200.x.x.
TAILNET_SECOND_OCTET = range(64, 128)

EXIT_ERROR = 1
EXIT_NO_TARGET = 2

_CLIENT_UPDATE_NOTICE: dict | None = None
_IDENTITY_UNSET = object()


class CcPeerError(Exception):
    """Anything the user should see as a one-line failure."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class NoTargetError(CcPeerError):
    """A requested saved session cannot be resolved."""


# --------------------------------------------------------------------------
# Codex discovery, home ownership, queue submission and wake.
# --------------------------------------------------------------------------


def codex_home(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "codex_home", None) or os.environ.get("CODEX_HOME")
                or Path.home() / ".codex").expanduser().resolve()


def configured_codex_home_paths() -> list[Path]:
    """Parse only explicitly configured candidates; never enumerate the disk."""
    configured = os.environ.get("SESSION_PEER_CODEX_HOMES")
    if configured is None:
        return []
    try:
        paths = json.loads(configured)
    except ValueError as exc:
        raise CcPeerError("SESSION_PEER_CODEX_HOMES must be a JSON array of absolute home paths; "
                          "fix it or select --codex-home explicitly") from exc
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p.strip() for p in paths):
        raise CcPeerError("SESSION_PEER_CODEX_HOMES must be a JSON array of non-empty absolute home paths; "
                          "fix it or select --codex-home explicitly")
    result = [Path(value).expanduser() for value in paths]
    if any(not path.is_absolute() for path in result):
        raise CcPeerError("SESSION_PEER_CODEX_HOMES paths must be absolute (or start with ~/); "
                          "fix it or select --codex-home explicitly")
    return result


def codex_listing_candidates(args: argparse.Namespace) -> tuple[list[dict], list[dict]]:
    """Best-effort listing inventory. Send's strict inventory remains separate."""
    homes: dict[str, dict] = {}
    errors = []

    def add(path: Path, source: str, required: bool) -> None:
        try:
            canonical = str(path.expanduser().resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append({"source": source, "path": str(path), "code": "home_resolution_failed", "error": str(exc)})
            return
        if canonical not in homes:
            homes[canonical] = {"codexHome": canonical,
                                "stateDb": str(Path(canonical) / "state_5.sqlite"),
                                "sources": [], "required": False}
        item = homes[canonical]
        if source not in item["sources"]:
            item["sources"].append(source)
        item["required"] |= required

    explicit = getattr(args, "codex_home", None)
    if explicit:
        add(Path(explicit), "argument", True)
        return list(homes.values()), errors
    add(Path.home() / ".codex", "default", False)
    if os.environ.get("CODEX_HOME"):
        add(Path(os.environ["CODEX_HOME"]), "environment", True)
    if sys.platform == "darwin":
        accounts = Path.home() / "Library/Application Support/orca/codex-accounts"
        try:
            entries = sorted(accounts.iterdir())
        except FileNotFoundError:
            entries = []
        except OSError as exc:
            entries = []
            errors.append({"source": "orca", "path": str(accounts),
                           "code": "candidate_enumeration_failed", "error": str(exc)})
        for account in entries:
            add(account / "home", "orca", False)
    try:
        for path in configured_codex_home_paths():
            add(path, "configured", True)
    except (CcPeerError, OSError, RuntimeError, ValueError) as exc:
        errors.append({"source": "configured", "code": "invalid_home_configuration", "error": str(exc)})
    return list(homes.values()), errors


def collect_codex_listing(args: argparse.Namespace) -> dict:
    homes, errors = codex_listing_candidates(args)
    sessions = []
    diagnostics = []
    for candidate in homes:
        item = {key: value for key, value in candidate.items() if key != "required"}
        db = Path(item["stateDb"])
        try:
            try:
                mode = db.stat().st_mode
            except (FileNotFoundError, NotADirectoryError):
                if candidate["required"]:
                    item.update(status="error", code="state_db_missing", error=f"Codex state DB not found at {db}")
                else:
                    item.update(status="absent", code="state_db_absent")
                diagnostics.append(item)
                continue
            if not stat.S_ISREG(mode):
                item.update(status="error", code="state_db_not_regular", error=f"Codex state DB is not a regular file: {db}")
                diagnostics.append(item)
                continue
            home_args = argparse.Namespace(**vars(args))
            home_args.codex_home = item["codexHome"]
            rows = discover_codex(home_args)
            if any(not isinstance(row["updatedAt"], (int, float)) or
                   not isinstance(row["id"], str) or not row["id"] for row in rows):
                raise CcPeerError("Unsupported Codex row; expected a thread ID and numeric updated_at")
            sessions.extend(rows)
            item.update(status="ok", sessionCount=len(rows))
        except PermissionError as exc:
            item.update(status="error", code="permission_denied", error=str(exc))
        except (CcPeerError, OSError, RuntimeError, ValueError) as exc:
            item.update(status="error", code="state_db_read_failed", error=str(exc))
        diagnostics.append(item)
    failed = bool(errors) or any(item["status"] == "error" for item in diagnostics)
    status = "error" if failed else ("ok" if any(item["status"] == "ok" for item in diagnostics) else "not_installed")
    discovery = {"status": status, "homes": diagnostics}
    if errors:
        discovery["errors"] = errors
    if failed:
        discovery["error"] = "Codex home discovery is incomplete; inspect homes and errors"
    sessions.sort(key=lambda row: (-row["updatedAt"], row["codexHome"], row["id"]))
    result = {"sessions": sessions, "discovery": discovery}
    if len(homes) == 1 and not errors:
        result["codexHome"] = homes[0]["codexHome"]
    return result


def known_codex_homes(selected: Path) -> list[Path]:
    """Bounded destination-side inventory, not process/liveness detection.

    Only existing default/Orca DBs are auto-discovered. Configured additional
    homes must not be silently skipped if their DB is missing. Do not use glob:
    some Python versions suppress scanning errors that should fail closed.
    """
    homes = [selected]

    def add_existing(home: Path) -> None:
        try:
            mode = (home / "state_5.sqlite").stat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            return
        if not stat.S_ISREG(mode):
            raise CcPeerError(f"Codex state DB is not a regular file in {home}; select --codex-home explicitly")
        homes.append(home.resolve())

    try:
        add_existing(Path.home() / ".codex")
        if sys.platform == "darwin":
            accounts = Path.home() / "Library/Application Support/orca/codex-accounts"
            try:
                entries = sorted(accounts.iterdir())
            except FileNotFoundError:
                entries = []
            for account in entries:
                add_existing(account / "home")

        homes.extend(path.resolve() for path in configured_codex_home_paths())
    except (OSError, RuntimeError, ValueError) as exc:
        raise CcPeerError(f"Cannot inspect Codex homes: {exc}; select --codex-home explicitly") from exc
    return list(dict.fromkeys(homes))  # resolved aliases do not create ambiguity


def _codex_thread_is_saved(home: Path, thread_id: str) -> bool:
    db = home / "state_5.sqlite"
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=3)
    try:
        conn.execute("PRAGMA query_only=ON")
        return conn.execute(
            "SELECT 1 FROM threads WHERE id = ? LIMIT 1", (thread_id,)
        ).fetchone() is not None
    finally:
        conn.close()


def _codex_lock_snapshot(path: Path) -> tuple[int, int, int, int] | None:
    try:
        value = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _windows_probe_lock(descriptor: int) -> tuple[str, str]:
    """Probe the native byte-range lock without writing or truncating the file."""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = [("internal", ctypes.c_size_t), ("internalHigh", ctypes.c_size_t),
                    ("offset", wintypes.DWORD), ("offsetHigh", wintypes.DWORD),
                    ("event", wintypes.HANDLE)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
    kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.POINTER(Overlapped)]
    handle, overlap = msvcrt.get_osfhandle(descriptor), Overlapped()
    # FAIL_IMMEDIATELY | EXCLUSIVE; cover Codex's full-file lock range.
    if not kernel.LockFileEx(handle, 3, 0, 0xffffffff, 0xffffffff, ctypes.byref(overlap)):
        if ctypes.get_last_error() == 33:  # ERROR_LOCK_VIOLATION, not access denied
            return "held", "kernel_lock_held"
        return "unknown", "lock_probe_failed"
    if not kernel.UnlockFileEx(handle, 0, 0xffffffff, 0xffffffff, ctypes.byref(overlap)):
        return "unknown", "lock_probe_release_failed"
    return "free", "kernel_lock_free"


# A subprocess bounds Restart Manager inspection and works for streamed standalone
# execution too. No process arguments, credentials, shutdown or restart operations.
_WINDOWS_PROCESS_INSPECTOR = r'''
import ctypes as c
from ctypes import wintypes as w
import json, ntpath, sys

class Unique(c.Structure):
    _fields_ = [('pid', w.DWORD), ('start', w.FILETIME)]
class Process(c.Structure):
    _fields_ = [('process', Unique), ('app', w.WCHAR * 256), ('service', w.WCHAR * 64),
                ('kind', w.DWORD), ('status', w.ULONG), ('session', w.DWORD), ('restartable', w.BOOL)]
class TokenUser(c.Structure):
    _fields_ = [('sid', w.LPVOID), ('attributes', w.DWORD)]

k = c.WinDLL('kernel32', use_last_error=True)
a = c.WinDLL('advapi32', use_last_error=True)
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.CloseHandle.argtypes = [w.HANDLE]
k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
k.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
k.LocalFree.argtypes = [w.HLOCAL]
k.LocalFree.restype = w.HLOCAL
a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
a.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, w.LPVOID, w.DWORD, c.POINTER(w.DWORD)]
a.ConvertSidToStringSidW.argtypes = [w.LPVOID, c.POINTER(w.LPWSTR)]

def checked(value):
    if not value: raise OSError('native process inspection failed')

def identity(pid, expected_start=None):
    handle = k.OpenProcess(0x1000, False, pid)
    checked(handle)
    try:
        creation, end, kernel, user = (w.FILETIME() for _ in range(4))
        checked(k.GetProcessTimes(handle, c.byref(creation), c.byref(end), c.byref(kernel), c.byref(user)))
        start = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        if expected_start is not None and expected_start != start: raise ValueError('pid reused')
        image, size = c.create_unicode_buffer(32768), w.DWORD(32768)
        checked(k.QueryFullProcessImageNameW(handle, 0, image, c.byref(size)))
        token = w.HANDLE()
        checked(a.OpenProcessToken(handle, 8, c.byref(token)))
        try:
            needed = w.DWORD()
            a.GetTokenInformation(token, 1, None, 0, c.byref(needed))
            if not 0 < needed.value <= 65536: raise ValueError('invalid token info size')
            buffer = c.create_string_buffer(needed.value)
            checked(a.GetTokenInformation(token, 1, buffer, needed.value, c.byref(needed)))
            sid = c.cast(buffer, c.POINTER(TokenUser)).contents.sid
            text = w.LPWSTR()
            checked(a.ConvertSidToStringSidW(sid, c.byref(text)))
            try: uid = text.value
            finally: k.LocalFree(c.cast(text, w.HLOCAL))
        finally: k.CloseHandle(token)
        return {'pid': pid, 'uid': uid, 'command': ntpath.basename(image.value), 'startTime': str(start)}
    finally: k.CloseHandle(handle)

def openers(path):
    rm = c.WinDLL('Rstrtmgr')
    rm.RmStartSession.argtypes = [c.POINTER(w.DWORD), w.DWORD, w.LPWSTR]
    rm.RmRegisterResources.argtypes = [w.DWORD, w.UINT, c.POINTER(w.LPCWSTR), w.UINT, c.POINTER(Unique), w.UINT, c.POINTER(w.LPCWSTR)]
    rm.RmGetList.argtypes = [w.DWORD, c.POINTER(w.UINT), c.POINTER(w.UINT), c.POINTER(Process), c.POINTER(w.DWORD)]
    rm.RmEndSession.argtypes = [w.DWORD]
    session, key = w.DWORD(), c.create_unicode_buffer(33)
    checked(rm.RmStartSession(c.byref(session), 0, key) == 0)
    try:
        files = (w.LPCWSTR * 1)(path)
        checked(rm.RmRegisterResources(session, 1, files, 0, None, 0, None) == 0)
        needed, count, reasons = w.UINT(), w.UINT(128), w.DWORD()
        rows = (Process * 128)()
        checked(rm.RmGetList(session, c.byref(needed), c.byref(count), rows, c.byref(reasons)) == 0)
        if count.value > 128: raise ValueError('too many owners')
        return [identity(row.process.pid, (row.process.start.dwHighDateTime << 32) | row.process.start.dwLowDateTime)
                for row in rows[:count.value]]
    finally: rm.RmEndSession(session)

try:
    result = [identity(int(sys.argv[2]))] if sys.argv[1] == 'identity' else openers(sys.argv[2])
    print(json.dumps(result))
except Exception:
    sys.exit(1)
'''


def _windows_process_inspect(mode: str, value: str) -> list[dict] | None:
    try:
        done = subprocess.run(
            [sys.executable, "-c", _WINDOWS_PROCESS_INSPECTOR, mode, value],
            capture_output=True, encoding="utf-8", timeout=DETECT_TIMEOUT,
        )
        if done.returncode or len(done.stdout) > 64 * 1024:
            return None
        rows = json.loads(done.stdout)
        if not isinstance(rows, list) or len(rows) > 128:
            return None
        if any(not isinstance(row, dict) or type(row.get("pid")) is not int
               or row["pid"] <= 0 or any(not isinstance(row.get(key), str) or not row[key]
                                        for key in ("uid", "command", "startTime")) for row in rows):
            return None
        return rows
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _codex_current_user():
    if sys.platform == "win32":
        rows = _windows_process_inspect("identity", str(os.getpid()))
        return rows[0]["uid"] if rows and len(rows) == 1 else None
    return os.getuid() if hasattr(os, "getuid") else None


def probe_codex_writer_lock(path: Path) -> tuple[str, str]:
    """Probe Codex's real advisory lock without changing the lock file."""
    try:
        before = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return "absent", "lock_absent"
    except OSError:
        return "unknown", "lock_stat_failed"
    if stat.S_ISLNK(before.st_mode):
        return "unknown", "lock_symlink"
    if not stat.S_ISREG(before.st_mode):
        return "unknown", "lock_not_regular"
    if fcntl is None and sys.platform != "win32":
        return "unknown", "lock_probe_unsupported"

    descriptor = None
    try:
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            return "unknown", "lock_changed_while_opening"
        if sys.platform == "win32":
            return _windows_probe_lock(descriptor)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return "held", "kernel_lock_held"
            return "unknown", "lock_probe_failed"
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            return "unknown", "lock_probe_release_failed"
        return "free", "kernel_lock_free"
    except OSError:
        return "unknown", "lock_open_failed"
    finally:
        if descriptor is not None:
            os.close(descriptor)


def parse_lsof_processes(output: str) -> list[dict]:
    """Parse lsof's NUL/newline-delimited PID, command, and UID fields."""
    processes: dict[int, dict] = {}
    current = None
    for token in re.split(r"[\0\n]", output):
        if len(token) < 2:
            continue
        field, value = token[0], token[1:].strip()
        if field == "p":
            try:
                pid = int(value)
            except ValueError:
                current = None
                continue
            if pid <= 0:
                current = None
                continue
            current = processes.setdefault(pid, {"pid": pid, "command": None, "uid": None})
        elif field == "c" and current is not None:
            current["command"] = value or None
        elif field == "u" and current is not None:
            try:
                current["uid"] = int(value)
            except ValueError:
                current["uid"] = None
    return [processes[pid] for pid in sorted(processes)]


def _lsof_executable() -> str | None:
    for candidate in ("/usr/sbin/lsof", "/usr/bin/lsof"):
        if Path(candidate).is_file():
            return candidate
    return shutil.which("lsof")


def _process_start_time(pid: int) -> str | None:
    try:
        env = os.environ.copy()
        # ps formats lstart according to LC_TIME.  Bridges may be launched by
        # an interactive TUI with a different locale from relay workers, so a
        # localized value is not a stable PID-reuse identity.
        env["LC_ALL"] = "C"
        done = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="], capture_output=True,
            encoding="utf-8", errors="replace", timeout=DETECT_TIMEOUT, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = done.stdout.strip() if done.returncode == 0 else ""
    return value or None


def _codex_lock_openers(path: Path) -> tuple[list[dict], str | None]:
    if sys.platform == "win32":
        rows = _windows_process_inspect("openers", str(path))
        return (rows, None) if rows is not None else ([], "windows_owner_inspection_failed")
    executable = _lsof_executable()
    if executable is None:
        return [], "lsof_unavailable"
    try:
        done = subprocess.run(
            [executable, "-nP", "-F0pcu", "--", str(path)], capture_output=True,
            encoding="utf-8", errors="replace", timeout=DETECT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return [], "lsof_failed"
    processes = parse_lsof_processes(done.stdout)
    if done.returncode not in (0, 1) or (done.returncode == 1 and processes):
        return processes, "lsof_failed"
    for process in processes:
        process["startTime"] = _process_start_time(process["pid"])
    return processes, None


def _codex_lock_sample(path: Path) -> dict:
    writer_lock, probe_reason = probe_codex_writer_lock(path)
    openers, opener_error = _codex_lock_openers(path) if writer_lock == "held" else ([], None)
    return {
        "snapshot": _codex_lock_snapshot(path),
        "writerLock": writer_lock,
        "probeReason": probe_reason,
        "openers": openers,
        "openerError": opener_error,
    }


def inspect_codex_writer(home: Path, thread_id: str) -> dict:
    """Classify one candidate home from bounded, UUID-specific lock evidence."""
    lock_path = home / "thread-writer-locks" / f"{thread_id}.lock"
    before = _codex_lock_sample(lock_path)
    if before["writerLock"] != "held":
        activity = "inactive" if before["writerLock"] in ("absent", "free") else "unknown"
        return {"activity": activity, "writerLock": before["writerLock"],
                "reason": before["probeReason"]}

    time.sleep(CODEX_HOME_STABILITY_SECONDS)
    after = _codex_lock_sample(lock_path)
    result = {"activity": "unknown", "writerLock": after["writerLock"]}
    if before["snapshot"] != after["snapshot"]:
        return {**result, "reason": "lock_file_changed"}
    if after["writerLock"] != "held":
        return {**result, "reason": "lock_state_changed"}
    if before["openerError"] or after["openerError"]:
        return {**result, "reason": before["openerError"] or after["openerError"]}
    if len(before["openers"]) != 1 or len(after["openers"]) != 1:
        return {**result, "reason": "lock_owner_not_unique"}

    first, second = before["openers"][0], after["openers"][0]
    identity = ("pid", "uid", "command", "startTime")
    if any(first.get(key) != second.get(key) for key in identity):
        return {**result, "reason": "lock_owner_changed"}
    if first.get("startTime") is None:
        return {**result, "reason": "lock_owner_start_time_unknown"}
    current_uid = _codex_current_user()
    if current_uid is None or first.get("uid") != current_uid:
        return {**result, "reason": "lock_owner_wrong_user"}
    command = str(first.get("command") or "").lower()
    if sys.platform == "win32" and command.endswith(".exe"):
        command = command[:-4]
    if command != "codex" and not command.startswith("codex-"):
        return {**result, "reason": "lock_owner_not_codex"}
    return {
        "activity": "live_writer", "writerLock": "held",
        "ownerPid": first["pid"], "ownerStable": True,
        "ownerStartTime": first["startTime"],
        "reason": "stable_live_writer",
    }


def _home_resolution(status: str, selected: Path | None, reason: str,
                     candidates: list[dict]) -> dict:
    return {
        "schemaVersion": 1,
        "status": status,
        "selected": str(selected) if selected is not None else None,
        "reason": reason,
        "candidates": candidates,
    }


def resolve_codex_home(args: argparse.Namespace, selected: Path,
                       thread_id: str) -> tuple[Path, dict]:
    """Select a destination home or fail closed with structured evidence."""
    explicit = bool(getattr(args, "codex_home", None))
    inactive_opt_in = bool(getattr(args, "allow_inactive_codex_home", False))
    wake = bool(getattr(args, "wake", False))
    if inactive_opt_in and not explicit:
        resolution = _home_resolution(
            "unknown", None, "inactive_opt_in_requires_explicit_home", []
        )
        raise CcPeerError(
            "--allow-inactive-codex-home requires --codex-home; nothing queued.",
            {"codexHomeResolution": resolution},
        )
    homes = known_codex_homes(selected)
    candidates = [
        {"codexHome": str(home), "savedThread": None,
         "writerLock": "not_checked", "reason": "not_inspected"}
        for home in homes
    ]
    for home, candidate in zip(homes, candidates):
        db = home / "state_5.sqlite"
        if not db.is_file():
            candidate["savedThread"] = False
            candidate["reason"] = "state_db_absent"
            if home == selected:
                continue
            resolution = _home_resolution(
                "unknown", None, "home_inventory_unreadable", candidates
            )
            raise CcPeerError(
                f"Cannot check Codex home {home}: state_5.sqlite is absent; "
                "nothing queued.", {"codexHomeResolution": resolution},
            )
        try:
            candidate["savedThread"] = _codex_thread_is_saved(home, thread_id)
        except sqlite3.Error as exc:
            candidate["reason"] = "state_db_unreadable"
            resolution = _home_resolution(
                "unknown", None, "home_inventory_unreadable", candidates
            )
            raise CcPeerError(
                f"Cannot check Codex home {home}: {exc}; select --codex-home "
                "explicitly before sending",
                {"codexHomeResolution": resolution},
            ) from exc
    matches = [candidate for candidate in candidates if candidate["savedThread"]]
    if not matches:
        resolution = _home_resolution(
            "unknown", None, "thread_not_saved_in_known_homes", candidates
        )
        raise NoTargetError(
            f"No saved Codex thread {thread_id} in known homes; nothing queued.",
            {"codexHomeResolution": resolution},
        )

    by_home = {str(home): home for home in homes}
    for candidate in matches:
        candidate.update(inspect_codex_writer(by_home[candidate["codexHome"]], thread_id))
    live = [candidate for candidate in matches if candidate.get("activity") == "live_writer"]
    unknown = any(candidate.get("activity") == "unknown" for candidate in matches)
    paths = ", ".join(candidate["codexHome"] for candidate in matches)
    if unknown:
        resolution = _home_resolution(
            "unknown", None, "active_writer_unverified", candidates
        )
        raise CcPeerError(
            f"Cannot verify every Codex writer for thread {thread_id} in homes: {paths}; "
            "nothing queued.", {"codexHomeResolution": resolution},
        )
    if len(live) > 1:
        resolution = _home_resolution(
            "ambiguous", None, "multiple_live_writers", candidates
        )
        raise CcPeerError(
            f"Multiple live Codex writers exist for thread {thread_id} in homes: {paths}; "
            "nothing queued.", {"codexHomeResolution": resolution},
        )
    if len(live) == 1:
        active = by_home[live[0]["codexHome"]]
        if explicit and active != selected:
            resolution = _home_resolution(
                "ambiguous", None, "explicit_home_conflicts_with_live_writer", candidates
            )
            raise CcPeerError(
                f"Explicit Codex home {selected} is not the unique live writer for thread "
                f"{thread_id}; the live writer is in {active}. Nothing queued and the home "
                "was not changed automatically.",
                {"codexHomeResolution": resolution},
            )
        status = "explicit" if explicit else "selected"
        reason = "explicit_live_writer" if explicit else "single_stable_live_writer"
        return active, _home_resolution(status, active, reason, candidates)

    if explicit and str(selected) not in {candidate["codexHome"] for candidate in matches}:
        resolution = _home_resolution(
            "unknown", None, "thread_not_saved_in_explicit_home", candidates
        )
        raise NoTargetError(
            f"No saved Codex thread {thread_id} in explicit home {selected}; nothing queued.",
            {"codexHomeResolution": resolution},
        )
    if explicit and (inactive_opt_in or wake):
        reason = "explicit_inactive_wake" if wake else "explicit_inactive_opt_in"
        return selected, _home_resolution("explicit", selected, reason, candidates)

    resolution = _home_resolution(
        "ambiguous", None, "inactive_queue_requires_opt_in", candidates
    )
    raise CcPeerError(
        f"All saved copies of Codex thread {thread_id} are inactive in homes: {paths}. "
        "To queue for a future resume, select one with --codex-home and add "
        "--allow-inactive-codex-home; nothing queued.",
        {"codexHomeResolution": resolution},
    )


def revalidate_codex_home(root: Path, thread_id: str, resolution: dict) -> None:
    reason = resolution.get("reason")
    live_selection = reason in ("single_stable_live_writer", "explicit_live_writer")
    inactive_selection = reason in ("explicit_inactive_opt_in", "explicit_inactive_wake")
    if not (live_selection or inactive_selection):
        return
    previous = next(
        candidate for candidate in resolution["candidates"]
        if candidate["codexHome"] == str(root)
    )
    updated = []
    for candidate in resolution["candidates"]:
        current = (
            inspect_codex_writer(Path(candidate["codexHome"]), thread_id)
            if candidate.get("savedThread")
            else candidate
        )
        updated.append({**candidate, **current})

    selected = next(
        candidate for candidate in updated if candidate["codexHome"] == str(root)
    )
    competitors = [
        candidate for candidate in updated
        if candidate.get("savedThread") and candidate["codexHome"] != str(root)
    ]
    if live_selection:
        if (
            (selected.get("activity"), selected.get("writerLock"),
             selected.get("ownerPid"), selected.get("ownerStartTime"))
            == ("live_writer", "held", previous.get("ownerPid"),
                previous.get("ownerStartTime"))
            and all(candidate.get("activity") == "inactive" for candidate in competitors)
        ):
            return
    elif (
        selected.get("activity") == "inactive"
        and all(candidate.get("activity") == "inactive" for candidate in competitors)
    ):
        return
    failed = _home_resolution(
        "unknown", None, "writer_evidence_changed_before_queue", updated
    )
    raise CcPeerError(
        f"Codex writer evidence for {thread_id} changed before queue submission; nothing queued. "
        "Retry discovery or select --codex-home explicitly.",
        {"codexHomeResolution": failed},
    )


def codex_executable(args: argparse.Namespace) -> str:
    requested = getattr(args, "codex_bin", None) or "codex"
    executable = shutil.which(os.path.expanduser(requested))
    if executable is None:
        raise CcPeerError(f"Codex executable not found: {requested!r}; set --codex-bin on the destination")
    return str(Path(executable).absolute())


def discover_codex(args: argparse.Namespace) -> list[dict]:
    """Experimental saved-session discovery; never write Codex's internal DB."""
    root = codex_home(args)
    db = root / "state_5.sqlite"
    if not db.is_file():
        raise CcPeerError(f"Codex state_5.sqlite not found in {root}; check --codex-home (tested with CLI 0.154.0)")
    try:
        conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            conn.execute("PRAGMA query_only=ON")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
            required = {"id", "title", "cwd", "updated_at", "archived", "rollout_path"}
            if not required <= columns:
                raise CcPeerError("Unsupported Codex threads schema; missing: " + ", ".join(sorted(required - columns)))
            name = "COALESCE(NULLIF(name, ''), NULLIF(title, ''), id)" if "name" in columns else "COALESCE(NULLIF(title, ''), id)"
            query = f"SELECT id, {name}, cwd, updated_at, archived FROM threads"
            if not getattr(args, "all", False):
                query += " WHERE archived = 0"
            query += " ORDER BY updated_at DESC, id ASC"
            return [{"agent": "codex", "id": r[0], "name": str(r[1]).splitlines()[0][:120], "cwd": r[2],
                     "updatedAt": r[3], "archived": bool(r[4]),
                     "codexHome": str(root), "stateDb": str(db)} for r in conn.execute(query)]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise CcPeerError(f"Cannot read Codex state DB at {db}: {exc}") from exc


def codex_thread(target: str) -> str:
    value = target.removeprefix("codex:")
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise CcPeerError("Codex target must be codex:<full-thread-uuid>")
    return str(uuid.UUID(value))


def check_codex_message(text: str) -> None:
    size = len(text.encode("utf-8"))
    if "\x00" in text:
        raise CcPeerError("Codex messages cannot contain NUL characters (CLI argument limitation)")
    if size > MAX_CODEX_MESSAGE_BYTES:
        raise CcPeerError(f"Codex message is {size} UTF-8 bytes; session-peer limit is {MAX_CODEX_MESSAGE_BYTES}, including headers")


def _queue_codex(args: argparse.Namespace, text: str) -> dict:
    thread_id = codex_thread(args.to)
    check_codex_message(text)
    executable = codex_executable(args)
    selected = codex_home(args)
    root, home_resolution = resolve_codex_home(args, selected, thread_id)
    result = {"ok": True, "target": {"agent": "codex", "id": thread_id},
              "chars": len(text), "dryRun": args.dry_run,
              "codexHome": str(root), "submitted": not args.dry_run,
              "consumptionConfirmed": False,
              "status": "validated" if args.dry_run else "queued",
              "codexHomeResolution": home_resolution}
    if args.dry_run:
        discovery_args = argparse.Namespace(codex_home=str(root), all=True)
        if not any(s["id"] == thread_id for s in discover_codex(discovery_args)):
            raise NoTargetError(f"No saved Codex thread {thread_id} in {root}")
        return result
    revalidate_codex_home(root, thread_id, home_resolution)
    # Relay receivers on WSL inspect the native Windows state DB through its
    # mounted POSIX path, but the native codex.exe process needs the Windows
    # spelling of that same home.  This private adapter value is derived from
    # operator policy; it is never accepted from a paired request.
    process_home = getattr(args, "codex_native_home", None) or str(root)
    env = dict(os.environ, CODEX_HOME=process_home)
    try:
        done = subprocess.run([executable, "queue", "--thread", thread_id, "--message", text],
                              env=env, capture_output=True, encoding="utf-8", errors="replace",
                              timeout=CODEX_QUEUE_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise CcPeerError("Codex queue timed out; submission outcome unknown. Check the target queue before retrying.") from exc
    except OSError as exc:
        raise CcPeerError(f"Could not execute Codex queue: {exc}") from exc
    if done.returncode:
        detail = (done.stderr.strip() or done.stdout.strip())[:2000]
        raise CcPeerError(f"Codex queue failed (exit {done.returncode}, home {root}): {detail}")
    match = re.search(r"^Queued message (\S+) for thread " + re.escape(thread_id) + r"\.$", done.stdout, re.MULTILINE)
    if match:
        result["queueId"] = match.group(1)
    return result


# Wake uses the native app-server lifecycle: unlike exec resume, thread/resume
# does not insert a second user prompt. Supported versions are evidence-based.
CODEX_WAKE_VERSIONS = {"codex-cli 0.154.0"}


def wake_refused(reason: str, message: str) -> CcPeerError:
    return CcPeerError(message, {"submitted": False, "consumptionConfirmed": False,
                               "wake": {"status": "refused", "reason": reason}})


def codex_wake_preflight(root: Path, thread_id: str, executable: str) -> dict:
    if fcntl is None or sys.platform not in ("darwin", "linux"):
        raise wake_refused("unsupported_platform", "Codex wake supports macOS/Linux only")
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                 timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise wake_refused("version_unavailable", "Cannot establish native Codex wake support") from exc
    if version not in CODEX_WAKE_VERSIONS:
        raise wake_refused("unsupported_version", f"Codex wake is not validated for {version}")
    try:
        with contextlib.closing(sqlite3.connect((root / "state_5.sqlite").as_uri() + "?mode=ro", uri=True, timeout=3)) as conn:
            conn.execute("PRAGMA query_only=ON")
            row = conn.execute("SELECT cwd, archived, rollout_path FROM threads WHERE id=?", (thread_id,)).fetchone()
    except sqlite3.Error as exc:
        raise wake_refused("state_unavailable", "Cannot read Codex wake target") from exc
    if row is None:
        raise wake_refused("missing_thread", "Codex wake target does not exist")
    cwd, archived, rollout = row
    if archived:
        raise wake_refused("archived_thread", "Archived Codex threads cannot be woken")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise wake_refused("cwd_unavailable", "Original Codex working directory is unavailable")
    if not isinstance(rollout, str) or not Path(rollout).is_file() or Path(rollout).stat().st_size == 0:
        raise wake_refused("uninitialized_thread", "Codex wake requires an initialized rollout")
    writer = inspect_codex_writer(root, thread_id)
    if writer["activity"] == "unknown":
        raise wake_refused("writer_unknown", "Cannot safely establish Codex writer ownership")
    return {"cwd": cwd, "writer": writer, "version": version}


@contextlib.contextmanager
def codex_wake_guard(root: Path, thread_id: str):
    directory = root / "session-peer" / "wake-locks"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(directory / (thread_id + ".lock"),
                 os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise wake_refused("wake_in_progress", "Another session-peer wake is in progress; nothing submitted") from exc
        yield
    finally:
        os.close(fd)


def run_codex_wake(executable: str, root: Path, thread_id: str, cwd: str, timeout: float) -> dict:
    """Resume one thread, await one turn, and own/clean up the native process."""
    process = None
    def cancelled(signum, frame):
        raise KeyboardInterrupt
    managed_signals = (signal.SIGTERM, signal.SIGHUP)
    previous_signals = {number: signal.signal(number, cancelled) for number in managed_signals}
    outcome = {"status": "unknown", "reason": "activation_outcome_unknown"}
    deadline = time.monotonic() + timeout
    try:
        # Do not stream transcript-bearing native stdout or arbitrary stderr
        # into CLI JSON. Only lifecycle states and bounded error text escape.
        with tempfile.TemporaryFile() as diagnostics:
            process = subprocess.Popen([executable, "app-server"], cwd=cwd,
                env=dict(os.environ, CODEX_HOME=str(root)), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=diagnostics, start_new_session=True)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            pending = b""
            resumed = False
            completed = False

            def send(value: dict) -> None:
                process.stdin.write((json.dumps(value) + "\n").encode())
                process.stdin.flush()

            send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "session-peer-wake", "version": __version__}}})
            try:
                while time.monotonic() < deadline:
                    ready = selector.select(max(0, deadline - time.monotonic()))
                    if not ready:
                        break
                    data = os.read(process.stdout.fileno(), 65536)
                    if not data:
                        return {"status": "failed", "reason": "native_process_exited"}
                    pending += data
                    if len(pending) > 16 * 1024 * 1024:
                        return {"status": "failed", "reason": "native_response_too_large"}
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        value = json.loads(line)
                        if "method" in value and "id" in value:
                            # Never auto-approve commands, permissions or tools.
                            send({"id": value["id"], "error": {
                                "code": -32601, "message": "Interactive approval unavailable in session-peer wake"}})
                            return {"status": "failed", "reason": "approval_required"}
                        if value.get("id") in (1, 2) and "error" in value:
                            return {"status": "failed", "reason": "native_resume_rejected",
                                    "error": str(value["error"].get("message", "Native error"))[:1000]}
                        if value.get("id") == 1:
                            send({"method": "initialized"})
                            send({"id": 2, "method": "thread/resume", "params": {
                                "threadId": thread_id, "cwd": cwd, "excludeTurns": True}})
                        elif value.get("id") == 2:
                            actual = value.get("result", {}).get("thread", {}).get("id")
                            if actual != thread_id:
                                return {"status": "failed", "reason": "native_thread_mismatch"}
                            resumed = True
                        elif value.get("method") == "turn/completed":
                            params = value.get("params", {})
                            if params.get("threadId") == thread_id:
                                turn = params.get("turn", {})
                                if turn.get("status") != "completed":
                                    return {"status": "failed", "reason": "native_turn_failed",
                                            "error": str((turn.get("error") or {}).get("message", "Native turn failed"))[:1000]}
                                completed = True
                        if resumed and completed:
                            return {"status": "completed", "reason": "native_turn_completed"}
                outcome = {"status": "timed_out", "reason": "activation_deadline_exceeded"}
            finally:
                selector.close()
    except (OSError, ValueError) as exc:
        outcome = {"status": "failed", "reason": "native_transport_failed",
                   "error": type(exc).__name__}
    finally:
        for number, handler in previous_signals.items():
            signal.signal(number, handler)
        if process is not None:
            # Keep the child unreaped until its group is stopped: a zombie
            # leader still reserves the PID even if descendants outlive it.
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                except ProcessLookupError:
                    process.wait(timeout=3)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
    return outcome


def queue_codex(args: argparse.Namespace, text: str) -> dict:
    if not getattr(args, "wake", False):
        return _queue_codex(args, text)
    thread_id = codex_thread(args.to)
    check_codex_message(text)
    try:
        root, resolution = resolve_codex_home(args, codex_home(args), thread_id)
    except CcPeerError as exc:
        resolution = exc.details.get("codexHomeResolution")
        if resolution and resolution.get("reason") == "active_writer_unverified":
            exc.details.setdefault(
                "wake", {"status": "refused", "reason": "writer_unknown"}
            )
        raise
    executable = codex_executable(args)
    preflight = codex_wake_preflight(root, thread_id, executable)
    selected = argparse.Namespace(**vars(args))
    selected.codex_home = str(root)
    if args.dry_run:
        result = _queue_codex(selected, text)
        result["wake"] = {"status": "validated", "reason": "dry_run", "cwd": preflight["cwd"]}
        return result
    with codex_wake_guard(root, thread_id):
        revalidate_codex_home(root, thread_id, resolution)
        preflight = codex_wake_preflight(root, thread_id, executable)
        result = _queue_codex(selected, text)
        result["codexHomeResolution"] = resolution
        try:
            writer = inspect_codex_writer(root, thread_id)
            if writer["activity"] == "live_writer":
                wake = {"status": "already_active", "reason": "stable_live_writer"}
            elif writer["activity"] == "unknown":
                wake = {"status": "refused", "reason": "writer_changed_after_submission"}
            else:
                wake = run_codex_wake(executable, root, thread_id, preflight["cwd"],
                                      getattr(args, "wake_timeout", 30))
        except KeyboardInterrupt:
            wake = {"status": "unknown", "reason": "activation_interrupted"}
        except Exception as exc:
            wake = {"status": "unknown", "reason": "activation_outcome_unknown", "error": type(exc).__name__}
        result["wake"] = {**wake, "cwd": preflight["cwd"]}
        result["ok"] = wake["status"] in ("completed", "already_active")
        return result


def codex_remote_options(args: argparse.Namespace) -> list[str]:
    argv = []
    for attribute, flag in (("codex_home", "--codex-home"), ("codex_bin", "--codex-bin")):
        value = getattr(args, attribute, None)
        if value:
            argv.extend([flag, value])
    if getattr(args, "wake", False):
        argv += ["--wake", "--wake-timeout", str(args.wake_timeout)]
    if getattr(args, "allow_inactive_codex_home", False):
        argv.append("--allow-inactive-codex-home")
    return argv


def render_codex(sessions: list[dict], where: str) -> str:
    rows = [f"Saved Codex sessions on {where} (execution state unknown):", "THREAD  NAME  ARCHIVED  CWD  CODEX HOME"]
    rows.extend(f"{s['id']}  {s['name']}  {s['archived']}  {s['cwd']}  {s.get('codexHome', '-')}" for s in sessions)
    return "\n".join(rows) if sessions else f"No saved Codex sessions on {where}."


def codex_submission_text(result: dict, where: str) -> str:
    home = f" (Codex home: {result['codexHome']})" if "codexHome" in result else ""
    if result.get("submitted") is False and result.get("ok") is False and "wake" in result:
        reason = result.get("error") or result["wake"].get("reason", "refused")
        return f"Codex wake refused on {where}{home}: {reason}; nothing queued."
    if result["dryRun"]:
        return f"Validated Codex thread {result['target']['id']} on {where}{home}; nothing queued (submission not guaranteed)."
    if "wake" in result:
        wake = result["wake"]
        return (f"Queued for Codex thread {result['target']['id']} on {where}{home}; "
                f"wake={wake['status']} ({wake['reason']}); consumption not confirmed. "
                f"{wake.get('error', '')} "
                f"Queue ID: {result.get('queueId', 'unknown')}. Do not resend automatically.")
    return f"Queued for Codex thread {result['target']['id']} on {where}{home}; consumption not confirmed."


# --------------------------------------------------------------------------
# Discovery. Runs on whichever machine owns the sessions — locally when there
# is no --host, inside the remote shell when there is.
# --------------------------------------------------------------------------


def sessions_dir() -> Path:
    """Where Claude Code keeps its per-session records."""
    for var in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_CONFIG_DIR"):
        root = os.environ.get(var)
        if root:
            return Path(root) / "sessions"
    return Path.home() / ".claude" / "sessions"


IS_WINDOWS = sys.platform == "win32"


def pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    if IS_WINDOWS:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def discover(include_unreachable: bool = False) -> list[dict]:
    """List this machine's Claude Code sessions.

    The socket path is read from each record, never guessed. It is not always
    under /tmp: a session may bind under $XDG_RUNTIME_DIR, or under a private
    per-user directory when Claude Code rejects the one it would have used.
    """
    found: list[dict] = []
    directory = sessions_dir()
    try:
        entries = sorted(path for path in directory.iterdir() if path.suffix == ".json")
    except FileNotFoundError:
        return found
    except OSError as exc:
        raise CcPeerError(f"Cannot read Claude sessions at {directory}: {exc}") from exc
    for record_file in entries:
        if not record_file.stem.isdigit():
            continue
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        pid = record.get("pid")
        if not isinstance(pid, int):
            continue

        sock = record.get("messagingSocketPath") or ""
        alive = pid_alive(pid)
        if IS_WINDOWS:
            has_inbox = bool(sock) and sock.startswith("\\\\.\\pipe\\")
        else:
            has_inbox = bool(sock) and Path(sock).is_socket()

        entry = {
            "agent": "claude",
            "pid": pid,
            "name": record.get("name"),
            "status": record.get("status"),
            "cwd": record.get("cwd"),
            "kind": record.get("kind"),
            "version": record.get("version"),
            "tmux": record.get("tmux"),
            "socket": sock,
            "alive": alive,
            "reachable": alive and has_inbox,
        }
        if entry["reachable"] or include_unreachable:
            found.append(entry)

    return found


def resolve_target(sessions: list[dict], target: str) -> dict:
    """Find one session by name, or by pid when the target is all digits."""
    reachable = [s for s in sessions if s["reachable"]]

    if target.isdigit():
        matches = [s for s in reachable if s["pid"] == int(target)]
    else:
        wanted = target.casefold()
        matches = [s for s in reachable if (s["name"] or "").casefold() == wanted]

    if not matches:
        known = ", ".join(sorted(s["name"] or str(s["pid"]) for s in reachable))
        raise CcPeerError(
            f"no reachable session named {target!r}"
            + (f" (reachable: {known})" if known else " (no reachable sessions)")
        )
    if len(matches) > 1:
        pids = ", ".join(str(s["pid"]) for s in matches)
        raise CcPeerError(
            f"{len(matches)} sessions answer to {target!r} (pids: {pids}) — "
            f"address one by pid instead"
        )
    return matches[0]


def check_message(text: str, remote: bool) -> None:
    """Reject a message that can't be delivered, before anything is sent.

    Kept out of post_to_socket so --dry-run and the remote path get the same
    answer as a real send: a rehearsal that passes and a send that fails is
    worse than no rehearsal.
    """
    if not text.strip():
        raise CcPeerError("refusing to send an empty message")
    if len(text) > MAX_MESSAGE_CHARS:
        raise CcPeerError(
            f"message is {len(text)} characters; the limit is {MAX_MESSAGE_CHARS}"
        )
    if remote and len(text) > MAX_REMOTE_MESSAGE_CHARS:
        raise CcPeerError(
            f"message is {len(text)} characters; over SSH the limit is "
            f"{MAX_REMOTE_MESSAGE_CHARS}, because it travels as a command-line "
            f"argument. Send it from a session on that machine to use the full "
            f"{MAX_MESSAGE_CHARS}."
        )


def _read_win_auth(pid: int) -> str | None:
    """Read the Windows auth key for a session and return the auth JSON line."""
    directory = sessions_dir()
    for key_file in directory.glob(f"{pid}.*.key"):
        try:
            data = json.loads(key_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        token = data.get("peerToken")
        if not isinstance(token, str) or not token.strip():
            continue
        # The registry schema is not the wire protocol. Windows requires a
        # first-line {"type": "auth", "token": ...}; forwarding peerToken and
        # process metadata verbatim causes the receiver to drop the connection.
        return json.dumps({"type": "auth", "token": token}, ensure_ascii=False)
    return None


def _post_to_pipe(pipe_path: str, pid: int, text: str) -> None:
    """Write one message to a Windows named pipe inbox."""
    check_message(text, remote=False)

    auth_line = _read_win_auth(pid)
    if auth_line is None:
        raise CcPeerError(f"no auth key found for pid {pid} — cannot post to Windows pipe")

    payload = json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}},
        ensure_ascii=False,
    )

    import time
    try:
        with open(pipe_path, "wb") as pipe:
            pipe.write((auth_line + "\n").encode("utf-8"))
            pipe.write((payload + "\n").encode("utf-8"))
            pipe.flush()
            time.sleep(DRAIN_TIMEOUT)
    except OSError as exc:
        raise CcPeerError(f"cannot reach inbox at {pipe_path}: {exc}") from exc


def post_to_socket(socket_path: str, text: str, pid: int = 0) -> None:
    """Write one message to a session's inbox socket.

    On macOS and Linux the {"type":"auth",...} line the docs describe is
    optional, so this sends the message on its own. On Windows, auth is
    mandatory — the token is read from the session's .key file and sent
    before the message. Claude Code closes a connection that has not sent
    a complete line within 30 seconds, so the message is built before the
    socket is opened.
    """
    if IS_WINDOWS and socket_path.startswith("\\\\.\\pipe\\"):
        _post_to_pipe(socket_path, pid, text)
        return

    check_message(text, remote=False)

    payload = json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}},
        ensure_ascii=False,
    )

    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(CONNECT_TIMEOUT)
    try:
        try:
            conn.connect(socket_path)
        except OSError as exc:
            raise CcPeerError(f"cannot reach inbox at {socket_path}: {exc}") from exc

        try:
            conn.sendall((payload + "\n").encode("utf-8"))
            conn.shutdown(socket.SHUT_WR)
            conn.settimeout(DRAIN_TIMEOUT)
            try:
                conn.recv(1)
            except OSError:
                pass
        except OSError as exc:
            raise CcPeerError(f"failed writing to {socket_path}: {exc}") from exc
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Reply address. A cross-machine message carries no reply address of its own,
# so the receiving Claude has no way to know answering is even possible. This
# appends one line saying where to send an answer.
#
# It grants nothing: the far side can only reply if it could already SSH here.
# What it adds is knowing that, which is what the receiver otherwise lacks.
# --------------------------------------------------------------------------


def is_tailnet_address(candidate: str) -> bool:
    parts = candidate.split(".")
    if len(parts) != 4 or not all(p.isdigit() and len(p) <= 3 for p in parts):
        return False
    octets = [int(p) for p in parts]
    if any(o > 255 for o in octets):
        return False
    return octets[0] == 100 and octets[1] in TAILNET_SECOND_OCTET


def _run(command: list[str]) -> str:
    try:
        done = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace", timeout=DETECT_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout


def tailscale_status() -> dict | None:
    """Return the local tailnet map when the Tailscale CLI is available."""
    commands = [["tailscale", "status", "--json"]]
    if sys.platform == "darwin":
        commands.append([
            "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
            "status", "--json",
        ])
    for command in commands:
        try:
            done = subprocess.run(
                command, capture_output=True, encoding="utf-8", errors="replace",
                timeout=DETECT_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode:
            continue
        try:
            status = json.loads(done.stdout)
        except ValueError:
            continue
        if isinstance(status, dict) and status.get("BackendState") == "Running":
            return status
    return None


def _magicdns_enabled(status: dict) -> bool:
    tailnet = status.get("CurrentTailnet")
    return isinstance(tailnet, dict) and tailnet.get("MagicDNSEnabled") is True


def _tailnet_nodes(status: dict) -> list[dict]:
    nodes = []
    own = status.get("Self")
    if isinstance(own, dict):
        nodes.append(own)
    peers = status.get("Peer")
    if isinstance(peers, dict):
        nodes.extend(peer for peer in peers.values() if isinstance(peer, dict))
    return nodes


def _node_names(node: dict) -> set[str]:
    names = set()
    dns_name = str(node.get("DNSName") or "").rstrip(".").lower()
    hostname = str(node.get("HostName") or "").rstrip(".").lower()
    if dns_name:
        names.add(dns_name)
        names.add(dns_name.split(".", 1)[0])
    if hostname:
        names.add(hostname)
    addresses = node.get("TailscaleIPs")
    if isinstance(addresses, list):
        names.update(str(address).lower() for address in addresses)
    return names


def resolve_ssh_destination(destination: str, status: dict | None = None) -> str:
    """Resolve a known online Tailscale peer's canonical MagicDNS identity.

    A destination that is not in the local tailnet map remains an ordinary SSH
    destination. Callers keep the requested value as SSH's destination alias and
    override HostName with this result, preserving Host/User/Port/IdentityFile
    configuration while connecting to the verified MagicDNS name.
    """
    check_ssh_argument(destination, "--host")
    user, separator, host = destination.rpartition("@")
    if not separator:
        user, host = "", destination
    lookup = host.strip("[]").rstrip(".").lower()
    status = tailscale_status() if status is None else status
    if not status or not _magicdns_enabled(status):
        return destination

    matches = [node for node in _tailnet_nodes(status) if lookup in _node_names(node)]
    if not matches:
        return destination
    unique = {str(node.get("ID") or node.get("PublicKey") or id(node)): node for node in matches}
    if len(unique) != 1:
        raise CcPeerError(
            f"Tailscale destination {host!r} is ambiguous; use its full MagicDNS name"
        )
    node = next(iter(unique.values()))
    dns_name = str(node.get("DNSName") or "").rstrip(".")
    if not dns_name:
        return destination
    if node.get("Online") is False:
        raise CcPeerError(f"Tailscale peer {dns_name} is offline")
    return f"{user}@{dns_name}" if user else dns_name


def is_self_ssh_destination(destination: str, status: dict | None = None) -> bool:
    """Whether an SSH destination names this OS user on this machine."""
    user, separator, host = destination.rpartition("@")
    if not separator:
        user, host = "", destination
    if user and user != getpass.getuser():
        return False
    lookup = host.strip("[]").rstrip(".").lower()
    local_names = {
        "localhost", "127.0.0.1", "::1",
        socket.gethostname().rstrip(".").lower(),
    }
    status = tailscale_status() if status is None else status
    if status:
        own = status.get("Self")
        if isinstance(own, dict):
            local_names.update(_node_names(own))
    return lookup in local_names


def detect_reply_host() -> str | None:
    """This machine's tailnet address, or None if it can't be determined.

    Prefer the canonical MagicDNS name from `tailscale status --json`. Fall back
    to a Tailscale IPv4 address for older/unavailable clients, then interfaces.
    """
    status = tailscale_status()
    if status:
        own = status.get("Self")
        if isinstance(own, dict):
            dns_name = str(own.get("DNSName") or "").rstrip(".")
            if dns_name and _magicdns_enabled(status):
                return dns_name
            addresses = own.get("TailscaleIPs")
            if isinstance(addresses, list):
                for candidate in addresses:
                    if is_tailnet_address(str(candidate)):
                        return str(candidate)
    for command in (["tailscale", "ip", "-4"], ["ip", "-4", "-o", "addr", "show"], ["ifconfig"]):
        for candidate in re.findall(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", _run(command)):
            if is_tailnet_address(candidate):
                return candidate
    return None


def own_session() -> dict | None:
    """The session this process is running inside, if any.

    Claude Code exports the session's own inbox socket path, which carries its
    pid; the registry turns that into a name. Empty when run from a plain shell.
    """
    socket_path = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    match = re.search(r"(\d+)\.sock$", socket_path)
    if not match:
        return None
    pid = int(match.group(1))
    for session in discover(include_unreachable=True):
        if session["pid"] == pid:
            return session
    return None


def sender_agent() -> dict | None:
    """The agent session running this process, when its environment says so."""
    session = own_session()
    if session is not None:
        name = session["name"] or str(session["pid"])
        return {"agent": "claude", "id": str(name).splitlines()[0], "target": str(name)}

    thread = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
    if thread:
        try:
            thread = str(uuid.UUID(thread))
        except ValueError:
            return None
        result = {"agent": "codex", "id": thread, "target": f"codex:{thread}"}
        configured_home = os.environ.get("CODEX_HOME")
        if configured_home:
            result["codexHome"] = str(Path(configured_home).expanduser().resolve())
        return result
    return agy_sender()


def configured_reply_host(explicit_host: str | None) -> str | None:
    return explicit_host or (
        os.environ.get("SESSION_PEER_REPLY_HOST") or os.environ.get("CC_PEER_REPLY_HOST")
    )


def sender_identity(explicit_host: str | None) -> dict | None:
    """Agent-qualified identity and reachable address for this session.

    Both the From: header and the Reply: line are built from this, so they
    can't drift apart. None outside a session, where there is no name to give.
    """
    identity = sender_agent()
    if identity is None:
        return None
    configured_host = configured_reply_host(explicit_host)
    host = resolve_ssh_destination(configured_host) if configured_host else detect_reply_host()
    if host and "@" not in host:
        host = f"{getpass.getuser()}@{host}"
    return {**identity, "host": host}


def _from_identity(identity: dict | None) -> str | None:
    """Format who is speaking from one already-detected identity."""
    if identity is None:
        return None
    agent, identifier, host = identity["agent"], identity["id"], identity["host"]
    # Fall back to the local hostname so this line survives even when no
    # tailnet address turns up; it is for reading, not for connecting.
    where = host or f"{getpass.getuser()}@{socket.gethostname()}"
    return f"From: {agent}:{identifier} @ {where}"


def from_header(explicit_host: str | None) -> str | None:
    """Detect and format who is speaking.

    Claude Code records an arriving peer message with `from: "unknown"` when
    it was posted to the socket directly, so without this the receiver has no
    idea who is asking — and it is told to treat the message as a teammate's
    request. Separate from the reply address on purpose: knowing the sender
    stays useful when answering isn't possible.
    """
    return _from_identity(sender_identity(explicit_host))


def wrap_message(
    text: str, explicit_host: str | None, with_from: bool, with_reply: bool,
    local_reply: bool = False, identity: dict | None | object = _IDENTITY_UNSET,
) -> str:
    """Put the body in an envelope: who sent it, and how to answer.

    Deliberately minimal. Claude Code already prefaces an arriving peer
    message and appends its own guidance about what a peer may and may not
    ask for — repeating any of that here would duplicate it in every message
    and compound with each hop. The two facts it *doesn't* have are the
    sender's identity and a working return address.
    """
    if identity is _IDENTITY_UNSET:
        identity = sender_identity(explicit_host) if with_from or with_reply else None
    header = _from_identity(identity) if with_from else None
    footer = _reply_from_identity(identity, local=local_reply) if with_reply else None
    address = reply_address(identity, local=local_reply) if with_reply else None
    body = text.strip("\n")
    parts = ([header, ""] if header else []) + [body]
    if address or footer:
        parts += ["", "---"]
        if address:
            parts.append(f"Reply-To: {address}")
        if footer:
            parts.append(footer)
    return "\n".join(parts)


def _safe_reply_value(value: str, field: str) -> str:
    if not value or len(value) > MAX_REPLY_ADDRESS_CHARS:
        raise CcPeerError(f"Reply-To {field} is empty or too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CcPeerError(f"Reply-To {field} contains a control character")
    return value


def reply_address(identity: dict | None, local: bool = False) -> str | None:
    """Return a versioned, inert address that can be passed back to --to."""
    if identity is None:
        return None
    agent = identity["agent"]
    AGENTS.get(agent)
    identifier = _safe_reply_value(str(identity["id"]), "session")
    host = identity.get("host")
    if not local and not host:
        return None
    fields = [
        ("agent", agent),
        ("session", identifier),
        ("transport", "local" if local else "ssh"),
    ]
    if not local:
        fields.append(("host", _safe_reply_value(str(host), "host")))
    codex_root = identity.get("codexHome")
    if agent == "codex" and codex_root:
        fields.append(("codexHome", _safe_reply_value(str(codex_root), "codexHome")))
    uri = urllib.parse.urlunsplit((
        REPLY_ADDRESS_SCHEME,
        REPLY_ADDRESS_VERSION,
        "/reply",
        urllib.parse.urlencode(fields),
        "",
    ))
    if len(uri) > MAX_REPLY_ADDRESS_CHARS:
        raise CcPeerError("Reply-To address is too long")
    return uri


def parse_reply_address(value: str) -> dict | None:
    """Parse a Reply-To URI as data. No field is ever evaluated as a command."""
    if not value.startswith(f"{REPLY_ADDRESS_SCHEME}:"):
        return None
    if len(value) > MAX_REPLY_ADDRESS_CHARS:
        raise CcPeerError("Reply-To address is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CcPeerError("Reply-To address contains a control character")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != REPLY_ADDRESS_SCHEME
        or parsed.netloc != REPLY_ADDRESS_VERSION
        or parsed.path != "/reply"
        or parsed.fragment
    ):
        raise CcPeerError("Reply-To must use session-peer://v1/reply without a fragment")
    if re.search(r"%(?![0-9a-fA-F]{2})", parsed.query):
        raise CcPeerError("Malformed percent escape in Reply-To query")
    try:
        pairs = urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True,
        )
    except ValueError as exc:
        raise CcPeerError(f"Malformed Reply-To query: {exc}") from exc
    allowed = {"agent", "session", "transport", "host", "codexHome"}
    fields: dict[str, str] = {}
    for key, item in pairs:
        if key not in allowed:
            raise CcPeerError(f"Unknown Reply-To field: {key}")
        if key in fields:
            raise CcPeerError(f"Duplicate Reply-To field: {key}")
        fields[key] = _safe_reply_value(item, key)
    missing = {"agent", "session", "transport"} - fields.keys()
    if missing:
        raise CcPeerError("Reply-To is missing: " + ", ".join(sorted(missing)))
    adapter = AGENTS.get(fields["agent"])
    if fields["transport"] not in ("local", "ssh"):
        raise CcPeerError("Reply-To transport must be local or ssh")
    if fields["transport"] == "ssh":
        if "host" not in fields:
            raise CcPeerError("SSH Reply-To is missing host")
        if any(character.isspace() for character in fields["host"]):
            raise CcPeerError("Reply-To host must not contain whitespace")
        check_ssh_argument(fields["host"], "--host")
    elif "host" in fields:
        raise CcPeerError("Local Reply-To must not include host")
    target = adapter.target(fields["session"])
    adapter.identity(target, ExecutionContext(fields.get("host", "local"),
                     argparse.Namespace(codex_home=fields.get("codexHome"))))
    if fields["agent"] != "codex" and "codexHome" in fields:
        raise CcPeerError("Claude Reply-To must not include codexHome")
    if "codexHome" in fields and not (
        PurePosixPath(fields["codexHome"]).is_absolute()
        or PureWindowsPath(fields["codexHome"]).is_absolute()
    ):
        raise CcPeerError("Reply-To codexHome must be an absolute path")
    return {**fields, "target": target, "uri": value}


def reply_route(identity: dict | None, local: bool) -> dict | None:
    """Describe the generated reply route without parsing untrusted body text."""
    uri = reply_address(identity, local=local)
    if uri is None:
        return None
    status = "verified" if local else "unverified"
    return {
        "uri": uri, "transport": "local" if local else "ssh", "status": status,
        "reason": "same_machine_route" if local else "reverse_ssh_not_checked",
    }


def apply_reply_target(args: argparse.Namespace) -> dict | None:
    """Resolve a structured --to address into ordinary, validated CLI fields."""
    address = parse_reply_address(args.to)
    if address is None:
        return None
    if args.host:
        raise CcPeerError("Do not combine a Reply-To URI with --host")
    uri_home = address.get("codexHome")
    configured_home = getattr(args, "codex_home", None)
    if uri_home and configured_home and configured_home != uri_home:
        raise CcPeerError("Reply-To codexHome conflicts with --codex-home")
    if uri_home:
        args.codex_home = uri_home
    transport = address["transport"]
    if transport == "ssh":
        host = address["host"]
        if is_self_ssh_destination(host):
            address = {**address, "transport": "local", "normalizedFrom": "ssh_self"}
        else:
            args.host = [host]
    args.to = address["target"]
    return address


def _reply_from_identity(identity: dict | None, local: bool = False) -> str | None:
    """Format a reply command from one already-detected identity."""
    if identity is None:
        return None
    target, host = identity["target"], identity["host"]
    if not host and not local:
        return None
    script = Path(__file__).resolve()
    script_str = (
        shlex.quote(str(script))
        if script.is_file()
        else '~/.local/share/session-peer/session_peer.py'
    )
    route = "" if local else f"--host {shlex.quote(host)} "
    return (f"Reply: python3 {script_str} send {route}"
            f"--to {shlex.quote(target)} --no-reply-to")


def reply_line(explicit_host: str | None) -> str | None:
    """Detect how to answer and return a command that runs verbatim.

    Three things the first version left out, each of which broke it in
    practice:

    * the **user**, because the receiver otherwise connects as its own local
      account — a worker running as `ubuntu` cannot reach a laptop's `abruptly`
    * an **absolute script path**, because a non-interactive SSH session never
      sources the profile that puts ~/.local/bin on PATH, so a bare `session-peer`
      is not found
    * `--no-reply-to`, so answering an answer doesn't ping-pong

    The username is the sender's; there's no guarantee the far side knows it,
    but it is right whenever accounts match and strictly better than nothing.
    """
    return _reply_from_identity(sender_identity(explicit_host))


# --------------------------------------------------------------------------
# Remote dispatch. Ships this file over SSH and runs it there, so the remote
# machine needs nothing installed beyond python3.
# --------------------------------------------------------------------------


# ssh options that make ssh run a command on *this* machine. A host or an
# --ssh-opt value carrying one of these turns "message a session" into "run
# whatever I say, locally". ProxyJump is deliberately absent: it takes a host,
# not a command, and is the right way to reach a box behind a bastion.
LOCAL_EXEC_SSH_OPTIONS = ("proxycommand", "localcommand", "permitlocalcommand")


def check_ssh_argument(value: str, flag: str) -> None:
    """Refuse a value that would make ssh do something other than connect.

    ssh has no `--` separator, so a leading dash turns a destination into a
    flag. Hosts never legitimately start with one, while --ssh-opt values
    always do — so the leading-dash rule applies only to the host, and both
    are checked for options that execute a local command.
    """
    if flag == "--host" and value.startswith("-"):
        raise CcPeerError(
            f"--host must not start with '-' (ssh would read {value!r} as an option)"
        )
    collapsed = value.lower().replace(" ", "").replace("=", "")
    for banned in LOCAL_EXEC_SSH_OPTIONS:
        if banned in collapsed:
            raise CcPeerError(
                f"{flag} must not carry {banned} — it would run a command on this "
                f"machine. Put it in ~/.ssh/config if you really need it."
            )


SSH_METADATA_FIELDS = ("sshUser", "sshUserSource")


def ssh_metadata_from(payload: dict) -> dict:
    return {key: payload[key] for key in SSH_METADATA_FIELDS if key in payload}


def ssh_user_metadata(host: str, ssh_opts: list[str]) -> dict:
    """Ask OpenSSH which login user it will use without making a connection."""
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")

    explicit_user, separator, _ = host.rpartition("@")
    if separator and explicit_user:
        return {"sshUser": explicit_user, "sshUserSource": "explicit"}

    try:
        completed = subprocess.run(
            ["ssh", "-G", *ssh_opts, host], capture_output=True,
            encoding="utf-8", errors="replace", timeout=DETECT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return {"sshUser": None, "sshUserSource": "unknown"}
    if completed.returncode != 0:
        return {"sshUser": None, "sshUserSource": "unknown"}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition(" ")
        if separator and key.lower() == "user" and value.strip():
            return {
                "sshUser": value.strip(),
                "sshUserSource": "ssh_config_or_local_default",
            }
    return {"sshUser": None, "sshUserSource": "unknown"}


def classify_ssh_failure(detail: str, returncode: int | None = None) -> str | None:
    lowered = detail.lower()
    if any(marker in lowered for marker in (
        "permission denied", "authentication failed",
        "no supported authentication methods available", "too many authentication failures",
    )):
        return "authentication_failed"
    if any(marker in lowered for marker in (
        "host key verification failed", "remote host identification has changed",
        "offending key in", "known_hosts",
    )):
        return "host_key_failed"
    if any(marker in lowered for marker in (
        "operation timed out", "connection timed out", "connect timeout", "timed out",
    )):
        return "timeout"
    if returncode == 255:
        return "transport_failed"
    return None


def ssh_failure_error(host: str, ssh_info: dict, failure: str,
                      detail: str | None = None) -> CcPeerError:
    user = ssh_info.get("sshUser")
    _, separator, hostname = host.rpartition("@")
    target = f"{user}@{hostname if separator else host}" if user else host
    if failure == "authentication_failed":
        message = (
            f"SSH authentication failed for {target}; use --host USER@HOST or "
            "configure User for the original host alias in ~/.ssh/config"
        )
    elif failure == "host_key_failed":
        message = (
            f"SSH host-key verification failed for {target}; verify the destination "
            "and its ~/.ssh/known_hosts entry"
        )
    elif failure == "timeout":
        message = f"SSH connection to {target} timed out"
    else:
        suffix = f": {detail.strip()[:2000]}" if detail and detail.strip() else ""
        message = f"SSH transport failed for {target}{suffix}"
    return CcPeerError(message, {**ssh_info, "sshFailure": failure})


def run_remote(host: str, argv: list[str], ssh_opts: list[str]) -> dict:
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")

    try:
        source = Path(__file__).resolve().read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - only when run from a pipe
        raise CcPeerError(f"cannot read own source to send to {host}: {exc}") from exc

    ssh_info = ssh_user_metadata(host, ssh_opts)

    # ssh joins everything after the destination with spaces and hands the
    # result to the remote *shell*, so an argv list is not the protection it
    # looks like: a metacharacter in any element executes over there. Build
    # the remote command as one already-quoted string instead.
    remote = " ".join(shlex.quote(a) for a in ["python3", "-", *argv, "--json"])
    command = ["ssh", *ssh_opts, host, remote]
    try:
        completed = subprocess.run(
            command, input=source, encoding="utf-8", capture_output=True, timeout=120
        )
    except FileNotFoundError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", "ssh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ssh_failure_error(host, ssh_info, "timeout") from exc
    except OSError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", str(exc)) from exc

    stdout = completed.stdout.strip()
    detail = completed.stderr.strip() or f"ssh exited {completed.returncode}"
    failure = (
        classify_ssh_failure(detail, completed.returncode)
        if completed.returncode != 0 else None
    )
    if failure:
        raise ssh_failure_error(host, ssh_info, failure, detail)
    runtime_output = (completed.stdout + "\n" + completed.stderr).strip().lower()
    if (runtime_output == "python"
            or "python was not found" in runtime_output
            or ("python3" in runtime_output and any(marker in runtime_output for marker in (
                "command not found", "not recognized as", "no such file", "python3: not found",
            )))):
        raise CcPeerError(
            f"{host}: remote python3 did not start a usable interpreter. "
            "Source-streamed SSH requires a working python3 and a POSIX-compatible "
            "remote shell. A Windows Store execution alias is not sufficient. "
            "For native Windows, run the installed CLI locally, or use a WSL SSH "
            "endpoint with Python installed. No fallback or resend was attempted.",
            {**ssh_info, "remoteRuntimeFailure": "python3_unavailable_or_unsupported_shell"},
        )
    if not stdout:
        raise CcPeerError(f"{host}: {detail}", ssh_info)
    try:
        result = json.loads(stdout)
    except ValueError as exc:
        raise CcPeerError(f"{host}: unexpected output: {stdout[:200]}", ssh_info) from exc
    if isinstance(result, dict):
        result.update(ssh_info)

    # The far end reports its own failures in-band; surface them here rather
    # than letting a caller read an error payload as a success.
    if isinstance(result, dict) and result.get("ok") is False:
        if (argv and argv[0] == "send" and result.get("command") == "send"
                and result.get("schemaVersion") == JSON_RESPONSE_SCHEMA_VERSION
                and result.get("agent") == "antigravity"
                and (result.get("status") in ("unknown", "refused") or result.get("reason"))):
            return result
        if (argv and argv[0] == "send" and result.get("command") == "send"
                and result.get("schemaVersion") == JSON_RESPONSE_SCHEMA_VERSION
                and (isinstance(result.get("wake"), dict) or result.get("submitted") is True
                     or (result.get("agent") == "antigravity" and result.get("status") == "unknown"
                         and result.get("retryAllowed") is False and result.get("requestId")))):
            return result
        if (
            argv and argv[0] == "list"
            and result.get("command") == "list"
            and result.get("schemaVersion") == JSON_RESPONSE_SCHEMA_VERSION
            and isinstance(result.get("sessions"), list)
            and isinstance(result.get("discovery"), dict)
            and result["discovery"]
            and all(agent in AGENTS.names() and isinstance(info, dict)
                    and info.get("status") in ("ok", "error", "not_installed")
                    for agent, info in result["discovery"].items())
            and any(info["status"] == "error" for info in result["discovery"].values())
        ):
            return result
        details = {}
        if "codexHomeResolution" in result:
            details["codexHomeResolution"] = result["codexHomeResolution"]
        raise CcPeerError(
            f"{host}: {result.get('error', 'remote command failed')}", details
        )
    return result


def push_to_remote(host: str, ssh_opts: list[str], ssh_info: dict | None = None) -> str:
    """Push this script to a remote machine's skill dir over SSH.

    Returns the version string reported by the newly installed copy.
    The remote machine needs only python3 and ssh access — no internet,
    no install.sh.
    """
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")

    try:
        source = Path(__file__).resolve().read_bytes()
    except OSError as exc:
        raise CcPeerError(f"cannot read own source to push to {host}: {exc}") from exc

    ssh_info = ssh_user_metadata(host, ssh_opts) if ssh_info is None else ssh_info

    source_b64 = base64.b64encode(source).decode("ascii")

    remote_script = (
        "set -eu; "
        'D="$HOME/.local/share/session-peer"; '
        'mkdir -p "$D" "$HOME/.local/bin"; '
        'base64 -d > "$D/session_peer.py"; '
        'chmod +x "$D/session_peer.py"; '
        'ln -sf "$D/session_peer.py" "$HOME/.local/bin/session-peer"; '
        'python3 "$D/session_peer.py" --version 2>/dev/null || echo "session-peer unknown"'
    )
    command = ["ssh", *ssh_opts, host, remote_script]
    try:
        completed = subprocess.run(
            command, input=source_b64, encoding="utf-8",
            capture_output=True, timeout=120,
        )
    except FileNotFoundError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", "ssh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ssh_failure_error(host, ssh_info, "timeout") from exc
    except OSError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", str(exc)) from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"ssh exited {completed.returncode}"
        failure = classify_ssh_failure(detail, completed.returncode)
        if failure:
            raise ssh_failure_error(host, ssh_info, failure, detail)
        raise CcPeerError(f"{host}: {detail}", ssh_info)

    version_line = completed.stdout.strip()
    parts = version_line.split()
    return parts[-1] if parts else "unknown"


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def render_sessions(sessions: list[dict], where: str) -> str:
    if not sessions:
        return f"No reachable Claude Code sessions on {where}."

    rows = [("NAME", "PID", "STATUS", "CWD")]
    for s in sessions:
        name = s["name"] or "(unnamed)"
        if not s["reachable"]:
            name += " [no inbox]" if s["alive"] else " [stale record]"
        rows.append((name, str(s["pid"]), s["status"] or "-", s["cwd"] or "-"))

    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    lines = [
        f"{r[0]:<{widths[0]}}  {r[1]:<{widths[1]}}  {r[2]:<{widths[2]}}  {r[3]}"
        for r in rows
    ]
    return f"Sessions on {where}:\n" + "\n".join(lines)


JSON_RESPONSE_SCHEMA_VERSION = 1


def local_host() -> str:
    """Stable, network-independent identity for results produced locally."""
    return socket.gethostname()


def json_result(command: str, payload: dict | None = None, *,
                host: str | None = None, ok: bool | None = None) -> dict:
    """Build one command result with the common machine-readable envelope."""
    detail = dict(payload or {})
    payload_ok = detail.pop("ok", True)
    payload_host = detail.pop("host", None)
    for reserved in ("schemaVersion", "command"):
        detail.pop(reserved, None)
    return {
        "schemaVersion": JSON_RESPONSE_SCHEMA_VERSION,
        "ok": bool(payload_ok if ok is None else ok),
        "host": host or payload_host or local_host(),
        "command": command,
        **detail,
    }


def one_or_many(results: list[dict]) -> dict | list[dict]:
    """Keep one destination flat; use an array only for repeated --host."""
    return results[0] if len(results) == 1 else results


def with_client_update(payload: dict | list[dict]) -> dict | list[dict]:
    """Attach the invoking client's cached update fact to each result object."""
    if _CLIENT_UPDATE_NOTICE is None:
        return payload
    if isinstance(payload, list):
        return [
            {**item, "clientUpdate": dict(_CLIENT_UPDATE_NOTICE)}
            if isinstance(item, dict) else item
            for item in payload
        ]
    return {**payload, "clientUpdate": dict(_CLIENT_UPDATE_NOTICE)}


def emit(as_json: bool, payload: dict, human: str, *, command: str,
         host: str | None = None, ok: bool | None = None) -> None:
    result = json_result(command, payload, host=host, ok=ok)
    print(json.dumps(with_client_update(result), ensure_ascii=False) if as_json else human)


def emit_json_results(results: list[dict]) -> None:
    print(json.dumps(with_client_update(one_or_many(results)), ensure_ascii=False))


def emit_human_update_notice() -> None:
    if _CLIENT_UPDATE_NOTICE is None:
        return
    print(
        f"Update available: {_CLIENT_UPDATE_NOTICE['current']} → "
        f"{_CLIENT_UPDATE_NOTICE['latest']}. "
        f"Run: {_CLIENT_UPDATE_NOTICE['command']}",
        file=sys.stderr,
    )


def host_metadata(ssh_host: str, canonical_host: str) -> dict:
    metadata = {"host": canonical_host}
    if ssh_host != canonical_host:
        metadata["sshHost"] = ssh_host
    return metadata


def display_host(ssh_host: str, canonical_host: str) -> str:
    if ssh_host == canonical_host:
        return canonical_host
    return f"{canonical_host} (via SSH {ssh_host})"


def tailscale_ssh_options(ssh_host: str, canonical_host: str) -> list[str]:
    """Route an SSH alias to its verified MagicDNS name without losing config.

    Keeping ssh_host as the command destination preserves matching `Host` and
    `User` settings. HostKeyAlias preserves an existing known_hosts entry keyed
    by the caller's original IP or hostname.
    """
    if ssh_host == canonical_host:
        return []
    _, _, original_name = ssh_host.rpartition("@")
    _, _, magicdns_name = canonical_host.rpartition("@")
    original_name = (original_name or ssh_host).strip("[]")
    magicdns_name = (magicdns_name or canonical_host).strip("[]")
    return [
        "-o", f"HostName={magicdns_name}",
        "-o", f"HostKeyAlias={original_name}",
    ]


# --------------------------------------------------------------------------
# Diagnostics. These checks are read-only: no inbox connection, queue write,
# login change, host-key enrollment, or permission change is attempted.
# --------------------------------------------------------------------------


def _diagnostic(status: str, code: str, message: str, **detail) -> dict:
    return {"status": status, "code": code, "message": message, **detail}


def diagnose_claude() -> dict:
    directory = sessions_dir()
    result = {
        "sessionsDir": str(directory), "records": 0, "invalidRecords": 0,
        "aliveSessions": 0, "availableInboxes": 0, "checks": [],
    }
    try:
        mode = directory.stat().st_mode
    except FileNotFoundError:
        result["checks"].append(_diagnostic(
            "error", "sessions_dir_missing",
            "Claude sessions directory does not exist; check CLAUDE_CONFIG_DIR",
        ))
        return {"status": "missing_home", **result}
    except PermissionError:
        result["checks"].append(_diagnostic(
            "error", "sessions_dir_permission_denied",
            "Claude sessions directory is not readable by this user",
        ))
        return {"status": "permission_denied", **result}
    except OSError as exc:
        result["checks"].append(_diagnostic(
            "unknown", "sessions_dir_unreadable", f"Cannot inspect Claude sessions: {exc}",
        ))
        return {"status": "unknown", **result}
    if not stat.S_ISDIR(mode):
        result["checks"].append(_diagnostic(
            "error", "sessions_path_not_directory",
            "Configured Claude sessions path is not a directory",
        ))
        return {"status": "wrong_home", **result}
    try:
        entries = sorted(
            entry for entry in directory.iterdir()
            if entry.name.endswith(".json")
        )
    except PermissionError:
        result["checks"].append(_diagnostic(
            "error", "sessions_dir_permission_denied",
            "Claude sessions directory cannot be listed by this user",
        ))
        return {"status": "permission_denied", **result}
    except OSError as exc:
        result["checks"].append(_diagnostic(
            "unknown", "sessions_dir_unreadable", f"Cannot list Claude sessions: {exc}",
        ))
        return {"status": "unknown", **result}

    permission_failures = 0
    for record_file in entries:
        if not record_file.stem.isdigit():
            continue
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except PermissionError:
            permission_failures += 1
            continue
        except (OSError, ValueError):
            result["invalidRecords"] += 1
            continue
        pid = record.get("pid")
        if not isinstance(pid, int):
            result["invalidRecords"] += 1
            continue
        result["records"] += 1
        alive = pid_alive(pid)
        if alive:
            result["aliveSessions"] += 1
        inbox = str(record.get("messagingSocketPath") or "")
        try:
            present = (
                inbox.startswith("\\\\.\\pipe\\") if IS_WINDOWS
                else bool(inbox) and Path(inbox).is_socket()
            )
        except OSError:
            present = False
        if alive and present:
            result["availableInboxes"] += 1

    if permission_failures:
        result["checks"].append(_diagnostic(
            "error", "session_record_permission_denied",
            "One or more Claude session records are not readable",
            count=permission_failures,
        ))
        return {"status": "permission_denied", **result}
    if result["availableInboxes"]:
        result["checks"].append(_diagnostic(
            "ok", "inbox_present",
            "At least one live Claude session advertises an inbox",
            verification="filesystem_only",
        ))
        return {"status": "available", **result}
    if result["aliveSessions"]:
        result["checks"].append(_diagnostic(
            "warning", "inbox_unavailable",
            "Live Claude sessions exist but none advertises an available inbox",
        ))
        return {"status": "inbox_unavailable", **result}
    result["checks"].append(_diagnostic(
        "warning", "no_live_sessions",
        "No live Claude session with an inbox was found",
    ))
    return {"status": "unavailable", **result}


def _codex_home_source(args: argparse.Namespace) -> str:
    if getattr(args, "codex_home", None):
        return "explicit"
    if os.environ.get("CODEX_HOME"):
        return "environment"
    return "default"


def diagnose_codex_home(home: Path) -> dict:
    db = home / "state_5.sqlite"
    item = {"codexHome": str(home), "stateDb": str(db), "sessionCount": None}
    try:
        mode = db.stat().st_mode
    except FileNotFoundError:
        return {**item, "status": "missing_home", "code": "state_db_missing"}
    except PermissionError:
        return {**item, "status": "permission_denied", "code": "state_db_permission_denied"}
    except OSError as exc:
        return {**item, "status": "unknown", "code": "state_db_unreadable", "detail": str(exc)}
    if not stat.S_ISREG(mode):
        return {**item, "status": "wrong_home", "code": "state_db_not_regular"}
    try:
        conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            conn.execute("PRAGMA query_only=ON")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
            required = {"id", "title", "cwd", "updated_at", "archived", "rollout_path"}
            if not required <= columns:
                return {
                    **item, "status": "unsupported", "code": "unsupported_threads_schema",
                    "missingColumns": sorted(required - columns),
                }
            count = int(conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error as exc:
        detail = str(exc)
        lowered = detail.lower()
        status = "permission_denied" if "permission" in lowered else "unknown"
        code = "state_db_permission_denied" if status == "permission_denied" else "state_db_unreadable"
        return {**item, "status": status, "code": code, "detail": detail}
    return {**item, "status": "available", "code": "state_db_readable", "sessionCount": count}


def diagnose_codex(args: argparse.Namespace) -> dict:
    selected = codex_home(args)
    requested_bin = getattr(args, "codex_bin", None) or "codex"
    executable = shutil.which(os.path.expanduser(requested_bin))
    checks = []
    if executable:
        checks.append(_diagnostic(
            "ok", "codex_executable_found", "Codex executable is available",
            path=str(Path(executable).absolute()),
        ))
    else:
        checks.append(_diagnostic(
            "error", "codex_executable_missing",
            "Codex executable is not on PATH; set --codex-bin on the destination",
            requested=requested_bin,
        ))
    inventory_error = None
    try:
        homes = known_codex_homes(selected)
    except CcPeerError as exc:
        homes = [selected]
        inventory_error = str(exc)
    candidates = [diagnose_codex_home(home) for home in homes]
    selected_item = next(
        (candidate for candidate in candidates if candidate["codexHome"] == str(selected)),
        candidates[0],
    )
    if inventory_error:
        checks.append(_diagnostic(
            "unknown", "home_inventory_unreadable", inventory_error,
        ))
    checks.append(_diagnostic(
        "ok" if selected_item["status"] == "available" else "error",
        selected_item["code"],
        "Selected Codex home is readable" if selected_item["status"] == "available"
        else "Selected Codex home cannot be used",
    ))
    status = selected_item["status"]
    if status == "available" and not executable:
        status = "missing_tool"
    if inventory_error and status == "available":
        status = "unknown"
    return {
        "status": status, "selectedHome": str(selected),
        "homeSource": _codex_home_source(args), "executable": executable,
        "homes": candidates, "checks": checks,
    }


def probe_return_route(destination: str) -> dict:
    """Test reverse SSH without prompts, key enrollment, or config mutation."""
    check_ssh_argument(destination, "--host")
    if is_self_ssh_destination(destination):
        return {
            "status": "verified", "transport": "local", "host": local_host(),
            "reason": "self_route_normalized",
        }
    executable = shutil.which("ssh")
    if executable is None:
        return {
            "status": "failed", "transport": "ssh", "host": destination,
            "reason": "ssh_executable_missing",
        }
    ssh_info = ssh_user_metadata(destination, [])
    command = [
        executable,
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "NumberOfPasswordPrompts=0",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UpdateHostKeys=no",
        "-o", "ConnectTimeout=5",
        "-o", "ConnectionAttempts=1",
        "-o", "ControlMaster=no",
        destination, "true",
    ]
    try:
        done = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace", timeout=8,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "failed", "transport": "ssh", "host": destination,
            "reason": "timeout", **ssh_info,
        }
    except OSError as exc:
        return {
            "status": "failed", "transport": "ssh", "host": destination,
            "reason": "transport_failed", "detail": str(exc), **ssh_info,
        }
    if done.returncode == 0:
        return {
            "status": "verified", "transport": "ssh", "host": destination,
            "reason": "ssh_command_succeeded", **ssh_info,
        }
    detail = (done.stderr.strip() or done.stdout.strip())[:1000]
    return {
        "status": "failed", "transport": "ssh", "host": destination,
        "reason": classify_ssh_failure(detail, done.returncode) or "remote_command_failed",
        **({"detail": detail} if detail else {}), **ssh_info,
    }


def doctor_payload(args: argparse.Namespace) -> dict:
    diagnostics = {}
    for name in AGENTS.names():
        try:
            diagnostics[name] = LocalTransport().execute("doctor", AGENTS.get(name), args)
        except (CcPeerError, OSError) as exc:
            diagnostics[name] = {"status": "unknown", "checks": [
                _diagnostic("error", "adapter_failed", str(exc))]}
    active = [item for item in diagnostics.values() if item["status"] != "disabled"]
    available = sum(item["status"] == "available" for item in active)
    payload = {
        "status": "healthy" if available == len(active) else ("partial" if available else "issues_found"),
        **diagnostics,
        "capabilities": {
            "agents": {name: dict(AGENTS.get(name).capabilities._asdict()) for name in AGENTS.names()},
            "replyObservation": {
                "status": "unsupported",
                "reason": "no_cross_agent_acknowledgement_api",
                "claudeLocalIdleNotice": "native_claude_only",
                "automatedWait": False,
            },
        },
    }
    return_host = getattr(args, "_return_host", None)
    if return_host:
        payload["returnRoute"] = probe_return_route(return_host)
    return payload


def render_doctor(payload: dict, where: str) -> str:
    lines = [
        f"Diagnostics on {where}:",
        *("  " + AGENTS.get(name).diagnostic_text(payload[name]) for name in AGENTS.names() if name in payload),
        "  Automated reply observation: unsupported across Claude, Codex, and SSH",
    ]
    for component in AGENTS.names():
        for check in payload.get(component, {}).get("checks", []):
            if check.get("status") != "ok":
                lines.append(f"    - {check['code']}: {check['message']}")
    route = payload.get("returnRoute")
    if route:
        lines.append(
            f"  Return route: {route['status']} via {route['transport']} "
            f"({route['reason']})"
        )
    else:
        lines.append("  Return route: not checked (use --check-return-route)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


# Internal extension contract. Keep this in the streamed standalone source.
ADAPTER_CONTRACT_VERSION = 1


class SessionIdentity(NamedTuple):
    agent: str
    host: str
    identifier: str
    codex_home: str | None = None


class ExecutionContext(NamedTuple):
    host: str
    options: argparse.Namespace


class DiscoveryResult(TypedDict):
    sessions: list[dict]
    discovery: dict


class SubmissionResult(TypedDict, total=False):
    # Native payloads may additionally carry target, chars, home and wake data.
    ok: bool
    status: str
    submitted: bool
    consumptionConfirmed: bool
    queueId: str


class AgentCapabilities(NamedTuple):
    list: bool = True
    send: bool = True
    wake: bool = False
    wait: bool = False
    ack: bool = False


class AdapterError(CcPeerError):
    def __init__(self, agent: str, code: str, message: str):
        super().__init__(message, {"agent": agent, "reason": code})


class AgentAdapter:
    """Internal v1 contract; native result dictionaries retain their wire shape.

    list returns sessions/discovery plus optional top-level metadata; submit
    returns the existing agent-specific payload. Neither implies consumption.
    Only source-registered adapters run; there is no external plugin loader.
    """
    contract_version = ADAPTER_CONTRACT_VERSION
    name = ""
    capabilities = AgentCapabilities()

    def target(self, identifier: str) -> str:
        return f"{self.name}:{identifier}"

    def identity(self, target: str, context: ExecutionContext) -> SessionIdentity:
        prefix = self.name + ":"
        if not target.startswith(prefix) or not target[len(prefix):]:
            raise AdapterError(self.name, "invalid_target", "Invalid agent target")
        return SessionIdentity(self.name, context.host, target[len(prefix):])

    def validate_send(self, args: argparse.Namespace, text: str | None = None) -> None:
        if not self.capabilities.send:
            raise AdapterError(self.name, "unsupported_capability", "Agent does not support send")
        if getattr(args, "wake", False) and not self.capabilities.wake:
            raise wake_refused("unsupported_agent", "--wake requires a Codex target")
        self.identity(args.to, ExecutionContext("local", args))

    def list(self, context: ExecutionContext) -> DiscoveryResult:
        raise NotImplementedError

    def submit(self, context: ExecutionContext, text: str) -> SubmissionResult:
        raise NotImplementedError

    def diagnose(self, context: ExecutionContext) -> dict:
        return {"status": "unavailable", "checks": []}

    def diagnostic_text(self, result: dict) -> str:
        return f"{self.name}: {result['status']}"

    def remote_options(self, args: argparse.Namespace) -> list[str]:
        return []

    def display_row(self, session: dict) -> tuple[str, str]:
        return str(session["id"]), str(session.get("status", "unknown"))

    def render(self, sessions: list[dict], where: str) -> str:
        return f"Sessions on {where}:\n" + "\n".join(
            f"{self.name}  {self.display_row(row)[0]}  {self.display_row(row)[1]}"
            for row in sessions)

    def listing_notes(self, payload: dict) -> list[str]:
        return []

    def submission_text(self, result: dict, where: str) -> str:
        return f"{self.name} submission on {where}: {result.get('status', 'unknown')}"

    def remote_submission(self, result: dict, args: argparse.Namespace, text: str) -> dict:
        return result


class ClaudeAdapter(AgentAdapter):
    name = "claude"

    def target(self, identifier: str) -> str:
        return identifier

    def identity(self, target: str, context: ExecutionContext) -> SessionIdentity:
        if not target:
            raise AdapterError(self.name, "invalid_target", "Empty Claude target")
        return SessionIdentity(self.name, context.host, target)

    def list(self, context: ExecutionContext) -> DiscoveryResult:
        return {"sessions": [{**row, "agent": self.name} for row in
                             discover(include_unreachable=context.options.all)],
                "discovery": {"status": "ok"}}

    def submit(self, context: ExecutionContext, text: str) -> SubmissionResult:
        args = context.options
        session = resolve_target(discover(include_unreachable=True), args.to)
        if not args.dry_run:
            post_to_socket(session["socket"], text, pid=session["pid"])
        return {"ok": True, "target": {"pid": session["pid"], "name": session["name"]},
                "chars": len(text), "dryRun": args.dry_run}

    def diagnose(self, context: ExecutionContext) -> dict:
        return diagnose_claude()

    def diagnostic_text(self, result: dict) -> str:
        return f"Claude inbox: {result['status']}"

    def display_row(self, session: dict) -> tuple[str, str]:
        status = session.get("status") or "-"
        if not session["reachable"]:
            status = "no inbox" if session["alive"] else "stale record"
        return str(session["pid"]), status

    def render(self, sessions: list[dict], where: str) -> str:
        return render_sessions(sessions, where)

    def submission_text(self, result: dict, where: str) -> str:
        target = result.get("target", {})
        name = target.get("name") or target.get("pid")
        verb = "Would post to" if result["dryRun"] else "Posted to"
        return f"{verb} {name}'s inbox on {where} ({result['chars']} chars)."

    def remote_submission(self, result: dict, args: argparse.Namespace, text: str) -> dict:
        return {"target": result.get("target", {}), **ssh_metadata_from(result),
                "chars": len(text), "dryRun": args.dry_run}


class CodexAdapter(AgentAdapter):
    name = "codex"
    capabilities = AgentCapabilities(wake=True)

    def identity(self, target: str, context: ExecutionContext) -> SessionIdentity:
        return SessionIdentity(self.name, context.host, codex_thread(target),
                               str(codex_home(context.options)))

    def validate_send(self, args: argparse.Namespace, text: str | None = None) -> None:
        super().validate_send(args, text)
        if text is not None:
            check_codex_message(text)

    def list(self, context: ExecutionContext) -> DiscoveryResult:
        return collect_codex_listing(context.options)

    def submit(self, context: ExecutionContext, text: str) -> SubmissionResult:
        return queue_codex(context.options, text)

    def diagnose(self, context: ExecutionContext) -> dict:
        return diagnose_codex(context.options)

    def diagnostic_text(self, result: dict) -> str:
        return f"Codex: {result['status']} ({result.get('selectedHome', 'unknown')})"

    def remote_options(self, args: argparse.Namespace) -> list[str]:
        return codex_remote_options(args)

    def display_row(self, session: dict) -> tuple[str, str]:
        return session["id"], ("archived; execution unknown" if session["archived"]
                               else "execution unknown")

    def render(self, sessions: list[dict], where: str) -> str:
        return render_codex(sessions, where)

    def listing_notes(self, payload: dict) -> list[str]:
        notes = []
        if "codexHome" in payload:
            notes.append(f"Codex home: {payload['codexHome']} (single candidate home).")
        info = payload.get("discovery", {}).get(self.name, {})
        if info.get("status") == "not_installed":
            notes.append("No Codex installation found in known homes.")
        for item in info.get("homes", []):
            if item["status"] == "error":
                notes.append(f"Codex home {item['codexHome']}: {item['code']}: {item['error']}")
        for error in info.get("errors", []):
            notes.append(f"Codex {error['source']}: {error['code']}: {error['error']}")
        return notes

    def submission_text(self, result: dict, where: str) -> str:
        return codex_submission_text(result, where)


# Antigravity is opt-in: only runtime-registered sessions are discoverable.
AGY_MAX_BYTES = 32768
AGY_FRAME_BYTES = 262144


def agy_error(code: str) -> AdapterError:
    return AdapterError('antigravity', code, 'Antigravity: ' + code)


def agy_uuid(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise agy_error('invalid_uuid')


def agy_private(path: Path, directory: bool = False) -> None:
    st = path.lstat()
    if (st.st_uid != os.getuid() or st.st_mode & 0o077 or
            (not stat.S_ISDIR(st.st_mode) if directory else stat.S_ISLNK(st.st_mode))):
        raise agy_error('unsafe_runtime_path')


def agy_root(create: bool = False) -> Path:
    if os.name != 'posix':
        raise agy_error('unsupported_platform')
    root = Path('/tmp') / ('session-peer-agy-' + str(os.getuid()))
    if create:
        root.mkdir(mode=0o700, exist_ok=True)
    if root.exists() or root.is_symlink():
        agy_private(root, True)
    return root


def agy_process(pid: int) -> dict:
    """No process environment or full argument collection."""
    if sys.platform.startswith('linux'):
        proc = Path('/proc') / str(pid)
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            raise agy_error('owner_not_live')
        return {'pid': pid, 'ppid': int(fields[1]), 'start': fields[19],
                'uid': proc.stat().st_uid, 'comm': (proc / 'comm').read_text().strip()}
    if sys.platform == 'darwin':
        p = subprocess.run(['ps', '-p', str(pid), '-o', 'ppid=', '-o', 'uid=', '-o', 'comm='],
                           capture_output=True, text=True, timeout=3)
        row = p.stdout.strip().split(None, 2)
        born = _process_start_time(pid)
        if len(row) != 3 or not born:
            raise agy_error('owner_not_live')
        return {'pid': pid, 'ppid': int(row[0]), 'uid': int(row[1]),
                'comm': Path(row[2]).name, 'start': born}
    raise agy_error('unsupported_platform')


def agy_has_presence(pid: int, home: Path, thread: str) -> bool:
    expected = (home / 'presence' / (thread + '.lock')).resolve()
    if sys.platform.startswith('linux'):
        for fd in (Path('/proc') / str(pid) / 'fd').iterdir():
            try:
                if fd.resolve(strict=True) == expected:
                    return True
            except OSError:
                pass
        return False
    executable = _lsof_executable()
    if not executable:
        raise agy_error('lsof_unavailable')
    p = subprocess.run([executable, '-a', '-p', str(pid), '-Fn'],
                       capture_output=True, text=True, timeout=3)
    if p.returncode:
        raise agy_error('presence_unverifiable')
    return any(line.startswith('n') and Path(line[1:]).resolve() == expected
               for line in p.stdout.splitlines())


def agy_owner(home: Path, thread: str) -> dict:
    pid = os.getppid()
    for _ in range(24):
        proc = agy_process(pid)
        if (proc['uid'] == os.getuid() and proc['comm'] == 'agy'
                and agy_has_presence(pid, home, thread)):
            return proc
        pid = proc['ppid']
        if pid <= 1:
            break
    raise agy_error('run_bridge_inside_target_tui')


def agy_owner_live(info: dict) -> bool:
    try:
        proc = agy_process(info['ownerPid'])
        return (proc['uid'] == os.getuid() and proc['comm'] == 'agy'
                and proc['start'] == info['ownerStart']
                and agy_has_presence(proc['pid'], Path(info['antigravityHome']), info['id']))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, CcPeerError):
        return False


def agy_read_frame(stream: socket.socket, timeout: float = 3) -> dict:
    data = bytearray()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise agy_error("frame_timeout")
        stream.settimeout(remaining)
        chunk = stream.recv(min(4096, AGY_FRAME_BYTES + 1 - len(data)))
        if not chunk:
            raise agy_error('incomplete_frame')
        data.extend(chunk)
        if len(data) > AGY_FRAME_BYTES:
            raise agy_error('frame_too_large')
        if b'\n' in data:
            line, rest = data.split(b'\n', 1)
            if rest:
                raise agy_error('invalid_frame')
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                raise agy_error('invalid_frame')
            if not isinstance(value, dict):
                raise agy_error('invalid_frame')
            return value


def agy_write_frame(stream: socket.socket, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode() + b'\n'
    if len(data) > AGY_FRAME_BYTES:
        raise agy_error('frame_too_large')
    stream.sendall(data)


def agy_peer_uid(stream: socket.socket) -> int:
    if sys.platform.startswith('linux'):
        import struct
        return struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if sys.platform == 'darwin':
        import ctypes
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.getpeereid(stream.fileno(), ctypes.byref(uid), ctypes.byref(gid)):
            raise agy_error('peer_identity_unavailable')
        return uid.value
    raise agy_error('unsupported_platform')


def agy_rpc(info: dict, request: dict) -> dict:
    path = agy_root() / (info['_key'] + '.sock')
    agy_private(path)
    if not stat.S_ISSOCK(path.lstat().st_mode):
        raise agy_error('unsafe_runtime_path')
    with socket.socket(socket.AF_UNIX) as stream:
        stream.settimeout(20)
        stream.connect(str(path))
        if agy_peer_uid(stream) != os.getuid():
            raise agy_error('wrong_uid')
        agy_write_frame(stream, request)
        return agy_read_frame(stream, 20)


def agy_registrations(args: argparse.Namespace) -> list[dict]:
    if os.name != 'posix':
        return []
    root = agy_root()
    selected = getattr(args, 'antigravity_home', None)
    selected = str(Path(selected).expanduser().resolve()) if selected else None
    rows = []
    for path in sorted(root.glob('*.json')):
        try:
            agy_private(path)
            if not path.is_file() or path.stat().st_size > 8192:
                continue
            info = json.loads(path.read_text())
            agy_uuid(info['id']); agy_uuid(info['generation'])
            if not re.fullmatch(r'[a-f0-9]{32}', path.stem):
                continue
            if info.get('schemaVersion') != 1 or (selected and info['antigravityHome'] != selected):
                continue
            info['_key'] = path.stem
            if not agy_owner_live(info):
                continue
            response = agy_rpc(info, {'op': 'status', 'generation': info['generation']})
            if response.get('ready') is True and response.get('generation') == info['generation']:
                rows.append(info)
        except (OSError, ValueError, TypeError, KeyError, CcPeerError):
            continue
    return rows


class AgyBridge:
    """One owner and generation; in-memory duplicate suppression, no retries."""
    def __init__(self, info: dict, api: Path, limit: int):
        self.info, self.api, self.limit = info, api, limit
        self.seen: dict[str, tuple[str, dict]] = {}

    def handle(self, req: dict) -> dict:
        import hashlib
        if req.get('generation') != self.info['generation']:
            raise agy_error('stale_generation')
        if not agy_owner_live(self.info):
            raise agy_error('owner_not_live')
        if req == {'op': 'status', 'generation': self.info['generation']}:
            return {'ready': True, 'generation': self.info['generation']}
        if set(req) != {'op', 'generation', 'target', 'requestId', 'text'} or req['op'] != 'send':
            raise agy_error('invalid_request')
        if req['target'] != self.info['id']:
            raise agy_error('wrong_target')
        ident = agy_uuid(req['requestId'])
        text = req['text']
        if not isinstance(text, str) or not text.strip() or '\0' in text or len(text.encode()) > AGY_MAX_BYTES:
            raise agy_error('invalid_message')
        signature = hashlib.sha256(text.encode()).hexdigest()
        if ident in self.seen:
            prior_sig, result = self.seen[ident]
            if prior_sig != signature:
                raise agy_error('request_id_conflict')
            return {**result, 'duplicateSuppressed': True}
        if len(self.seen) >= self.limit:
            raise agy_error('request_limit')
        result = {'ok': False, 'agent': 'antigravity', 'status': 'unknown',
                  'submitted': False, 'consumptionConfirmed': False, 'retryAllowed': False,
                  'requestId': ident, 'generation': self.info['generation'],
                  'antigravityHome': self.info['antigravityHome'],
                  'target': {'agent': 'antigravity', 'id': self.info['id']}}
        self.seen[ident] = signature, result
        try:
            # No shell; native stdout/stderr may contain credentials and are discarded.
            done = subprocess.run([str(self.api), 'send-message', '--title=session-peer',
                                   self.info['id'], text], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=15)
            result = {**result, 'nativeExitCode': done.returncode}
            if done.returncode == 0:
                result.update(ok=True, status='submitted', submitted=True)
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.seen[ident] = signature, result
        return result


def cmd_agy_bridge(args: argparse.Namespace) -> int:
    import hashlib
    if fcntl is None:
        raise agy_error('unsupported_platform')
    thread = agy_uuid(args.thread)
    home = Path(args.antigravity_home or '~/.gemini/antigravity-cli').expanduser().resolve()
    root = agy_root(True)
    key = hashlib.sha256((str(home) + '\0' + thread).encode()).hexdigest()[:32]
    sockpath, registration = root / (key + '.sock'), root / (key + '.json')
    if args.action == 'stop':
        # Take the lock: never delete another live bridge's files.
        for info in agy_registrations(args):
            if info['_key'] == key:
                response = agy_rpc(info, {'op': 'stop', 'generation': info['generation']})
                print(json.dumps(response)); return 0
        raise agy_error('not_registered')
    owner = agy_owner(home, thread)
    api = home / 'bin/agentapi'
    if not api.is_file() or not os.access(api, os.X_OK):
        raise agy_error('agentapi_unavailable')
    lockpath = root / (key + '.lock')
    fd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        agy_private(lockpath)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise agy_error('already_registered')
        sockpath.unlink(missing_ok=True)
        registration.unlink(missing_ok=True)
        info = {'schemaVersion': 1, 'agent': 'antigravity', 'id': thread,
                'name': thread, 'cwd': os.getcwd(), 'antigravityHome': str(home),
                'ownerPid': owner['pid'], 'ownerStart': owner['start'],
                'generation': str(uuid.uuid4()), 'bridgePid': os.getpid()}
        bridge = AgyBridge(info, api, args.max_requests)
        stopped = False
        def stop(signum, frame):
            nonlocal stopped
            stopped = True
        signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
        prior = {sig: signal.signal(sig, stop) for sig in signals}
        try:
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(sockpath)); sockpath.chmod(0o600)
                server.listen(4); server.settimeout(1)
                fd = os.open(registration, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w') as out:
                    json.dump(info, out)
                print(json.dumps({'ready': True, 'generation': info['generation'],
                                  'expiresInSeconds': args.ttl}), flush=True)
                deadline = time.monotonic() + args.ttl
                while not stopped and time.monotonic() < deadline and agy_owner_live(info):
                    try:
                        client, _ = server.accept()
                    except socket.timeout:
                        continue
                    with client:
                        client.settimeout(3)
                        try:
                            if agy_peer_uid(client) != os.getuid():
                                continue
                            request = agy_read_frame(client)
                            if request == {'op': 'stop', 'generation': info['generation']}:
                                stopped = True
                                response = {'stopped': True}
                            else:
                                response = bridge.handle(request)
                            agy_write_frame(client, response)
                        except CcPeerError as exc:
                            with contextlib.suppress(OSError):
                                agy_write_frame(client, {'ok': False, 'status': 'refused', 'submitted': False,
                                                        'consumptionConfirmed': False, 'error': str(exc),
                                                        **exc.details, 'retryAllowed': False})
                        except (OSError, ValueError, TypeError):
                            pass
        finally:
            sockpath.unlink(missing_ok=True)
            registration.unlink(missing_ok=True)
            for sig, handler in prior.items():
                signal.signal(sig, handler)
    # Lock inode intentionally remains to prevent split-lock races.
    return 0


def agy_sender() -> dict | None:
    try:
        rows = agy_registrations(argparse.Namespace())
        if not rows:
            return None
        pid = os.getppid()
        for _ in range(24):
            matches = [row for row in rows if row['ownerPid'] == pid]
            if len(matches) == 1:
                thread = matches[0]['id']
                return {'agent': 'antigravity', 'id': thread, 'target': 'antigravity:' + thread}
            if matches:
                return None
            pid = agy_process(pid)['ppid']
            if pid <= 1:
                break
    except (OSError, ValueError, subprocess.SubprocessError, CcPeerError):
        pass
    return None


class AntigravityAdapter(AgentAdapter):
    name = 'antigravity'

    def identity(self, target: str, context: ExecutionContext) -> SessionIdentity:
        result = super().identity(target, context)
        agy_uuid(result.identifier)
        return result

    def remote_options(self, args: argparse.Namespace) -> list[str]:
        return [part for name in ('antigravity_home', 'antigravity_generation', 'request_id')
                if getattr(args, name, None) for part in ('--' + name.replace('_', '-'), getattr(args, name))]

    def list(self, context: ExecutionContext) -> DiscoveryResult:
        rows = agy_registrations(context.options)
        return {'sessions': [{k: v for k, v in {**row, 'status': 'registered',
                             'target': self.target(row['id'])}.items() if k != '_key'} for row in rows],
                'discovery': {'status': 'ok' if rows else 'not_installed',
                              'scope': 'registered_bridges', 'reason': None if rows else 'no_live_registration'}}

    def diagnose(self, context: ExecutionContext) -> dict:
        return {'status': 'available' if os.name == 'posix' and agy_registrations(context.options) else 'disabled',
                'scope': 'registered_bridges', 'checks': []}

    def validate_send(self, args: argparse.Namespace, text: str | None = None) -> None:
        super().validate_send(args, text)
        if getattr(args, 'request_id', None):
            agy_uuid(args.request_id)
            if not getattr(args, 'antigravity_generation', None):
                raise agy_error('request_id_requires_generation')
        if text is not None and ('\0' in text or len(text.encode()) > AGY_MAX_BYTES):
            raise agy_error('invalid_message')

    def submit(self, context: ExecutionContext, text: str) -> SubmissionResult:
        args = context.options
        thread = self.identity(args.to, context).identifier
        rows = [row for row in agy_registrations(args) if row['id'] == thread]
        if len(rows) != 1:
            raise agy_error('ambiguous_home' if rows else 'not_registered')
        info = rows[0]
        if getattr(args, 'antigravity_generation', None) not in (None, info['generation']):
            raise agy_error('stale_generation')
        if args.dry_run:
            return {'ok': True, 'status': 'dry_run', 'submitted': False,
                    'consumptionConfirmed': False, 'generation': info['generation'],
                    'antigravityHome': info['antigravityHome']}
        req = {'op': 'send', 'generation': info['generation'], 'target': thread,
               'requestId': getattr(args, 'request_id', None) or str(uuid.uuid4()), 'text': text}
        try:
            return agy_rpc(info, req)
        except (OSError, CcPeerError):
            return {'ok': False, 'agent': 'antigravity', 'status': 'unknown', 'submitted': False,
                    'consumptionConfirmed': False, 'retryAllowed': False,
                    'requestId': req['requestId'], 'generation': info['generation']}


class AgentRegistry:
    def __init__(self):
        self._adapters: dict[str, AgentAdapter] = {}

    def register(self, adapter: AgentAdapter) -> None:
        name = getattr(adapter, "name", "")
        if (not isinstance(adapter, AgentAdapter) or not isinstance(name, str)
                or not re.fullmatch(r"[a-z][a-z0-9_-]*", name)
                or type(adapter.contract_version) is not int
                or adapter.contract_version != ADAPTER_CONTRACT_VERSION
                or not isinstance(adapter.capabilities, AgentCapabilities)
                or any(type(value) is not bool for value in adapter.capabilities)
                or type(adapter).list is AgentAdapter.list
                or type(adapter).submit is AgentAdapter.submit
                or any(not callable(getattr(adapter, method, None)) for method in
                       ("list", "submit", "diagnose", "identity", "target", "validate_send",
                        "remote_options", "render", "display_row", "listing_notes", "diagnostic_text",
                        "submission_text", "remote_submission"))):
            raise AdapterError(name, "invalid_adapter_contract", "Invalid or incompatible agent adapter")
        if name in self._adapters:
            raise AdapterError(name, "duplicate_agent", "Agent already registered")
        self._adapters[name] = adapter

    def names(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def get(self, name: str) -> AgentAdapter:
        if name not in self._adapters:
            raise AdapterError(name, "unknown_agent", f"Unknown agent: {name}")
        return self._adapters[name]

    def for_target(self, target: str) -> AgentAdapter:
        prefix, separator, _ = target.partition(":")
        # Unregistered prefixes remain literal Claude names for compatibility.
        if separator and prefix in self._adapters and prefix != "claude":
            return self.get(prefix)
        return self.get("claude")


AGENTS = AgentRegistry()
AGENTS.register(ClaudeAdapter())
AGENTS.register(CodexAdapter())
AGENTS.register(AntigravityAdapter())


class LocalTransport:
    def execute(self, operation: str, adapter: AgentAdapter,
                args: argparse.Namespace, text: str | None = None) -> dict:
        context = ExecutionContext("local", args)
        try:
            if operation == "list":
                if not adapter.capabilities.list:
                    raise AdapterError(adapter.name, "unsupported_capability", "Agent does not support list")
                result = adapter.list(context)
                if (not isinstance(result, dict)
                        or not isinstance(result.get("sessions"), list)
                        or not isinstance(result.get("discovery"), dict)
                        or result["discovery"].get("status") not in ("ok", "error", "not_installed")
                        or (result["discovery"].get("status") == "error"
                            and not isinstance(result["discovery"].get("error"), str))
                        or any(not isinstance(row, dict) or row.get("agent") != adapter.name
                               for row in result["sessions"])):
                    raise AdapterError(adapter.name, "invalid_adapter_result", "Invalid discovery result")
                # Validate rendering before aggregating so malformed rows cannot
                # destroy successful results from other adapters, even in JSON mode.
                for row in result["sessions"]:
                    adapter.display_row(row)
                return result
            if operation == "send":
                adapter.validate_send(args, text)
                result = adapter.submit(context, text)
                if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                    raise AdapterError(adapter.name, "outcome_unknown",
                                       "Invalid submission result; do not automatically retry")
                return result
            if operation == "doctor":
                result = adapter.diagnose(context)
                if not isinstance(result, dict) or not isinstance(result.get("status"), str):
                    raise AdapterError(adapter.name, "invalid_adapter_result", "Invalid diagnostic result")
                return result
            raise AdapterError(adapter.name, "unsupported_capability", "Unsupported operation")
        except CcPeerError:
            raise
        except OSError:
            raise
        except Exception as exc:
            # Do not echo arbitrary adapter exceptions (which may contain secrets).
            code = "outcome_unknown" if operation == "send" else "adapter_failed"
            message = ("Submission outcome unknown; do not automatically retry"
                       if operation == "send" else "Agent operation failed")
            raise AdapterError(adapter.name, code, message) from exc


class SshTransport:
    def __init__(self, requested_host: str, args: argparse.Namespace, status: dict):
        self.requested_host = requested_host
        self.host = resolve_ssh_destination(requested_host, status)
        self.ssh_opts = tailscale_ssh_options(requested_host, self.host) + args.ssh_opt

    def execute(self, argv: list[str]) -> dict:
        return run_remote(self.requested_host, argv, self.ssh_opts)


def validate_agent_send(adapter: AgentAdapter, args: argparse.Namespace,
                        text: str | None = None) -> None:
    try:
        adapter.validate_send(args, text)
    except CcPeerError:
        raise
    except Exception as exc:
        raise AdapterError(adapter.name, "adapter_failed", "Agent validation failed") from exc


def agent_remote_options(args: argparse.Namespace, selected: str | None = None) -> list[str]:
    options = []
    for name in ([selected] if selected else AGENTS.names()):
        options.extend(AGENTS.get(name).remote_options(args))
    return options


def collect_listing(args: argparse.Namespace) -> dict:
    selected = getattr(args, "agent", None)
    payload = {"sessions": [], "version": __version__, "discovery": {}, "ok": True}
    for agent in ([selected] if selected else AGENTS.names()):
        try:
            listing = LocalTransport().execute("list", AGENTS.get(agent), args)
            payload["sessions"].extend(listing["sessions"])
            payload["discovery"][agent] = listing["discovery"]
            for key, value in listing.items():
                if key not in {"sessions", "discovery", "ok", "error", "version"}:
                    payload[key] = value
            if listing["discovery"]["status"] == "error":
                payload["ok"] = False
        except (CcPeerError, OSError) as exc:
            payload["ok"] = False
            payload["discovery"][agent] = {"status": "error", "error": str(exc)}
    failed = [agent for agent, info in payload["discovery"].items()
              if info["status"] == "error"]
    if failed:
        payload["error"] = "Discovery failed for: " + ", ".join(failed)
    return payload


def render_listing(payload: dict, where: str, selected: str | None) -> str:
    sessions = payload["sessions"]
    if selected:
        human = AGENTS.get(selected).render(sessions, where)
    else:
        rows = ["AGENT  NAME  ID/PID  STATUS  CWD  CODEX HOME"]
        for session in sessions:
            identifier, status = AGENTS.get(session["agent"]).display_row(session)
            rows.append(f"{session['agent']}  {session.get('name') or '(unnamed)'}  "
                        f"{identifier}  {status}  {session.get('cwd') or '-'}  {session.get('codexHome') or '-'}")
        human = f"Sessions on {where}:\n" + "\n".join(rows)
    for name in payload.get("discovery", {}):
        for note in AGENTS.get(name).listing_notes(payload):
            human += "\n" + note
    for agent, info in payload.get("discovery", {}).items():
        if info["status"] == "error":
            human += f"\n{agent} discovery failed: {info['error']}"
    return human


def cmd_list(args: argparse.Namespace) -> int:
    if getattr(args, "device", None):
        return optional_relay().invoke_core(args)
    selected = getattr(args, "agent", None)
    if not args.host:
        result = collect_listing(args)
        emit(args.json, result, render_listing(result, "this machine", selected), command="list")
        return 0 if result["ok"] else EXIT_ERROR

    exit_code = 0
    all_results = []
    tailnet_status = tailscale_status() or {}
    for requested_host in args.host:
        host = requested_host
        try:
            transport = SshTransport(requested_host, args, tailnet_status)
            host, ssh_opts = transport.host, transport.ssh_opts
            argv = ["list", "--no-update-notice"] + (["--all"] if args.all else [])
            if selected:
                argv += ["--agent", selected]
            argv += agent_remote_options(args, selected)
            result = transport.execute(argv)
            sessions = result.get("sessions", [])
            ssh_info = ssh_metadata_from(result)
            remote_version = remote_installed_version(requested_host, ssh_opts, ssh_info)
            shown_host = display_host(requested_host, host)
            human = render_listing(result, shown_host, selected)
            if result.get("ok") is False:
                exit_code = EXIT_ERROR
            if remote_version and remote_version != __version__:
                human = (
                    f"{shown_host} runs session-peer {remote_version}; this machine has {__version__}."
                    f"\nUpdate it with:  session-peer update --host {requested_host}\n\n{human}"
                )
            host_result = json_result("list", {
                **host_metadata(requested_host, host),
                **ssh_info,
                **{key: result[key] for key in ("discovery", "error", "codexHome")
                   if key in result},
                "ok": result.get("ok", True),
                "sessions": sessions, "version": __version__,
                **({"remoteVersion": remote_version} if remote_version else {}),
            })
            all_results.append(host_result)
            if not args.json:
                if len(all_results) > 1:
                    print()
                print(human)
        except CcPeerError as exc:
            exit_code = EXIT_ERROR
            all_results.append(json_result(
                "list",
                {**host_metadata(requested_host, host), "error": str(exc), **exc.details},
                ok=False,
            ))
            if not args.json:
                print(f"session-peer: {requested_host}: {exc}", file=sys.stderr)

    if args.json:
        emit_json_results(all_results)
    return exit_code


def _doctor_return_host(args: argparse.Namespace) -> str | None:
    host = configured_reply_host(getattr(args, "reply_to", None)) or detect_reply_host()
    if host and "@" not in host:
        host = f"{getpass.getuser()}@{host}"
    return host


def cmd_doctor(args: argparse.Namespace) -> int:
    if args.reply_to and not args.check_return_route:
        raise CcPeerError("--reply-to requires --check-return-route")

    if not args.host:
        if args.check_return_route and not args._return_host:
            args._return_host = _doctor_return_host(args)
        payload = doctor_payload(args)
        if args.check_return_route and not args._return_host:
            payload["returnRoute"] = {
                "status": "failed", "transport": "ssh", "host": None,
                "reason": "return_host_unavailable",
            }
        emit(
            args.json, payload, render_doctor(payload, "this machine"), command="doctor",
        )
        return 0

    exit_code = 0
    all_results = []
    tailnet_status = tailscale_status() or {}
    return_host = _doctor_return_host(args) if args.check_return_route else None
    for requested_host in args.host:
        host = requested_host
        try:
            transport = SshTransport(requested_host, args, tailnet_status)
            host, ssh_opts = transport.host, transport.ssh_opts
            remote_argv = ["doctor", "--no-update-notice"] + agent_remote_options(args)
            if return_host:
                remote_argv.extend(["--_return-host", return_host])
            result = transport.execute(remote_argv)
            payload = {
                key: value for key, value in result.items()
                if key not in {"schemaVersion", "ok", "host", "command", *SSH_METADATA_FIELDS}
            }
            if args.check_return_route and not return_host:
                payload["returnRoute"] = {
                    "status": "failed", "transport": "ssh", "host": None,
                    "reason": "return_host_unavailable",
                }
            host_result = json_result("doctor", {
                **host_metadata(requested_host, host), **ssh_metadata_from(result), **payload,
            })
            all_results.append(host_result)
            if not args.json:
                if len(all_results) > 1:
                    print()
                print(render_doctor(payload, display_host(requested_host, host)))
        except CcPeerError as exc:
            exit_code = EXIT_ERROR
            all_results.append(json_result(
                "doctor",
                {**host_metadata(requested_host, host), "error": str(exc), **exc.details},
                ok=False,
            ))
            if not args.json:
                print(f"session-peer: {requested_host}: {exc}", file=sys.stderr)
    if args.json:
        emit_json_results(all_results)
    return exit_code


def read_message(args: argparse.Namespace) -> str:
    named = getattr(args, "message_option", None)
    if sum(value is not None for value in (args.message, named, args.b64)) > 1:
        raise CcPeerError("Choose one message source: positional message, --message/-m, or internal --b64")
    message = named if named is not None else args.message
    if args.b64 is not None:
        try:
            return base64.b64decode(args.b64, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise CcPeerError(f"--b64 is not valid base64-encoded UTF-8: {exc}") from exc
    if message is None or message == "-":
        if sys.stdin.isatty():
            raise CcPeerError(
                "no message given and stdin is a terminal — "
                "pass --message TEXT, a positional message, or pipe one in"
            )
        try:
            return sys.stdin.read()
        except UnicodeDecodeError as exc:
            raise CcPeerError(f"stdin is not valid UTF-8: {exc}") from exc
    return message


def remote_installed_version(host: str, ssh_opts: list[str],
                             ssh_info: dict | None = None) -> str | None:
    """Version of the copy *installed* on that machine.

    Not the same thing as asking the remote command to report itself:
    run_remote() ships our own source and runs that, so it would always echo
    our version back. The installed file is what a session over there will
    actually use, and it is what can fall behind.
    """
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")
    ssh_info = ssh_user_metadata(host, ssh_opts) if ssh_info is None else ssh_info
    probe = 'python3 "$HOME/.local/share/session-peer/session_peer.py" --version 2>/dev/null'
    try:
        done = subprocess.run(
            ["ssh", *ssh_opts, host, probe],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except FileNotFoundError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", "ssh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ssh_failure_error(host, ssh_info, "timeout") from exc
    except OSError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", str(exc)) from exc
    out = done.stdout.strip()
    detail = done.stderr.strip() or f"ssh exited {done.returncode}"
    failure = classify_ssh_failure(detail, done.returncode) if done.returncode != 0 else None
    if failure:
        raise ssh_failure_error(host, ssh_info, failure, detail)
    return out.split()[-1] if out.startswith("session-peer") else None


def parse_version(text: str) -> tuple[int, ...]:
    """(1, 2, 3) from "v1.2.3". Unparseable parts sort lowest."""
    parts = text.strip().lstrip("vV").split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts[:3])


def stable_version(text: object) -> tuple[int, int, int] | None:
    """Strict stable release version; prereleases and partial tags are ignored."""
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r"[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", text.strip())
    if match is None:
        return None
    values = tuple(int(part) for part in match.groups())
    return values if all(value <= sys.maxsize for value in values) else None


def release_version(text: object) -> tuple[int, int, int, int, int] | None:
    """Strict comparable stable/alpha/beta/rc version without a packaging dependency."""
    if not isinstance(text, str):
        return None
    match = re.fullmatch(
        r"[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:(?:-)?(a|alpha|b|beta|rc|pre|preview)[.-]?(0|[1-9]\d*))?",
        text.strip(),
        re.IGNORECASE,
    )
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups()[:3])
    if any(value > sys.maxsize for value in (major, minor, patch)):
        return None
    label, serial = match.groups()[3:]
    if label is None:
        return major, minor, patch, 3, 0
    stage = {
        "a": 0,
        "alpha": 0,
        "b": 1,
        "beta": 1,
        "rc": 2,
        "pre": 2,
        "preview": 2,
    }[label.lower()]
    return major, minor, patch, stage, int(serial)


def normalized_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def update_cache_path() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / "session-peer" / "update.json"


def update_notices_disabled(args: argparse.Namespace | None = None) -> bool:
    if args is not None and getattr(args, "no_update_notice", False):
        return True
    return os.environ.get(UPDATE_NOTICE_ENV, "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def read_update_cache(path: Path | None = None, now: float | None = None) -> dict:
    """Return an explicit internal cache state; never raise into a CLI command."""
    path = update_cache_path() if path is None else path
    now = time.time() if now is None else now
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            return {"status": "invalid", "reason": "not_regular"}
        if info.st_size > UPDATE_CACHE_MAX_BYTES:
            return {"status": "invalid", "reason": "too_large"}
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "missing"}
    except (OSError, UnicodeError, ValueError):
        return {"status": "invalid", "reason": "unreadable_or_malformed"}

    if not isinstance(value, dict) or value.get("schemaVersion") != UPDATE_CACHE_SCHEMA_VERSION:
        return {"status": "invalid", "reason": "schema"}
    latest = stable_version(value.get("latest"))
    checked_at = value.get("checkedAt")
    if (
        latest is None
        or isinstance(checked_at, bool)
        or not isinstance(checked_at, (int, float))
        or checked_at != checked_at
        or checked_at > now + 300
    ):
        return {"status": "invalid", "reason": "fields"}

    state = {
        "status": "fresh",
        "latest": normalized_version(latest),
        "checkedAt": float(checked_at),
    }
    if now - checked_at >= UPDATE_CACHE_TTL_SECONDS:
        state["status"] = "expired"
    return state


def write_update_cache(tag: str, path: Path | None = None,
                       checked_at: float | None = None) -> Path:
    """Atomically store only public release metadata with user-only permissions."""
    parsed = stable_version(tag)
    if parsed is None:
        raise ValueError("latest release is not a stable semantic version")
    path = update_cache_path() if path is None else path
    checked_at = time.time() if checked_at is None else checked_at
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    encoded = json.dumps({
        "schemaVersion": UPDATE_CACHE_SCHEMA_VERSION,
        "latest": normalized_version(parsed),
        "checkedAt": int(checked_at),
    }, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return path


def update_refresh_lock_path(path: Path | None = None) -> Path:
    cache = update_cache_path() if path is None else path
    return cache.with_name("update.lock")


def schedule_update_refresh(path: Path | None = None, now: float | None = None,
                            popen=None) -> bool:
    """Start one detached refresh and return immediately; all failures are isolated."""
    path = update_cache_path() if path is None else path
    now = time.time() if now is None else now
    source = Path(__file__).resolve()
    if not source.is_file():  # `python3 -` on an SSH destination has no reusable source file.
        return False
    lock = update_refresh_lock_path(path)
    descriptor = None
    owns_lock = False
    try:
        lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            lock.parent.chmod(0o700)
        except OSError:
            pass
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            owns_lock = True
        except FileExistsError:
            try:
                if now - lock.stat().st_mtime < UPDATE_REFRESH_LOCK_SECONDS:
                    return False
                lock.unlink()
            except (FileNotFoundError, OSError):
                return False
            try:
                descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                owns_lock = True
            except FileExistsError:
                # Another invocation won the stale-lock replacement race.
                return False
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        descriptor = None

        launch = subprocess.Popen if popen is None else popen
        options = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            options["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            options["start_new_session"] = True
        launch([sys.executable, str(source), UPDATE_REFRESH_ARG], **options)
        return True
    except Exception:
        if owns_lock:
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                pass
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def refresh_update_cache_background() -> int:
    lock = update_refresh_lock_path()
    try:
        tag, _ = latest_release()
        write_update_cache(tag)
    except (CcPeerError, OSError, ValueError):
        pass
    finally:
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def update_command() -> str:
    if not installed_as_distribution():
        return "session-peer update"
    prefix = tuple(part.lower() for part in Path(sys.prefix).parts)
    if "pipx" in prefix and "venvs" in prefix:
        return "pipx upgrade session-peer"
    if "uv" in prefix and "tools" in prefix:
        return "uv tool upgrade session-peer"
    return "python -m pip install --upgrade session-peer"


def prepare_client_update(args: argparse.Namespace, now: float | None = None,
                          launcher=None) -> dict | None:
    """Read only local cached state; an expired/missing cache refreshes later."""
    if update_notices_disabled(args):
        return None
    if getattr(args, "command", None) == "update" and not getattr(args, "host", []):
        return None
    state = read_update_cache(now=now)
    if state["status"] != "fresh":
        try:
            (schedule_update_refresh if launcher is None else launcher)()
        except Exception:
            pass
        return None
    current = release_version(__version__)
    latest = release_version(state["latest"])
    if current is None or latest is None or latest <= current:
        return None
    checked_at = datetime.fromtimestamp(state["checkedAt"], timezone.utc)
    return {
        "schemaVersion": UPDATE_CACHE_SCHEMA_VERSION,
        "status": "available",
        "current": __version__.lstrip("vV"),
        "latest": state["latest"],
        "checkedAt": checked_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "github_release_cache",
        "command": update_command(),
    }


def latest_release() -> tuple[str, str]:
    """(tag, download URL) of the newest release on GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=DETECT_TIMEOUT * 4) as response:
            release = json.load(response)
            if not isinstance(release, dict):
                raise ValueError("unexpected release response")
            tag = release.get("tag_name", "")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CcPeerError(
            f"could not reach GitHub to check for updates: {exc}. "
            f"On a host with no route out, update it from a machine that has one: "
            f"session-peer update --host <this host>"
        ) from exc
    if not tag:
        raise CcPeerError("GitHub returned no release tag")
    if stable_version(tag) is None:
        raise CcPeerError(f"GitHub returned a non-stable release tag: {tag!r}")
    return tag, f"https://raw.githubusercontent.com/{GITHUB_REPO}/{tag}/session_peer.py"


def installed_as_distribution() -> bool:
    """Do not overwrite a file owned by pip/pipx/uv with the script updater."""
    try:
        dist = metadata.distribution("session-peer")
    except metadata.PackageNotFoundError:
        return False
    target = Path(__file__).resolve()
    return any(Path(dist.locate_file(f)).resolve() == target for f in (dist.files or []))


def cmd_update(args: argparse.Namespace) -> int:
    if not args.host and installed_as_distribution():
        command = update_command()
        if args.check:
            tag, _ = latest_release()
            try:
                write_update_cache(tag)
            except (OSError, ValueError):
                pass
            latest, current = release_version(tag), release_version(__version__)
            outdated = latest is not None and current is not None and current < latest
            state = f"{tag} available" if outdated else "up to date"
            emit(
                args.json,
                {"current": __version__, "latest": tag, "outdated": outdated,
                 "managedBy": "package-manager", "updateCommand": command},
                f"session-peer {__version__} — {state}. Upgrade with: {command}",
                command="update",
            )
            return 0
        emit(
            args.json,
            {"current": __version__, "updated": False,
             "managedBy": "package-manager", "updateCommand": command},
            f"This installation is package-managed. Upgrade with: {command}",
            command="update",
        )
        return 0
    if args.host:
        exit_code = 0
        all_results = []
        tailnet_status = tailscale_status() or {}
        for requested_host in args.host:
            host = requested_host
            try:
                host = resolve_ssh_destination(requested_host, tailnet_status)
                ssh_opts = tailscale_ssh_options(requested_host, host) + args.ssh_opt
                shown_host = display_host(requested_host, host)
                ssh_info = ssh_user_metadata(requested_host, ssh_opts)
                there = remote_installed_version(requested_host, ssh_opts, ssh_info)

                if args.check:
                    if there is None:
                        state = "not installed"
                    elif there == __version__:
                        state = "up to date"
                    else:
                        state = f"{there} → {__version__} available"
                    all_results.append(json_result("update", {
                        **host_metadata(requested_host, host), **ssh_info,
                        "remoteVersion": there, "current": __version__,
                        "outdated": there != __version__,
                    }))
                    if not args.json:
                        print(f"{shown_host}: session-peer {there or '(none)'} — {state}")
                    continue

                if there == __version__:
                    all_results.append(json_result("update", {
                        **host_metadata(requested_host, host), **ssh_info,
                        "remoteVersion": there, "current": __version__,
                        "updated": False,
                    }))
                    if not args.json:
                        print(f"{shown_host} runs session-peer {there} — already current.")
                    continue

                new_version = push_to_remote(requested_host, ssh_opts, ssh_info)
                all_results.append(json_result("update", {
                    **host_metadata(requested_host, host), **ssh_info,
                    "previous": there, "current": __version__, "updated": True,
                }))
                if not args.json:
                    prev = there or "(none)"
                    print(f"{shown_host}: session-peer {prev} → {new_version}")

            except CcPeerError as exc:
                exit_code = EXIT_ERROR
                all_results.append(json_result(
                    "update",
                    {**host_metadata(requested_host, host), "error": str(exc), **exc.details},
                    ok=False,
                ))
                if not args.json:
                    print(f"session-peer: {requested_host}: {exc}", file=sys.stderr)
        if args.json:
            emit_json_results(all_results)
        return exit_code

    tag, url = latest_release()
    try:
        write_update_cache(tag)
    except (OSError, ValueError):
        pass
    latest, current = release_version(tag), release_version(__version__)
    if latest is None or current is None:
        raise CcPeerError("could not compare the installed and latest release versions")

    if args.check:
        state = "up to date" if current >= latest else f"{tag} available"
        emit(
            args.json,
            {"current": __version__, "latest": tag, "outdated": current < latest},
            f"session-peer {__version__} — {state}",
            command="update",
        )
        return 0

    if current >= latest:
        emit(
            args.json,
            {"current": __version__, "latest": tag, "updated": False},
            f"session-peer {__version__} is already current ({tag}).",
            command="update",
        )
        return 0

    target = Path(__file__).resolve()
    try:
        with urllib.request.urlopen(url, timeout=DETECT_TIMEOUT * 4) as response:
            source = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise CcPeerError(f"could not download {tag}: {exc}") from exc
    if b"__version__" not in source:
        raise CcPeerError(f"what came back from {url} does not look like session_peer.py")

    # We are running from the file being replaced. Write beside it and rename,
    # so a failed download can't leave a half-written script behind.
    staged = target.with_suffix(".py.new")
    try:
        staged.write_bytes(source)
        staged.chmod(target.stat().st_mode & 0o777)
        staged.replace(target)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise CcPeerError(f"could not replace {target}: {exc}") from exc

    emit(
        args.json,
        {"current": __version__, "latest": tag, "updated": True, "path": str(target)},
        f"session-peer {__version__} → {tag}  ({target})",
        command="update",
    )
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    if getattr(args, "device", None):
        return optional_relay().invoke_core(args)
    resolved_address = apply_reply_target(args)
    text = read_message(args)
    adapter = AGENTS.for_target(args.to)
    if resolved_address and resolved_address["agent"] != adapter.name:
        raise AdapterError(adapter.name, "invalid_target", "Reply URI agent conflicts with target")
    validate_agent_send(adapter, args)

    # Check the body the user actually wrote. Doing this after the reply line
    # is appended would let an empty message through on the strength of the
    # line alone — which still starts a turn on the other machine.
    check_message(text, remote=bool(args.host))

    # Built here, before dispatch: detection has to run on the sender's machine.
    # Doing it on the far side would advertise the receiver's own address back
    # at it. The --b64 path is this script re-running remotely, where the
    # envelope is already part of the payload.
    advertised_route = None
    if args.b64 is None:
        identity = (
            sender_identity(args.reply_to)
            if not args.no_from or not args.no_reply_to else None
        )
        configured_host = configured_reply_host(args.reply_to)
        local_reply = not args.host and (
            configured_host is None
            or bool(
                identity
                and identity.get("host")
                and is_self_ssh_destination(str(identity["host"]))
            )
        )
        text = wrap_message(
            text,
            explicit_host=args.reply_to,
            with_from=not args.no_from,
            with_reply=not args.no_reply_to,
            local_reply=local_reply,
            identity=identity,
        )
        if not args.no_reply_to:
            advertised_route = reply_route(identity, local_reply)
        if (
            not args.no_reply_to
            and (args.reply_to or (os.environ.get("SESSION_PEER_REPLY_HOST") or os.environ.get("CC_PEER_REPLY_HOST")))
            and identity is None
            and not args.json
        ):
            # A reply address names a session, and outside one there is no name
            # to give. Say so rather than dropping the flag without a word.
            print(
                "session-peer: no reply address sent — a reply needs a session to name, "
                "and this isn't running inside one",
                file=sys.stderr,
            )

    routing_metadata = {}
    if advertised_route:
        routing_metadata["replyRoute"] = advertised_route
    if resolved_address:
        routing_metadata["addressResolution"] = {
            "uri": resolved_address["uri"],
            "transport": resolved_address["transport"],
            **({"normalizedFrom": resolved_address["normalizedFrom"]}
               if "normalizedFrom" in resolved_address else {}),
        }

    validate_agent_send(adapter, args, text)

    if not args.host:
        result = LocalTransport().execute("send", adapter, args, text)
        result.update(routing_metadata)
        emit(args.json, result, adapter.submission_text(result, "this machine"), command="send")
        if advertised_route and advertised_route["status"] == "unverified" and not args.json:
            print(
                "session-peer: reverse SSH reply route was not checked; "
                "run doctor --check-return-route to test it", file=sys.stderr)
        return 0 if result.get("ok", True) else EXIT_ERROR

    exit_code = 0
    all_results = []
    tailnet_status = tailscale_status() or {}
    for requested_host in args.host:
        host = requested_host
        try:
            transport = SshTransport(requested_host, args, tailnet_status)
            host, ssh_opts = transport.host, transport.ssh_opts
            shown_host = display_host(requested_host, host)
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            remote_argv = ["send", "--no-update-notice", "--to", args.to, "--b64", encoded]
            remote_argv += adapter.remote_options(args)
            if args.dry_run:
                remote_argv.append("--dry-run")
            result = transport.execute(remote_argv)
            payload = adapter.remote_submission(result, args, text)
            payload.update(host_metadata(requested_host, host))
            payload.update(routing_metadata)
            all_results.append(json_result("send", payload))
            if payload.get("ok") is False:
                exit_code = EXIT_ERROR
            if not args.json:
                print(adapter.submission_text(payload, shown_host))
        except CcPeerError as exc:
            exit_code = EXIT_ERROR
            all_results.append(json_result(
                "send",
                {**host_metadata(requested_host, host), "error": str(exc), **exc.details},
                ok=False,
            ))
            if not args.json:
                print(f"session-peer: {requested_host}: {exc}", file=sys.stderr)

    if args.json:
        emit_json_results(all_results)
    elif (
        advertised_route and advertised_route["status"] == "unverified"
        and any(result.get("ok") for result in all_results)
    ):
        print(
            "session-peer: reverse SSH reply route was not checked; "
            "run doctor --check-return-route to test it",
            file=sys.stderr,
        )
    return exit_code


def optional_relay():
    if sys.version_info < (3, 11) or os.name != 'posix':
        raise CcPeerError('Paired devices require Python 3.11+ on macOS/Linux')
    try:
        from session_peer_relay import cli
        return cli
    except ImportError as exc:
        raise CcPeerError('Install session-peer[relay] to use paired devices') from exc


def cmd_optional_relay(args):
    return optional_relay().main(args.command, ["--help"] if args.relay_help else args.relay_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="session-peer",
        description="Message Claude Code and Codex sessions locally or over SSH.",
    )
    parser.add_argument("--version", action="version", version=f"session-peer {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--host", action="append", default=[], metavar="DEST",
            help="SSH [USER@]HOST, repeatable; otherwise User comes from SSH config/default",
        )
        sub.add_argument(
            "--ssh-opt",
            action="append",
            default=[],
            metavar="OPT",
            help="extra ssh argument, repeatable (e.g. --ssh-opt -p --ssh-opt 2222)",
        )
        sub.add_argument("--output-format", choices=("text", "json"),
                         help="command result format (default: text); does not change message input")
        sub.add_argument("--json", action="store_true", help="alias for --output-format json (command results only)")
        sub.add_argument(
            "--no-update-notice", action="store_true",
            help="disable automatic cached update notices and refreshes",
        )

    listing = subparsers.add_parser("list", help="list sessions that can be messaged")
    add_common(listing)
    listing.add_argument("--agent", choices=AGENTS.names(), default=None,
                         help="filter by agent (default: all registered adapters)")
    home_help = ("select one Codex home on the destination (default: CODEX_HOME or ~/.codex); "
                 "set explicitly for Orca/multiple homes")
    listing.add_argument("--codex-home", help="list only this destination home (default: known default, CODEX_HOME, Orca and configured homes)")
    listing.add_argument("--codex-bin", help="Codex executable on the destination (used by send)")
    listing.add_argument(
        "--all", action="store_true", help="include stale records and sessions with no inbox"
    )
    listing.set_defaults(func=cmd_list)

    doctor = subparsers.add_parser(
        "doctor", help="diagnose agent homes, inboxes, tools, and optional return routes",
    )
    add_common(doctor)
    doctor.add_argument("--codex-home", help=home_help)
    doctor.add_argument("--codex-bin", help="Codex executable on the destination machine")
    doctor.add_argument(
        "--check-return-route", action="store_true",
        help="from the diagnosed host, test a non-interactive SSH route back here",
    )
    doctor.add_argument(
        "--reply-to", metavar="HOST",
        help="return host to test (default: this machine's detected tailnet address)",
    )
    doctor.add_argument("--_return-host", dest="_return_host", help=argparse.SUPPRESS)
    doctor.set_defaults(func=cmd_doctor)

    sending = subparsers.add_parser("send", help="send one message to a session")
    add_common(sending)
    sending.add_argument(
        "--to", required=True, metavar="TARGET|REPLY-URI",
        help="session name, PID, codex:UUID, antigravity:UUID, or session-peer://v1/reply address",
    )
    sending.add_argument("--codex-home", help=home_help)
    sending.add_argument(
        "--allow-inactive-codex-home", action="store_true",
        help="with --codex-home, intentionally queue an inactive thread for a future resume",
    )
    sending.epilog = ("All matching known homes are checked even with --codex-home. A unique "
                      "stable live writer is required unless --codex-home and "
                      "--allow-inactive-codex-home explicitly select an all-inactive copy. "
                      "Known homes: selected/default, macOS "
                      "Orca account homes, and destination SESSION_PEER_CODEX_HOMES (JSON array "
                      "of paths). Queued/submitted never confirms consumption.")
    sending.add_argument("--codex-bin", help="Codex executable on the destination machine")
    sending.add_argument("message", nargs="?", help="message text (legacy positional form); omit or use - to read stdin")
    sending.add_argument("--message", "-m", dest="message_option", metavar="TEXT",
                         help="message body; use - for stdin; cannot combine with a positional message")
    sending.add_argument("--b64", help=argparse.SUPPRESS)  # used for remote dispatch
    sending.add_argument(
        "--reply-to",
        metavar="HOST",
        help="reply address to advertise (default: this machine's tailnet address)",
    )
    sending.add_argument(
        "--no-reply-to", action="store_true", help="send without a reply address"
    )
    sending.add_argument(
        "--no-from", action="store_true", help="send without the From: header"
    )
    sending.add_argument("--wake", action="store_true", help="explicitly resume a Codex thread; may use models and modify history")
    sending.add_argument("--wake-timeout", type=int, choices=range(1, 61), default=30, metavar="SECONDS",
                         help="wake deadline, 1..60 seconds (default: 30)")
    sending.add_argument("--dry-run", action="store_true", help="resolve the target, send nothing")
    sending.set_defaults(func=cmd_send)

    updating = subparsers.add_parser("update", help="update this installation")
    add_common(updating)
    updating.add_argument(
        "--check", action="store_true", help="report the available version, change nothing"
    )
    updating.set_defaults(func=cmd_update)

    for sub in (listing, sending, doctor):
        sub.add_argument('--antigravity-home', help='filter registered Antigravity home on the destination')
    sending.add_argument('--antigravity-generation', help='require this registered bridge generation')
    sending.add_argument('--request-id', help='attempt UUID for paired-device journaling or generation-pinned Antigravity deduplication')
    bridge = subparsers.add_parser('antigravity-bridge', help='opt-in bridge; start inside the target agy TUI tool environment')
    bridge.add_argument('action', choices=('serve', 'stop'))
    bridge.add_argument('--thread', required=True, help='exact existing Antigravity conversation UUID')
    bridge.add_argument('--antigravity-home', help='target home (default: ~/.gemini/antigravity-cli)')
    bridge.add_argument('--ttl', type=int, choices=range(1, 86401), default=3600, metavar='SECONDS')
    bridge.add_argument('--max-requests', type=int, choices=range(1, 10001), default=1000, metavar='COUNT')
    bridge.set_defaults(func=cmd_agy_bridge, json=False, no_update_notice=True)

    for sub in (listing, sending):
        sub.add_argument('--device', help='paired receiver fingerprint; exclusive with --host')
        sub.add_argument('--device-state', help='local device state directory')
        sub.add_argument('--device-route', choices=('auto', 'direct', 'relay'), default='auto')
        sub.add_argument('--relay-admission-file', help='private client admission credential file')
        sub.add_argument('--relay-login', action='store_true', help='use an explicitly saved device login for relay admission')
    for name in ('device', 'relay'):
        sub = subparsers.add_parser(name, add_help=False, help='optional paired-device '+name+' management')
        sub.add_argument('--help', '-h', dest='relay_help', action='store_true')
        sub.add_argument('relay_args', nargs=argparse.REMAINDER)
        sub.set_defaults(func=cmd_optional_relay, json=True, no_update_notice=True)
    return parser


def json_error_result(args: argparse.Namespace, payload: dict) -> dict | list[dict]:
    """Attribute command-wide failures to every requested destination."""
    command = getattr(args, "command", None) or "unknown"
    hosts = list(getattr(args, "host", None) or [])
    if not hosts:
        return json_result(command, payload, ok=False)
    return one_or_many([
        json_result(command, payload, host=host, ok=False)
        for host in hosts
    ])


def main(argv: list[str] | None = None) -> int:
    global _CLIENT_UPDATE_NOTICE
    cli_invocation = argv is None
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv == [UPDATE_REFRESH_ARG]:
        return refresh_update_cache_background()

    if IS_WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(raw_argv)
    output_format = getattr(args, "output_format", None)
    if args.json and output_format == "text":
        parser.error("--json conflicts with --output-format text")
    args.json = args.json or output_format == "json"
    try:
        _CLIENT_UPDATE_NOTICE = prepare_client_update(args) if cli_invocation else None
    except Exception:
        # Update discovery is advisory. Even an unexpected cache or launcher
        # failure must not change the requested command's result or exit code.
        _CLIENT_UPDATE_NOTICE = None
    show_human_notice = True
    try:
        exit_code = args.func(args)
    except CcPeerError as exc:
        message = str(exc)
        if args.json:
            payload = json_error_result(args, {"error": message, **exc.details})
            print(json.dumps(with_client_update(payload), ensure_ascii=False))
        else:
            print(f"session-peer: {message}", file=sys.stderr)
        exit_code = (
            EXIT_NO_TARGET
            if isinstance(exc, NoTargetError) or "no reachable session" in message
            else EXIT_ERROR
        )
    except KeyboardInterrupt:
        show_human_notice = False
        exit_code = 130
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if getattr(args, "json", False):
            payload = json_error_result(args, {"error": message})
            print(json.dumps(with_client_update(payload), ensure_ascii=False))
        else:
            print(f"session-peer: {message}", file=sys.stderr)
        exit_code = EXIT_ERROR
    if show_human_notice and not args.json:
        emit_human_update_notice()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
