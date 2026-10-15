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


def successful_queue_reply(request):
    return {"result": {"queuedSubmission": {
        "id": "fixture-submission", "input": request["params"]["input"],
        "clientUserMessageId": request["params"]["clientUserMessageId"]}}}


class FakeWebSocket:
    def __init__(self, home, queue_response, queue_list_response=None):
        self.home = home
        self.queue_response = queue_response
        self.queue_list_response = queue_list_response
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
                                 "canAcceptDirectInput": True, "ephemeral": False}}
        elif method == "thread/queue/list":
            response = ({"result": {"data": [], "nextCursor": None}} if self.queue_list_response is None
                        else self.queue_list_response)
            return self.encode_reply(request, response)
        else:
            response = successful_queue_reply(request) if self.queue_response is None else self.queue_response
            return self.encode_reply(request, response)
        return json.dumps({"id": request["id"], "result": result})

    @staticmethod
    def encode_reply(request, response):
        if callable(response):
            response = response(request)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, str):
            return response
        return json.dumps(dict(response, id=request["id"]))


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

    def invoke(self, server_home, queue_response=None, supplied_home=None, mode="queue", queue_list_response=None):
        ws = FakeWebSocket(server_home, queue_response, queue_list_response)
        args = ["--socket", str(self.endpoint), "--codex-home", supplied_home or str(self.home),
                "--expected-cwd", str(self.home), "--mode", mode, "--ack-marker", "ACK TEST"]
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
        self.assertIs(json.loads(output.splitlines()[-1])["accepted"], False)
        self.assertFalse(json.loads(output.splitlines()[-1])["retryAllowed"])
        self.assertNotIn("PRIVATE", output)

    def test_queue_preflight_is_bound_and_immediately_precedes_the_only_add(self):
        exit_code, sent, output = self.invoke(str(self.home))
        self.assertEqual(exit_code, 0)
        self.assertEqual([item["method"] for item in sent][-2:], ["thread/queue/list", "thread/queue/add"])
        listed, added = sent[-2:]
        self.assertEqual(listed["params"], {"threadId": "owned-thread", "limit": 1})
        self.assertEqual(added["params"]["threadId"], listed["params"]["threadId"])
        self.assertEqual(added["params"]["input"][0]["text_elements"], [])
        self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
        self.assertTrue(json.loads(output.splitlines()[-1])["accepted"])
        self.assertFalse(json.loads(output.splitlines()[-1])["consumptionConfirmed"])
        self.assertTrue(added["params"]["clientUserMessageId"] not in output, "client ID reflected")
        self.assertTrue("fixture-submission" not in output, "queue ID reflected")

    def test_nonempty_or_unproven_queue_refuses_without_any_add(self):
        results = [None, [], {}, {"data": []}, {"data": None, "nextCursor": None},
                   {"data": {}, "nextCursor": None}, {"data": [], "nextCursor": True},
                   {"data": [], "nextCursor": "PRIVATE cursor"},
                   {"data": [{"input": "PRIVATE queued body"}], "nextCursor": None}]
        responses = [{"result": value} for value in results]
        responses += [{"error": {"code": -1, "message": "PRIVATE error"}},
                      TimeoutError("PRIVATE timeout"), "PRIVATE invalid JSON", KeyboardInterrupt()]
        for index, response in enumerate(responses):
            with self.subTest(case=index):
                code, sent, output = self.invoke(str(self.home), queue_list_response=response)
                self.assertEqual(code, 130 if isinstance(response, KeyboardInterrupt) else 1)
                self.assertFalse(any(item["method"] == "thread/queue/add" for item in sent))
                result = json.loads(output.splitlines()[-1])
                self.assertIs(result["accepted"], False)
                self.assertEqual(result["outcome"], "not_attempted")
                self.assertFalse(result["retryAllowed"])
                self.assertNotIn("PRIVATE", output)

    def test_invalid_queued_submission_shapes_preserve_unknown_after_one_add(self):
        for index, queued in enumerate((None, [], True, "PRIVATE", {}, {"id": "fixture-submission"})):
            with self.subTest(case=index):
                code, sent, output = self.invoke(str(self.home), {"result": {"queuedSubmission": queued}})
                self.assertEqual(code, 1)
                self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
                result = json.loads(output.splitlines()[-1])
                self.assertEqual(result["error"], "invalid_queue_result")
                self.assertIsNone(result["accepted"])
                self.assertEqual(result["outcome"], "unknown")
                self.assertFalse(result["retryAllowed"])
                self.assertNotIn("PRIVATE", output)

    def test_submission_fields_and_echo_must_match_the_request(self):
        changes = [("id", value) for value in (None, False, [], "")]
        changes += [("input", value) for value in (None, [], "PRIVATE", [{"type": "text", "text": "PRIVATE"}])]
        changes += [("clientUserMessageId", value) for value in (None, False, [], "PRIVATE mismatched ID")]
        for index, (key, value) in enumerate(changes):
            def response(request):
                reply = successful_queue_reply(request)
                reply["result"]["queuedSubmission"][key] = value
                return reply
            with self.subTest(case=index):
                code, sent, output = self.invoke(str(self.home), response)
                self.assertEqual(code, 1)
                self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
                result = json.loads(output.splitlines()[-1])
                self.assertIsNone(result["accepted"])
                self.assertEqual(result["outcome"], "unknown")
                self.assertFalse(result["retryAllowed"])
                self.assertNotIn("PRIVATE", output)

    def test_response_ids_require_the_exact_integer_request_id(self):
        original = FakeWebSocket.recv
        for phase in ("initialize", "thread/queue/add"):
            for kind in ("float", "bool", "missing"):
                def metadata(ws, timeout):
                    raw = original(ws, timeout)
                    if ws.sent[-1]["method"] == phase:
                        value = json.loads(raw)
                        if kind == "missing":
                            value.pop("id")
                            # Unknown notifications remain bounded by 200 frames.
                        else:
                            value["id"] = float(value["id"]) if kind == "float" else True
                        return json.dumps(value)
                    return raw
                with self.subTest(phase=phase, kind=kind), mock.patch.object(FakeWebSocket, "recv", metadata):
                    code, sent, output = self.invoke(str(self.home))
                    self.assertEqual(code, 1)
                    expected_attempts = 1 if phase == "thread/queue/add" else 0
                    self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), expected_attempts)
                    result = json.loads(output.splitlines()[-1])
                    if expected_attempts:
                        self.assertIsNone(result["accepted"])
                        self.assertEqual(result["outcome"], "unknown")
                    else:
                        self.assertIs(result["accepted"], False)
                        self.assertEqual(result["outcome"], "not_attempted")
                    self.assertFalse(result["retryAllowed"])

    def test_malformed_errors_fail_without_traceback_or_retry(self):
        for error in (None, [], "PRIVATE", {"code": True, "message": "PRIVATE"},
                      {"code": "-32603", "message": "PRIVATE"}, {}, {"code": -32603},
                      {"code": -32603, "message": None}, {"code": -32603, "message": 1},
                      {"code": -32603, "message": []}):
            with self.subTest(error=error):
                exit_code, sent, output = self.invoke(str(self.home), {"error": error})
                self.assertEqual(exit_code, 1)
                self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
                self.assertEqual(json.loads(output.splitlines()[-1])["error"], "invalid_rpc_error")
                self.assertIsNone(json.loads(output.splitlines()[-1])["accepted"])
                self.assertEqual(json.loads(output.splitlines()[-1])["outcome"], "unknown")
                self.assertFalse(json.loads(output.splitlines()[-1])["retryAllowed"])
                self.assertNotIn("PRIVATE", output)

    def test_rpc_result_uses_the_same_complete_error_validation(self):
        for error in ({"code": -1}, {"code": -1, "message": None},
                      {"code": -1, "message": 1}, {"code": True, "message": "PRIVATE"}):
            with self.subTest(error=error), self.assertRaises(self.probe.ProbeError) as caught:
                self.probe.rpc_result({"error": error})
            self.assertEqual(str(caught.exception), "invalid_rpc_error")
        for message in ("", "PRIVATE native text"):
            with self.subTest(empty=not message), self.assertRaises(self.probe.ProbeError) as caught:
                self.probe.rpc_result({"error": {"code": -1, "message": message}})
            self.assertEqual(str(caught.exception), "rpc_rejected")

    def test_ephemeral_or_unproven_threads_refuse_before_database_or_queue(self):
        original = FakeWebSocket.recv
        for label, fields in (("ephemeral", {"ephemeral": True}), ("null", {"ephemeral": None}),
                              ("missing", {})):
            def metadata(ws, timeout):
                raw = original(ws, timeout)
                if ws.sent[-1]["method"] == "thread/read":
                    value = json.loads(raw)
                    value["result"]["thread"].pop("ephemeral", None)
                    value["result"]["thread"].update(fields)
                    return json.dumps(value)
                return raw
            with self.subTest(case=label), mock.patch.object(FakeWebSocket, "recv", metadata), \
                    mock.patch.object(self.probe.sqlite3, "connect", side_effect=AssertionError("DB must not open")) as db:
                exit_code, sent, output = self.invoke(str(self.home))
                self.assertEqual(exit_code, 1)
                self.assertEqual(db.call_count, 0)
                self.assertFalse(any(item["method"] == "thread/queue/add" for item in sent))
                result = json.loads(output.splitlines()[-1])
                self.assertEqual(result["error"], "persistent_thread_required")
                self.assertIs(result["accepted"], False)
                self.assertEqual(result["outcome"], "not_attempted")
                self.assertFalse(result["retryAllowed"])

    def test_inspection_does_not_claim_row_absence_proves_ephemeral_freshness(self):
        original = FakeWebSocket.recv
        for label, fields in (("ephemeral", {"ephemeral": True}), ("null", {"ephemeral": None}),
                              ("missing", {}), ("invalid", {"ephemeral": "PRIVATE"})):
            def metadata(ws, timeout):
                raw = original(ws, timeout)
                if ws.sent[-1]["method"] == "thread/read":
                    value = json.loads(raw)
                    value["result"]["thread"].pop("ephemeral", None)
                    value["result"]["thread"].update(fields)
                    return json.dumps(value)
                return raw
            with self.subTest(case=label), mock.patch.object(FakeWebSocket, "recv", metadata):
                exit_code, sent, output = self.invoke(str(self.home), mode="inspect")
                result = json.loads(output.splitlines()[-1])
                if label == "invalid":
                    self.assertEqual(exit_code, 1)
                    self.assertEqual(result["error"], "invalid_thread_metadata")
                    self.assertNotIn("PRIVATE", output)
                else:
                    self.assertEqual(exit_code, 0)
                    self.assertIs(result["ephemeral"], fields.get("ephemeral"))
                self.assertFalse(any(item["method"] == "thread/queue/add" for item in sent))

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
