# --------------------------------------------------------------------------
# Diagnostics. These checks are read-only: no inbox connection, queue write,
# login change, host-key enrollment, or permission change is attempted.
# --------------------------------------------------------------------------


def _diagnostic(status: str, code: str, message: str, **detail) -> dict:
    return {"status": status, "code": code, "message": message, **detail}


def diagnose_claude() -> dict:
    directory = sessions_dir()
    result = {
        "sessionsDir": str(directory), "records": 0, "invalidRecords": 0,
        "aliveSessions": 0, "availableInboxes": 0, "staleRecords": 0, "checks": [],
    }
    try:
        mode = directory.stat().st_mode
    except FileNotFoundError:
        result["checks"].append(_diagnostic(
            "error", "sessions_dir_missing",
            "Claude sessions directory does not exist; check CLAUDE_CONFIG_DIR",
        ))
        return {"status": "missing_home", **result}
    except PermissionError:
        result["checks"].append(_diagnostic(
            "error", "sessions_dir_permission_denied",
            "Claude sessions directory is not readable by this user",
        ))
        return {"status": "permission_denied", **result}
    except OSError as exc:
        result["checks"].append(_diagnostic(
            "unknown", "sessions_dir_unreadable", f"Cannot inspect Claude sessions: {exc}",
        ))
        return {"status": "unknown", **result}
    if not stat.S_ISDIR(mode):
        result["checks"].append(_diagnostic(
            "error", "sessions_path_not_directory",
            "Configured Claude sessions path is not a directory",
        ))
        return {"status": "wrong_home", **result}
    try:
        entries = sorted(
            entry for entry in directory.iterdir()
            if entry.name.endswith(".json")
        )
    except PermissionError:
        result["checks"].append(_diagnostic(
            "error", "sessions_dir_permission_denied",
            "Claude sessions directory cannot be listed by this user",
        ))
        return {"status": "permission_denied", **result}
    except OSError as exc:
        result["checks"].append(_diagnostic(
            "unknown", "sessions_dir_unreadable", f"Cannot list Claude sessions: {exc}",
        ))
        return {"status": "unknown", **result}

    permission_failures = 0
    for record_file in entries:
        if not record_file.stem.isdigit():
            continue
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except PermissionError:
            permission_failures += 1
            continue
        except (OSError, ValueError):
            result["invalidRecords"] += 1
            continue
        pid = record.get("pid")
        if not isinstance(pid, int):
            result["invalidRecords"] += 1
            continue
        result["records"] += 1
        alive, stale_reason = claude_process_state(record, int(record_file.stem))
        if stale_reason:
            result["staleRecords"] += 1
        if alive:
            result["aliveSessions"] += 1
        inbox = str(record.get("messagingSocketPath") or "")
        try:
            present = (
                inbox.startswith("\\\\.\\pipe\\") if IS_WINDOWS
                else bool(inbox) and Path(inbox).is_socket()
            )
        except OSError:
            present = False
        if alive and present:
            result["availableInboxes"] += 1

    if permission_failures:
        result["checks"].append(_diagnostic(
            "error", "session_record_permission_denied",
            "One or more Claude session records are not readable",
            count=permission_failures,
        ))
        return {"status": "permission_denied", **result}
    if result["staleRecords"]:
        result["checks"].append(_diagnostic(
            "warning", "stale_session_records",
            "Claude session records do not match live process identities",
            count=result["staleRecords"],
        ))
    if result["availableInboxes"]:
        result["checks"].append(_diagnostic(
            "ok", "inbox_present",
            "At least one live Claude session advertises an inbox",
            verification="filesystem_only",
        ))
        return {"status": "available", **result}
    if result["aliveSessions"]:
        result["checks"].append(_diagnostic(
            "warning", "inbox_unavailable",
            "Live Claude sessions exist but none advertises an available inbox",
        ))
        return {"status": "inbox_unavailable", **result}
    result["checks"].append(_diagnostic(
        "warning", "no_live_sessions",
        "No live Claude session with an inbox was found",
    ))
    return {"status": "unavailable", **result}


def _codex_home_source(args: argparse.Namespace) -> str:
    if getattr(args, "codex_home", None):
        return "explicit"
    if os.environ.get("CODEX_HOME"):
        return "environment"
    return "default"


