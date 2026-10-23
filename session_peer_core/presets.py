"""Explicit, route-only POSIX presets; never a session identity or authority."""

import hashlib


PRESET_MAX_BYTES = 65536
PRESET_MAX_ENTRIES = 128
PRESET_LOCK_SECONDS = 1.0


def _preset_error(reason):
    return CcPeerError("preset configuration refused: " + reason, {"reason": reason})


def _preset_cleanup(action, *args, preserve=False, **kwargs):
    """A secondary ordinary cleanup error must not replace an active failure.

    New KeyboardInterrupt/SystemExit are never swallowed. On a normal return,
    cleanup failure is still reported, without reflecting raw diagnostics.
    """
    try:
        return action(*args, **kwargs)
    except Exception as error:
        if not preserve:
            if isinstance(error, CcPeerError):
                raise
            raise _preset_error("preset_cleanup_failed") from None


@contextlib.contextmanager
def _preset_cleanup_scope(action, *args, **kwargs):
    """Derive preservation from this body, never an ambient caller exception."""
    try:
        yield
    except BaseException:
        _preset_cleanup(action, *args, preserve=True, **kwargs)
        raise
    else:
        _preset_cleanup(action, *args, **kwargs)


def _preset_platform():
    if IS_WINDOWS or fcntl is None or sys.platform not in ("darwin", "linux"):
        raise _preset_error("preset_platform_unsupported")


def _preset_darwin_mount_flags(fd):
    """Use the explicit statfs64 ABI, never the ambiguous legacy statfs ABI."""
    import ctypes
    try:
        class Statfs64(ctypes.Structure):
            # sys/mount.h __DARWIN_STRUCT_STATFS64. The reserved tail remains
            # 32 bytes across the f_flags_ext addition; no string is inspected.
            _fields_ = [
                ("f_bsize", ctypes.c_uint32), ("f_iosize", ctypes.c_int32),
                ("f_blocks", ctypes.c_uint64), ("f_bfree", ctypes.c_uint64),
                ("f_bavail", ctypes.c_uint64), ("f_files", ctypes.c_uint64),
                ("f_ffree", ctypes.c_uint64), ("f_fsid", ctypes.c_int32 * 2),
                ("f_owner", ctypes.c_uint32), ("f_type", ctypes.c_uint32),
                ("f_flags", ctypes.c_uint32), ("f_fssubtype", ctypes.c_uint32),
                ("f_fstypename", ctypes.c_char * 16),
                ("f_mntonname", ctypes.c_char * 1024),
                ("f_mntfromname", ctypes.c_char * 1024),
                ("f_reserved", ctypes.c_uint32 * 8),
            ]
        if (ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(Statfs64) != 2168
                or Statfs64.f_flags.offset != 64):
            raise _preset_error("preset_mount_unverifiable")
        api = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        api.fstatfs64.argtypes = [ctypes.c_int, ctypes.POINTER(Statfs64)]
        api.fstatfs64.restype = ctypes.c_int
        value = Statfs64()
        if api.fstatfs64(fd, ctypes.byref(value)) != 0:
            raise _preset_error("preset_mount_unverifiable")
        return value.f_flags
    except (OSError, AttributeError, TypeError, ValueError, OverflowError):
        raise _preset_error("preset_mount_unverifiable") from None


def _preset_check_ownership(fd):
    if sys.platform == "darwin" and _preset_darwin_mount_flags(fd) & 0x00200000:
        # MNT_IGNORE_OWNERSHIP can synthesize owner/mode metadata. Do not call
        # such metadata an owner-only store, even if its ACL is empty.
        raise _preset_error("preset_ownership_unenforced")


def _preset_check_fd(fd, *, private, directory=False):
    _preset_check_ownership(fd)
    _preset_check_acl(fd, private=private, directory=directory)


