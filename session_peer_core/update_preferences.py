# Local runtime notice preferences; standalone namespace, standard library only.
RUNTIME_NOTICE_PREFERENCE_BYTES = 4096
RUNTIME_NOTICE_PREFERENCE_LOCK_SECONDS = 2.0


def runtime_notice_cli_version(text):
    if type(text) is not str or len(text) > 64:
        raise argparse.ArgumentTypeError("expected an ASCII stable version X.Y.Z")
    match = re.fullmatch(r"[vV]?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", text, flags=re.ASCII)
    if match is None:
        raise argparse.ArgumentTypeError("expected an ASCII stable version X.Y.Z")
    values = tuple(int(part) for part in match.groups())
    if any(value > sys.maxsize for value in values):
        raise argparse.ArgumentTypeError("expected an ASCII stable version X.Y.Z")
    return ".".join(str(value) for value in values)


class RuntimeNoticePreferenceFailure(Exception):
    def __init__(self, reason):
        self.reason = reason


def _runtime_notice_fail(reason):
    raise RuntimeNoticePreferenceFailure("runtime_notice_preference_" + reason)


def _runtime_notice_supported():
    return sys.platform in ("linux", "darwin") and fcntl is not None


def _runtime_notice_directory_stat(info, *, private=False):
    owner = os.getuid()
    if not stat.S_ISDIR(info.st_mode):
        _runtime_notice_fail("unsafe")
    if private:
        # Inherited setgid/sticky bits do not grant group/other access. Keep
        # owner rwx and no group/other mode bits, without repairing any inode.
        if info.st_uid != owner or info.st_mode & 0o777 != 0o700:
            _runtime_notice_fail("unsafe")
    elif (info.st_uid not in (0, owner) or
          (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
        _runtime_notice_fail("unsafe")


def _runtime_notice_file_stat(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        _runtime_notice_fail("unsafe")


@contextlib.contextmanager
def _runtime_notice_directory(*, create=False):
    configured = os.environ.get("XDG_CONFIG_HOME")
    base = configured if configured else str(Path.home() / ".config")
    if (type(base) is not str or not base.startswith("/") or "\x00" in base
            or any(part in (".", "..") for part in base.split("/"))):
        _runtime_notice_fail("unsafe")
    components = [part for part in base.split("/") if part] + ["session-peer"]
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open("/", flags)
    try:
        _runtime_notice_directory_stat(os.fstat(fd))
        for index, name in enumerate(components):
            try:
                child = os.open(name, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    yield None
                    return
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
                child = os.open(name, flags, dir_fd=fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    _runtime_notice_fail("unsafe")
                raise
            try:
                _runtime_notice_directory_stat(os.fstat(child), private=index == len(components)-1)
            except BaseException:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _runtime_notice_open_file(directory, name, *, create=False):
    try:
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            return None
        before = None
    if before is not None:
        _runtime_notice_file_stat(before)
        if not create and before.st_size > RUNTIME_NOTICE_PREFERENCE_BYTES:
            _runtime_notice_fail("invalid")
    flags = (os.O_RDWR if create else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if create and before is None:
        flags |= os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(name, flags, 0o600, dir_fd=directory)
    except FileExistsError:
        if not create or before is not None:
            raise
        # Another cooperative first writer may have just created the stable
        # lock. Validate and bind its existing inode instead of replacing it.
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        _runtime_notice_file_stat(before)
        fd = os.open(name, flags & ~(os.O_CREAT | os.O_EXCL), 0o600, dir_fd=directory)
    try:
        after = os.fstat(fd)
        _runtime_notice_file_stat(after)
        if before is not None and (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            _runtime_notice_fail("unsafe")
        if not create and after.st_size > RUNTIME_NOTICE_PREFERENCE_BYTES:
            _runtime_notice_fail("invalid")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _runtime_notice_decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _runtime_notice_fail("invalid")
            result[key] = value
        return result
    def constant(value):
        _runtime_notice_fail("invalid")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        if (type(value) is not dict or set(value) != {"schemaVersion", "runtime"}
                or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
                or type(value["runtime"]) is not dict or set(value["runtime"]) != {"dismissedVersion"}):
            _runtime_notice_fail("invalid")
        version = value["runtime"]["dismissedVersion"]
        if version is not None and runtime_notice_cli_version(version) != version:
            _runtime_notice_fail("invalid")
        return version
    except (ValueError, TypeError, UnicodeError, argparse.ArgumentTypeError, RecursionError):
        _runtime_notice_fail("invalid")


def _runtime_notice_read(directory):
    fd = _runtime_notice_open_file(directory, "update-notices.json")
    if fd is None:
        return {"status": "missing", "dismissedVersion": None}
    try:
        chunks, size = [], 0
        while size <= RUNTIME_NOTICE_PREFERENCE_BYTES:
            chunk = os.read(fd, RUNTIME_NOTICE_PREFERENCE_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        raw = b"".join(chunks)
        if len(raw) > RUNTIME_NOTICE_PREFERENCE_BYTES:
            _runtime_notice_fail("invalid")
        version = _runtime_notice_decode(raw)
        return {"status": "clear" if version is None else "set", "dismissedVersion": version}
    finally:
        os.close(fd)


def read_runtime_notice_preference():
    if not _runtime_notice_supported():
        return {"status": "unsupported", "dismissedVersion": None, "reason": "runtime_notice_preference_unsupported"}
    try:
        with _runtime_notice_directory() as directory:
            return ({"status": "missing", "dismissedVersion": None} if directory is None
                    else _runtime_notice_read(directory))
    except Exception as exc:
        reason = exc.reason if isinstance(exc, RuntimeNoticePreferenceFailure) else "runtime_notice_preference_unavailable"
        return {"status": "invalid", "dismissedVersion": None, "reason": reason}


def write_runtime_notice_preference(version_or_none):
    if not _runtime_notice_supported():
        raise CcPeerError("Runtime notice preference refused", {"reason": "runtime_notice_preference_unsupported", "updated": False})
    replaced = False
    try:
        try:
            version = None if version_or_none is None else runtime_notice_cli_version(version_or_none)
        except argparse.ArgumentTypeError:
            _runtime_notice_fail("invalid")
        with _runtime_notice_directory(create=True) as directory:
            lock = _runtime_notice_open_file(directory, "update-notices.lock", create=True)
            temporary, identity = None, None
            try:
                deadline = time.monotonic() + RUNTIME_NOTICE_PREFERENCE_LOCK_SECONDS
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            _runtime_notice_fail("busy")
                        time.sleep(min(0.01, remaining))
                current = _runtime_notice_read(directory)
                status = "clear" if version is None else "set"
                if current["status"] != "missing" and current["dismissedVersion"] == version:
                    return {"status": status, "dismissedVersion": version, "changed": False}
                raw = json.dumps({"schemaVersion": 1, "runtime": {"dismissedVersion": version}},
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
                temporary = ".update-notices-" + uuid.uuid4().hex + ".tmp"
                fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
                try:
                    info = os.fstat(fd)
                    identity = (info.st_dev, info.st_ino)
                    _runtime_notice_file_stat(info)
                    offset = 0
                    while offset < len(raw):
                        count = os.write(fd, raw[offset:])
                        if count <= 0:
                            raise OSError()
                        offset += count
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.replace(temporary, "update-notices.json", src_dir_fd=directory, dst_dir_fd=directory)
                replaced, temporary = True, None
                os.fsync(directory)
                return {"status": status, "dismissedVersion": version, "changed": True}
            finally:
                try:
                    if temporary is not None and identity is not None:
                        info = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
                        if (info.st_dev, info.st_ino) == identity and info.st_uid == os.getuid():
                            os.unlink(temporary, dir_fd=directory)
                finally:
                    os.close(lock)
    except Exception as exc:
        reason = exc.reason if isinstance(exc, RuntimeNoticePreferenceFailure) else "runtime_notice_preference_write_failed"
        details = {"reason": reason, "updated": False}
        if replaced:
            details["preferenceMayHaveChanged"] = True
        raise CcPeerError("Runtime notice preference refused", details) from None
