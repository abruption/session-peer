# --------------------------------------------------------------------------
# Remote dispatch. Ships this file over SSH and runs it there, so the remote
# machine needs nothing installed beyond python3.
# --------------------------------------------------------------------------


# ssh options that make ssh run a command on *this* machine. A host or an
# --ssh-opt value carrying one of these turns "message a session" into "run
# whatever I say, locally". ProxyJump is deliberately absent: it takes a host,
# not a command, and is the right way to reach a box behind a bastion.
LOCAL_EXEC_SSH_OPTIONS = ("proxycommand", "localcommand", "permitlocalcommand")

# Linux with 4 KiB pages permits at most 128 KiB per exec argument,
# including NUL. Bound the entire quoted remote shell command, not characters
# or the unwrapped body alone. Source continues to travel over stdin.
MAX_SSH_COMMAND_BYTES = 128 * 1024 - 1


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
    stdout = output.strip() if isinstance(output, str) else ""

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
    except ValueError:
        return stdout, None, False, False
    valid = (
        isinstance(result, dict)
        and type(result.get("schemaVersion")) is int
        and result["schemaVersion"] == JSON_RESPONSE_SCHEMA_VERSION
        and type(result.get("ok")) is bool
        and bool(argv) and result.get("command") == argv[0]
    )
    return stdout, result, bool(stdout), valid


def run_remote(host: str, argv: list[str], ssh_opts: list[str]) -> dict:
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")

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
    try:
        completed = subprocess.run(
            command, input=source, encoding="utf-8", capture_output=True, timeout=120
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
                raise CcPeerError(
                    f"SSH send to {host} timed out; submission outcome unknown. "
                    "Do not automatically retry; check the target before retrying.",
                    {**ssh_info, "sshFailure": "timeout", "status": "unknown",
                     "reason": "outcome_unknown", "retryAllowed": False},
                ) from exc
            raise ssh_failure_error(host, ssh_info, "timeout") from exc
    except OSError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", str(exc)) from exc

    stdout, result, parsed_result, valid_result = parse_ssh_response(completed.stdout, argv)
    detail = completed.stderr.strip() or f"ssh exited {completed.returncode}"
    # A complete response proves the remote command ran, even if the SSH
    # process later exits 255. Login-shell stderr must not hide submission
    # evidence or turn a remote partial failure into an invitation to resend.
    failure = (
        classify_ssh_failure(detail, completed.returncode)
        if (not valid_result and completed.returncode != 0
            and (completed.returncode == 255 or not stdout)) else None
    )
    if failure:
        raise ssh_failure_error(host, ssh_info, failure, detail)
    runtime_output = (stdout + "\n" + completed.stderr).strip().lower()
    if not valid_result and (runtime_output == "python"
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
    if not parsed_result or (isinstance(result, dict)
                             and "schemaVersion" in result and not valid_result):
        raise CcPeerError(f"{host}: unexpected output: {stdout[:200]}", ssh_info)
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
    no install.sh. In-process publication/verification exceptions attempt
    rollback. Signals, rollback failure, or loss of SSH at publication can
    leave the commit outcome unknown; never automatically retry such a transfer.
    """
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")

    try:
        source = Path(__file__).resolve().read_bytes()
    except OSError as exc:
        raise CcPeerError(f"cannot read own source to push to {host}: {exc}") from exc

    ssh_info = ssh_user_metadata(host, ssh_opts) if ssh_info is None else ssh_info

    import hashlib

    source_b64 = base64.b64encode(source).decode("ascii")
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
    publisher = """import os, stat, subprocess, sys
staged, target, launcher, expected = sys.argv[1:]
backup = os.path.join(os.path.dirname(staged), 'previous.py')
previous = os.path.lexists(target)
if previous:
    if not stat.S_ISREG(os.lstat(target).st_mode):
        raise SystemExit('remote update: installed program is not a regular file')
    os.link(target, backup)
created = None
if os.path.lexists(launcher):
    if not os.path.islink(launcher) or os.path.realpath(launcher) != os.path.realpath(target):
        raise SystemExit('remote update: launcher belongs to another installation')
else:
    os.symlink(target, launcher)
    created = os.lstat(launcher)
published = False
try:
    os.replace(staged, target)
    published = True
    result = subprocess.run([sys.executable, target, '--version'],
                            capture_output=True, timeout=30)
    if result.returncode != 0 or result.stdout.strip() != expected.encode('utf-8'):
        raise RuntimeError('remote update: installed version mismatch')
except BaseException:
    if published:
        if previous:
            os.replace(backup, target)
        else:
            os.unlink(target)
    if created is not None:
        current = os.lstat(launcher)
        if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
            os.unlink(launcher)
    raise
print(expected)
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

    try:
        completed = subprocess.run(
            command, input=source_b64, encoding="utf-8",
            capture_output=True, timeout=120,
        )
    except FileNotFoundError as exc:
        raise push_failure("transport_failed", "ssh not found on PATH", started=False) from exc
    except subprocess.TimeoutExpired as exc:
        raise push_failure("timeout") from exc
    except OSError as exc:
        raise push_failure("transport_failed", str(exc)) from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"ssh exited {completed.returncode}"
        failure = classify_ssh_failure(detail, completed.returncode)
        if failure:
            raise push_failure(failure, detail)
        raise CcPeerError(f"{host}: {detail}", uncertain)

    if completed.stdout.strip() != expected_line:
        raise CcPeerError(f"{host}: installed version did not match {__version__}", uncertain)
    return __version__
