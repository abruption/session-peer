# --------------------------------------------------------------------------
# Remote dispatch. Ships this file over SSH and runs it there, so the remote
# machine needs nothing installed beyond python3.
# --------------------------------------------------------------------------


# Deliberately bounded: validate the complete argv before even `ssh -G`.
# OpenSSH configuration files remain a user-owned trust boundary; in particular
# `-F` must not let a supplied argument select an executable Match/Include file.
SSH_OPTION_KEYS = frozenset({
    "port", "user", "identityfile", "hostname", "hostkeyalias",
    "connecttimeout", "batchmode", "serveraliveinterval", "serveralivecountmax",
    "stricthostkeychecking", "proxyjump", "identitiesonly",
})

# Linux with 4 KiB pages permits at most 128 KiB per exec argument,
# including NUL. Bound the entire quoted remote shell command, not characters
# or the unwrapped body alone. Source continues to travel over stdin.
MAX_SSH_COMMAND_BYTES = 128 * 1024 - 1


def check_ssh_argument(value: str, flag: str) -> None:
    """Validate one destination; options must be validated as an argv list."""
    if flag != "--host":
        check_ssh_options([value])
        return
    if (not isinstance(value, str) or not value or value.startswith("-")
            or not re.fullmatch(r"[A-Za-z0-9_.@:\[\]%-]+", value)):
        raise CcPeerError("--host must be one [USER@]HOST without whitespace or shell syntax")


