"""Actual native Codex + loopback synthetic SSE provider; no account credentials.

First response gates prove ordering, not real-model latency/ACK. Stops on first
assertion failure. Fixture-created homes/sockets are temporary and private.
"""
import argparse
import contextlib
import http.server
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from steer import Rpc, Refused, Rejected, pages, steer


class Provider:
    def __init__(self):
        self.release = threading.Event()
        self.second = threading.Event()
        self.lock = threading.Lock()
        self.requests = []
        self.second_at = None
        self.started_at = time.monotonic()
        self.unexpected_paths = 0
        provider = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                if self.path != "/v1/responses":
                    provider.unexpected_paths += 1
                    self.send_error(404)
                    return
                n = int(self.headers.get("Content-Length", "0"))
                assert 0 < n < 4 * 1024 * 1024
                data = self.rfile.read(n)
                if self.headers.get("Content-Encoding") == "zstd":
                    raise RuntimeError("fixture needs compression disabled")
                payload = json.loads(data)
                # Only synthetic marker booleans are retained; no request dump.
                rendered = json.dumps(payload.get("input", []))
                with provider.lock:
                    number = len(provider.requests) + 1
                    provider.requests.append({"newInput": "UPDATE-STEER247" in rendered,
                                              "rejectedInput": "MUST-NOT-ACCEPT-247" in rendered})
                    if number == 2:
                        provider.second_at = time.monotonic()
                        provider.second.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

                def emit(value):
                    self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
                    self.wfile.flush()

                try:
                    emit({"type": "response.created", "response": {"id": f"resp-{number}"}})
                    if number == 1:
                        emit({"type": "response.output_item.added", "item": {
                            "type": "message", "role": "assistant", "id": "initial-msg",
                            "content": [{"type": "output_text", "text": ""}]}})
                        emit({"type": "response.output_text.delta", "delta": "ORIGINAL-PREFIX"})
                        if not provider.release.wait(40):
                            return
                    message = "ORIGINAL-FINISHED" if number == 1 else "SYNTHETIC-UPDATED-RESPONSE"
                    emit({"type": "response.output_item.done", "item": {
                        "type": "message", "role": "assistant", "id": f"msg-{number}",
                        "content": [{"type": "output_text", "text": message}]}})
                    emit({"type": "response.completed", "response": {
                        "id": f"resp-{number}", "usage": {
                            "input_tokens": 1, "input_tokens_details": None,
                            "output_tokens": 1, "output_tokens_details": None, "total_tokens": 2}}})
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Expected when ON steering preempts the initial stream.

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()


