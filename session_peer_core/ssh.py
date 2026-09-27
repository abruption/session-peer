# --------------------------------------------------------------------------
# Remote dispatch. Ships this file over SSH and runs it there, so the remote
# machine needs nothing installed beyond python3.
# --------------------------------------------------------------------------


# ssh options that make ssh run a command on *this* machine. A host or an
# --ssh-opt value carrying one of these turns "message a session" into "run
# whatever I say, locally". ProxyJump is deliberately absent: it takes a host,
# not a command, and is the right way to reach a box behind a bastion.
LOCAL_EXEC_SSH_OPTIONS = ("proxycommand", "localcommand", "permitlocalcommand")


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


def run_remote(host: str, argv: list[str], ssh_opts: list[str]) -> dict:
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")

    try:
        source = Path(__file__).resolve().read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - only when run from a pipe
        raise CcPeerError(f"cannot read own source to send to {host}: {exc}") from exc

    ssh_info = ssh_user_metadata(host, ssh_opts)

    # ssh joins everything after the destination with spaces and hands the
    # result to the remote *shell*, so an argv list is not the protection it
    # looks like: a metacharacter in any element executes over there. Build
    # the remote command as one already-quoted string instead.
    remote = " ".join(shlex.quote(a) for a in ["python3", "-", *argv, "--json"])
    command = ["ssh", *ssh_opts, host, remote]
    try:
        completed = subprocess.run(
            command, input=source, encoding="utf-8", capture_output=True, timeout=120
        )
    except FileNotFoundError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", "ssh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ssh_failure_error(host, ssh_info, "timeout") from exc
    except OSError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", str(exc)) from exc

    stdout = completed.stdout.strip()
    detail = completed.stderr.strip() or f"ssh exited {completed.returncode}"
    failure = (
        classify_ssh_failure(detail, completed.returncode)
        if completed.returncode != 0 else None
    )
    if failure:
        raise ssh_failure_error(host, ssh_info, failure, detail)
    runtime_output = (completed.stdout + "\n" + completed.stderr).strip().lower()
    if (runtime_output == "python"
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
    try:
        result = json.loads(stdout)
    except ValueError as exc:
        raise CcPeerError(f"{host}: unexpected output: {stdout[:200]}", ssh_info) from exc
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
    no install.sh.
    """
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")

    try:
        source = Path(__file__).resolve().read_bytes()
    except OSError as exc:
        raise CcPeerError(f"cannot read own source to push to {host}: {exc}") from exc

    ssh_info = ssh_user_metadata(host, ssh_opts) if ssh_info is None else ssh_info

    source_b64 = base64.b64encode(source).decode("ascii")

    remote_script = (
        "set -eu; "
        'D="$HOME/.local/share/session-peer"; '
        'mkdir -p "$D" "$HOME/.local/bin"; '
        'base64 -d > "$D/session_peer.py"; '
        'chmod +x "$D/session_peer.py"; '
        'ln -sf "$D/session_peer.py" "$HOME/.local/bin/session-peer"; '
        'python3 "$D/session_peer.py" --version 2>/dev/null || echo "session-peer unknown"'
    )
    command = ["ssh", *ssh_opts, host, remote_script]
    try:
        completed = subprocess.run(
            command, input=source_b64, encoding="utf-8",
            capture_output=True, timeout=120,
        )
    except FileNotFoundError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", "ssh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ssh_failure_error(host, ssh_info, "timeout") from exc
    except OSError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", str(exc)) from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"ssh exited {completed.returncode}"
        failure = classify_ssh_failure(detail, completed.returncode)
        if failure:
            raise ssh_failure_error(host, ssh_info, failure, detail)
        raise CcPeerError(f"{host}: {detail}", ssh_info)

    version_line = completed.stdout.strip()
    parts = version_line.split()
    return parts[-1] if parts else "unknown"
