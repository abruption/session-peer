# Opt-in connection identity. Native host-key verification, not remote JSON,
# supplies the fingerprint; an independent probe is not a send precondition.
SSH_FINGERPRINT_PATTERN = r"SHA256:[A-Za-z0-9+/]{43}"
SSH_IDENTITY_HELPER = r"""
import base64, hashlib, hmac, json, os, re, sys
try:
    path, expected, phase = sys.argv[1:4]
    if phase == "ORDER":
        sys.exit(0)
    if phase != "HOSTNAME" or len(sys.argv) != 6:
        sys.exit(1)
    kind, blob = sys.argv[4:]
    if kind not in ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256",
                    "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"):
        sys.exit(1)
    if len(blob) > 16384 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", blob):
        sys.exit(1)
    raw = base64.b64decode(blob, validate=True)
    length = int.from_bytes(raw[:4], "big")
    if not 1 <= length <= 64 or raw[4:4 + length].decode("ascii") != kind:
        sys.exit(1)
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
    matches = expected == "-" or hmac.compare_digest(expected, fingerprint)
    result = {"schemaVersion": 1, "algorithm": kind, "fingerprint": fingerprint,
              "decision": "observed" if matches else "refused"}
    with os.fdopen(os.open(path + ".new", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump(result, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(path + ".new", path)
    if expected != "-" and matches:
        print("session-peer-pinned", kind, blob)
except Exception:
    sys.exit(1)
"""


def validate_ssh_identity_options(args) -> None:
    expected = getattr(args, "require_ssh_host_key", None)
    requested = bool(expected is not None or getattr(args, "ssh_identity", False))
    if not requested:
        return
    if getattr(args, "command", None) not in ("list", "send", "doctor") or getattr(args, "device", None):
        raise CcPeerError("SSH identity is only available for list/send/doctor --host",
                          {"reason": "unsupported_ssh_identity_operation", "retryAllowed": False})
    if expected is not None and not re.fullmatch(SSH_FINGERPRINT_PATTERN, expected):
        raise CcPeerError("Invalid SHA256 SSH host-key fingerprint",
                          {"reason": "invalid_ssh_host_key", "retryAllowed": False})
    if not getattr(args, "host", None):
        raise CcPeerError("SSH identity options require --host",
                          {"reason": "ssh_identity_requires_host", "retryAllowed": False})
    if IS_WINDOWS:
        raise CcPeerError("Connection-bound SSH identity is currently POSIX-only",
                          {"reason": "unsupported_ssh_identity", "retryAllowed": False})


def ssh_identity_configuration(host: str, ssh_opts: list[str], *, handoff_budget=None) -> dict:
    check_ssh_argument(host, "--host")
    check_ssh_options(ssh_opts)
    try:
        completed = (ssh_handoff_configuration(host, ssh_opts, handoff_budget)
                     if handoff_budget is not None else subprocess.run(
                         ["ssh", "-G", *ssh_opts, host], capture_output=True, timeout=DETECT_TIMEOUT))
        output = completed.stdout
        if isinstance(output, bytes):
            if len(output) > 1024 * 1024:
                raise ValueError("config budget")
            output = output.decode("utf-8", errors="strict")
        # The bounded owned helper reserves the leader until group cleanup and
        # may return its own SIGKILL after full pipe EOF. Configuration metadata
        # is accepted only through that helper's no-error/full-output guard;
        # the actual connection callback still supplies all host-key evidence.
        valid_code = (completed.returncode in (0, -signal.SIGKILL)
                      if handoff_budget is not None else completed.returncode == 0)
        if not isinstance(output, str) or len(output.encode("utf-8")) > 1024 * 1024 or not valid_code:
            raise ValueError("config unavailable")
        values = {}
        for line in output.splitlines():
            key, sep, value = line.partition(" ")
            if sep and key.lower() in ("hostname", "port", "hostkeyalias", "knownhostscommand"):
                values[key.lower()] = value.strip()
        if values.get("knownhostscommand", "none").lower() != "none":
            raise CcPeerError("User-owned KnownHostsCommand cannot be replaced in identity mode",
                              {"reason": "unsupported_ssh_identity_config", "retryAllowed": False})
        hostname = values["hostname"]
        port = values["port"]
        alias = values.get("hostkeyalias", "none")
        if (not hostname or len(hostname.encode("utf-8")) > 1024
                or any(ord(c) < 32 or ord(c) == 127 for c in hostname + alias)
                or not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535
                or len(alias.encode("utf-8")) > 1024):
            raise ValueError("invalid config")
        return {"destination": hostname, "port": int(port),
                "keyLookupName": hostname if alias.lower() == "none" else alias}
    except CcPeerError:
        raise
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, KeyError) as exc:
        raise CcPeerError("Cannot inspect SSH identity configuration",
                          {"reason": "ssh_identity_config_unavailable", "retryAllowed": False}) from exc


def ssh_key_receipt(path: Path) -> dict | None:
    try:
        node = path.lstat()
        if (not stat.S_ISREG(node.st_mode) or node.st_size > 2048
                or node.st_uid != os.geteuid() or node.st_mode & 0o077):
            return None
        result = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(result, dict) or set(result) != {"schemaVersion", "algorithm", "fingerprint", "decision"}
                or type(result["schemaVersion"]) is not int or result["schemaVersion"] != 1
                or result["decision"] not in ("observed", "refused")
                or result["algorithm"] not in ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256",
                                                "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521")
                or not isinstance(result["fingerprint"], str)
                or not re.fullmatch(SSH_FINGERPRINT_PATTERN, result["fingerprint"])):
            return None
        return result
    except (OSError, UnicodeError, ValueError, KeyError):
        return None


