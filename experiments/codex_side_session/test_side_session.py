import json
import io
import os
import stat
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from side_session import Refused, Rpc, RpcRejected, Unknown, loaded_ids, send, main


TARGET = "00000000-0000-4000-8000-000000000001"


class Fake:
    def __init__(self, ephemeral=True, status="idle", direct=True, loaded=True, fail=None):
        self.calls = []
        self.ephemeral, self.status, self.direct, self.loaded, self.fail = ephemeral, status, direct, loaded, fail

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": [TARGET] if self.loaded else [], "nextCursor": None}
        if method == "thread/read":
            return {"thread": {"id": TARGET, "ephemeral": self.ephemeral,
                               "status": {"type": self.status}, "canAcceptDirectInput": self.direct}}
        if self.fail:
            raise self.fail
        return {"turn": {"id": "test-turn"}}


class FrameSocket:
    """In-memory JSON frames through the real RPC parser; no server or model."""

    def __init__(self, method, error, both=False):
        self.method, self.error = method, error
        self.both = both
        self.calls = []

    def send(self, frame):
        request = json.loads(frame)
        self.calls.append(request)
        result = Fake().call(request["method"], request["params"])
        self.response = {"id": request["id"], "result": result}
        if request["method"] == self.method:
            if not self.both:
                del self.response["result"]
            self.response["error"] = self.error

    def recv(self, timeout):
        return json.dumps(self.response)


class RpcResponseContract(unittest.TestCase):
    malformed_errors = (None, [], "private provider detail", {}, {"code": None},
                        {"code": True}, {"code": False}, {"code": -32600.0},
                        {"code": "-32600"}, {"code": []}, {"code": {}},
                        {"code": -32600}, {"code": -32600, "message": None},
                        {"code": -32600, "message": {"private": "detail"}})

    def rpc(self, method, error):
        rpc = Rpc("/unused-fixture.sock")
        rpc.socket = FrameSocket(method, error)
        return rpc

    def test_malformed_error_before_submission_is_refused(self):
        for error in self.malformed_errors:
            with self.subTest(error=error):
                rpc = self.rpc("thread/loaded/list", error)
                with self.assertRaisesRegex(Refused, "^invalid_rpc_response$") as raised:
                    send(rpc, TARGET, "hello", exclusive=True)
                self.assertIs(type(raised.exception), Refused)
                self.assertEqual([r["method"] for r in rpc.socket.calls], ["thread/loaded/list"])

    def test_malformed_error_after_attempt_is_unknown_without_resend(self):
        for error in self.malformed_errors:
            with self.subTest(error=error):
                rpc = self.rpc("turn/start", error)
                with self.assertRaisesRegex(Unknown, "^submission_outcome_unknown$"):
                    send(rpc, TARGET, "hello", exclusive=True)
                self.assertEqual([r["method"] for r in rpc.socket.calls],
                                 ["thread/loaded/list", "thread/read", "turn/start"])

    def test_valid_error_codes_keep_existing_classification(self):
        for code in (-32600, -32601, -32603, 0, 123):
            with self.subTest(code=code):
                rpc = self.rpc("turn/start", {"code": code, "message": "private provider detail"})
                expected = RpcRejected if code in (-32600, -32601) else Unknown
                with self.assertRaises(expected) as raised:
                    send(rpc, TARGET, "hello", exclusive=True)
                self.assertNotIn("private provider detail", str(raised.exception))
                self.assertEqual(sum(r["method"] == "turn/start" for r in rpc.socket.calls), 1)

    def test_absent_error_keeps_successful_result(self):
        rpc = self.rpc("unused", None)
        result = send(rpc, TARGET, "hello", exclusive=True)
        self.assertTrue(result["submitted"])
        self.assertFalse(result["consumptionConfirmed"])

    def test_ambiguous_envelope_never_proves_rejection(self):
        for method in ("thread/loaded/list", "turn/start"):
            rpc = self.rpc(method, {"code": -32600, "message": "private detail"})
            rpc.socket.both = True
            expected = Unknown if method == "turn/start" else Refused
            with self.subTest(method=method), self.assertRaises(expected) as raised:
                send(rpc, TARGET, "hello", exclusive=True)
            self.assertIs(type(raised.exception), expected)
            self.assertNotIn("private detail", str(raised.exception))
            self.assertEqual(sum(r["method"] == "turn/start" for r in rpc.socket.calls),
                             int(method == "turn/start"))

    def test_response_ids_require_exact_integers(self):
        for response_id in (True, 1.0, "1", None):
            rpc = self.rpc("unused", None)
            with patch.object(rpc.socket, "recv", return_value=json.dumps(
                    {"id": response_id, "result": {}})):
                with self.subTest(response_id=response_id), self.assertRaises(Refused):
                    rpc.call("thread/loaded/list", {})

    def test_bad_json_is_refused_before_attempt_and_unknown_after(self):
        for frame in ('{"private detail":', '[' * 2000 + '0' + ']' * 2000):
            for method in ("thread/loaded/list", "turn/start"):
                rpc = self.rpc("unused", None)
                original_recv = rpc.socket.recv
                def recv(timeout):
                    return frame if rpc.socket.calls[-1]["method"] == method else original_recv(timeout)
                with patch.object(rpc.socket, "recv", side_effect=recv):
                    expected = Unknown if method == "turn/start" else Refused
                    with self.subTest(method=method, size=len(frame)), self.assertRaises(expected) as raised:
                        send(rpc, TARGET, "hello", exclusive=True)
                    self.assertNotIn("private detail", str(raised.exception))


