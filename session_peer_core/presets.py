"""Explicit, route-only POSIX presets; never a session identity or authority."""

import hashlib


PRESET_MAX_BYTES = 65536
PRESET_MAX_ENTRIES = 128
PRESET_LOCK_SECONDS = 1.0


def _preset_error(reason):
    return CcPeerError("preset configuration refused: " + reason, {"reason": reason})


def _preset_platform():
    if IS_WINDOWS or fcntl is None:
        raise _preset_error("preset_platform_unsupported")


def _preset_name(name):
    if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) is None:
        raise _preset_error("preset_invalid_name")


def _preset_string(value, limit):
    if (not isinstance(value, str) or not value or len(value) > limit
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise _preset_error("preset_invalid_route")


def preset_validate_entry(entry):
    """Return a fresh allowlisted route, without executing or resolving it."""
    if not isinstance(entry, dict):
        raise _preset_error("preset_invalid_route")
    transport, agent = entry.get("transport"), entry.get("agent")
    if transport not in ("local", "ssh") or agent not in ("claude", "codex"):
        raise _preset_error("preset_invalid_route")
    expected = {"transport", "agent"}
    if transport == "ssh":
        expected.add("host")
    if agent == "codex":
        expected.add("codexHome")
    if set(entry) != expected:
        raise _preset_error("preset_invalid_route")
    if transport == "ssh":
        host = entry["host"]
        _preset_string(host, 1024)
        if (host.count("@") > 1 or ("@" in host and not all(host.split("@")))
                or ("@" in host and ":" in host.split("@", 1)[0])):
            raise _preset_error("preset_invalid_route")
        try:
            check_ssh_argument(host, "--host")
        except CcPeerError:
            raise _preset_error("preset_invalid_route") from None
    if agent == "codex":
        home = entry["codexHome"]
        _preset_string(home, 4096)
        if not PurePosixPath(home).is_absolute() or home.startswith("//") or "\\" in home:
            raise _preset_error("preset_invalid_route")
    return dict(entry)


def preset_revision(name, entry):
    """Change token over exact validated values, NOT identity or permission."""
    _preset_name(name)
    route = preset_validate_entry(entry)
    raw = json.dumps({"schemaVersion": 1, "name": name, "route": route},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return "dp1:" + hashlib.sha256(raw).hexdigest()


def _preset_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _preset_error("preset_corrupt")
        result[key] = value
    return result


def _preset_decode(raw):
    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_preset_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (not isinstance(value, dict) or set(value) != {"schemaVersion", "presets"}
                or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
                or not isinstance(value["presets"], dict)):
            raise ValueError()
        entries = value["presets"]
        if len(entries) > PRESET_MAX_ENTRIES:
            raise _preset_error("preset_capacity")
        validated = {}
        for name, entry in entries.items():
            _preset_name(name)
            validated[name] = preset_validate_entry(entry)
        return validated
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise _preset_error("preset_corrupt") from None


def _preset_path():
    configured = os.environ.get("XDG_CONFIG_HOME")
    raw_parent = configured if configured is not None else str(Path.home() / ".config")
    if (not raw_parent or len(raw_parent) > 4096
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in raw_parent)):
        raise _preset_error("preset_invalid_config_root")
    parent = Path(raw_parent)
    if not parent.is_absolute() or ".." in parent.parts:
        raise _preset_error("preset_invalid_config_root")
    return parent / "session-peer"


def _preset_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _preset_private(info, directory=False):
    if (info.st_uid != os.geteuid() or info.st_mode & (0o7077 if directory else 0o7177)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)):
        raise _preset_error("preset_unsafe_storage")


def _preset_directory(create=False):
    """Open every component without following symlinks; retain the app dir fd.

    App files are relative to this descriptor. Ancestors must not be writable by
    other users (a root-owned sticky temporary ancestor is permitted). This is
    local same-user configuration, not protection from the user's own processes.
    """
    root = _preset_path()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open("/", flags)
    try:
        for index, part in enumerate(root.parts[1:]):
            final = index == len(root.parts[1:]) - 1
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    return None
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=fd)
            info = os.fstat(child)
            try:
                if final:
                    _preset_private(info, directory=True)
                elif info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
                    raise _preset_error("preset_unsafe_storage")
                # The immediate configuration parent must belong to this user.
                if not final and index == len(root.parts[1:]) - 2 and info.st_uid != os.geteuid():
                    raise _preset_error("preset_unsafe_storage")
            except BaseException:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        result, fd = fd, None
        return result
    finally:
        if fd is not None:
            os.close(fd)