def _preset_darwin_acl_tags(fd):
    """Read only Darwin's extended ACL, without paths or a child process.

    Darwin returns 0 for an entry, -1/EINVAL at exhaustion (unlike Linux).
    Validate the independent ACL handle first; release it on every path.
    Constants and prototypes are from the macOS SDK sys/acl.h.
    """
    import ctypes
    try:
        api = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        api.acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
        api.acl_get_fd_np.restype = ctypes.c_void_p
        api.acl_valid.argtypes = [ctypes.c_void_p]
        api.acl_valid.restype = ctypes.c_int
        api.acl_get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        api.acl_get_entry.restype = ctypes.c_int
        api.acl_get_tag_type.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        api.acl_get_tag_type.restype = ctypes.c_int
        api.acl_free.argtypes = [ctypes.c_void_p]
        api.acl_free.restype = ctypes.c_int
        ctypes.set_errno(0)
        acl = api.acl_get_fd_np(fd, 0x100)  # ACL_TYPE_EXTENDED
        if not acl:
            # Darwin's fd getter returns NULL/ENOENT when FILESEC_ACL is absent
            # (Libc posix1e/acl_file.c and gen/filesec.c), not an empty object.
            if ctypes.get_errno() == errno.ENOENT:
                return ()
            raise _preset_error("preset_acl_unverifiable")
        acl_failed = False
        try:
            if api.acl_valid(acl) != 0:
                raise _preset_error("preset_acl_unverifiable")
            tags = []
            for index in range(129):
                entry = ctypes.c_void_p()
                ctypes.set_errno(0)
                result = api.acl_get_entry(acl, 0 if index == 0 else -1, ctypes.byref(entry))
                if result == -1 and ctypes.get_errno() == errno.EINVAL:
                    return tuple(tags)
                if result != 0 or not entry.value or index == 128:
                    raise _preset_error("preset_acl_unverifiable")
                tag = ctypes.c_int()
                if api.acl_get_tag_type(entry, ctypes.byref(tag)) != 0 or tag.value not in (1, 2):
                    raise _preset_error("preset_acl_unverifiable")
                tags.append(tag.value)  # ACL_EXTENDED_ALLOW=1, DENY=2
            raise _preset_error("preset_acl_unverifiable")
        except BaseException:
            acl_failed = True
            raise
        finally:
            def release_acl():
                if api.acl_free(acl) != 0:
                    raise _preset_error("preset_acl_unverifiable")
            _preset_cleanup(release_acl, preserve=acl_failed)
    except (OSError, AttributeError, TypeError, ValueError, OverflowError):
        raise _preset_error("preset_acl_unverifiable") from None


def _preset_check_acl(fd, *, private, directory=False):
    """Conservative ACL policy, not an effective-permissions interpreter."""
    if sys.platform == "darwin":
        tags = _preset_darwin_acl_tags(fd)
        if any(tag not in (1, 2) for tag in tags):
            raise _preset_error("preset_acl_unverifiable")
        if (private and tags) or (not private and 1 in tags):
            raise _preset_error("preset_unsafe_acl")
        return
    if sys.platform == "linux":
        try:
            for attribute in (("system.posix_acl_access", "system.posix_acl_default")
                              if directory else ("system.posix_acl_access",)):
                try:
                    os.getxattr(fd, attribute)
                except OSError as error:
                    if error.errno == errno.ENODATA:
                        continue
                    raise _preset_error("preset_acl_unverifiable") from None
                raise _preset_error("preset_unsafe_acl")
        except (AttributeError, TypeError, ValueError):
            raise _preset_error("preset_acl_unverifiable") from None
        return
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
    directory_failed = False
    try:
        _preset_check_fd(fd, private=False, directory=True)
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
            try:
                info = os.fstat(child)
                if final:
                    _preset_private(info, directory=True)
                else:
                    if info.st_uid not in (0, os.geteuid()):
                        raise _preset_error("preset_unsafe_storage")
                    if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
                        raise _preset_error("preset_unsafe_storage")
                # The immediate configuration parent must belong to this user.
                if not final and index == len(root.parts[1:]) - 2 and info.st_uid != os.geteuid():
                    raise _preset_error("preset_unsafe_storage")
                _preset_check_fd(child, private=final, directory=True)
            except BaseException:
                _preset_cleanup(os.close, child, preserve=True)
                raise
            previous, fd = fd, child
            _preset_cleanup(os.close, previous)
        result, fd = fd, None
        return result
    except BaseException:
        directory_failed = True
        raise
    finally:
        if fd is not None:
            _preset_cleanup(os.close, fd, preserve=directory_failed)


