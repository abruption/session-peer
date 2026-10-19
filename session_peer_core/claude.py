

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


# Registry records contain identity/inbox metadata, not conversation history.
# A 1 MiB ceiling leaves ample room for additional metadata without unbounded IO.
MAX_CLAUDE_RECORD_BYTES = 1024 * 1024
MAX_CLAUDE_PROFILES = 128
MAX_CLAUDE_RECORDS = 4096


class ClaudeSessions(list):
    """List-compatible internal discovery errors; never serialized as rows."""
    def __init__(self):
        super().__init__()
        self.errors = []
        self.enumerated = 0
        self.invalid_records = 0
        self.permission_failures = 0


class ClaudeSession(dict):
    """Native row with non-JSON provenance for the original registry selection."""
    pass


def claude_registry_directories():
    """Bounded known Orca inventory, never an arbitrary recursive home scan."""
    selected = sessions_dir()
    directories, errors = [selected], []
    if any(os.environ.get(key) for key in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_CONFIG_DIR")):
        return directories, errors
    # Orca's macOS account-profile location is not a cross-platform convention.
    if sys.platform != "darwin" or selected != Path.home() / ".claude/sessions":
        return directories, errors
    base = Path.home() / "Library/Application Support/orca/claude-profiles"
    try:
        _claude_safe_directory(base)
        with os.scandir(base) as iterator:
            entries = []
            for entry in iterator:
                if len(entries) >= MAX_CLAUDE_PROFILES:
                    errors.append("profile_inventory_limit")
                    break
                entries.append(Path(entry.path))
        for profile in sorted(entries):
            try:
                node = profile.lstat()
                if (not stat.S_ISDIR(node.st_mode) and not stat.S_ISLNK(node.st_mode)
                        and not getattr(node, "st_file_attributes", 0) & 0x400):
                    continue  # Finder/metadata files are not profile homes.
                for directory in (profile, profile / "home", profile / "home/sessions"):
                    _claude_safe_directory(directory)
                candidate = profile / "home/sessions"
                if candidate not in directories:
                    directories.append(candidate)
            except FileNotFoundError:
                continue  # A profile need not have started Claude yet.
            except (OSError, ValueError):
                errors.append("profile_directory_unavailable")
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        errors.append("profile_inventory_unavailable")
    return directories, errors


def _claude_safe_directory(path, *, same_user=True):
    node = path.lstat()
    if (not stat.S_ISDIR(node.st_mode) or getattr(node, "st_file_attributes", 0) & 0x400
            or (same_user and hasattr(os, "getuid") and node.st_uid != os.getuid())):
        raise ValueError("Unsafe Claude profile directory")
    return (node.st_dev, node.st_ino)


def claude_selection_directory(session):
    return getattr(session, "registry_directory", sessions_dir())


def revalidate_claude_selection(session):
    """Do not rediscover or retarget a selected profile after replacement."""
    if not isinstance(session, ClaudeSession):
        return  # Compatibility for adapter/test callers supplying legacy rows.
    try:
        directory = session.registry_directory
        if (directory.resolve() != session.registry_canonical
                or tuple(_claude_safe_directory(path, same_user=session.registry_same_user)
                         for path in session.registry_chain) != session.registry_identity):
            raise ValueError("Registry directory changed")
        record = read_claude_record(directory / f"{session['pid']}.json")
        if (record["pid"] != session["pid"] or record.get("messagingSocketPath") != session["socket"]
                or record.get("startedAt") != session.registry_started
                or not claude_process_state(record, session["pid"])[0]):
            raise ValueError("Registry selection changed")
        if not IS_WINDOWS:
            node = Path(session["socket"]).lstat()
            if (not stat.S_ISSOCK(node.st_mode)
                    or (node.st_dev, node.st_ino) != session.registry_endpoint):
                raise ValueError("Inbox changed")
    except (OSError, ValueError, KeyError, RuntimeError):
        raise CcPeerError("Selected Claude profile or inbox changed; discover again; nothing sent") from None


def parse_claude_pid(value) -> int | None:
    """Parse a bounded native PID without confusing digit-like names with PIDs.

    Decimal Unicode digits remain compatible with numeric addressing. Other
    numeric characters (for example superscripts) are names, not decimal PIDs.
    Reject invalid integers before signal inspection or Windows DWORD coercion.
    """
    if isinstance(value, str):
        if len(value) > 10 or not value.isdecimal():
            return None
        value = int(value)
    if type(value) is not int:
        return None
    maximum = (1 << 32) - 1 if IS_WINDOWS else (1 << 31) - 1
    return value if 1 < value <= maximum else None


def read_claude_record(path: Path) -> dict:
    """Read bounded regular-file metadata; leave permission errors to callers.

    POSIX nonblocking/no-follow opens reject FIFO/symlink replacement where the
    flags exist. Windows uses binary reads and descriptor/path identity checks;
    neither this fallback nor filesystem IO provides a universal time bound.
    """
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_CLAUDE_RECORD_BYTES:
        raise ValueError("Claude session record is not a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if not IS_WINDOWS:
        flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        identity = (before.st_dev, before.st_ino)
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode)
                or (opened.st_dev, opened.st_ino) != identity
                or (current.st_dev, current.st_ino) != identity
                or opened.st_size > MAX_CLAUDE_RECORD_BYTES):
            raise ValueError("Claude session record changed before reading")
        chunks = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_CLAUDE_RECORD_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_CLAUDE_RECORD_BYTES:
                raise ValueError("Claude session record exceeds the byte limit")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    try:
        record = json.loads(b"".join(chunks).decode("utf-8", errors="strict"))
    except RecursionError as exc:
        raise ValueError("Claude session record is too deeply nested") from exc
    if (not isinstance(record, dict) or type(record.get("pid")) is not int
            or parse_claude_pid(record.get("pid")) is None):
        raise ValueError("Claude session record must be an object with an integer PID")
    for field in ("name", "cwd", "status", "messagingSocketPath"):
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError("Claude session record has invalid text metadata")
        if isinstance(value, str):
            # Escaped lone surrogates can pass JSON decoding but cannot be
            # encoded safely for an inbox path, sender header or CLI output.
            value.encode("utf-8", errors="strict")
    if "\0" in (record.get("messagingSocketPath") or ""):
        raise ValueError("Claude session record has an invalid inbox path")
    return record


