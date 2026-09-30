"""Local-only opt-in proof of concept; not part of the installed CLI.

Requires exclusive control of a dedicated test session: turn/start can steer
if another caller wins the idle check race. Never use against a working session.
"""
import argparse
import json
import os
import stat
import sys
import time
import uuid
from pathlib import Path


class Refused(Exception):
    pass


class Unknown(Exception):
    pass


class RpcRejected(Refused):
    def __init__(self, method, code):
        super().__init__("rpc_rejected:" + method)
        self.code = code


class Rpc:
    MAX_FRAME = 1024 * 1024

    def __init__(self, path, timeout=10):
        self.path = Path(path)
        self.timeout = timeout
        self.socket = None
        self.buffer = b""
        self.sequence = 0
        self.notifications = []

    def __enter__(self):
        if not self.path.is_absolute():
            raise Refused("absolute_socket_required")
        parent = self.path.parent.stat()
        link = self.path.lstat()
        if link.st_uid != os.getuid():
            raise Refused("socket_not_owned")
        resolved = self.path.resolve(strict=True)
        value = resolved.lstat()
        if not stat.S_ISSOCK(value.st_mode) or value.st_uid != os.getuid():
            raise Refused("socket_not_owned")
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise Refused("private_socket_directory_required")
        resolved_parent = resolved.parent.stat()
        if resolved_parent.st_uid != os.getuid() or resolved_parent.st_mode & 0o077:
            raise Refused("private_socket_directory_required")
        try:
            from websockets.sync.client import unix_connect
        except ImportError as exc:
            raise Refused("websockets_dependency_missing") from exc
        # Codex's local control socket carries WebSocket frames, not JSONL.
        # Connect to the named server; never bootstrap a daemon.
        self.connection = unix_connect(str(resolved), open_timeout=self.timeout,
                                       close_timeout=1, max_size=self.MAX_FRAME)
        try:
            self.socket = self.connection.__enter__()
        except Exception as exc:
            raise Refused("connection_or_protocol_failed") from exc
        try:
            self.info = self.call("initialize", {
                "clientInfo": {"name": "session_peer_side_experiment",
                               "title": "session-peer side experiment", "version": "0.0.0"},
                "capabilities": {"experimentalApi": True},
            })
            if not self.info.get("userAgent", "").startswith("codex-tui/0.159.2 "):
                raise Refused("unsupported_server_version")
            self.write({"method": "initialized"})
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *args):
        self.connection.__exit__(*args if args else (None, None, None))

    def write(self, message):
        frame = json.dumps(message, ensure_ascii=False)
        if len(frame.encode("utf-8")) > self.MAX_FRAME:
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
        message = json.loads(frame)
        if not isinstance(message, dict):
            raise Refused("invalid_rpc_response")
        return message

    def call(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.write({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            message = self.read(deadline)
            if message.get("id") == request_id:
                if "error" in message:
                    # Never expose provider errors, transcript content or paths.
                    raise RpcRejected(method, message["error"].get("code"))
                result = message.get("result")
                if not isinstance(result, dict):
                    raise Refused("invalid_rpc_response")
                return result
            if "id" in message:
                raise Refused("server_interaction_required")
            if len(self.notifications) >= 100:
                raise Refused("notification_limit")
            self.notifications.append(message)


def loaded_ids(rpc):
    ids = []
    cursor = None
    for _ in range(32):
        params = {"limit": 100}
        if cursor is not None:
            params["cursor"] = cursor
        result = rpc.call("thread/loaded/list", params)
        data = result.get("data")
        if not isinstance(data, list) or any(not isinstance(x, str) for x in data):
            raise Refused("invalid_loaded_list")
        ids.extend(data)
        next_cursor = result.get("nextCursor")
        if next_cursor is None:
            return ids
        if not isinstance(next_cursor, str) or next_cursor == cursor:
            raise Refused("invalid_cursor")
        cursor = next_cursor
    raise Refused("inventory_limit")


def target_info(rpc, target):
    try:
        thread_id = str(uuid.UUID(target.removeprefix("codex:")))
    except ValueError as exc:
        raise Refused("full_thread_uuid_required") from exc
    if thread_id not in loaded_ids(rpc):
        raise Refused("target_not_loaded")
    thread = rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False}).get("thread")
    if not isinstance(thread, dict) or thread.get("id") != thread_id:
        raise Refused("target_mismatch")
    if thread.get("ephemeral") is not True:
        raise Refused("ephemeral_target_required")
    status = thread.get("status")
    if not isinstance(status, dict) or status.get("type") != "idle":
        raise Refused("target_not_idle")
    if thread.get("canAcceptDirectInput") is not True:
        raise Refused("direct_input_unverified")
    return thread_id


def send(rpc, target, text, *, dry_run=False, exclusive=False):
    if not exclusive:
        raise Refused("exclusive_test_session_required")
    if not text or "\x00" in text or len(text.encode("utf-8")) > 65536:
        raise Refused("invalid_message")
    thread_id = target_info(rpc, target)
    result = {"schemaVersion": 1, "ok": True, "experimental": True,
              "transport": "codex-live-app-server", "submitted": False,
              "consumptionConfirmed": False, "dryRun": dry_run}
    if dry_run:
        result["status"] = "validated"
        return result
    # No resume, fork, policy override, fallback, queue write, or retry.
    # This is NOT atomic idle-only submission; see the module's scope warning.
    try:
        started = rpc.call("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
            "clientUserMessageId": str(uuid.uuid4()),
        })
    except RpcRejected as exc:
        if exc.code in (-32600, -32601):
            raise
        raise Unknown("submission_outcome_unknown") from exc
    except (OSError, ValueError, TimeoutError, Refused) as exc:
        raise Unknown("submission_outcome_unknown") from exc
    turn = started.get("turn")
    if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
        raise Unknown("submission_response_invalid")
    result.update(status="accepted", submitted=True, turnId=turn["id"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experimental-side-session", action="store_true", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--timeout", type=float, default=10)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    sending = commands.add_parser("send")
    sending.add_argument("--to", required=True)
    sending.add_argument("--message", required=True)
    sending.add_argument("--dry-run", action="store_true")
    sending.add_argument("--exclusive-test-session", action="store_true")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 30:
        parser.error("timeout must be greater than 0 and at most 30")
    try:
        with Rpc(args.socket, args.timeout) as rpc:
            if args.command == "list":
                rows = []
                for thread_id in loaded_ids(rpc):
                    t = rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
                    if t.get("ephemeral") is True:
                        rows.append({"id": thread_id, "ephemeral": True, "kind": "ephemeral_unclassified",
                                     "status": t.get("status", {}).get("type"),
                                     "canAcceptDirectInput": t.get("canAcceptDirectInput")})
                result = {"schemaVersion": 1, "ok": True, "experimental": True, "sessions": rows}
            else:
                text = sys.stdin.read(65537) if args.message == "-" else args.message
                result = send(rpc, args.to, text, dry_run=args.dry_run,
                              exclusive=args.exclusive_test_session)
        code = 0
    except Unknown as exc:
        result = {"ok": False, "status": "unknown", "submitted": None,
                  "consumptionConfirmed": False, "reason": str(exc), "retryAllowed": False}
        code = 1
    except (Refused, OSError, ValueError) as exc:
        result = {"ok": False, "status": "refused", "submitted": False,
                  "consumptionConfirmed": False,
                  "reason": str(exc) if isinstance(exc, Refused) else "connection_or_protocol_failed"}
        code = 1
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