def _preset_read_at(directory, filename="destinations.json", decoder=None):
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return {}
    read_failed = False
    try:
        before = os.fstat(fd)
        _preset_private(before)
        _preset_check_fd(fd, private=True)
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
        _preset_check_fd(fd, private=True)
        current = os.stat(filename, dir_fd=directory, follow_symlinks=False)
        if _preset_identity(before) != _preset_identity(after) or _preset_identity(after) != _preset_identity(current):
            raise _preset_error("preset_storage_changed")
        return (decoder or _preset_decode)(bytes(raw))
    except BaseException:
        read_failed = True
        raise
    finally:
        _preset_cleanup(os.close, fd, preserve=read_failed)


def preset_read():
    """Read only: never creates a directory, file or lock."""
    _preset_platform()
    directory = None
    read_failed = False
    try:
        directory = _preset_directory()
        return {} if directory is None else _preset_read_at(directory)
    except OSError:
        read_failed = True
        raise _preset_error("preset_unsafe_storage") from None
    except BaseException:
        read_failed = True
        raise
    finally:
        if directory is not None:
            _preset_cleanup(os.close, directory, preserve=read_failed)


def preset_lookup(name):
    _preset_platform()
    _preset_name(name)
    entries = preset_read()
    if name not in entries:
        raise _preset_error("preset_not_found")
    route = dict(entries[name])
    return route, preset_revision(name, route)


