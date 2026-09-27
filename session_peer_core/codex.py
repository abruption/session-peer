
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
        # An unsaved first turn may already hold the native writer lock. This
        # is diagnostic evidence only: queueing still requires a saved thread.
        for home, candidate in zip(homes, candidates):
            candidate.update(inspect_codex_writer(home, thread_id))
        unsaved_live = [candidate for candidate in candidates
                        if candidate.get("activity") == "live_writer"]
        if len(unsaved_live) == 1 and (not explicit or unsaved_live[0]["codexHome"] == str(selected)):
            resolution = _home_resolution(
                "unknown", None, "thread_not_yet_persisted", candidates
            )
            raise NoTargetError(
                f"Codex thread {thread_id} has a live writer but is not saved yet. "
                "Wait for its first turn to finish; nothing queued.",
                {"codexHomeResolution": resolution},
            )
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


def count_unsaved_codex_writers(home: Path, *, limit: int = 256) -> tuple[int, bool]:
    """Bounded, read-only check for live writer locks absent from the state DB."""
    directory = home / "thread-writer-locks"
    try:
        entries = sorted(path for path in directory.iterdir() if path.suffix == ".lock")
    except FileNotFoundError:
        return 0, False
    count = 0
    for path in entries[:limit]:
        thread_id = path.stem
        try:
            if str(uuid.UUID(thread_id)) != thread_id or _codex_thread_is_saved(home, thread_id):
                continue
        except ValueError:
            continue
        if inspect_codex_writer(home, thread_id).get("activity") == "live_writer":
            count += 1
    return count, len(entries) > limit


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