def windows_process_start_ms(pid: int) -> int | None:
    """Read a live Windows process creation time without trusting a stale PID."""
    if parse_claude_pid(pid) is None or type(pid) is not int:
        return None
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.POINTER(FILETIME),
                                         ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                                         ctypes.POINTER(FILETIME))
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        return None
    try:
        if kernel32.WaitForSingleObject(handle, 0) != 0x102:  # WAIT_TIMEOUT: still running
            return None
        created, exited, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(kernel), ctypes.byref(user)):
            return None
        if kernel32.WaitForSingleObject(handle, 0) != 0x102:
            return None
        ticks = (created.high << 32) | created.low
        return (ticks - 116444736000000000) // 10000
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    if parse_claude_pid(pid) is None or type(pid) is not int:
        return False
    if IS_WINDOWS:
        return windows_process_start_ms(pid) is not None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def claude_process_state(record: dict, record_pid: int) -> tuple[bool, str | None]:
    """Fail closed when a Windows session record outlives its process identity."""
    pid = record.get("pid")
    if type(pid) is not int or parse_claude_pid(pid) is None or pid != record_pid:
        return False, "record_pid_mismatch"
    if not IS_WINDOWS:
        return pid_alive(pid), None
    current_start = windows_process_start_ms(pid)
    if current_start is None:
        return False, "process_not_live"
    recorded_start = record.get("startedAt")
    if type(recorded_start) is not int or recorded_start <= 0:
        return False, "missing_start_time"
    if current_start > recorded_start + 2000:
        return False, "pid_reused"
    return True, None


def discover(include_unreachable: bool = False) -> list[dict]:
    """List this machine's Claude Code sessions.

    The socket path is read from each record, never guessed. It is not always
    under /tmp: a session may bind under $XDG_RUNTIME_DIR, or under a private
    per-user directory when Claude Code rejects the one it would have used.
    """
    found = ClaudeSessions()
    directories, found.errors = claude_registry_directories()
    found.multiple = len(directories) > 1 or bool(found.errors)
    for directory in directories:
        _discover_claude_directory(directory, found)
    return _finish_claude_discovery(found, include_unreachable)


