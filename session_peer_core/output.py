# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def render_sessions(sessions: list[dict], where: str) -> str:
    if not sessions:
        return f"No reachable Claude Code sessions on {where}."

    rows = [("NAME", "PID", "STATUS", "CWD")]
    for s in sessions:
        name = s["name"] or "(unnamed)"
        if not s["reachable"]:
            name += " [no inbox]" if s["alive"] else " [stale record]"
        rows.append((name, str(s["pid"]), s["status"] or "-", s["cwd"] or "-"))

    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    lines = [
        f"{r[0]:<{widths[0]}}  {r[1]:<{widths[1]}}  {r[2]:<{widths[2]}}  {r[3]}"
        for r in rows
    ]
    return f"Sessions on {where}:\n" + "\n".join(lines)


JSON_RESPONSE_SCHEMA_VERSION = 1


def local_host() -> str:
    """Stable, network-independent identity for results produced locally."""
    return socket.gethostname()


def json_result(command: str, payload: dict | None = None, *,
                host: str | None = None, ok: bool | None = None) -> dict:
    """Build one command result with the common machine-readable envelope."""
    detail = dict(payload or {})
    payload_ok = detail.pop("ok", True)
    payload_host = detail.pop("host", None)
    for reserved in ("schemaVersion", "command"):
        detail.pop(reserved, None)
    return {
        "schemaVersion": JSON_RESPONSE_SCHEMA_VERSION,
        "ok": bool(payload_ok if ok is None else ok),
        "host": host or payload_host or local_host(),
        "command": command,
        **detail,
    }


def one_or_many(results: list[dict]) -> dict | list[dict]:
    """Keep one destination flat; use an array only for repeated --host."""
    return results[0] if len(results) == 1 else results


def with_client_update(payload: dict | list[dict]) -> dict | list[dict]:
    """Attach the invoking client's cached update fact to each result object."""
    if _CLIENT_UPDATE_NOTICE is None:
        return payload
    if isinstance(payload, list):
        return [
            {**item, "clientUpdate": dict(_CLIENT_UPDATE_NOTICE)}
            if isinstance(item, dict) else item
            for item in payload
        ]
    return {**payload, "clientUpdate": dict(_CLIENT_UPDATE_NOTICE)}


def emit(as_json: bool, payload: dict, human: str, *, command: str,
         host: str | None = None, ok: bool | None = None) -> None:
    result = json_result(command, payload, host=host, ok=ok)
    print(json.dumps(with_client_update(result), ensure_ascii=False) if as_json else human)


def emit_json_results(results: list[dict]) -> None:
    print(json.dumps(with_client_update(one_or_many(results)), ensure_ascii=False))


def emit_human_update_notice() -> None:
    if _CLIENT_UPDATE_NOTICE is None:
        return
    print(
        f"Update available: {_CLIENT_UPDATE_NOTICE['current']} → "
        f"{_CLIENT_UPDATE_NOTICE['latest']}. "
        f"Run: {_CLIENT_UPDATE_NOTICE['command']}",
        file=sys.stderr,
    )


def host_metadata(ssh_host: str, canonical_host: str) -> dict:
    metadata = {"host": canonical_host}
    if ssh_host != canonical_host:
        metadata["sshHost"] = ssh_host
    return metadata


def display_host(ssh_host: str, canonical_host: str) -> str:
    if ssh_host == canonical_host:
        return canonical_host
    return f"{canonical_host} (via SSH {ssh_host})"


def tailscale_ssh_options(ssh_host: str, canonical_host: str) -> list[str]:
    """Route an SSH alias to its verified MagicDNS name without losing config.

    Keeping ssh_host as the command destination preserves matching `Host` and
    `User` settings. HostKeyAlias preserves an existing known_hosts entry keyed
    by the caller's original IP or hostname.
    """
    if ssh_host == canonical_host:
        return []
    _, _, original_name = ssh_host.rpartition("@")
    _, _, magicdns_name = canonical_host.rpartition("@")
    original_name = (original_name or ssh_host).strip("[]")
    magicdns_name = (magicdns_name or canonical_host).strip("[]")
    return [
        "-o", f"HostName={magicdns_name}",
        "-o", f"HostKeyAlias={original_name}",
    ]