def check_ssh_options(options: list[str]) -> None:
    index = 0
    while index < len(options):
        token = options[index]
        if not isinstance(token, str) or any(ord(c) < 32 or ord(c) == 127 for c in token):
            raise CcPeerError("invalid --ssh-opt argument")
        index += 1
        if token in ("-4", "-6"):
            continue
        flag = token[:2]
        if flag not in ("-o", "-p", "-l", "-i", "-J"):
            raise CcPeerError("unsupported --ssh-opt; only connection options are allowed")
        value = token[2:]
        if not value:
            if index == len(options):
                raise CcPeerError("--ssh-opt option requires a value")
            value = options[index]
            index += 1
        if (not isinstance(value, str) or not value or value.startswith("-")
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise CcPeerError("invalid --ssh-opt value")
        if flag == "-o":
            key, separator, value = value.partition("=")
            key = key.lower()
            if not separator or key not in SSH_OPTION_KEYS or not value:
                raise CcPeerError("unsupported --ssh-opt setting; use an allowed KEY=value")
        else:
            key = {"-p": "port", "-l": "user", "-i": "identityfile", "-J": "proxyjump"}[flag]
        if key in ("hostname", "hostkeyalias", "user"):
            check_ssh_argument(value, "--host")
        if key == "proxyjump":
            for jump in value.split(","):
                check_ssh_argument(jump, "--host")
        if key in ("port", "connecttimeout", "serveraliveinterval", "serveralivecountmax"):
            if (not re.fullmatch(r"[0-9]+", value)
                    or (key == "port" and (len(value) > 5 or not 1 <= int(value) <= 65535))):
                raise CcPeerError("invalid numeric --ssh-opt value")
        if key in ("batchmode", "identitiesonly") and value.lower() not in ("yes", "no"):
            raise CcPeerError("invalid boolean --ssh-opt value")
        if key == "stricthostkeychecking" and value.lower() not in ("yes", "ask", "accept-new"):
            raise CcPeerError("invalid StrictHostKeyChecking value")


SSH_METADATA_FIELDS = ("sshUser", "sshUserSource")


def ssh_metadata_from(payload: dict) -> dict:
    return {key: payload[key] for key in SSH_METADATA_FIELDS if key in payload}


def ssh_user_metadata(host: str, ssh_opts: list[str]) -> dict:
    """Ask OpenSSH which login user it will use without making a connection."""
    check_ssh_argument(host, "--host")
    check_ssh_options(ssh_opts)

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


def parse_ssh_response(output, argv):
    """Parse one complete response with the same rules on exit and timeout.

    TimeoutExpired captures bytes even when run() requested text. Do not repair
    invalid UTF-8 or accept a prefix, duplicate keys, or non-JSON constants as
    proof that the remote command finished. Legacy JSON remains usable only
    on the normal-exit path, not as timeout outcome evidence.
    """
    if isinstance(output, bytes):
        try:
            output = output.decode("utf-8")
        except UnicodeDecodeError:
            return "", None, False, False
    # Only JSON's four whitespace characters may surround the document.
    # str.strip() also removes framing controls such as VT and FS, which must
    # not convert malformed captured output into a completed outcome.
    stdout = output.strip(" \t\r\n") if isinstance(output, str) else ""

    def object_value(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON response key")
            value[key] = item
        return value

    def constant_value(value):
        raise ValueError("non-JSON response constant")

    try:
        result = json.loads(stdout, object_pairs_hook=object_value,
                            parse_constant=constant_value) if stdout else None
    except (ValueError, RecursionError):
        return stdout, None, False, False
    valid = (
        isinstance(result, dict)
        and type(result.get("schemaVersion")) is int
        and result["schemaVersion"] == JSON_RESPONSE_SCHEMA_VERSION
        and type(result.get("ok")) is bool
        and bool(argv) and result.get("command") == argv[0]
    )
    if valid and "lastSeenTarget" in result:
        observed = result["lastSeenTarget"]
        requested = []
        targets = []
        for index, argument in enumerate(argv):
            if not isinstance(argument, str):
                continue
            if argument == "--target-generation" and index + 1 < len(argv):
                requested.append(argv[index + 1])
            elif argument.startswith("--target-generation="):
                requested.append(argument.split("=", 1)[1])
            if argument == "--to" and index + 1 < len(argv):
                targets.append(argv[index + 1])
            elif argument.startswith("--to="):
                targets.append(argument.split("=", 1)[1])
        last_seen_valid = (
            isinstance(observed, dict) and set(observed) == {"agent", "targetGeneration"}
            and observed["agent"] == "claude" and isinstance(observed["targetGeneration"], str)
            and re.fullmatch(r"tg1:[0-9a-f]{64}", observed["targetGeneration"]) is not None
            and argv[0] == "send" and len(targets) == 1
            and isinstance(targets[0], str) and bool(targets[0])
            and AGENTS.for_target(targets[0]).name == "claude"
            and requested == [observed["targetGeneration"]]
            and result["ok"] is False and result.get("status") == "refused"
            and result.get("reason") == "stale_target" and result.get("submitted") is False
            and result.get("retryAllowed") is False
        )
        if not last_seen_valid:
            # Bad optional refusal metadata cannot prove no effect. It also
            # cannot erase a complete positive response accepted by the
            # existing ordinary parser. Keep its existing native semantics without reflecting
            # the invalid optional metadata or granting resend permission.
            if result["ok"] is True or result.get("submitted") is True:
                result.pop("lastSeenTarget")
            else:
                valid = False
    return stdout, result, bool(stdout), valid


def run_remote(host: str, argv: list[str], ssh_opts: list[str]) -> dict:
    check_ssh_argument(host, "--host")
    check_ssh_options(ssh_opts)

    remote = " ".join(shlex.quote(a) for a in ["python3", "-", *argv, "--json"])
    if len(remote.encode("utf-8")) > MAX_SSH_COMMAND_BYTES:
        raise CcPeerError(
            "SSH encoded command exceeds the 131071-byte limit; shorten the message "
            "or options (UTF-8, base64 and reply-envelope overhead count). Nothing was sent.",
            {"reason": "ssh_command_too_large", "submitted": False,
             "maxCommandBytes": MAX_SSH_COMMAND_BYTES},
        )

    try:
        source = Path(__file__).resolve().read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - only when run from a pipe
        raise CcPeerError(f"cannot read own source to send to {host}: {exc}") from exc

    ssh_info = ssh_user_metadata(host, ssh_opts)

    # ssh joins everything after the destination with spaces and hands the
    # result to the remote *shell*, so an argv list is not the protection it
    # looks like: a metacharacter in any element executes over there. Build
    # the remote command as one already-quoted string instead.
    command = ["ssh", *ssh_opts, host, remote]

    def incomplete_response_error(message: str, details: dict | None = None) -> CcPeerError:
        metadata = {**ssh_info, **(details or {})}
        if argv and argv[0] == "send":
            # Diagnostics may come from a login shell or the remote command.
            # They do not prove that a launched send had no native effect.
            metadata.update(status="unknown", reason="outcome_unknown", retryAllowed=False)
            message += ("; submission outcome unknown. Do not automatically retry; "
                        "check the target before retrying.")
        return CcPeerError(message, metadata)

    try:
        completed = subprocess.run(
            command, input=source.encode("utf-8"), capture_output=True, timeout=120
        )
    except FileNotFoundError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", "ssh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        stdout, _, _, valid = parse_ssh_response(exc.output, argv)
        if valid:
            stderr = exc.stderr
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            # A timeout after the complete application response is a transport
            # shutdown problem, not evidence that its result was never received.
            completed = subprocess.CompletedProcess(command, 255, stdout,
                                                    stderr if isinstance(stderr, str) else "")
        else:
            if argv and argv[0] == "send":
                raise incomplete_response_error(
                    f"SSH send to {host} timed out", {"sshFailure": "timeout"},
                ) from exc
            raise ssh_failure_error(host, ssh_info, "timeout") from exc
    except OSError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", str(exc)) from exc

    stdout, result, parsed_result, valid_result = parse_ssh_response(completed.stdout, argv)
    # Legacy send objects retain their normal-exit compatibility, but an
    # arbitrary JSON object is not an outcome. Only versioned responses can
    # establish completion across abnormal transport exit/shutdown timeout.
    legacy_send_result = (
        argv and argv[0] == "send" and isinstance(result, dict)
        and "schemaVersion" not in result and type(result.get("ok")) is bool
        and result.get("command", "send") == "send"
        and completed.returncode in (0, 1, 2)
    )
    # Keep diagnostic decoding independent of protocol decoding. A locale's
    # stderr bytes must not prevent a complete stdout response reaching its
    # strict parser. Only diagnostic text may use replacement characters.
    stderr = completed.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    stderr = stderr if isinstance(stderr, str) else ""
    detail = stderr.strip() or f"ssh exited {completed.returncode}"
    # A complete response proves the remote command ran, even if the SSH
    # process later exits 255. Login-shell stderr must not hide submission
    # evidence or turn a remote partial failure into an invitation to resend.
    failure = (
        classify_ssh_failure(detail, completed.returncode)
        if (not valid_result and completed.returncode != 0
            and (completed.returncode == 255 or not stdout)) else None
    )
    if failure:
        error = ssh_failure_error(host, ssh_info, failure, detail)
        raise incomplete_response_error(str(error), error.details)
    runtime_output = (stdout + "\n" + stderr).strip().lower()
    if not valid_result and not legacy_send_result and (runtime_output == "python"
            or "python was not found" in runtime_output
            or ("python3" in runtime_output and any(marker in runtime_output for marker in (
                "command not found", "not recognized as", "no such file", "python3: not found",
            )))):
        raise incomplete_response_error(
            f"{host}: remote python3 did not start a usable interpreter. "
            "Source-streamed SSH requires a working python3 and a POSIX-compatible "
            "remote shell. A Windows Store execution alias is not sufficient. "
            "For native Windows, run the installed CLI locally, or use a WSL SSH "
            "endpoint with Python installed. No fallback or resend was attempted.",
            {**ssh_info, "remoteRuntimeFailure": "python3_unavailable_or_unsupported_shell"},
        )
    if not stdout:
        raise incomplete_response_error(f"{host}: {detail}")
    if not parsed_result or (isinstance(result, dict)
                             and "schemaVersion" in result and not valid_result) or (
            argv and argv[0] == "send" and not valid_result and not legacy_send_result):
        raise incomplete_response_error(f"{host}: unexpected output: {stdout[:200]}")
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
        if argv and argv[0] == "send" and valid_result:
            # Preserve completed refusals and native facts without replacing
            # the caller's command/host envelope or adding agent-specific fields.
            details = {key: value for key, value in result.items() if key not in (
                "schemaVersion", "command", "ok", "error", "host",
                "requestedHost", "resolvedHost",
            )}
        elif "codexHomeResolution" in result:
            details["codexHomeResolution"] = result["codexHomeResolution"]
        raise CcPeerError(
            f"{host}: {result.get('error', 'remote command failed')}", details
        )
    return result


def installed_update_receipt(output: str | bytes | None, expected: str) -> bool:
    """Accept only the publisher's complete single installed-version line."""
    if isinstance(output, bytes):
        try:
            output = output.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return False
    return isinstance(output, str) and output in (expected + "\n", expected + "\r\n")


def update_diagnostic_text(output: str | bytes | None) -> str:
    """Decode diagnostic bytes without repairing protocol stdout."""
    return output.decode("utf-8", errors="replace") if isinstance(output, bytes) else (output or "")


def installed_update_rejection(output: str | bytes | None, expected: str) -> dict | None:
    """Recognize only a complete publisher rejection before any publication."""
    if isinstance(output, bytes):
        try:
            output = output.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    if (not isinstance(output, str) or not output.startswith("{")
            or not output.endswith(("}\n", "}\r\n")) or output.count("\n") != 1):
        return None

    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate update rejection field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-JSON update rejection constant")

    try:
        result = json.loads(output, object_pairs_hook=unique_fields,
                            parse_constant=invalid_constant)
    except (ValueError, RecursionError):
        return None
    if (not isinstance(result, dict) or set(result) != {
            "schemaVersion", "command", "status", "reason", "remoteVersion"}
            or type(result["schemaVersion"]) is not int or result["schemaVersion"] != 1
            or result["command"] != "update" or result["status"] != "rejected"):
        return None
    reason, remote = result["reason"], result["remoteVersion"]
    if reason in ("installed_version_unusable", "local_version_unusable") and remote is None:
        return result
    try:
        current, wanted = release_version(remote), release_version(expected)
    except ValueError:
        return None
    if reason == "remote_not_older" and current is not None and wanted is not None and current >= wanted:
        return result
    return None


def push_to_remote(host: str, ssh_opts: list[str], ssh_info: dict | None = None) -> str:
    """Push this script to a remote machine's skill dir over SSH.

    Returns the version string reported by the newly installed copy.
    The remote machine needs only python3 and ssh access — no internet,
    no install.sh. In-process publication/verification exceptions attempt
    rollback. Signals, rollback failure, or loss of SSH at publication can
    leave the commit outcome unknown; never automatically retry such a transfer.
    A complete rejection reports publication as not_started even though the
    SSH transfer ran; it never permits automatic resubmission.
    """
    check_ssh_argument(host, "--host")
    check_ssh_options(ssh_opts)

    try:
        source = Path(__file__).resolve().read_bytes()
    except OSError as exc:
        raise CcPeerError(f"cannot read own source to push to {host}: {exc}") from exc

    ssh_info = ssh_user_metadata(host, ssh_opts) if ssh_info is None else ssh_info

    import hashlib

    source_b64 = base64.b64encode(source)
    # Python is already required on the destination. Strict, bounded decoding
    # avoids platform-specific base64 flags and detects even clean truncation.
    decoder = """import base64, hashlib, sys
digest = hashlib.sha256()
size = 0
with open(sys.argv[1], 'xb') as staged:
    while True:
        chunk = sys.stdin.buffer.read(65536)
        if not chunk:
            break
        decoded = base64.b64decode(chunk, validate=True)
        size += len(decoded)
        if size > int(sys.argv[3]):
            raise SystemExit('remote update: transfer exceeds expected size')
        digest.update(decoded)
        staged.write(decoded)
if size != int(sys.argv[3]) or digest.hexdigest() != sys.argv[2]:
    raise SystemExit('remote update: transfer digest or size mismatch')
"""
    publisher = """import fcntl, hashlib, json, os, re, stat, subprocess, sys, time
staged, target, launcher, expected = sys.argv[1:]
def comparable_update_release(text):
    match = re.fullmatch(
        r'[vV]?(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)'
        r'(?:(?:-)?(a|alpha|b|beta|rc|pre|preview)[.-]?(0|[1-9]\\d*))?',
        text.strip(), re.IGNORECASE)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups()[:3])
    if any(value > sys.maxsize for value in (major, minor, patch)):
        return None
    label, serial = match.groups()[3:]
    if label is None:
        return major, minor, patch, 3, 0
    stage = {'a': 0, 'alpha': 0, 'b': 1, 'beta': 1,
             'rc': 2, 'pre': 2, 'preview': 2}[label.lower()]
    return major, minor, patch, stage, int(serial)
def reject_update(reason, remote_version=None):
    print(json.dumps({'schemaVersion': 1, 'command': 'update', 'status': 'rejected',
                      'reason': reason, 'remoteVersion': remote_version}), flush=True)
    raise SystemExit(1)
lock_path = os.path.join(os.path.dirname(target), '.session-peer-install.lock')
lock = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
try:
    lock_stat = os.fstat(lock)
    if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
        raise SystemExit('remote update: installation lock is not a regular private file')
    deadline = time.monotonic() + 30
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise SystemExit('remote update: installation lock is busy')
            time.sleep(0.05)
    current_lock = os.lstat(lock_path)
    if (current_lock.st_dev, current_lock.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
        raise SystemExit('remote update: installation lock changed')
    backup = os.path.join(os.path.dirname(staged), 'previous.py')
    previous = os.path.lexists(target)
    wanted = comparable_update_release(expected.removeprefix('session-peer '))
    if wanted is None:
        reject_update('local_version_unusable')
    if previous:
        if not stat.S_ISREG(os.lstat(target).st_mode):
            raise SystemExit('remote update: installed program is not a regular file')
        try:
            observed = subprocess.run([sys.executable, target, '--version'],
                                      capture_output=True, timeout=30)
            reported = observed.stdout.decode('utf-8', errors='strict').strip()
            match = re.fullmatch(r'session-peer ([^\\s]+)', reported)
            current = comparable_update_release(match.group(1)) if match else None
        except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError):
            reject_update('installed_version_unusable')
        if observed.returncode != 0 or current is None:
            reject_update('installed_version_unusable')
        if current >= wanted:
            reject_update('remote_not_older', match.group(1))
        os.link(target, backup)
    created = None
    if os.path.lexists(launcher):
        if not os.path.islink(launcher) or os.path.realpath(launcher) != os.path.realpath(target):
            raise SystemExit('remote update: launcher belongs to another installation')
    else:
        os.symlink(target, launcher)
        created = os.lstat(launcher)
    staged_stat = os.stat(staged)
    with open(staged, 'rb') as source:
        published_digest = hashlib.sha256(source.read()).digest()
    def owns_publication():
        try:
            fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as installed:
                current = os.fstat(installed.fileno())
                if (not stat.S_ISREG(current.st_mode) or
                        (current.st_dev, current.st_ino) !=
                        (staged_stat.st_dev, staged_stat.st_ino) or
                        hashlib.sha256(installed.read()).digest() != published_digest):
                    return False
                bound = os.lstat(target)
                return (bound.st_dev, bound.st_ino) == (current.st_dev, current.st_ino)
        except OSError:
            return False
    published = False
    try:
        os.replace(staged, target)
        published = True
        result = subprocess.run([sys.executable, target, '--version'],
                                capture_output=True, timeout=30)
        if result.returncode != 0 or result.stdout.strip() != expected.encode('utf-8'):
            raise RuntimeError('remote update: installed version mismatch')
    except BaseException:
        owned = not published or owns_publication()
        if published and owned:
            if previous:
                os.replace(backup, target)
            else:
                os.unlink(target)
        if created is not None and owned:
            try:
                current = os.lstat(launcher)
            except FileNotFoundError:
                current = None
            if current is not None and (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                os.unlink(launcher)
        raise
    print(expected, flush=True)
finally:
    # Keep the lock inode: unlinking it lets a waiter and a new opener lock
    # different files. Kernel locks expire on close/termination, without PID
    # guesses, stale-file deletion, or touching another updater's staging.
    os.close(lock)
"""
    expected_line = f"session-peer {__version__}"
    remote_script = (
        "set -eu; umask 077; "
        'D="$HOME/.local/share/session-peer"; B="$HOME/.local/bin"; '
        'for P in "$HOME/.local" "$HOME/.local/share" "$D" "$B"; do '
        '[ ! -L "$P" ] || '
        "{ echo 'remote update: installation directory is a symlink' >&2; exit 1; }; done; "
        'mkdir -p "$D" "$B"; '
        'T=$(mktemp -d "$D/.session-peer-update.XXXXXXXX"); '
        "trap 'rm -rf \"$T\"' EXIT; trap 'exit 1' HUP INT TERM; "
        f'python3 -c {shlex.quote(decoder)} "$T/session_peer.py" '
        f"{hashlib.sha256(source).hexdigest()} {len(source)}; "
        'V=$(python3 "$T/session_peer.py" --version); '
        f'[ "$V" = {shlex.quote(expected_line)} ] || '
        "{ echo 'remote update: staged version mismatch' >&2; exit 1; }; "
        'chmod 755 "$T/session_peer.py"; '
        f'python3 -c {shlex.quote(publisher)} "$T/session_peer.py" '
        f'"$D/session_peer.py" "$B/session-peer" {shlex.quote(expected_line)}'
    )
    command = ["ssh", *ssh_opts, host, remote_script]
    uncertain = {**ssh_info, "commitStatus": "unknown", "retryAllowed": False}

    def push_failure(failure: str, detail: str | None = None,
                     started: bool = True) -> CcPeerError:
        error = ssh_failure_error(host, ssh_info, failure, detail)
        error.details.update({
            "commitStatus": "unknown" if started else "not_started",
            "retryAllowed": not started,
        })
        return error

    def reject_receipt(output: str | bytes | None) -> None:
        rejection = installed_update_rejection(output, __version__)
        if rejection is not None:
            raise CcPeerError(f"{host}: remote update rejected: {rejection['reason']}", {
                **ssh_info, "commitStatus": "not_started", "retryAllowed": False,
                "reason": rejection["reason"], "remoteVersion": rejection["remoteVersion"],
            })

    try:
        completed = subprocess.run(
            command, input=source_b64,
            capture_output=True, timeout=120,
        )
    except FileNotFoundError as exc:
        raise push_failure("transport_failed", "ssh not found on PATH", started=False) from exc
    except subprocess.TimeoutExpired as exc:
        if installed_update_receipt(exc.stdout, expected_line):
            return __version__
        reject_receipt(exc.stdout)
        raise push_failure("timeout") from exc
    except OSError as exc:
        raise push_failure("transport_failed", str(exc)) from exc

    if installed_update_receipt(completed.stdout, expected_line):
        return __version__
    reject_receipt(completed.stdout)
    if completed.returncode != 0:
        detail = update_diagnostic_text(completed.stderr).strip() or f"ssh exited {completed.returncode}"
        failure = classify_ssh_failure(detail, completed.returncode)
        if failure:
            raise push_failure(failure, detail)
        raise CcPeerError(f"{host}: {detail}", uncertain)

    raise CcPeerError(f"{host}: installed version did not match {__version__}", uncertain)