class CliContract(unittest.TestCase):
    def run_cli(self, rpc, command):
        output = io.StringIO()
        with patch("side_session.Rpc", return_value=rpc), redirect_stdout(output):
            code = main(["--experimental-side-session", "--socket", "/unused", *command])
        self.assertEqual(code, 1)
        return json.loads(output.getvalue())

    def test_attempted_malformed_response_is_unknown_in_cli(self):
        rpc = Rpc("/unused")
        rpc.socket = FrameSocket("turn/start", {"code": -32600})
        context = MagicMock()
        context.__enter__.return_value = rpc
        result = self.run_cli(context, ["send", "--to", TARGET, "--message", "hello",
                                        "--exclusive-test-session"])
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["submitted"])
        self.assertFalse(result["retryAllowed"])
        self.assertEqual(sum(r["method"] == "turn/start" for r in rpc.socket.calls), 1)

    def test_malformed_discovery_metadata_is_private_refusal(self):
        base = {"id": TARGET, "ephemeral": True, "status": {"type": "idle"}}
        responses = [{}, {"thread": None}, {"thread": "private detail"},
                     *({"thread": {**base, "status": status}} for status in
                       (None, [], "private detail", {}, {"type": {"private": "detail"}})),
                     {"thread": {**base, "canAcceptDirectInput": "private detail"}}]
        for response in responses:
            context = MagicMock()
            context.__enter__.return_value.call.side_effect = [{"data": [TARGET]}, response]
            with self.subTest(response=response):
                result = self.run_cli(context, ["list"])
                self.assertEqual(result["status"], "refused")
                self.assertFalse(result["submitted"])
                self.assertEqual(result["reason"], "invalid_thread_metadata")
                self.assertNotIn("private detail", json.dumps(result))

    def test_malformed_initialize_agent_is_refused(self):
        client = SimpleNamespace(unix_connect=MagicMock())
        for agent in (None, [], {}, 1, True):
            rpc = Rpc("/unused/socket")
            with patch.dict("sys.modules", {"websockets.sync.client": client}), \
                    patch("side_session.Path.stat", return_value=SimpleNamespace(st_uid=os.getuid(), st_mode=0o700)), \
                    patch("side_session.Path.lstat", return_value=SimpleNamespace(st_uid=os.getuid(), st_mode=stat.S_IFSOCK)), \
                    patch("side_session.Path.resolve", return_value=rpc.path), \
                    patch.object(rpc, "call", return_value={"userAgent": agent}):
                with self.subTest(agent=agent), self.assertRaisesRegex(Refused, "^unsupported_server_version$"):
                    rpc.__enter__()

    def test_cleanup_failure_preserves_submission_evidence(self):
        for method, expected_status, expected_submitted in (
                ("unused", "accepted", True),
                ("turn/start", "unknown", None),
                ("thread/loaded/list", "refused", False)):
            rpc = Rpc("/unused")
            rpc.socket = FrameSocket(method, {"code": -32600})
            rpc.connection = MagicMock()
            rpc.connection.__exit__.side_effect = OSError("private cleanup detail")
            output = io.StringIO()
            # Keep the real __exit__ while avoiding all native connections.
            with self.subTest(method=method), \
                    patch.object(Rpc, "__enter__", return_value=rpc), \
                    patch("side_session.Rpc", return_value=rpc), redirect_stdout(output):
                code = main(["--experimental-side-session", "--socket", "/unused",
                             "send", "--to", TARGET, "--message", "hello",
                             "--exclusive-test-session"])
            result = json.loads(output.getvalue())
            self.assertEqual(code, 0 if expected_submitted else 1)
            self.assertEqual(result["status"], expected_status)
            self.assertIs(result["submitted"], expected_submitted)
            self.assertTrue(rpc.close_failed)
            self.assertNotIn("private cleanup detail", output.getvalue())
            self.assertEqual(sum(r["method"] == "turn/start" for r in rpc.socket.calls),
                             0 if method == "thread/loaded/list" else 1)
            if expected_status == "unknown":
                self.assertFalse(result["retryAllowed"])

    def test_cleanup_does_not_swallow_process_interrupts(self):
        for interruption in (KeyboardInterrupt, SystemExit):
            rpc = Rpc("/unused")
            rpc.connection = MagicMock()
            rpc.connection.__exit__.side_effect = interruption()
            with self.subTest(interruption=interruption), self.assertRaises(interruption):
                rpc.__exit__()


