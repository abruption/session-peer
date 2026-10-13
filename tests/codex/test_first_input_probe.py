"""Synthetic probe guards; no native server, model turn, or receipt validation."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock


class FakeWebSocket:
    def __init__(self, home, queue_response):
        self.home = home
        self.queue_response = queue_response
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def send(self, message):
        self.sent.append(json.loads(message))
        if self.sent[-1]["method"] == "thread/queue/add" and self.queue_response == "send-error":
            raise OSError("PRIVATE send details")

    def recv(self, timeout):
        request = self.sent[-1]
        method = request["method"]
        if method == "initialize":
            result = {"userAgent": "codex-tui/0.162.1 test"}
            if self.home is not None:
                result["codexHome"] = self.home
        elif method == "thread/loaded/list":
            result = {"data": ["owned-thread"], "nextCursor": None}
        elif method == "thread/read":
            result = {"thread": {"cwd": self.home, "status": {"type": "idle"},
                                 "canAcceptDirectInput": True, "ephemeral": True}}
        else:
            if isinstance(self.queue_response, BaseException):
                raise self.queue_response
            if isinstance(self.queue_response, str):
                return self.queue_response
            return json.dumps(dict(self.queue_response, id=request["id"]))
        return json.dumps({"id": request["id"], "result": result})


@unittest.skipUnless(hasattr(socket, "AF_UNIX") and hasattr(os, "getuid"), "Unix experiment only")
class FirstInputProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import with only the transport symbol stubbed: tests need no optional dependency.
        client = types.ModuleType("websockets.sync.client")
        client.unix_connect = lambda *args, **kwargs: None
        spec = importlib.util.spec_from_file_location(
            "first_input_probe", Path(__file__).resolve().parents[2] /
            "experiments/codex_first_input/probe.py")
        cls.probe = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"websockets.sync.client": client}):
            spec.loader.exec_module(cls.probe)

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.home = Path(self.scratch.name).resolve()
        self.endpoint = self.home / "probe.sock"
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(str(self.endpoint))
        self.addCleanup(self.listener.close)
        with contextlib.closing(sqlite3.connect(self.home / "state_5.sqlite")) as db:
            db.execute("CREATE TABLE threads (id TEXT)")
            db.commit()

    def invoke(self, server_home, queue_response=None, supplied_home=None):
        ws = FakeWebSocket(server_home, {"result": {"queuedSubmission": {}}} if queue_response is None else queue_response)
        args = ["--socket", str(self.endpoint), "--codex-home", supplied_home or str(self.home),
                "--expected-cwd", str(self.home), "--mode", "queue", "--ack-marker", "ACK TEST"]
        output = io.StringIO()
        with mock.patch.object(self.probe, "unix_connect", return_value=ws), contextlib.redirect_stdout(output):
            exit_code = self.probe.run(args)
        return exit_code, ws.sent, output.getvalue()

    def test_missing_or_mismatched_home_refuses_before_thread_or_database(self):
        for server_home in (None, str(self.home.parent), "relative", ""):
            with self.subTest(server_home=server_home), mock.patch.object(
                    self.probe.sqlite3, "connect", side_effect=AssertionError("DB must not open")) as database:
                exit_code, sent, output = self.invoke(server_home)
                database.assert_not_called()
                self.assertEqual(exit_code, 1)
                self.assertEqual([item["method"] for item in sent], ["initialize"])
                self.assertNotIn(str(self.home), output)

    def test_relative_home_is_canonical_before_sqlite_uri(self):
        relative = os.path.relpath(str(self.home), os.getcwd())
        exit_code, sent, output = self.invoke(str(self.home), supplied_home=relative)
        self.assertEqual(exit_code, 0)
        self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
        self.assertFalse(json.loads(output.splitlines()[-1])["consumptionConfirmed"])

    def test_queue_rejection_returns_failure_without_retry(self):
        exit_code, sent, output = self.invoke(str(self.home), {"error": {"code": -32603, "message": "PRIVATE"}})
        self.assertEqual(exit_code, 1)
        self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
        self.assertEqual(json.loads(output.splitlines()[-1])["errorCode"], -32603)
        self.assertNotIn("PRIVATE", output)

    def test_malformed_errors_fail_without_traceback_or_retry(self):
        for error in (None, [], "PRIVATE", {"code": True}, {"code": "-32603"}, {}):
            with self.subTest(error=error):
                exit_code, sent, output = self.invoke(str(self.home), {"error": error})
                self.assertEqual(exit_code, 1)
                self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
                self.assertEqual(json.loads(output.splitlines()[-1])["error"], "invalid_rpc_error")
                self.assertIsNone(json.loads(output.splitlines()[-1])["accepted"])
                self.assertEqual(json.loads(output.splitlines()[-1])["outcome"], "unknown")
                self.assertNotIn("PRIVATE", output)

    def test_uncertain_queue_failures_preserve_unknown_and_no_retry(self):
        for response in (TimeoutError("PRIVATE timeout"), OSError("PRIVATE transport"),
                         "send-error", "PRIVATE invalid JSON", {"result": []},
                         {"result": {}}, {"error": {"code": -1}, "result": {}},
                         KeyboardInterrupt()):
            with self.subTest(response=type(response).__name__):
                exit_code, sent, output = self.invoke(str(self.home), response)
                self.assertEqual(exit_code, 130 if isinstance(response, KeyboardInterrupt) else 1)
                self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
                failure = json.loads(output.splitlines()[-1])
                self.assertIsNone(failure["accepted"])
                self.assertEqual(failure["outcome"], "unknown")
                self.assertFalse(failure["retryAllowed"])
                self.assertNotIn("PRIVATE", output)
                self.assertNotIn(str(self.home), output)

    def test_preflight_exception_is_sanitized_without_queue(self):
        for failure in (FileNotFoundError("PRIVATE path"), sqlite3.DatabaseError("PRIVATE DB"),
                        AssertionError("PRIVATE assertion"), ValueError("PRIVATE value")):
            with self.subTest(failure=type(failure).__name__), mock.patch.object(
                    self.probe.sqlite3, "connect", side_effect=failure):
                exit_code, sent, output = self.invoke(str(self.home))
                self.assertEqual(exit_code, 1)
                self.assertFalse(any(item["method"] == "thread/queue/add" for item in sent))
                result = json.loads(output.splitlines()[-1])
                self.assertIs(result["accepted"], False)
                self.assertEqual(result["outcome"], "not_attempted")
                self.assertNotIn("PRIVATE", output)

    def test_invalid_ephemeral_is_not_reflected_or_submitted(self):
        original = FakeWebSocket.recv

        def malicious_metadata(ws, timeout):
            raw = original(ws, timeout)
            if ws.sent[-1]["method"] == "thread/read":
                value = json.loads(raw)
                value["result"]["thread"]["ephemeral"] = "PRIVATE"
                return json.dumps(value)
            return raw

        with mock.patch.object(FakeWebSocket, "recv", malicious_metadata):
            exit_code, sent, output = self.invoke(str(self.home))
        self.assertEqual(exit_code, 1)
        self.assertFalse(any(item["method"] == "thread/queue/add" for item in sent))
        self.assertNotIn("PRIVATE", output)


if __name__ == "__main__":
    unittest.main()
