"""Opt-in local steering prototype (#247), excluded from installed packages.

This connects to an existing owner; it never starts/resumes a destination,
enables a feature, cancels a turn, answers approvals, queues or retries input.
"""
import argparse
import json
import os
import re
import stat
import sys
import time
import uuid
from pathlib import Path


class Refused(Exception):
    pass


class Unknown(Exception):
    pass


class Rejected(Refused):
    def __init__(self, method, code):
        super().__init__("rpc_rejected:" + method)
        self.code = code


class Rpc:
    LIMIT = 1024 * 1024

    def __init__(self, path, timeout=10):
        self.path, self.timeout = Path(path), timeout
        self.sequence = 0
        self.events = []

    def __enter__(self):
        if not self.path.is_absolute():
            raise Refused("absolute_socket_required")
        original = self.path.lstat()
        resolved = self.path.resolve(strict=True)
        target = resolved.lstat()
        if original.st_uid != os.getuid() or target.st_uid != os.getuid() or not stat.S_ISSOCK(target.st_mode):
            raise Refused("owned_socket_required")
        if target.st_mode & 0o077:
            raise Refused("private_socket_required")
        for parent in (self.path.parent, resolved.parent):
            value = parent.stat()
            if value.st_uid != os.getuid() or value.st_mode & 0o077:
                raise Refused("private_directory_required")
        try:
            from websockets.sync.client import unix_connect
        except ImportError as exc:
            raise Refused("websockets_dependency_missing") from exc
        self.connection = unix_connect(str(resolved), open_timeout=self.timeout,
                                       close_timeout=1, max_size=self.LIMIT)
        try:
            self.socket = self.connection.__enter__()
        except Exception as exc:
            raise Refused("connection_failed") from exc
        try:
            self.info = self.call("initialize", {
                "clientInfo": {"name": "session_peer_steer_experiment", "version": "0.0.0"},
                "capabilities": {"experimentalApi": True},
            })
            if not re.match(r"(?:codex-tui|codex_cli_rs|codex-cli|session_peer_steer_experiment)/0\.159\.2(?:\s|$)", self.info.get("userAgent", "")):
                raise Refused("unsupported_server_version")
            self.write({"method": "initialized"})
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        self.connection.__exit__(*args)

    def write(self, value):
        frame = json.dumps(value, ensure_ascii=False)
        if len(frame.encode("utf-8")) > self.LIMIT:
            raise Refused("frame_too_large")
        try:
            self.socket.send(frame)
        except Exception as exc:
            raise ConnectionError("transport_closed") from exc

    def read(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        try:
            frame = self.socket.recv(timeout=remaining)
        except TimeoutError:
            raise
        except Exception as exc:
            raise ConnectionError("transport_closed") from exc
        if not isinstance(frame, str):
            raise Refused("invalid_frame")
        value = json.loads(frame)
        if not isinstance(value, dict):
            raise Refused("invalid_rpc_response")
        return value

    def call(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.write({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            value = self.read(deadline)
            if value.get("id") == request_id:
                if "error" in value:
                    raise Rejected(method, value["error"].get("code"))
                if not isinstance(value.get("result"), dict):
                    raise Refused("invalid_rpc_response")
                return value["result"]
            if "id" in value:
                raise Refused("server_interaction_required")
            if len(self.events) >= 2000:
                raise Refused("event_limit")
            self.events.append(value)

    def wait_event(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while True:
            for index, event in enumerate(self.events):
                if predicate(event):
                    return self.events.pop(index)
            event = self.read(deadline)
            if "id" in event:
                raise Refused("server_interaction_required")
            if predicate(event):
                return event
            if len(self.events) >= 2000:
                raise Refused("event_limit")
            self.events.append(event)


def pages(rpc, method, params):
    cursor = None
    for _ in range(32):
        query = dict(params, limit=100)
        if cursor is not None:
            query["cursor"] = cursor
        result = rpc.call(method, query)
        if not isinstance(result.get("data"), list):
            raise Refused("invalid_inventory")
        yield from result["data"]
        next_cursor = result.get("nextCursor")
        if next_cursor is None:
            return
        if not isinstance(next_cursor, str) or next_cursor == cursor:
            raise Refused("invalid_cursor")
        cursor = next_cursor
    raise Refused("inventory_limit")


def steer(rpc, target, turn_id, text, *, expected_home, opt_in=False,
          require_instant=False, dry_run=False):
    if not opt_in:
        raise Refused("steering_opt_in_required")
    if not isinstance(turn_id, str) or not turn_id.strip() or len(turn_id) > 128:
        raise Refused("expected_turn_required")
    if not text or "\x00" in text or len(text.encode("utf-8")) > 65536:
        raise Refused("invalid_message")
    try:
        thread_id = str(uuid.UUID(target.removeprefix("codex:")))
    except ValueError as exc:
        raise Refused("full_thread_uuid_required") from exc
    actual_home = rpc.info.get("codexHome")
    if not expected_home or not isinstance(actual_home, str) or Path(actual_home).resolve() != Path(expected_home).resolve():
        raise Refused("server_home_mismatch")
    if thread_id not in list(pages(rpc, "thread/loaded/list", {})):
        raise Refused("target_not_loaded")
    thread = rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False}).get("thread")
    if not isinstance(thread, dict) or thread.get("id") != thread_id:
        raise Refused("thread_mismatch")
    status = thread.get("status")
    if not isinstance(status, dict) or status.get("type") != "active":
        raise Refused("target_not_active")
    if status.get("activeFlags"):
        raise Refused("active_interaction_pending")
    if thread.get("canAcceptDirectInput") is not True:
        raise Refused("direct_input_unverified")
    flag = next((f.get("enabled") for f in pages(rpc, "experimentalFeature/list", {"threadId": thread_id})
                 if isinstance(f, dict) and f.get("name") == "instant_interrupt"), None)
    if flag is not True and flag is not False:
        flag = None
    if require_instant and flag is not True:
        raise Refused("instant_interrupt_not_enabled_or_verified")
    result = {"schemaVersion": 1, "ok": True, "experimental": True, "mode": "steer",
              "submitted": False, "consumptionConfirmed": False, "dryRun": dry_run,
              "instantInterruptEnabledSnapshot": flag,
              "status": "validated" if dry_run else "accepted"}
    if dry_run:
        # Native expectedTurnId is checked only on submission; do not pretend
        # that this metadata-only dry-run proves it is the current turn.
        result["expectedTurnValidated"] = False
        return result
    try:
        accepted = rpc.call("turn/steer", {
            "threadId": thread_id, "expectedTurnId": turn_id,
            "input": [{"type": "text", "text": text}],
            "clientUserMessageId": str(uuid.uuid4()),
        })
    except Rejected as exc:
        if exc.code in (-32600, -32601):
            raise
        raise Unknown("submission_outcome_unknown") from exc
    except (OSError, ValueError, Refused) as exc:
        raise Unknown("submission_outcome_unknown") from exc
    if accepted.get("turnId") != turn_id:
        raise Unknown("returned_turn_mismatch")
    return dict(result, submitted=True, turnId=turn_id)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experimental-steering", action="store_true", required=True)
    p.add_argument("--socket", required=True)
    p.add_argument("--expected-home", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--expected-turn-id", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--require-instant", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    try:
        text = sys.stdin.read(65537) if args.message == "-" else args.message
        with Rpc(args.socket) as rpc:
            result = steer(rpc, args.to, args.expected_turn_id, text,
                           expected_home=args.expected_home, opt_in=True,
                           require_instant=args.require_instant, dry_run=args.dry_run)
        code = 0
    except Unknown as exc:
        result = {"ok": False, "submitted": None, "status": "unknown",
                  "reason": str(exc), "retryAllowed": False}
        code = 1
    except (Refused, OSError, ValueError) as exc:
        result = {"ok": False, "submitted": False, "status": "refused",
                  "reason": str(exc) if isinstance(exc, Refused) else "connection_failed"}
        code = 1
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