def _finish_claude_discovery(found, include_unreachable):
    # Neither PID nor inbox ownership may depend on inventory order. Exact
    # duplicates are aliases; divergent claims remain visible but unreachable.
    unique, by_pid, by_socket, conflicts = [], {}, {}, set()
    for row in found:
        if not row["alive"]:
            unique.append(row)
            continue  # A proven dead/stale process no longer claims an inbox.
        candidates = by_pid.get(row["pid"], []) + by_socket.get(row["socket"], [])
        if any(dict(item) == dict(row) and item.registry_canonical == row.registry_canonical
               and item.registry_started == row.registry_started for item in candidates):
            continue
        for other in candidates:
            conflicts.update((id(row), id(other)))
        unique.append(row)
        by_pid.setdefault(row["pid"], []).append(row)
        if row["socket"]:
            by_socket.setdefault(row["socket"], []).append(row)
    found.clear()
    if conflicts:
        found.errors.append("conflicting_session_records")
    for row in unique:
        if id(row) in conflicts:
            row.update(reachable=False, staleReason="conflicting_session_records")
        if row["reachable"] or include_unreachable:
            found.append(row)
    return found


def _discover_claude_directory(directory, found):
    try:
        selected = directory.resolve()
        base = Path.home() / "Library/Application Support/orca/claude-profiles"
        automatic_profile = directory != sessions_dir() and directory.parent.parent.parent == base
        chain = ([base, directory.parent.parent, directory.parent, directory]
                 if automatic_profile else [selected])
        identity = tuple(_claude_safe_directory(path, same_user=automatic_profile) for path in chain)
        entries = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                if found.enumerated >= MAX_CLAUDE_RECORDS:
                    found.errors.append("session_inventory_limit")
                    break
                # Count all entries, not only records, to bound enumeration.
                entries.append(Path(entry.path))
                found.enumerated += 1
        entries.sort()
    except FileNotFoundError:
        if directory != sessions_dir():
            found.errors.append("sessions_directory_unavailable")
        return
    except (OSError, ValueError, RuntimeError):
        if not found.multiple and directory == sessions_dir():
            raise CcPeerError("Cannot read Claude sessions: selected directory is unavailable") from None
        found.errors.append("sessions_directory_unavailable")
        return
    for record_file in entries:
        if record_file.suffix != ".json":
            continue
        record_pid = parse_claude_pid(record_file.stem)
        if record_pid is None:
            if record_file.stem.isdigit():
                found.invalid_records += 1
            continue
        try:
            record = read_claude_record(record_file)
        except (OSError, ValueError) as exc:
            found.invalid_records += 1
            if isinstance(exc, PermissionError):
                found.permission_failures += 1
            if found.multiple or directory != sessions_dir():
                found.errors.append("session_record_unavailable")
            continue

        pid = record.get("pid")
        if not isinstance(pid, int):
            continue

        sock = record.get("messagingSocketPath") or ""
        alive, stale_reason = claude_process_state(record, record_pid)
        if IS_WINDOWS:
            has_inbox = bool(sock) and sock.startswith("\\\\.\\pipe\\")
        else:
            try:
                has_inbox = bool(sock) and Path(sock).is_socket()
            except OSError:
                has_inbox = False

        entry = ClaudeSession({
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
        })
        try:
            if (directory.resolve() != selected
                    or tuple(_claude_safe_directory(path, same_user=automatic_profile)
                             for path in chain) != identity):
                raise ValueError("Registry changed")
            entry.registry_directory = directory
            entry.registry_canonical = selected
            entry.registry_chain = chain
            entry.registry_same_user = automatic_profile
            entry.registry_identity = identity
            entry.registry_started = record.get("startedAt")
            if not IS_WINDOWS and has_inbox:
                node = Path(sock).lstat()
                entry.registry_endpoint = (node.st_dev, node.st_ino)
            else:
                entry.registry_endpoint = None
        except (OSError, ValueError, RuntimeError):
            found.errors.append("session_record_unavailable")
            continue
        if stale_reason:
            entry["staleReason"] = stale_reason
        found.append(entry)


def resolve_target(sessions: list[dict], target: str) -> dict:
    """Find one session by name, or by pid when the target is all digits."""
    if getattr(sessions, "errors", []):
        raise CcPeerError("Claude profile discovery is incomplete; cannot select an unambiguous target; "
                          "set CLAUDE_CONFIG_DIR to the intended profile and discover again")
    reachable = [s for s in sessions if s["reachable"]]

    if target.isdecimal():
        target_pid = parse_claude_pid(target)
        matches = [s for s in reachable if s["pid"] == target_pid]
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


def _read_win_auth(pid: int, directory=None) -> str | None:
    """Read the Windows auth key for a session and return the auth JSON line."""
    directory = sessions_dir() if directory is None else directory
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


