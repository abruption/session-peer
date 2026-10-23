"""Opt-in local SSH configuration validation; never a remote identity proof."""

import hashlib
from contextvars import ContextVar

SSH_CONFIG_MAX_BYTES = 65536
SSH_CONFIG_SELECTION = ContextVar("ssh_config_selection", default=None)

def _ssh_config_error(reason):
    return CcPeerError("trusted SSH configuration refused: " + reason,
                       {"reason": reason, "retryAllowed": False})


def _ssh_config_cleanup(action, *args, preserve=False, **kwargs):
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
            raise _ssh_config_error("ssh_config_cleanup_failed") from None


@contextlib.contextmanager
def _ssh_config_cleanup_scope(action, *args, **kwargs):
    """Derive preservation from this body, never an ambient caller exception."""
    try:
        yield
    except BaseException:
        # A caller may already supply this policy for a nested cleanup. The
        # active body's failure takes precedence without a duplicate keyword.
        _ssh_config_cleanup(action, *args, **{**kwargs, "preserve": True})
        raise
    else:
        _ssh_config_cleanup(action, *args, **kwargs)


def _ssh_config_platform():
    if IS_WINDOWS or fcntl is None or sys.platform not in ("darwin", "linux"):
        raise _ssh_config_error("ssh_config_platform_unsupported")


def _ssh_config_darwin_mount_flags(fd):
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
            raise _ssh_config_error("ssh_config_mount_unverifiable")
        api = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        api.fstatfs64.argtypes = [ctypes.c_int, ctypes.POINTER(Statfs64)]
        api.fstatfs64.restype = ctypes.c_int
        value = Statfs64()
        if api.fstatfs64(fd, ctypes.byref(value)) != 0:
            raise _ssh_config_error("ssh_config_mount_unverifiable")
        return value.f_flags
    except (OSError, AttributeError, TypeError, ValueError, OverflowError):
        raise _ssh_config_error("ssh_config_mount_unverifiable") from None


def _ssh_config_check_ownership(fd):
    if sys.platform == "darwin" and _ssh_config_darwin_mount_flags(fd) & 0x00200000:
        # MNT_IGNORE_OWNERSHIP can synthesize owner/mode metadata. Do not call
        # such metadata an owner-only store, even if its ACL is empty.
        raise _ssh_config_error("ssh_config_ownership_unenforced")


def _ssh_config_check_fd(fd, *, private, directory=False):
    _ssh_config_check_ownership(fd)
    _ssh_config_check_acl(fd, private=private, directory=directory)


def _ssh_config_darwin_acl_tags(fd):
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
            raise _ssh_config_error("ssh_config_acl_unverifiable")
        acl_failed = False
        try:
            if api.acl_valid(acl) != 0:
                raise _ssh_config_error("ssh_config_acl_unverifiable")
            tags = []
            for index in range(129):
                entry = ctypes.c_void_p()
                ctypes.set_errno(0)
                result = api.acl_get_entry(acl, 0 if index == 0 else -1, ctypes.byref(entry))
                if result == -1 and ctypes.get_errno() == errno.EINVAL:
                    return tuple(tags)
                if result != 0 or not entry.value or index == 128:
                    raise _ssh_config_error("ssh_config_acl_unverifiable")
                tag = ctypes.c_int()
                if api.acl_get_tag_type(entry, ctypes.byref(tag)) != 0 or tag.value not in (1, 2):
                    raise _ssh_config_error("ssh_config_acl_unverifiable")
                tags.append(tag.value)  # ACL_EXTENDED_ALLOW=1, DENY=2
            raise _ssh_config_error("ssh_config_acl_unverifiable")
        except BaseException:
            acl_failed = True
            raise
        finally:
            def release_acl():
                if api.acl_free(acl) != 0:
                    raise _ssh_config_error("ssh_config_acl_unverifiable")
            _ssh_config_cleanup(release_acl, preserve=acl_failed)
    except (OSError, AttributeError, TypeError, ValueError, OverflowError):
        raise _ssh_config_error("ssh_config_acl_unverifiable") from None


def _ssh_config_check_acl(fd, *, private, directory=False):
    """Conservative ACL policy, not an effective-permissions interpreter."""
    if sys.platform == "darwin":
        tags = _ssh_config_darwin_acl_tags(fd)
        if any(tag not in (1, 2) for tag in tags):
            raise _ssh_config_error("ssh_config_acl_unverifiable")
        if (private and tags) or (not private and 1 in tags):
            raise _ssh_config_error("ssh_config_unsafe_acl")
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
                    raise _ssh_config_error("ssh_config_acl_unverifiable") from None
                raise _ssh_config_error("ssh_config_unsafe_acl")
        except (AttributeError, TypeError, ValueError):
            raise _ssh_config_error("ssh_config_acl_unverifiable") from None
        return
    raise _ssh_config_error("ssh_config_platform_unsupported")



def _ssh_config_path(path):
    if (not isinstance(path, str) or not path or len(path) > 4096
            or not path.startswith("/") or path.startswith("//")
            or ".." in path.split("/")
            or any(ord(c) < 32 or 127 <= ord(c) <= 159
                   or 0xD800 <= ord(c) <= 0xDFFF for c in path)):
        raise _ssh_config_error("ssh_config_invalid_path")
    return path


