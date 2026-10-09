# Optional discovery-to-inbox preconditions. These are not ACK or dedup keys.

def generation_refused(reason: str, message: str, *, expected_generation=None) -> CcPeerError:
    details = {"status": "refused", "reason": reason,
               "submitted": False, "retryAllowed": False}
    # Original discovery precondition only: never reflect a successor's name,
    # PID, host, path or native creation evidence as "last seen" metadata.
    if (reason == "stale_target" and isinstance(expected_generation, str)
            and re.fullmatch(r"tg1:[0-9a-f]{64}", expected_generation)):
        details["lastSeenTarget"] = {"agent": "claude", "targetGeneration": expected_generation}
    return CcPeerError(message, details)


def process_generation(pid: int) -> str | None:
    """Use native creation evidence, never the second-resolution ps display."""
    if type(pid) is not int or pid <= 1:
        return None
    try:
        if sys.platform == "linux":
            # comm may contain spaces and ')'; fields after the final ')' start
            # at field 3, so starttime (22) is offset 19.
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            return f"linux:{boot}:{fields[19]}" if fields[19].isdigit() else None
        if sys.platform == "darwin":
            import ctypes
            class BsdInfo(ctypes.Structure):
                _fields_ = [("prefix", ctypes.c_uint32 * 12),
                            ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
                            ("suffix", ctypes.c_uint32 * 6),
                            ("seconds", ctypes.c_uint64), ("micros", ctypes.c_uint64)]
            lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            lib.proc_pidinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                        ctypes.c_void_p, ctypes.c_int)
            lib.proc_pidinfo.restype = ctypes.c_int
            value = BsdInfo()
            if lib.proc_pidinfo(pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value)) != ctypes.sizeof(value):
                return None
            if value.prefix[3] != pid or not value.seconds:
                return None
            return f"darwin:{value.seconds}:{value.micros}"
        if sys.platform == "win32":
            rows = _windows_process_inspect("identity", str(pid))
            return "win32:" + rows[0]["startTime"] if rows and len(rows) == 1 else None
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    return None


def claude_generation(session: dict) -> str | None:
    """Hash bounded registry/process/endpoint facts; expose no raw native key."""
    import hashlib
    try:
        pid = session["pid"]
        birth = process_generation(pid)
        if not birth:
            return None
        directory = sessions_dir().resolve()
        record = read_claude_record(directory / f"{pid}.json")
        endpoint = record.get("messagingSocketPath")
        if record["pid"] != pid or endpoint != session["socket"]:
            return None
        identity = ["claude", sys.platform, socket.gethostname(), str(directory), pid, birth, endpoint]
        if not IS_WINDOWS:
            node = Path(endpoint).lstat()
            if not stat.S_ISSOCK(node.st_mode):
                return None
            identity += [node.st_dev, node.st_ino]
        else:
            if not endpoint.startswith("\\\\.\\pipe\\"):
                return None
            identity += [record.get("startedAt")]
        return "tg1:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False,
                                                separators=(",", ":")).encode("utf-8")).hexdigest()
    except (OSError, ValueError, KeyError, RuntimeError):
        return None


def validate_target_generation(value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"tg1:[0-9a-f]{64}", value)):
        raise generation_refused("invalid_target_generation", "Invalid target generation; run discovery again")


def require_claude_generation(session: dict, expected: str) -> None:
    validate_target_generation(expected)
    current = claude_generation(session)
    if current is None:
        raise generation_refused("target_generation_unavailable", "Cannot prove the selected inbox generation; nothing sent")
    if current != expected:
        raise generation_refused("stale_target", "The selected inbox generation changed; nothing sent",
                                 expected_generation=expected)


def connected_inbox_pid(conn) -> int | None:
    """Read credentials for the connected endpoint, not its current pathname."""
    import struct
    try:
        if sys.platform == "linux" and hasattr(socket, "SO_PEERCRED"):
            return struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]
        if sys.platform == "darwin":
            # SOL_LOCAL / LOCAL_PEERPID from sys/un.h.
            return struct.unpack("i", conn.getsockopt(0, 2, 4))[0]
    except (OSError, ValueError, struct.error):
        pass
    return None


def connected_pipe_pid(pipe) -> int | None:
    try:
        import ctypes
        from ctypes import wintypes
        import msvcrt
        function = ctypes.windll.kernel32.GetNamedPipeServerProcessId
        function.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
        function.restype = wintypes.BOOL
        pid = wintypes.ULONG()
        return pid.value if function(msvcrt.get_osfhandle(pipe.fileno()), ctypes.byref(pid)) else None
    except (OSError, AttributeError, ValueError):
        return None


def verify_connected_generation(session: dict, expected: str, server_pid: int | None) -> None:
    if server_pid is None:
        raise generation_refused("target_generation_unavailable", "Connected inbox identity unavailable; nothing sent")
    if server_pid != session["pid"]:
        raise generation_refused("stale_target", "Connected inbox belongs to another process; nothing sent",
                                 expected_generation=expected)
    require_claude_generation(session, expected)