def _preset_lock(directory, filename="destinations.lock"):
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(filename, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
    except FileExistsError:
        fd = os.open(filename, flags, dir_fd=directory)
    try:
        _preset_private(os.fstat(fd))
        _preset_check_fd(fd, private=True)
        deadline = time.monotonic() + PRESET_LOCK_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _preset_error("preset_busy")
                time.sleep(0.01)
        info = os.stat(filename, dir_fd=directory, follow_symlinks=False)
        if _preset_identity(info) != _preset_identity(os.fstat(fd)):
            raise _preset_error("preset_storage_changed")
        _preset_check_fd(fd, private=True)
        return fd
    except BaseException:
        _preset_cleanup(os.close, fd, preserve=True)
        raise


def _preset_entry_identity(directory, filename="destinations.json"):
    try:
        info = os.stat(filename, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    _preset_private(info)
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    identity_failed = False
    try:
        opened = os.fstat(fd)
        if _preset_identity(opened) != _preset_identity(info):
            raise _preset_error("preset_storage_changed")
        _preset_check_fd(fd, private=True)
    except BaseException:
        identity_failed = True
        raise
    finally:
        _preset_cleanup(os.close, fd, preserve=identity_failed)
    return _preset_identity(info)


def preset_mutate(action, name, entry=None, expected_revision=None, *, _storage=None):
    """Explicit management only; serialize writers and CAS replace/remove."""
    _preset_platform()
    _preset_name(name)
    if action not in ("add", "replace", "remove"):
        raise _preset_error("preset_invalid_action")
    validate_entry = _storage["validate_entry"] if _storage else preset_validate_entry
    revision = _storage["revision"] if _storage else preset_revision
    revision_prefix = _storage["revision_prefix"] if _storage else "dp1"
    filename = _storage["filename"] if _storage else "destinations.json"
    route = validate_entry(entry) if action != "remove" else None
    if action == "remove" and entry is not None:
        raise _preset_error("preset_invalid_route")
    if action in ("replace", "remove") and (not isinstance(expected_revision, str)
            or re.fullmatch(revision_prefix + r":[0-9a-f]{64}", expected_revision) is None):
        raise _preset_error("preset_revision_required")
    if action == "add" and expected_revision is not None:
        raise _preset_error("preset_invalid_revision")
    directory = lock = None
    temporary = None
    committed = False
    mutation_failed = False
    try:
        directory = _preset_directory(create=action == "add")
        if directory is None:
            raise _preset_error("preset_not_found")
        lock = _preset_lock(directory, _storage["lockname"]) if _storage else _preset_lock(directory)
        def identity():
            return _preset_entry_identity(directory, filename) if _storage else _preset_entry_identity(directory)
        original_identity = identity()
        entries = _preset_read_at(directory, filename, _storage["decoder"]) if _storage else _preset_read_at(directory)
        if identity() != original_identity:
            raise _preset_error("preset_storage_changed")
        if action == "add":
            if name in entries:
                raise _preset_error("preset_already_exists")
        else:
            if name not in entries:
                raise _preset_error("preset_not_found")
            if revision(name, entries[name]) != expected_revision:
                raise _preset_error("preset_revision_mismatch")
        previous = entries.get(name)
        if action == "remove":
            del entries[name]
        else:
            entries[name] = route
        if _storage:
            _storage["validate_entries"](entries)
        raw = json.dumps({"schemaVersion": 1, _storage["collection"] if _storage else "presets": entries}, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
        if len(entries) > PRESET_MAX_ENTRIES or len(raw) > PRESET_MAX_BYTES:
            raise _preset_error("preset_capacity")
        # Reject ancestry replacement before committing through the held fd.
        check = _preset_directory()
        check_failed = False
        try:
            if check is None or (os.fstat(check).st_dev, os.fstat(check).st_ino) != (
                    os.fstat(directory).st_dev, os.fstat(directory).st_ino):
                raise _preset_error("preset_storage_changed")
        except BaseException:
            check_failed = True
            raise
        finally:
            if check is not None:
                _preset_cleanup(os.close, check, preserve=check_failed)
        temporary = "." + filename.removesuffix(".json") + "-" + uuid.uuid4().hex + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        temporary_failed = False
        try:
            stream = None
            stream_failed = False
            try:
                stream = os.fdopen(fd, "wb")
                _preset_private(os.fstat(stream.fileno()))
                _preset_check_fd(stream.fileno(), private=True)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                _preset_check_fd(stream.fileno(), private=True)
            except BaseException:
                stream_failed = True
                raise
            finally:
                if stream is not None:
                    _preset_cleanup(stream.close, preserve=stream_failed)
                else:
                    _preset_cleanup(os.close, fd, preserve=stream_failed)
            if identity() != original_identity:
                raise _preset_error("preset_storage_changed")
            os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
            temporary = None
            committed = True
            os.fsync(directory)
        except BaseException:
            temporary_failed = True
            raise
        finally:
            if temporary is not None:
                def remove_temporary():
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError:
                        # Rename can finish immediately before an interrupt.
                        pass
                _preset_cleanup(remove_temporary, preserve=temporary_failed)
                temporary = None
        result_route = previous if action == "remove" else route
        result = {"name": name, _storage["result_key"] if _storage else "route": dict(result_route),
                  "revision": revision(name, result_route)}
        if action == "remove":
            result["removed"] = True
        return result
    except OSError:
        mutation_failed = True
        if committed:
            raise CcPeerError("preset commit unconfirmed; inspect configuration before retrying",
                              {"reason": "preset_commit_unconfirmed"}) from None
        raise _preset_error("preset_unsafe_storage") from None
    except BaseException:
        mutation_failed = True
        raise
    finally:
        def close_storage():
            def close_directory():
                if directory is not None:
                    os.close(directory)
            with _preset_cleanup_scope(close_directory):
                if lock is not None:
                    _preset_cleanup(os.close, lock)
        try:
            _preset_cleanup(close_storage, preserve=mutation_failed)
        except CcPeerError:
            if committed:
                raise CcPeerError("preset commit unconfirmed; inspect configuration before retrying",
                                  {"reason": "preset_commit_unconfirmed"}) from None
            raise