def _post_to_pipe(pipe_path: str, pid: int, text: str, *, generation_session=None,
                  expected_generation=None) -> None:
    """Write one message to a Windows named pipe inbox."""
    check_message(text, remote=False)

    auth_line = (_read_win_auth(pid, claude_selection_directory(generation_session))
                 if isinstance(generation_session, ClaudeSession) else _read_win_auth(pid))
    if auth_line is None:
        raise CcPeerError(f"no auth key found for pid {pid} — cannot post to Windows pipe")

    payload = json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}},
        ensure_ascii=False,
    )

    import time
    try:
        with open(pipe_path, "wb") as pipe:
            if generation_session is not None:
                revalidate_claude_selection(generation_session)
            if expected_generation is not None:
                verify_connected_generation(generation_session, expected_generation, connected_pipe_pid(pipe))
            pipe.write((auth_line + "\n").encode("utf-8"))
            pipe.write((payload + "\n").encode("utf-8"))
            pipe.flush()
            time.sleep(DRAIN_TIMEOUT)
    except OSError as exc:
        raise CcPeerError(f"cannot reach inbox at {pipe_path}: {exc}") from exc


def post_to_socket(socket_path: str, text: str, pid: int = 0, *, generation_session=None,
                   expected_generation=None, effect_deadline=None, total_deadline=None) -> None:
    """Write one message to a session's inbox socket.

    On macOS and Linux the {"type":"auth",...} line the docs describe is
    optional, so this sends the message on its own. On Windows, auth is
    mandatory — the token is read from the session's .key file and sent
    before the message. Claude Code closes a connection that has not sent
    a complete line within 30 seconds, so the message is built before the
    socket is opened.
    """
    if generation_session is not None:
        revalidate_claude_selection(generation_session)
    bounded = effect_deadline is not None or total_deadline is not None
    if bounded:
        import math
        if (type(effect_deadline) not in (int, float) or type(total_deadline) not in (int, float)
                or not math.isfinite(effect_deadline) or not math.isfinite(total_deadline)
                or effect_deadline > total_deadline):
            raise generation_refused("invalid_effect_deadline", "Invalid private effect budget; nothing sent")
        if IS_WINDOWS:
            # Python's synchronous named-pipe open/write has no proven bounded
            # cancellation contract. Never advertise it as bounded handoff.
            raise generation_refused("unsupported_bounded_inbox", "Bounded Windows pipe submission is unsupported")
        if time.monotonic() >= effect_deadline:
            raise generation_refused("effect_deadline_exhausted", "Effect budget exhausted; nothing sent")
    if IS_WINDOWS and socket_path.startswith("\\\\.\\pipe\\"):
        _post_to_pipe(socket_path, pid, text, generation_session=generation_session,
                      expected_generation=expected_generation)
        return

    check_message(text, remote=False)

    payload = json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}},
        ensure_ascii=False,
    )

    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        remaining = effect_deadline - time.monotonic() if bounded else CONNECT_TIMEOUT
        if remaining <= 0:
            raise generation_refused("effect_deadline_exhausted", "Effect budget exhausted; nothing sent")
        conn.settimeout(min(CONNECT_TIMEOUT, remaining))
        try:
            conn.connect(socket_path)
        except OSError as exc:
            if bounded:
                raise generation_refused("inbox_connection_failed", "Inbox connection failed before any write") from exc
            raise CcPeerError(f"cannot reach inbox at {socket_path}: {exc}") from exc

        try:
            if generation_session is not None:
                revalidate_claude_selection(generation_session)
            if expected_generation is not None:
                verify_connected_generation(generation_session, expected_generation, connected_inbox_pid(conn))
            if bounded:
                remaining = effect_deadline - time.monotonic()
                if remaining <= 0:
                    raise generation_refused("effect_deadline_exhausted", "Effect budget exhausted; nothing sent")
                conn.settimeout(remaining)
            conn.sendall((payload + "\n").encode("utf-8"))
            conn.shutdown(socket.SHUT_WR)
            remaining = effect_deadline - time.monotonic() if bounded else DRAIN_TIMEOUT
            if remaining <= 0:
                return  # Full write retained; no further wait beyond cutoff.
            conn.settimeout(min(DRAIN_TIMEOUT, remaining))
            try:
                conn.recv(1)
            except OSError:
                pass
        except OSError as exc:
            if bounded:
                raise CcPeerError("Inbox write outcome unknown; do not automatically retry",
                                  {"status": "unknown", "reason": "outcome_unknown",
                                   "retryAllowed": False}) from exc
            raise CcPeerError(f"failed writing to {socket_path}: {exc}") from exc
    finally:
        conn.close()