def _ssh_config_overflow_uid():
    if sys.platform != "linux":
        return None
    try:
        with open("/proc/sys/kernel/overflowuid", "rb") as stream:
            raw = stream.read(32)
        if not raw.strip().isdigit() or len(raw) == 32:
            raise ValueError()
        return int(raw)
    except (OSError, ValueError):
        raise _ssh_config_error("ssh_config_ownership_unverifiable") from None


def _ssh_config_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_gid, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _ssh_config_metadata(info, overflow_uid, *, directory=False):
    if overflow_uid is not None and info.st_uid == overflow_uid:
        raise _ssh_config_error("ssh_config_ownership_unverifiable")
    if directory:
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid())
                or (info.st_mode & 0o022
                    and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
            raise _ssh_config_error("ssh_config_unsafe_storage")
    elif (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
          or info.st_nlink != 1 or info.st_mode & 0o7022):
        raise _ssh_config_error("ssh_config_unsafe_storage")


def _ssh_config_snapshot(path):
    _ssh_config_platform()
    _ssh_config_path(path)
    overflow_uid = _ssh_config_overflow_uid()
    directory = fd = None
    ancestors = []
    failed = False
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        directory = os.open("/", flags | os.O_DIRECTORY)
        parts = path.split("/")[1:]
        # Reject trailing slash / empty filename, but harmless internal repeated
        # separators do not change the original path passed to OpenSSH.
        if not parts[-1]:
            raise _ssh_config_error("ssh_config_invalid_path")
        for part in parts[:-1]:
            info = os.fstat(directory)
            _ssh_config_metadata(info, overflow_uid, directory=True)
            _ssh_config_check_fd(directory, private=False, directory=True)
            if not part:
                continue
            ancestors.append((info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid))
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            previous, directory = directory, child
            _ssh_config_cleanup(os.close, previous)
        info = os.fstat(directory)
        _ssh_config_metadata(info, overflow_uid, directory=True)
        ancestors.append((info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid))
        _ssh_config_check_fd(directory, private=False, directory=True)
        fd = os.open(parts[-1], flags, dir_fd=directory)
        before = os.fstat(fd)
        _ssh_config_metadata(before, overflow_uid)
        _ssh_config_check_fd(fd, private=False)
        if before.st_size > SSH_CONFIG_MAX_BYTES:
            raise _ssh_config_error("ssh_config_capacity")
        raw = bytearray()
        while len(raw) <= SSH_CONFIG_MAX_BYTES:
            chunk = os.read(fd, min(8192, SSH_CONFIG_MAX_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > SSH_CONFIG_MAX_BYTES:
            raise _ssh_config_error("ssh_config_capacity")
        after = os.fstat(fd)
        _ssh_config_metadata(after, overflow_uid)
        _ssh_config_check_fd(fd, private=False)
        current = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        if (_ssh_config_identity(before) != _ssh_config_identity(after)
                or _ssh_config_identity(after) != _ssh_config_identity(current)):
            raise _ssh_config_error("ssh_config_storage_changed")
        return tuple(ancestors), _ssh_config_identity(after), hashlib.sha256(raw).digest()
    except OSError:
        failed = True
        raise _ssh_config_error("ssh_config_unsafe_storage") from None
    except BaseException:
        failed = True
        raise
    finally:
        def close_directory():
            if directory is not None:
                os.close(directory)
        with _ssh_config_cleanup_scope(
                _ssh_config_cleanup, close_directory, preserve=failed):
            if fd is not None:
                _ssh_config_cleanup(os.close, fd, preserve=failed)


class _TrustedSshConfig:
    # Source-streamed consumers may execute without a registered module entry;
    # dataclass annotation resolution on supported older Python cannot do so.
    __slots__ = ("_path", "_snapshot")

    def __init__(self, path, snapshot):
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_snapshot", snapshot)

    @property
    def path(self):
        return self._path

    def __setattr__(self, name, value):
        raise AttributeError("trusted SSH selection is immutable")

    def __delattr__(self, name):
        raise AttributeError("trusted SSH selection is immutable")

    def __repr__(self):
        return "<trusted SSH configuration>"

    def revalidate(self):
        if _ssh_config_snapshot(self.path) != self._snapshot:
            raise _ssh_config_error("ssh_config_storage_changed")


def select_trusted_ssh_config(path):
    """Validate without executing config, resolving Includes or making copies.

    Revalidation detects changes since selection. OpenSSH subsequently reopens
    the original path: same-user races and executable config remain user trust.
    """
    return _TrustedSshConfig(path, _ssh_config_snapshot(path))


def trusted_ssh_command(ssh_opts, host, *remote, prefix=(), identity_options=()):
    selected = SSH_CONFIG_SELECTION.get()
    safety = []
    if selected is not None:
        selected.revalidate()
        safety = [
            "-oStrictHostKeyChecking=yes", "-oUpdateHostKeys=no",
            "-oForwardAgent=no", "-oPermitLocalCommand=no", "-oBatchMode=yes",
            "-oControlMaster=no", "-oControlPath=none", "-oControlPersist=no",
            "-F", selected.path,
        ]
    return ["ssh", *prefix, *identity_options, *safety, *ssh_opts, host, *remote]


def redact_ssh_config_path(text):
    """Mask the selected local path; not a general secret/content sanitizer."""
    selected = SSH_CONFIG_SELECTION.get()
    return text.replace(selected.path, "<ssh-config>") if selected is not None else text
