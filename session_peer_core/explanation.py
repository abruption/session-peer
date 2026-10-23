# Display-only explanation facts. No discovery, transport, ledger or clock I/O.


def validated_delivery_context(value):
    """Accept the complete private receiver context, never guessed fragments."""
    if not isinstance(value, dict) or set(value) != {
            "schemaVersion", "agent", "target", "home", "capabilities"}:
        return None
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        return None
    if value["agent"] not in ("claude", "codex", "antigravity"):
        return None
    for key in ("target", "home"):
        item = value[key]
        if item is not None:
            if (not isinstance(item, str) or not item or item.lower().startswith("session-peer:")
                    or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in item)):
                return None
            try:
                if len(item.encode("utf-8")) > 4096:
                    return None
            except UnicodeError:
                return None
    if value["target"] is not None:
        pattern = (r"claude:[1-9][0-9]*" if value["agent"] == "claude" else
                   value["agent"] + r":[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
        if re.fullmatch(pattern, value["target"]) is None:
            return None
    if value["home"] is not None and not (PurePosixPath(value["home"]).is_absolute()
                                          or PureWindowsPath(value["home"]).is_absolute()):
        return None
    caps = value["capabilities"]
    if not isinstance(caps, dict) or set(caps) != {"send", "wake", "wait", "ack"}:
        return None
    if any(type(item) is not bool for item in caps.values()):
        return None
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 8192:
        return None
    return {**value, "capabilities": dict(caps)}


def explanation_text(value):
    """Sanitize only opt-in explanations, preserving ordinary output behavior."""
    text = human_text(value)
    return "".join("\\u%04x" % ord(c) if ord(c) in (
        0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x202a, 0x202b,
        0x202c, 0x202d, 0x202e, 0x2060, 0x2066, 0x2067, 0x2068, 0x2069, 0xfeff)
        else c for c in text)


def build_delivery_explanation(args, result, *, mode="readiness", failed=False):
    """Normalize only allowlisted facts already supplied by the caller.

    Declaration never proves eligibility, and a snapshot never proves delivery.
    The returned object is internal and is not a new JSON/wire contract.
    """
    if mode not in ("readiness", "doctor", "existing_intent"):
        raise ValueError("unsupported delivery explanation mode")
    paired = bool(getattr(args, "device", None))
    context = validated_delivery_context(getattr(args, "_delivery_explanation_context", None)) if paired else None
    requested = str(getattr(args, "to", "") or "")
    uri = requested.lower().startswith("session-peer:")
    agent = (context["agent"] if context else None) if paired else (
        None if uri or not requested else "codex" if requested.startswith("codex:") else
        "antigravity" if requested.startswith("antigravity:") else "claude")
    caps = context["capabilities"] if context else None
    if not paired and agent is not None:
        caps = {key: getattr(AGENTS.get(agent).capabilities, key)
                for key in ("send", "wake", "wait", "ack")}
    home = context["home"] if context else None
    if not paired and agent in ("codex", "antigravity"):
        value = result.get("codexHome" if agent == "codex" else "antigravityHome")
        home = value if isinstance(value, str) else None
    facts = {"mode": mode, "paired": paired, "agent": agent,
             "target": context["target"] if context else None, "home": home,
             "capabilities": caps, "agents": [], "handoff": None,
             "selectedRoute": result.get("route") if paired and result.get("route") in ("direct", "relay") else None,
             "available": not failed, "historyContext": None}
    if mode == "doctor":
        declared = result.get("capabilities", {})
        declared = declared.get("agents", {}) if isinstance(declared, dict) else {}
        for name in ("claude", "codex", "antigravity"):
            diagnostic = result.get(name, {})
            status = diagnostic.get("status") if isinstance(diagnostic, dict) else None
            allowed_status = {"available", "unavailable", "missing_home", "permission_denied",
                              "wrong_home", "missing_tool", "unknown", "disabled", "unsupported", "inbox_unavailable"}
            declaration = declared.get(name, {}) if isinstance(declared, dict) else {}
            home = diagnostic.get("selectedHome") if isinstance(diagnostic, dict) else None
            facts["agents"].append({"agent": name, "status": status if isinstance(status, str) and status in allowed_status else "unknown",
                "home": home if isinstance(home, str) else None,
                "capabilities": {key: declaration[key] if isinstance(declaration, dict)
                                 and type(declaration.get(key)) is bool else None
                                 for key in ("send", "wake", "wait", "ack")}})
    elif mode == "existing_intent":
        query = result.get("handoffQuery")
        if isinstance(query, dict) and query.get("context") in (
                "ledger_missing", "ledger_corrupt", "id_unknown", "history_unavailable"):
            facts["historyContext"] = query["context"]
        public = result.get("handoff")
        if isinstance(public, dict):
            snapshot = {}
            allowed = {"submission": {"not_attempted", "submitted", "refused", "unknown"},
                       "observation": {"unsupported", "not_requested", "pending", "observed", "failed"},
                       "ack": {"pending", "unsupported", "not_requested", "acknowledged"},
                       "wait": {"not_requested", "pending", "satisfied", "timed_out_unknown", "unsupported", "stopped", "failed"}}
            for key, statuses in allowed.items():
                value = public.get(key)
                status = value.get("status") if isinstance(value, dict) else None
                snapshot[key] = status if isinstance(status, str) and status in statuses else "unknown"
            ack = public.get("ack", {})
            observed = ack.get("receivedAtUtcMs") if isinstance(ack, dict) else None
            snapshot["receivedAtUtcMs"] = observed if type(observed) is int and 0 <= observed <= 9007199254740991 else None
            snapshot["late"] = ack.get("late") if isinstance(ack, dict) and type(ack.get("late")) is bool else None
            assurance = ack.get("assurance") if isinstance(ack, dict) else None
            snapshot["assurance"] = assurance if assurance in ("token_possession", "operator_confirmed") else None
            if snapshot["ack"] != "acknowledged":
                snapshot.update(receivedAtUtcMs=None, late=None, assurance=None)
            wait = public.get("wait", {})
            goal = wait.get("for") if isinstance(wait, dict) else None
            snapshot["waitFor"] = goal if goal in ("none", "delivered", "acknowledged") else None
            reason = wait.get("reason") if isinstance(wait, dict) else None
            snapshot["waitReason"] = reason if reason in ("insufficient_budget", "deadline_before_effect", "evidence_unsupported", "evidence_failed", "history_unavailable", "stopped_by_operator", "invalid_handoff") else None
            facts["handoff"] = snapshot
    return facts


def render_delivery_fact_lines(facts):
    def capability(value):
        return "supported (declared; eligibility unverified)" if value is True else "unsupported (declared)" if value is False else "unknown (not reported)"
    if facts["mode"] == "doctor":
        lines = ["Delivery capabilities (existing diagnostic snapshot)" if facts["available"] else
                 "Delivery capabilities unavailable (diagnostic snapshot not received)"]
        for item in facts["agents"]:
            basis = "diagnostic report" if item["status"] != "unknown" else "not reported"
            lines.append(item["agent"] + " availability: " + item["status"] + " (" + basis + "; not per-target readiness)")
            if item["agent"] in ("codex", "antigravity"):
                lines.append("  Selected home: " + (explanation_text(item["home"]) if item["home"] else "unknown (not reported)"))
            for key, value in item["capabilities"].items():
                lines.append("  " + key.capitalize() + ": " + capability(value))
        return lines + ["Injection observation: unsupported", "Task completion: unknown",
                        "Last delivery observation: unknown (not reported)",
                        "A diagnostic snapshot does not guarantee later delivery."]
    if facts["mode"] == "existing_intent":
        value = facts["handoff"] or {}
        lines = ["Delivery evidence (existing intent snapshot)" if facts["available"] else
                 "Delivery evidence unavailable (history not read)"]
        if facts["historyContext"]:
            lines.append("History query: " + facts["historyContext"] + "; no history initialized or repaired.")
        for key, label in (("submission", "Submission"), ("observation", "Injection observation"),
                           ("ack", "Explicit receipt"), ("wait", "Latest stored wait")):
            lines.append(label + ": " + value.get(key, "unknown") + (" (stored observation)" if facts["available"] else " (not available)"))
        observed = value.get("receivedAtUtcMs")
        lines.append("Receipt recorded at (stored UTC milliseconds): " + (str(observed) if observed is not None else "unknown (not reported)"))
        if value.get("assurance"):
            lines.append("Receipt assurance: " + value["assurance"] + "; does not prove task completion")
            if value["assurance"] == "token_possession":
                lines.append("Receipt proves token possession, not original agent/model identity.")
        if value.get("waitFor"):
            lines.append("Latest stored wait goal: " + value["waitFor"])
        if value.get("waitReason"):
            lines.append("Latest stored wait reason: " + value["waitReason"])
        if value.get("late") is not None:
            lines.append("Receipt late relative to first wait: " + str(value["late"]).lower())
        return lines + ["Task completion: unknown", "Stored evidence may be stale; this view does not refresh delivery.",
                        "Do not automatically resend after an unknown outcome."]
    caps = facts["capabilities"] or {}
    return ["Submission capability: " + capability(caps.get("send")),
            "Wake capability: " + capability(caps.get("wake")),
            "Injection observation: unsupported" if not facts["paired"] else "Injection observation: unknown (not reported)",
            "Last delivery observation: unknown (not reported)",
            "Task completion: unknown"]