def diagnose_codex_home(home: Path) -> dict:
    db = home / "state_5.sqlite"
    item = {"codexHome": str(home), "stateDb": str(db), "sessionCount": None}
    try:
        mode = db.stat().st_mode
    except FileNotFoundError:
        return {**item, "status": "missing_home", "code": "state_db_missing"}
    except PermissionError:
        return {**item, "status": "permission_denied", "code": "state_db_permission_denied"}
    except OSError as exc:
        return {**item, "status": "unknown", "code": "state_db_unreadable", "detail": str(exc)}
    if not stat.S_ISREG(mode):
        return {**item, "status": "wrong_home", "code": "state_db_not_regular"}
    try:
        conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            conn.execute("PRAGMA query_only=ON")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
            required = {"id", "title", "cwd", "updated_at", "archived", "rollout_path"}
            if not required <= columns:
                return {
                    **item, "status": "unsupported", "code": "unsupported_threads_schema",
                    "missingColumns": sorted(required - columns),
                }
            count = int(conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error as exc:
        detail = str(exc)
        lowered = detail.lower()
        status = "permission_denied" if "permission" in lowered else "unknown"
        code = "state_db_permission_denied" if status == "permission_denied" else "state_db_unreadable"
        return {**item, "status": status, "code": code, "detail": detail}
    return {**item, "status": "available", "code": "state_db_readable", "sessionCount": count}


def diagnose_codex(args: argparse.Namespace) -> dict:
    selected = codex_home(args)
    requested_bin = getattr(args, "codex_bin", None) or "codex"
    executable = shutil.which(os.path.expanduser(requested_bin))
    checks = []
    if executable:
        checks.append(_diagnostic(
            "ok", "codex_executable_found", "Codex executable is available",
            path=str(Path(executable).absolute()),
        ))
    else:
        checks.append(_diagnostic(
            "error", "codex_executable_missing",
            "Codex executable is not on PATH; set --codex-bin on the destination",
            requested=requested_bin,
        ))
    inventory_error = None
    try:
        homes = known_codex_homes(selected)
    except CcPeerError as exc:
        homes = [selected]
        inventory_error = str(exc)
    candidates = [diagnose_codex_home(home) for home in homes]
    selected_item = next(
        (candidate for candidate in candidates if candidate["codexHome"] == str(selected)),
        candidates[0],
    )
    if inventory_error:
        checks.append(_diagnostic(
            "unknown", "home_inventory_unreadable", inventory_error,
        ))
    checks.append(_diagnostic(
        "ok" if selected_item["status"] == "available" else "error",
        selected_item["code"],
        "Selected Codex home is readable" if selected_item["status"] == "available"
        else "Selected Codex home cannot be used",
    ))
    status = selected_item["status"]
    if status == "available" and not executable:
        status = "missing_tool"
    if inventory_error and status == "available":
        status = "unknown"
    unsaved_count = 0
    unsaved_scan_truncated = False
    if selected_item["status"] == "available":
        try:
            unsaved_count, unsaved_scan_truncated = count_unsaved_codex_writers(selected)
        except (OSError, sqlite3.Error):
            checks.append(_diagnostic(
                "unknown", "unsaved_writer_check_unavailable",
                "Could not inspect unsaved Codex writer locks",
            ))
        if unsaved_count:
            checks.append(_diagnostic(
                "warning", "unsaved_live_writer",
                "A live Codex writer has not saved its thread yet; wait for its first turn to finish",
                count=unsaved_count,
            ))
    return {
        "status": status, "selectedHome": str(selected),
        "homeSource": _codex_home_source(args), "executable": executable,
        "homes": candidates, "checks": checks,
        "unsavedLiveWriters": unsaved_count, "unsavedWriterScanTruncated": unsaved_scan_truncated,
    }


def probe_return_route(destination: str) -> dict:
    """Test reverse SSH without prompts, key enrollment, or config mutation."""
    check_ssh_argument(destination, "--host")
    if is_self_ssh_destination(destination):
        return {
            "status": "verified", "transport": "local", "host": local_host(),
            "reason": "self_route_normalized",
        }
    executable = shutil.which("ssh")
    if executable is None:
        return {
            "status": "failed", "transport": "ssh", "host": destination,
            "reason": "ssh_executable_missing",
        }
    ssh_info = ssh_user_metadata(destination, [])
    command = [
        executable,
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "NumberOfPasswordPrompts=0",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UpdateHostKeys=no",
        "-o", "ConnectTimeout=5",
        "-o", "ConnectionAttempts=1",
        "-o", "ControlMaster=no",
        destination, "true",
    ]
    try:
        done = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace", timeout=8,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "failed", "transport": "ssh", "host": destination,
            "reason": "timeout", **ssh_info,
        }
    except OSError as exc:
        return {
            "status": "failed", "transport": "ssh", "host": destination,
            "reason": "transport_failed", "detail": str(exc), **ssh_info,
        }
    if done.returncode == 0:
        return {
            "status": "verified", "transport": "ssh", "host": destination,
            "reason": "ssh_command_succeeded", **ssh_info,
        }
    detail = (done.stderr.strip() or done.stdout.strip())[:1000]
    return {
        "status": "failed", "transport": "ssh", "host": destination,
        "reason": classify_ssh_failure(detail, done.returncode) or "remote_command_failed",
        **({"detail": detail} if detail else {}), **ssh_info,
    }


def doctor_payload(args: argparse.Namespace) -> dict:
    diagnostics = {}
    for name in AGENTS.names():
        try:
            diagnostics[name] = LocalTransport().execute("doctor", AGENTS.get(name), args)
        except (CcPeerError, OSError) as exc:
            diagnostics[name] = {"status": "unknown", "checks": [
                _diagnostic("error", "adapter_failed", str(exc))]}
    active = [item for item in diagnostics.values() if item["status"] != "disabled"]
    available = sum(item["status"] == "available" for item in active)
    payload = {
        "status": "healthy" if available == len(active) else ("partial" if available else "issues_found"),
        **diagnostics,
        "capabilities": {
            "agents": {name: dict(AGENTS.get(name).capabilities._asdict()) for name in AGENTS.names()},
            "replyObservation": {
                "status": "unsupported",
                "reason": "no_cross_agent_acknowledgement_api",
                "claudeLocalIdleNotice": "native_claude_only",
                "automatedWait": False,
            },
        },
    }
    return_host = getattr(args, "_return_host", None)
    if return_host:
        payload["returnRoute"] = probe_return_route(return_host)
    return payload


def render_doctor(payload: dict, where: str) -> str:
    lines = [
        f"Diagnostics on {where}:",
        *("  " + AGENTS.get(name).diagnostic_text(payload[name]) for name in AGENTS.names() if name in payload),
        "  Automated reply observation: unsupported across Claude, Codex, and SSH",
    ]
    for component in AGENTS.names():
        for check in payload.get(component, {}).get("checks", []):
            if check.get("status") != "ok":
                lines.append(f"    - {check['code']}: {check['message']}")
    route = payload.get("returnRoute")
    if route:
        lines.append(
            f"  Return route: {route['status']} via {route['transport']} "
            f"({route['reason']})"
        )
    else:
        lines.append("  Return route: not checked (use --check-return-route)")
    return "\n".join(lines)