def _preset_read_at(directory):
    try:
        fd = os.open("destinations.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return {}
    try:
        before = os.fstat(fd)
        _preset_private(before)
        if before.st_size > PRESET_MAX_BYTES:
            raise _preset_error("preset_capacity")
        raw = bytearray()
        while len(raw) <= PRESET_MAX_BYTES:
            chunk = os.read(fd, min(8192, PRESET_MAX_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > PRESET_MAX_BYTES:
            raise _preset_error("preset_capacity")
        after = os.fstat(fd)
        current = os.stat("destinations.json", dir_fd=directory, follow_symlinks=False)
        if _preset_identity(before) != _preset_identity(after) or _preset_identity(after) != _preset_identity(current):
            raise _preset_error("preset_storage_changed")
        return _preset_decode(bytes(raw))
    finally:
        os.close(fd)


def preset_read():
    """Read only: never creates a directory, file or lock."""
    _preset_platform()
    directory = None
    try:
        directory = _preset_directory()
        return {} if directory is None else _preset_read_at(directory)
    except OSError:
        raise _preset_error("preset_unsafe_storage") from None
    finally:
        if directory is not None:
            os.close(directory)


def preset_lookup(name):
    _preset_platform()
    _preset_name(name)
    entries = preset_read()
    if name not in entries:
        raise _preset_error("preset_not_found")
    route = dict(entries[name])
    return route, preset_revision(name, route)


def _preset_lock(directory):
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open("destinations.lock", flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
    except FileExistsError:
        fd = os.open("destinations.lock", flags, dir_fd=directory)
    try:
        _preset_private(os.fstat(fd))
        deadline = time.monotonic() + PRESET_LOCK_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _preset_error("preset_busy")
                time.sleep(0.01)
        info = os.stat("destinations.lock", dir_fd=directory, follow_symlinks=False)
        if _preset_identity(info) != _preset_identity(os.fstat(fd)):
            raise _preset_error("preset_storage_changed")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _preset_entry_identity(directory):
    try:
        info = os.stat("destinations.json", dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    _preset_private(info)
    return _preset_identity(info)


def preset_mutate(action, name, entry=None, expected_revision=None):
    """Explicit management only; serialize writers and CAS replace/remove."""
    _preset_platform()
    _preset_name(name)
    if action not in ("add", "replace", "remove"):
        raise _preset_error("preset_invalid_action")
    route = preset_validate_entry(entry) if action != "remove" else None
    if action == "remove" and entry is not None:
        raise _preset_error("preset_invalid_route")
    if action in ("replace", "remove") and (not isinstance(expected_revision, str)
            or re.fullmatch(r"dp1:[0-9a-f]{64}", expected_revision) is None):
        raise _preset_error("preset_revision_required")
    if action == "add" and expected_revision is not None:
        raise _preset_error("preset_invalid_revision")
    directory = lock = None
    temporary = None
    try:
        directory = _preset_directory(create=action == "add")
        if directory is None:
            raise _preset_error("preset_not_found")
        lock = _preset_lock(directory)
        original_identity = _preset_entry_identity(directory)
        entries = _preset_read_at(directory)
        if _preset_entry_identity(directory) != original_identity:
            raise _preset_error("preset_storage_changed")
        if action == "add":
            if name in entries:
                raise _preset_error("preset_already_exists")
        else:
            if name not in entries:
                raise _preset_error("preset_not_found")
            if preset_revision(name, entries[name]) != expected_revision:
                raise _preset_error("preset_revision_mismatch")
        previous = entries.get(name)
        if action == "remove":
            del entries[name]
        else:
            entries[name] = route
        raw = json.dumps({"schemaVersion": 1, "presets": entries}, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
        if len(entries) > PRESET_MAX_ENTRIES or len(raw) > PRESET_MAX_BYTES:
            raise _preset_error("preset_capacity")
        # Reject ancestry replacement before committing through the held fd.
        check = _preset_directory()
        try:
            if check is None or (os.fstat(check).st_dev, os.fstat(check).st_ino) != (
                    os.fstat(directory).st_dev, os.fstat(directory).st_ino):
                raise _preset_error("preset_storage_changed")
        finally:
            if check is not None:
                os.close(check)
        temporary = ".destinations-" + uuid.uuid4().hex + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if _preset_entry_identity(directory) != original_identity:
                raise _preset_error("preset_storage_changed")
            os.replace(temporary, "destinations.json", src_dir_fd=directory, dst_dir_fd=directory)
            temporary = None
            os.fsync(directory)
        finally:
            if temporary is not None:
                os.unlink(temporary, dir_fd=directory)
                temporary = None
        result_route = previous if action == "remove" else route
        result = {"name": name, "route": dict(result_route), "revision": preset_revision(name, result_route)}
        if action == "remove":
            result["removed"] = True
        return result
    except OSError:
        raise _preset_error("preset_unsafe_storage") from None
    finally:
        if lock is not None:
            os.close(lock)
        if directory is not None:
            os.close(directory)
