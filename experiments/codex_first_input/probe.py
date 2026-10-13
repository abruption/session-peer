"""One-shot first-input probe for an exclusively owned Codex app server.

Requires websockets 17.x. Never starts a server or retries a submission.
Prints sanitized facts, not conversation IDs, paths, or native text.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid

from websockets.sync.client import unix_connect


class ProbeError(Exception):
    """Sanitized protocol/precondition failure, without native response text."""


def rpc_result(response):
    if "error" in response:
        error = response["error"]
        if not isinstance(error, dict) or type(error.get("code")) is not int:
            raise ProbeError("invalid_rpc_error")
        raise ProbeError("rpc_rejected")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ProbeError("invalid_rpc_result")
    return result


def main(argv=None, state=None):
    if state is None:
        state = {"attempted": False, "accepted": None}
    if not __debug__:
        raise ProbeError("optimization_not_supported")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--expected-cwd", required=True)
    parser.add_argument("--mode", choices=("inspect", "queue"), default="inspect")
    parser.add_argument("--ack-marker", help="Harmless ASCII test receipt marker; no credentials")
    args = parser.parse_args(argv)
    if args.ack_marker is not None and not re.fullmatch(r"[A-Za-z0-9 _-]{1,100}", args.ack_marker):
        parser.error("invalid ACK marker")
    codex_home = Path(args.codex_home).resolve(strict=True)
    socket = Path(args.socket)
    assert socket.lstat().st_uid == os.getuid()
    assert socket.parent.stat().st_mode & 0o077 == 0
    socket = socket.resolve(strict=True)
    st = socket.lstat()
    assert stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()
    assert socket.parent.stat().st_mode & 0o077 == 0
    sequence = 0
    with unix_connect(str(socket), open_timeout=5, close_timeout=1, max_size=1048576) as ws:
        def call(method, params):
            nonlocal sequence
            sequence += 1
            request = json.dumps({"id": sequence, "method": method, "params": params})
            if method == "thread/queue/add":
                # An exception from send cannot prove that no bytes reached the server.
                state["attempted"] = True
            ws.send(request)
            deadline = time.monotonic() + 15
            for _ in range(200):
                message = json.loads(ws.recv(timeout=max(.01, deadline-time.monotonic())))
                if not isinstance(message, dict):
                    raise ProbeError("invalid_rpc_response")
                if message.get("id") == sequence:
                    if ("error" in message) == ("result" in message):
                        raise ProbeError("invalid_rpc_response")
                    return message
                if "id" in message:
                    raise RuntimeError("unexpected server interaction; no approval supplied")
            raise RuntimeError("notification limit")
        hello = call("initialize", {"clientInfo": {"name": "session-peer-first-input-probe", "version": "0"}, "capabilities": {"experimentalApi": True}})
        initialized = rpc_result(hello)
        assert initialized["userAgent"].startswith("codex-tui/0.162.1 ")
        server_home = initialized.get("codexHome")
        if not isinstance(server_home, str) or not server_home or not Path(server_home).is_absolute():
            raise ProbeError("missing_or_invalid_server_home")
        try:
            bound_home = Path(server_home).resolve(strict=True)
        except (OSError, ValueError):
            raise ProbeError("missing_or_invalid_server_home") from None
        if bound_home != codex_home:
            raise ProbeError("server_home_mismatch")
        ws.send(json.dumps({"method": "initialized"}))
        loaded = rpc_result(call("thread/loaded/list", {"limit": 100}))
        assert loaded.get("nextCursor") is None and len(loaded["data"]) == 1
        thread_id = loaded["data"][0]
        thread = rpc_result(call("thread/read", {"threadId": thread_id, "includeTurns": False}))["thread"]
        assert Path(thread["cwd"]).resolve() == Path(args.expected_cwd).resolve()
        assert thread["status"]["type"] == "idle" and thread["canAcceptDirectInput"] is True
        ephemeral = thread.get("ephemeral")
        if ephemeral is not None and type(ephemeral) is not bool:
            raise ProbeError("invalid_thread_metadata")
        rows = 0
        dbs = list(codex_home.glob("state_*.sqlite"))
        assert dbs
        for db in dbs:
            with closing(sqlite3.connect(db.as_uri()+"?mode=ro", uri=True)) as connection:
                rows += connection.execute("SELECT count(*) FROM threads WHERE id=?", (thread_id,)).fetchone()[0]
        facts = {"version": "0.162.1", "loadedThreads": 1, "storedRowsBefore": rows, "idle": True, "directInput": True, "ephemeral": ephemeral, "mode": args.mode}
        print(json.dumps(facts), flush=True)
        if args.mode == "inspect":
            return 0
        assert rows == 0, "requires fresh pre-first-input thread"
        marker = args.ack_marker or "ACK CODEX-FIRST-INPUT-306-" + args.mode.upper()
        message = "Owner-authorized one-shot transport test. Reply exactly " + marker + ". Do not run tools or modify files."
        method = "thread/queue/add"
        result = call(method, {"threadId": thread_id, "input": [{"type": "text", "text": message}], "clientUserMessageId": str(uuid.uuid4())})
        if "error" in result:
            error = result["error"]
            if not isinstance(error, dict) or type(error.get("code")) is not int:
                raise ProbeError("invalid_rpc_error")
            state["accepted"] = False
            print(json.dumps({"method": method, "accepted": False, "errorCode": error["code"], "retryAllowed": False}), flush=True)
            return 1
        else:
            queued = rpc_result(result)
            if "queuedSubmission" not in queued:
                raise ProbeError("invalid_queue_result")
            state["accepted"] = True
            print(json.dumps({"method": method, "accepted": True, "consumptionConfirmed": False}), flush=True)
            return 0


def run(argv=None):
    state = {"attempted": False, "accepted": None}
    try:
        return main(argv, state)
    except KeyboardInterrupt:
        report_failure(state, "interrupted")
        return 130
    except Exception as exc:
        # Do not reflect paths, server messages, JSON fragments, or exception text.
        report_failure(state, str(exc) if isinstance(exc, ProbeError) else "probe_failed")
        return 1


def report_failure(state, error):
    accepted = state["accepted"] if state["attempted"] else False
    outcome = ("unknown" if accepted is None else
               "accepted" if accepted else "rejected" if state["attempted"] else "not_attempted")
    print(json.dumps({"accepted": accepted, "outcome": outcome, "error": error,
                      "retryAllowed": False}), flush=True)


if __name__ == "__main__":
    raise SystemExit(run())