def run_remote_with_identity(host: str, argv: list[str], ssh_opts: list[str],
                             expected: str | None = None, *, handoff_budget=None,
                             handoff_context=None) -> dict:
    if IS_WINDOWS:
        raise CcPeerError("Connection-bound SSH identity is currently POSIX-only",
                          {"reason": "unsupported_ssh_identity", "retryAllowed": False})
    if expected is not None and not re.fullmatch(SSH_FINGERPRINT_PATTERN, expected):
        raise CcPeerError("Invalid SHA256 SSH host-key fingerprint",
                          {"reason": "invalid_ssh_host_key", "retryAllowed": False})
    if handoff_budget is not None or handoff_context is not None:
        ssh_handoff_request(handoff_budget, handoff_context, require_context=True)
        try:
            handoff_validate_remote_argv(argv, handoff_context)
        except (CcPeerError, ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise CcPeerError("Invalid private SSH handoff command",
                              {"reason": "invalid_ssh_handoff_command", "retryAllowed": False, "spawned": False}) from exc
    configuration = (ssh_identity_configuration(host, ssh_opts, handoff_budget=handoff_budget)
                     if handoff_budget is not None else ssh_identity_configuration(host, ssh_opts))
    with tempfile.TemporaryDirectory(prefix="session-peer-ssh-identity-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        helper = root / "known-hosts.py"
        receipt = root / "receipt.json"
        with os.fdopen(os.open(helper, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
            stream.write(SSH_IDENTITY_HELPER)
        # OpenSSH does not shell-escape token expansions. All expanded values
        # here are native enum/key-type/base64, quoted even when ORDER is empty.
        parts = [sys.executable, "-I", str(helper), str(receipt), expected or "-"]
        command = " ".join(shlex.quote(part.replace("%", "%%")) for part in parts)
        command += " '%I' '%t' '%K'"
        fixed = ["-oControlMaster=no", "-oControlPath=none", "-oControlPersist=no",
                 "-oStrictHostKeyChecking=yes", "-oVerifyHostKeyDNS=no",
                 "-oCheckHostIP=no", "-oUpdateHostKeys=no", "-oKnownHostsCommand=" + command]
        if expected is not None:
            fixed += ["-oUserKnownHostsFile=none", "-oGlobalKnownHostsFile=none",
                      "-oHostKeyAlias=session-peer-pinned"]
        try:
            if handoff_budget is not None:
                result = _run_remote_dispatch(host, argv, ssh_opts, identity_options=fixed,
                                              handoff_budget=handoff_budget, handoff_context=handoff_context)
            else:
                result = _run_remote_dispatch(host, argv, ssh_opts, identity_options=fixed)
        except CcPeerError as exc:
            proof = ssh_key_receipt(receipt)
            # An offered key is not verified authentication or remote execution.
            identity = {"schemaVersion": 1, "status": "unknown", **configuration}
            if proof is not None:
                identity.update(algorithm=proof["algorithm"], fingerprint=proof["fingerprint"],
                                status="refused" if proof["decision"] == "refused" else "observed")
                if (expected is not None and proof["decision"] == "refused"
                        and exc.details.get("submitted") is not True
                        and "queueId" not in exc.details and "target" not in exc.details):
                    # Native strict key verification precedes auth and remote
                    # execution. This local negative receipt is stronger than
                    # arbitrary remote stderr and proves this pin had no effect.
                    exc.details.update(status="refused", submitted=False,
                                       reason="ssh_host_key_mismatch", retryAllowed=False)
            exc.details["sshIdentity"] = identity
            raise
        proof = ssh_key_receipt(receipt)
        valid = proof is not None and proof["decision"] == "observed"
        if expected is not None:
            import hmac
            valid = valid and hmac.compare_digest(proof["fingerprint"], expected)
        if expected is not None and not valid:
            # Retain independently validated native facts, never create a
            # submitted:false claim or invite a second submission.
            details = {key: value for key, value in result.items()
                       if key not in ("ok", "error", "command", "schemaVersion")}
            details.update(reason="ssh_identity_evidence_unavailable", retryAllowed=False,
                           sshIdentity={"schemaVersion": 1, "status": "unknown", **configuration})
            raise CcPeerError("SSH key evidence unavailable; do not automatically retry", details)
        result["sshIdentity"] = {"schemaVersion": 1, "status": "verified" if valid else "unsupported",
                                 **configuration}
        if valid:
            result["sshIdentity"].update(algorithm=proof["algorithm"], fingerprint=proof["fingerprint"])
        return result


def run_remote(host: str, argv: list[str], ssh_opts: list[str], *, handoff_budget=None,
               handoff_context=None) -> dict:
    if handoff_budget is not None or handoff_context is not None:
        return _run_remote_dispatch(host, argv, ssh_opts, handoff_budget=handoff_budget,
                                     handoff_context=handoff_context)
    return _run_remote_dispatch(host, argv, ssh_opts)