def kill_owned(process):
    # Keep the leader PID unreaped through group cleanup, never reuse an old pgid.
    for sig, grace in ((signal.SIGTERM, 0.2), (signal.SIGKILL, 0)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS reports EPERM for groups containing only zombies. Do not
            # ignore denial while any member is still running.
            members = subprocess.run(["ps", "-o", "stat=", "-g", str(process.pid)],
                                     capture_output=True, text=True, timeout=3)
            if sys.platform != "darwin" or members.returncode not in (0, 1) or any(
                    line.strip() and not line.strip().startswith("Z") for line in members.stdout.splitlines()):
                raise
        if grace:
            time.sleep(grace)
    process.wait(timeout=5)
    check = subprocess.run(["ps", "-o", "stat=", "-g", str(process.pid)],
                           capture_output=True, text=True, timeout=3)
    assert check.returncode in (0, 1)
    assert not any(line.strip() and not line.strip().startswith("Z") for line in check.stdout.splitlines())


def run_case(executable, root, mode, enabled):
    t0 = time.monotonic()
    case = root / (mode + ("-on" if enabled else "-off"))
    case.mkdir(mode=0o700)
    home, cwd = case / "home", case / "cwd"
    home.mkdir(mode=0o700)
    cwd.mkdir(mode=0o700)
    sock = case / "app.sock"
    provider = Provider()
    port = provider.server.server_address[1]
    # This configuration is generated fixture state. It contains no credentials.
    config = f'''model = "gpt-6.1-sol"
model_provider = "local_fixture"
sandbox_mode = "read-only"
approval_policy = "on-request"
[analytics]
enabled = false
[features]
instant_interrupt = {str(enabled).lower()}
enable_request_compression = false
[model_providers.local_fixture]
name = "Loopback synthetic fixture"
base_url = "http://127.0.0.1:{port}/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
'''
    (home / "config.toml").write_text(config)
    (home / "config.toml").chmod(0o600)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")}
    env["CODEX_HOME"] = str(home)
    process = None
    physical = None
    deadline_hit = threading.Event()
    watchdog_done = threading.Event()

    def watchdog():
        if not watchdog_done.wait(45) and process is not None:
            deadline_hit.set()
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)

    watcher = threading.Thread(target=watchdog, daemon=True)
    watcher.start()
    try:
        process = subprocess.Popen([executable, "app-server", "--listen", "unix://" + str(sock)],
                                   cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        deadline = t0 + 15
        while not sock.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("fixture_native_startup_deadline")
            time.sleep(0.05)
        physical = sock.resolve()
        observer = Rpc(sock, timeout=10)
        with observer:
            target = observer.call("thread/start", {
                "cwd": str(cwd), "model": "gpt-6.1-sol", "sandbox": "read-only",
                "approvalPolicy": "on-request", "ephemeral": False,
            })["thread"]["id"]
            turn = observer.call("turn/start", {"threadId": target,
                "input": [{"type": "text", "text": "INITIAL-STEER247 synthetic protocol scenario"}]})["turn"]["id"]
            observer.wait_event(lambda e: e.get("method") == "item/agentMessage/delta"
                                and "ORIGINAL-PREFIX" in e.get("params", {}).get("delta", ""))
            with Rpc(sock, timeout=10) as sender:
                flag_rows = list(pages(sender, "experimentalFeature/list", {"threadId": target}))
                flag = next(f["enabled"] for f in flag_rows if f["name"] == "instant_interrupt")
                assert flag is enabled, "feature_snapshot_mismatch"
                for target_id, home_path in ((target, str(home) + "-wrong"),
                                            ("00000000-0000-4000-8000-000000000001", str(home))):
                    try:
                        steer(sender, target_id, turn, "MUST-NOT-ACCEPT-247",
                              expected_home=home_path, opt_in=True)
                    except Refused:
                        pass
                    else:
                        raise AssertionError("identity_guard_failed")
                if not enabled:
                    try:
                        steer(sender, target, turn, "MUST-NOT-ACCEPT-247", expected_home=str(home),
                              opt_in=True, require_instant=True)
                    except Refused:
                        pass
                    else:
                        raise AssertionError("disabled_instant_accepted")
                # Wrong expected turn must reject before any input; no retry.
                try:
                    sender.call("turn/steer", {"threadId": target, "expectedTurnId": "wrong-turn-id",
                        "input": [{"type": "text", "text": "MUST-NOT-ACCEPT-247"}]})
                except Rejected as exc:
                    assert exc.code == -32600
                else:
                    raise AssertionError("wrong_turn_accepted")
                submitted_at = time.monotonic()
                if mode == "steer":
                    result = steer(sender, target, turn, "UPDATE-STEER247 synthetic direction change",
                                   expected_home=str(home), opt_in=True, require_instant=enabled)
                    assert result["submitted"] and not result["consumptionConfirmed"]
                    assert result["turnId"] == turn
                else:
                    sender.call("thread/queue/add", {"threadId": target,
                        "clientUserMessageId": str(__import__("uuid").uuid4()),
                        "input": [{"type": "text", "text": "UPDATE-STEER247 synthetic queued follow-up"}]})
                before_release = provider.second.wait(5 if mode == "steer" and enabled else 0.75)
                expected = mode == "steer" and enabled
                assert before_release is expected, "preemption_gate_mismatch"
                provider.release.set()
                assert provider.second.wait(10), "updated_request_missing"
                observer.wait_event(lambda e: e.get("method") == "item/completed"
                    and e.get("params", {}).get("item", {}).get("text") == "SYNTHETIC-UPDATED-RESPONSE", timeout=10)
                done = observer.wait_event(lambda e: e.get("method") == "turn/completed"
                    and e.get("params", {}).get("turn", {}).get("status") == "completed"
                    and (mode == "queue" or e.get("params", {}).get("turn", {}).get("id") == turn), timeout=10)
                completion_turn = done["params"]["turn"]["id"]
                if mode == "queue" and completion_turn == turn:
                    done = observer.wait_event(lambda e: e.get("method") == "turn/completed"
                        and e.get("params", {}).get("turn", {}).get("id") != turn, timeout=10)
                    completion_turn = done["params"]["turn"]["id"]
                assert (completion_turn == turn) is (mode == "steer")
                assert provider.requests == [{"newInput": False, "rejectedInput": False},
                                             {"newInput": True, "rejectedInput": False}]
                assert provider.unexpected_paths == 0
                # Completed turn refuses steering; there is no queued fallback.
                try:
                    steer(sender, target, completion_turn, "DO-NOT-SEND-AFTER-COMPLETION",
                          expected_home=str(home), opt_in=True)
                except Refused:
                    pass
                else:
                    raise AssertionError("idle_steer_accepted")
                assert len(provider.requests) == 2
            result = {"mode": mode, "instantInterrupt": enabled, "pass": True,
                      "secondRequestBeforeRelease": before_release,
                      "secondRequestAfterSubmitMs": round((provider.second_at - submitted_at) * 1000, 2),
                      "sameTurn": completion_turn == turn, "modelRequests": len(provider.requests),
                      "syntheticResponseObserved": True, "wrongTurnRejected": True,
                      "idleRejected": True, "homeMismatchRejected": True,
                      "missingTargetRejected": True, "elapsedMs": round((time.monotonic() - t0) * 1000, 2)}
        return result
    except Refused as exc:
        if str(exc) == "unsupported_server_version" and hasattr(observer, "info"):
            brand = observer.info.get("userAgent", "").split(" ", 1)[0]
            print(json.dumps({"fixtureSetupFailed": True, "nativeBrand": brand}), flush=True)
        raise
    finally:
        provider.release.set()
        watchdog_done.set()
        watcher.join(timeout=2)
        try:
            if process is not None:
                kill_owned(process)
        finally:
            provider.close()
            if physical is not None:
                # Exact unique test-created socket/lock, never its shared parent.
                for path in (physical, Path(str(physical) + ".lock")):
                    if path.exists() and path.stat().st_uid == os.getuid():
                        path.unlink()
            if sock.is_symlink() or sock.exists():
                sock.unlink()
        assert not deadline_hit.is_set(), "batch_deadline_hit"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-native-fixture", action="store_true", required=True)
    p.add_argument("--temp-root", required=True)
    p.add_argument("--repetitions", type=int, default=1, choices=range(1, 6))
    args = p.parse_args()
    executable = shutil.which("codex")
    version = subprocess.check_output([executable, "--version"], text=True).strip()
    if version != "codex-cli 0.159.2":
        raise RuntimeError("unsupported_fixture_version")
    # tempfile is strictly within the operator-selected approved scratch root.
    with tempfile.TemporaryDirectory(prefix="codex-steer247-", dir=args.temp_root) as tmp:
        root = Path(tmp)
        for repetition in range(1, args.repetitions + 1):
            repeat_root = root / str(repetition)
            repeat_root.mkdir(mode=0o700)
            for mode, enabled in (("queue", False), ("queue", True), ("steer", False), ("steer", True)):
                print(json.dumps(dict(run_case(executable, repeat_root, mode, enabled),
                                      repetition=repetition)), flush=True)
    print(json.dumps({"complete": True, "nativeVersion": version, "cases": 4 * args.repetitions,
                      "temporaryHomesRemoved": True, "credentialsUsed": False}), flush=True)


if __name__ == "__main__":
    main()
