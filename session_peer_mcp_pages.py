"""Bounded, per-process MCP listing snapshots; no native or MCP SDK imports.

Captured-output limits do not bound discovery work before output. Cache byte
charges count serialized public state, not Python allocator/RSS overhead.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import secrets
import time

PAGE_OUTPUT_BYTES = 64 * 1024
PAGE_INPUT_BYTES = 4 * 1024 * 1024
PAGE_STDERR_BYTES = 64 * 1024
PAGE_COLLECTION_SECONDS = 10
PAGE_CACHE_COUNT = 4
PAGE_CACHE_BYTES = 8 * 1024 * 1024
PAGE_TTL_SECONDS = 30
PAGE_MAX_LIFETIME_SECONDS = 600
PAGE_MAX_ROWS = 20000
PAGE_ID_BYTES = 8192
PAGE_LABEL_BYTES = 512
PAGE_ARGUMENTS = frozenset({"destination", "agent", "include_inactive", "limit", "cursor"})
# Source-qualified listing envelopes: output.py/json_result, commands.py/cmd_list,
# registry.py/collect_listing and ssh.py/SSH_METADATA_FIELDS. These advisory
# route/version fields are not discovery evidence and are never projected.
_RAW_KEYS = frozenset({"schemaVersion", "command", "ok", "host", "sshHost", "sshUser",
    "sshUserSource", "sshIdentity", "sessions", "version", "discovery", "error", "errors",
    "truncated", "codexHome", "remoteVersion", "remoteVersionProbe", "clientUpdate", "skillUpdates"})
_COMMON_EVIDENCE_KEYS = frozenset({"status", "error", "errors", "truncated"})
_INFO_KEYS = {"claude": _COMMON_EVIDENCE_KEYS,
    "codex": _COMMON_EVIDENCE_KEYS | {"homes"},
    "antigravity": _COMMON_EVIDENCE_KEYS | {"scope", "reason"}}
# codex.py/collect_codex_listing candidate/home diagnostics.
_HOME_KEYS = frozenset({"codexHome", "stateDb", "sources", "status", "code", "error",
                        "errors", "truncated", "sessionCount"})


class PageRefusal(ValueError):
    """Only fixed, reviewed reason codes may be passed to this exception."""


def page_refusal(reason):
    return {"ok": False, "schemaVersion": 1, "command": "mcp.sessions_page",
            "type": "refusal", "reason": reason, "retryAllowed": False}


def serialized(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def page_arguments(arguments):
    """Validate original JSON values before an SDK can coerce/drop arguments."""
    if (not isinstance(arguments, dict) or set(arguments) - PAGE_ARGUMENTS
            or not {"destination", "agent"} <= set(arguments)):
        raise PageRefusal("invalid_arguments")
    destination, agent = arguments["destination"], arguments["agent"]
    inactive, limit, cursor = (arguments.get("include_inactive", False),
                               arguments.get("limit", 50), arguments.get("cursor"))
    if (type(destination) is not str or not destination or len(destination) > 128
            or type(agent) is not str or not agent or len(agent) > 64
            or type(inactive) is not bool or type(limit) is not int or not 1 <= limit <= 50
            or cursor is not None and (type(cursor) is not str or len(cursor) != 64
                                      or any(ch not in "0123456789abcdef" for ch in cursor))):
        raise PageRefusal("invalid_arguments")
    try:
        if len(destination.encode("utf-8")) > 128:
            raise PageRefusal("invalid_arguments")
    except UnicodeError:
        raise PageRefusal("invalid_arguments") from None
    return destination, agent, inactive, limit, cursor


def _reported_problem(value):
    return (isinstance(value, dict) and
            (bool(value.get("error")) or bool(value.get("errors")) or value.get("truncated") is True))


def project_listing(raw, agent, returncode):
    """Retain identities exactly, and sanitize source completeness evidence.

    The caller uses one explicit agent on one policy-pinned route/home. Repeated
    IDs refuse rather than merging records or inventing cross-home identity.
    """
    if (not isinstance(raw, dict) or type(raw.get("ok")) is not bool
            or not isinstance(raw.get("sessions"), list)):
        raise PageRefusal("collection_schema_unavailable")
    if len(raw["sessions"]) > PAGE_MAX_ROWS:
        raise PageRefusal("collection_row_limit")
    rows, seen = [], set()
    try:
        for source in raw["sessions"]:
            if not isinstance(source, dict) or source.get("agent") != agent:
                raise PageRefusal("collection_scope_mismatch")
            if agent == "claude":
                # Native Claude discovery identifies records by integer PID,
                # not an id field. Decimal encoding is exact and reversible;
                # a label/name never substitutes for that selected identity.
                pid = source.get("pid")
                if type(pid) is not int or not 1 < pid < 2 ** 63:
                    raise PageRefusal("identity_unrepresentable")
                identifier = str(pid)
            else:
                identifier = source.get("id")
            if type(identifier) is not str or not identifier or len(identifier.encode("utf-8")) > PAGE_ID_BYTES:
                raise PageRefusal("identity_unrepresentable")
            if identifier in seen:
                raise PageRefusal("duplicate_identity")
            seen.add(identifier)
            row = {"agent": agent, "id": identifier}
            label = source.get("name")
            if isinstance(label, str):
                try:
                    encoded = label.encode("utf-8")
                except UnicodeError:
                    row["nameOmitted"] = True
                else:
                    row["name"] = encoded[:PAGE_LABEL_BYTES].decode("utf-8", errors="ignore")
                    if len(encoded) > PAGE_LABEL_BYTES:
                        row["nameTruncated"] = True
            rows.append(row)
    except UnicodeError:
        raise PageRefusal("identity_unrepresentable") from None
    discovery = raw.get("discovery")
    info = discovery.get(agent) if isinstance(discovery, dict) else None
    status = info.get("status") if isinstance(info, dict) else None
    # These are the canonical adapter discovery states. Unknown/older schemas
    # retain rows but cannot claim complete discovery.
    status = status if isinstance(status, str) and status in {"ok", "error", "not_installed"} else "unknown"
    malformed = not isinstance(discovery, dict) or set(discovery) != {agent} or not isinstance(info, dict)
    malformed |= bool(set(raw) - _RAW_KEYS)
    if isinstance(info, dict):
        malformed |= bool(set(info) - _INFO_KEYS.get(agent, _COMMON_EVIDENCE_KEYS))
    for value in (raw, info):
        if isinstance(value, dict):
            malformed |= "truncated" in value and type(value["truncated"]) is not bool
            malformed |= "error" in value and not isinstance(value["error"], str)
            malformed |= "errors" in value and not isinstance(value["errors"], list)
    problems = _reported_problem(raw) or _reported_problem(info)
    truncated = raw.get("truncated") is True or isinstance(info, dict) and info.get("truncated") is True
    # Codex home-level partial/error evidence must not be erased by top-level ok.
    if isinstance(info, dict) and "homes" in info:
        homes = info["homes"]
        if not isinstance(homes, list):
            malformed = True
        else:
            for home in homes:
                if not isinstance(home, dict):
                    malformed = True
                    continue
                home_status = home.get("status")
                malformed |= bool(set(home) - _HOME_KEYS)
                # Canonical Codex discovery emits ok/error/absent. Do not
                # promote missing, malformed or future home evidence to ok.
                malformed |= (not isinstance(home_status, str)
                              or home_status not in ("ok", "error", "absent"))
                malformed |= "error" in home and not isinstance(home["error"], str)
                malformed |= "errors" in home and not isinstance(home["errors"], list)
                malformed |= "truncated" in home and type(home["truncated"]) is not bool
                problems |= _reported_problem(home) or home_status == "error"
                truncated |= home.get("truncated") is True
    # Error arrays are not home records. Any nonempty error list already marks
    # problems above, irrespective of whether its entries have a valid schema.
    incomplete = not raw["ok"] or returncode != 0 or malformed or problems or status not in ("ok", "not_installed")
    evidence = {"sourceOk": raw["ok"], "collectionExitNonzero": returncode != 0,
                "errorPresent": bool(problems), "truncated": bool(truncated),
                "discoveryStatus": status, "incomplete": bool(incomplete),
                "detailProjection": "sanitized_summary_only"}
    return rows, evidence


class ListingPages:
    """One admission slot plus finite snapshots/cursors, shared by this server.

    No awaits occur between checking/claiming admission, or while editing cache
    state. A continuation reads only a previously projected public snapshot.
    """
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.snapshots = OrderedDict()
        self.cursors = {}
        self.charged_bytes = 0
        self.collecting = False

    def _drop(self, key):
        snapshot = self.snapshots.pop(key)
        self.charged_bytes -= snapshot["charge"]
        for token in snapshot["tokens"].values():
            self.cursors.pop(token, None)

    def _expire(self):
        now = self.clock()
        for key, snapshot in list(self.snapshots.items()):
            if now >= snapshot["expires"] or now >= snapshot["absoluteExpires"]:
                self._drop(key)

    @staticmethod
    def binding(destination, agent, inactive, limit, entry):
        # Hash exact effective policy entry, including route and all grants.
        # Neither digest nor private route material is returned or cached.
        digest = hashlib.sha256(serialized(entry)).hexdigest()
        return destination, agent, inactive, limit, digest

    @staticmethod
    def _page(snapshot, offset, limit, token):
        end = min(len(snapshot["rows"]), offset + limit)
        return {"ok": True, "schemaVersion": 1, "command": "mcp.sessions_page", "type": "page",
                "sessions": snapshot["rows"][offset:end], "complete": not snapshot["evidence"]["incomplete"],
                "total": len(snapshot["rows"]), "offset": offset,
                "nextCursor": token if end < len(snapshot["rows"]) else None,
                "evidence": snapshot["evidence"], "retryAllowed": False,
                "limitations": {"callerIdentity": "unavailable", "readiness": "not_checked",
                                "submission": "not_attempted", "consumption": "not_checked", "ack": "not_checked"}}

    async def page(self, arguments, *, authorize, collect, measure, supported=True):
        destination, agent, inactive, limit, cursor = page_arguments(arguments)
        # Authorize before any cursor access, pruning, ledger/cache inspection or
        # subprocess work. Adapter authorization is reused by the integration.
        entry = authorize(destination, agent)
        if not supported:
            raise PageRefusal("platform_unsupported")
        binding = self.binding(destination, agent, inactive, limit, entry)
        self._expire()
        if cursor is not None:
            found = self.cursors.get(cursor)
            if found is None or found[2] != binding:
                raise PageRefusal("cursor_unavailable")
            key, offset, _ = found
            snapshot = self.snapshots.get(key)
            if snapshot is None:
                raise PageRefusal("cursor_unavailable")
        else:
            if self.collecting:
                raise PageRefusal("collection_busy")
            self.collecting = True
            try:
                raw, returncode = await collect(entry, agent, inactive)
                collected_at = self.clock()
                current = authorize(destination, agent)
                if binding != self.binding(destination, agent, inactive, limit, current):
                    raise PageRefusal("policy_changed")
                rows, evidence = project_listing(raw, agent, returncode)
                # Reject an unrepresentable later identity before any earlier
                # page can claim a complete snapshot. Include the real total,
                # row offset and worst-case opaque continuation token size.
                check = {"rows": rows, "evidence": evidence}
                for index in range(len(rows)):
                    single = self._page(check, index, 1, "f" * 64)
                    single["nextCursor"] = "f" * 64
                    if measure(single) > PAGE_OUTPUT_BYTES:
                        raise PageRefusal("identity_unrepresentable")
                public = serialized({"rows": rows, "evidence": evidence})
                # Charge exact public serialized state plus a bounded allowance
                # per possible cursor (one per row), not an RSS estimate.
                charge = len(public) + max(1, len(rows)) * 256
                if charge > PAGE_CACHE_BYTES:
                    raise PageRefusal("snapshot_cache_limit")
                while self.snapshots and (len(self.snapshots) >= PAGE_CACHE_COUNT
                        or self.charged_bytes + charge > PAGE_CACHE_BYTES):
                    self._drop(next(iter(self.snapshots)))
                key = secrets.token_hex(32)
                snapshot = {"rows": rows, "evidence": evidence, "charge": charge,
                            "expires": collected_at + PAGE_TTL_SECONDS,
                            "absoluteExpires": collected_at + PAGE_MAX_LIFETIME_SECONDS, "tokens": {}}
                self.snapshots[key] = snapshot
                self.charged_bytes += charge
                offset = 0
            finally:
                self.collecting = False
        # Pin all filters including limit. Replayed cursors return the same page
        # and next token, with no cache growth on repeated identical requests.
        count = min(limit, len(snapshot["rows"]) - offset)
        while True:
            end = offset + count
            token = snapshot["tokens"].get(end) or secrets.token_hex(32)
            value = self._page(snapshot, offset, count, token)
            if measure(value) <= PAGE_OUTPUT_BYTES:
                break
            if count <= 1:
                self._drop(key)
                raise PageRefusal("identity_unrepresentable")
            count -= 1
        now = self.clock()
        if now >= snapshot["expires"] or now >= snapshot["absoluteExpires"]:
            self._drop(key)
            raise PageRefusal("cursor_unavailable")
        if value["nextCursor"]:
            snapshot["tokens"][end] = token
            self.cursors[token] = key, end, binding
        if cursor is not None:
            # Only a successfully authorized and formed continuation renews
            # idle time; activity can never extend the absolute lifetime.
            snapshot["expires"] = min(now + PAGE_TTL_SECONDS, snapshot["absoluteExpires"])
        return value