class Contract(unittest.TestCase):
    def test_opt_in(self):
        rpc = Fake()
        with self.assertRaisesRegex(Refused, "exclusive"):
            send(rpc, TARGET, "hello")
        self.assertEqual(rpc.calls, [])

    def test_dry_run(self):
        rpc = Fake()
        self.assertFalse(send(rpc, TARGET, "hello", exclusive=True, dry_run=True)["submitted"])
        self.assertNotIn("turn/start", [m for m, _ in rpc.calls])

    def test_accept_not_ack(self):
        rpc = Fake()
        result = send(rpc, "codex:" + TARGET, "hello", exclusive=True)
        self.assertTrue(result["submitted"])
        self.assertFalse(result["consumptionConfirmed"])
        self.assertEqual([m for m, _ in rpc.calls], ["thread/loaded/list", "thread/read", "turn/start"])
        params = rpc.calls[-1][1]
        self.assertEqual(set(params), {"threadId", "input", "clientUserMessageId"})
        self.assertFalse(rpc.calls[1][1]["includeTurns"])

    def test_persistent_refused(self):
        with self.assertRaisesRegex(Refused, "ephemeral"):
            send(Fake(ephemeral=False), TARGET, "hello", exclusive=True)

    def test_busy_refused(self):
        with self.assertRaisesRegex(Refused, "idle"):
            send(Fake(status="active"), TARGET, "hello", exclusive=True)

    def test_unloaded_refused(self):
        with self.assertRaisesRegex(Refused, "not_loaded"):
            send(Fake(loaded=False), TARGET, "hello", exclusive=True)

    def test_loaded_idle_has_no_ui_lifetime_proof(self):
        # Models the live closure finding. This is a documented limitation,
        # not a test claiming that UI-closed destinations are safely refused.
        rpc = Fake(loaded=True, ephemeral=True, status="idle")
        result = send(rpc, TARGET, "hello", exclusive=True, dry_run=True)
        self.assertEqual(result["status"], "validated")
        self.assertNotIn("turn/start", [m for m, _ in rpc.calls])

    def test_capability_refused(self):
        with self.assertRaisesRegex(Refused, "unverified"):
            send(Fake(direct=None), TARGET, "hello", exclusive=True)

    def test_timeout_unknown_no_retry(self):
        rpc = Fake(fail=TimeoutError())
        with self.assertRaises(Unknown):
            send(rpc, TARGET, "hello", exclusive=True)
        self.assertEqual(sum(m == "turn/start" for m, _ in rpc.calls), 1)

    def test_rejection_no_retry(self):
        rpc = Fake(fail=RpcRejected("turn/start", -32600))
        with self.assertRaises(Refused):
            send(rpc, TARGET, "hello", exclusive=True)
        self.assertEqual(sum(m == "turn/start" for m, _ in rpc.calls), 1)

    def test_internal_error_unknown(self):
        with self.assertRaises(Unknown):
            send(Fake(fail=RpcRejected("turn/start", -32603)), TARGET, "hello", exclusive=True)

    def test_invalid_response_unknown(self):
        with self.assertRaises(Unknown):
            send(Fake(fail=Refused("invalid_rpc_response")), TARGET, "hello", exclusive=True)

    def test_invalid_inputs(self):
        for text in ("", "\x00", "가" * 22000):
            with self.subTest(text_length=len(text)), self.assertRaises(Refused):
                send(Fake(), TARGET, text, exclusive=True)
        with self.assertRaises(Refused):
            send(Fake(), "not-uuid", "hello", exclusive=True)


if __name__ == "__main__":
    unittest.main()
