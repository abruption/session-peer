

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
    if not isinstance(record, dict) or type(record.get("pid")) is not int:
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
    if pid <= 1:
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
    if pid <= 1:
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
    if type(pid) is not int or pid != record_pid:
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
            record = read_claude_record(record_file)
        except (OSError, ValueError):
            continue

        pid = record.get("pid")
        if not isinstance(pid, int):
            continue

        sock = record.get("messagingSocketPath") or ""
        alive, stale_reason = claude_process_state(record, int(record_file.stem))
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
        if stale_reason:
            entry["staleReason"] = stale_reason
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


def _post_to_pipe(pipe_path: str, pid: int, text: str, *, generation_session=None,
                  expected_generation=None) -> None:
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
