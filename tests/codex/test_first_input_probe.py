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
    def __init__(self, home, queue_response, queue_list_response=None, turns_responses=None,
                 thread_snapshots=None):
        self.home = home
        self.queue_response = queue_response
        self.queue_list_response = queue_list_response
        self.sent = []
        self.turns_responses = turns_responses
        self.thread_snapshots = thread_snapshots
        self.turns_count = 0
        self.thread_count = 0

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
            result = {"thread": {"id": "owned-thread", "cwd": self.home, "status": {"type": "idle"},
                                 "canAcceptDirectInput": True, "ephemeral": False, "preview": ""}}
            if self.thread_snapshots is not None:
                result["thread"].update(self.thread_snapshots[min(self.thread_count, len(self.thread_snapshots)-1)])
            self.thread_count += 1
        elif method == "thread/turns/list":
            response = {"result": {"data": [], "nextCursor": None, "backwardsCursor": None}}
            if self.turns_responses is not None:
                response = self.turns_responses[min(self.turns_count, len(self.turns_responses)-1)]
            self.turns_count += 1
            return self.encode_reply(request, response)
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

    def invoke(self, server_home, queue_response=None, supplied_home=None, mode="queue", queue_list_response=None,
               turns_responses=None, thread_snapshots=None, allow_history=True):
        ws = FakeWebSocket(server_home, queue_response, queue_list_response, turns_responses, thread_snapshots)
        args = ["--socket", str(self.endpoint), "--codex-home", supplied_home or str(self.home),
                "--expected-cwd", str(self.home), "--mode", mode, "--ack-marker", "ACK TEST"]
        if allow_history:
            args.append("--allow-server-history-db-init")
        output = io.StringIO()
        with mock.patch.object(self.probe, "unix_connect", return_value=ws) as connect, \
                mock.patch.object(sqlite3, "connect", side_effect=AssertionError("No local DB reads")) as database, \
                contextlib.redirect_stdout(output):
            exit_code = self.probe.run(args)
        database.assert_not_called()
        if not allow_history:
            connect.assert_not_called()
        for item in ws.sent:
            self.assertNotIn(item["method"], ("thread/start", "thread/resume", "turn/start"))
            if item["method"] == "thread/read":
                self.assertIs(item["params"]["includeTurns"], False)
            if item["method"] == "thread/turns/list":
                self.assertEqual(item["params"], {"threadId": "owned-thread", "limit": 1,
                                                "sortDirection": "desc", "itemsView": "notLoaded"})
        return exit_code, ws.sent, output.getvalue()

    def test_missing_or_mismatched_home_refuses_before_thread_or_database(self):
        for server_home in (None, str(self.home.parent), "relative", ""):
            with self.subTest(server_home=server_home):
                exit_code, sent, output = self.invoke(server_home)
                self.assertEqual(exit_code, 1)
                self.assertEqual([item["method"] for item in sent], ["initialize"])
                self.assertNotIn(str(self.home), output)

    def test_relative_home_is_canonical_before_server_binding(self):
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

    def test_queue_and_turn_preflights_are_bound_before_the_only_add(self):
        # Independent pinned-wire fixture, not an echo of the generated request.
        client_id = "00000000-0000-4000-8000-000000000001"
        expected_input = [{"type": "text", "text": "Owner-authorized one-shot transport test. Reply exactly ACK TEST. Do not run tools or modify files.",
                           "text_elements": []}]
        reply = {"result": {"queuedSubmission": {"id": "fixture-submission", "input": expected_input,
                                                  "clientUserMessageId": client_id}}}
        with mock.patch.object(self.probe.uuid, "uuid4", return_value=self.probe.uuid.UUID(client_id)):
            exit_code, sent, output = self.invoke(str(self.home), reply)
        self.assertEqual(exit_code, 0)
        self.assertEqual([item["method"] for item in sent][-4:],
                         ["thread/queue/list", "thread/read", "thread/turns/list", "thread/queue/add"])
        listed, added = sent[-4], sent[-1]
        self.assertEqual(listed["params"], {"threadId": "owned-thread", "limit": 1})
        self.assertEqual(added["params"]["threadId"], listed["params"]["threadId"])
        self.assertEqual(added["params"]["input"], expected_input)
        self.assertEqual(added["params"]["clientUserMessageId"], client_id)
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

        def missing_default(request):
            reply = successful_queue_reply(request)
            text = request["params"]["input"][0]["text"]
            reply["result"]["queuedSubmission"]["input"] = [{"type": "text", "text": text}]
            return reply
        code, sent, output = self.invoke(str(self.home), missing_default)
        self.assertEqual(code, 1)
        self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
        result = json.loads(output.splitlines()[-1])
        self.assertIsNone(result["accepted"])
        self.assertEqual(result["outcome"], "unknown")
        self.assertFalse(result["retryAllowed"])

    def test_response_ids_require_the_exact_integer_request_id(self):
        original = FakeWebSocket.recv
        for phase in ("initialize", "thread/read", "thread/turns/list", "thread/queue/list", "thread/queue/add"):
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
            with self.subTest(case=label), mock.patch.object(FakeWebSocket, "recv", metadata):
                exit_code, sent, output = self.invoke(str(self.home))
                self.assertEqual(exit_code, 1)
                self.assertFalse(any(item["method"] == "thread/queue/add" for item in sent))
                result = json.loads(output.splitlines()[-1])
                self.assertEqual(result["error"], "persistent_thread_required")
                self.assertIs(result["accepted"], False)
                self.assertEqual(result["outcome"], "not_attempted")
                self.assertFalse(result["retryAllowed"])

    def test_inspection_requires_proven_persistent_metadata_too(self):
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
                    self.assertEqual(exit_code, 1)
                    self.assertEqual(result["error"], "persistent_thread_required")
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
                    FakeWebSocket, "__enter__", side_effect=failure):
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

    def assert_pre_effect_failure(self, code, sent, output):
        self.assertEqual(code, 1)
        self.assertFalse(any(item["method"] == "thread/queue/add" for item in sent))
        result = json.loads(output.splitlines()[-1])
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["outcome"], "not_attempted")
        self.assertFalse(result["retryAllowed"])
        self.assertNotIn("PRIVATE", output)

    def test_history_read_opt_in_required_before_any_connection(self):
        for mode in ("inspect", "queue"):
            with self.subTest(mode=mode):
                code, sent, output = self.invoke(str(self.home), mode=mode, allow_history=False)
                self.assert_pre_effect_failure(code, sent, output)
                self.assertEqual(sent, [])
                self.assertEqual(json.loads(output)["error"], "server_history_read_requires_opt_in")

    def test_stale_empty_account_database_cannot_override_server_turns(self):
        (self.home / "config.toml").write_text('sqlite_home = "PRIVATE configured storage"\n')
        with mock.patch.dict(os.environ, {"CODEX_SQLITE_HOME": "PRIVATE inherited storage"}):
            code, sent, output = self.invoke(str(self.home), turns_responses=[{
                "result": {"data": [{"id": "PRIVATE old turn"}], "nextCursor": None, "backwardsCursor": None}}])
        self.assert_pre_effect_failure(code, sent, output)
        self.assertEqual(json.loads(output.splitlines()[-1])["error"], "server_turns_present_or_unproven")
        self.assertEqual(sum(item["method"] == "thread/turns/list" for item in sent), 1)
        self.assertFalse(any(item["method"] == "thread/queue/list" for item in sent))

    def test_empty_server_turns_do_not_consult_nonempty_or_missing_account_database(self):
        with contextlib.closing(sqlite3.connect(self.home / "state_5.sqlite")) as db:
            db.execute("INSERT INTO threads VALUES ('owned-thread')")
            db.commit()
        for missing in (False, True):
            if missing:
                (self.home / "state_5.sqlite").unlink()
            with self.subTest(missing=missing):
                code, sent, output = self.invoke(str(self.home))
                self.assertEqual(code, 0)
                self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
                facts = json.loads(output.splitlines()[0])
                self.assertIs(facts["serverTurnsEmpty"], True)
                self.assertEqual(facts["freshnessSource"], "thread/turns/list")
                self.assertNotIn("storedRowsBefore", facts)

    def test_probe_environment_and_root_configuration_are_not_server_storage_authority(self):
        (self.home / "config.toml").write_text('sqlite_home = "PRIVATE fixture relocation"\n')
        with mock.patch.dict(os.environ, {"CODEX_SQLITE_HOME": "PRIVATE fixture environment"}):
            code, sent, output = self.invoke(str(self.home))
        self.assertEqual(code, 0)
        self.assertEqual(sum(item["method"] == "thread/queue/add" for item in sent), 1)
        self.assertNotIn("PRIVATE", output)

    def test_invalid_or_nonempty_server_turns_refuse_at_both_snapshots(self):
        empty = {"result": {"data": [], "nextCursor": None, "backwardsCursor": None}}
        values = [None, [], {}, {"data": []},
                  {"data": None, "nextCursor": None, "backwardsCursor": None},
                  {"data": {}, "nextCursor": None, "backwardsCursor": None},
                  {"data": [], "nextCursor": "PRIVATE cursor", "backwardsCursor": None},
                  {"data": [], "nextCursor": None, "backwardsCursor": "PRIVATE cursor"},
                  {"data": [], "nextCursor": True, "backwardsCursor": None},
                  {"data": [], "nextCursor": None, "backwardsCursor": False},
                  {"data": [], "nextCursor": None},
                  {"data": [], "backwardsCursor": None},
                  {"data": [{"id": "PRIVATE turn"}], "nextCursor": None, "backwardsCursor": None}]
        responses = [{"result": value} for value in values]
        responses += [{"error": {"code": -1, "message": "PRIVATE"}},
                      {"error": {"code": -1}}, TimeoutError("PRIVATE"), "PRIVATE invalid JSON"]
        for phase in (0, 1):
            for index, response in enumerate(responses):
                with self.subTest(phase=phase, case=index):
                    snapshots = [response] if phase == 0 else [empty, response]
                    code, sent, output = self.invoke(str(self.home), turns_responses=snapshots)
                    self.assert_pre_effect_failure(code, sent, output)
                    self.assertEqual(sum(item["method"] == "thread/queue/list" for item in sent), phase)

    def test_preview_must_be_explicit_empty_string_at_both_snapshots(self):
        original = FakeWebSocket.recv
        for phase in (0, 1):
            for kind, preview in (("nonempty", "PRIVATE text"), ("null", None),
                                  ("nonstring", 123), ("missing", None)):
                def metadata(ws, timeout):
                    raw = original(ws, timeout)
                    if ws.sent[-1]["method"] == "thread/read" and ws.thread_count == phase + 1:
                        value = json.loads(raw)
                        thread = value["result"]["thread"]
                        if kind == "missing":
                            thread.pop("preview")
                        else:
                            thread["preview"] = preview
                        return json.dumps(value)
                    return raw
                with self.subTest(phase=phase, case=kind), mock.patch.object(FakeWebSocket, "recv", metadata):
                    code, sent, output = self.invoke(str(self.home))
                    self.assert_pre_effect_failure(code, sent, output)
                    self.assertEqual(sum(item["method"] == "thread/queue/list" for item in sent), phase)

    def test_inspect_reports_only_server_snapshot_and_never_submits(self):
        code, sent, output = self.invoke(str(self.home), mode="inspect")
        self.assertEqual(code, 0)
        self.assertEqual([item["method"] for item in sent],
                         ["initialize", "initialized", "thread/loaded/list", "thread/read", "thread/turns/list"])
        facts = json.loads(output)
        self.assertEqual(facts, {"version": "0.162.1", "loadedThreads": 1, "serverTurnsEmpty": True,
                                 "freshnessSource": "thread/turns/list", "idle": True,
                                 "directInput": True, "ephemeral": False, "mode": "inspect"})

    def test_thread_identity_and_idle_direct_input_constraints_hold_at_both_snapshots(self):
        invalid = [{"id": "PRIVATE other thread"}, {"id": None},
                   {"cwd": str(self.home.parent)}, {"status": {"type": "active"}},
                   {"status": None}, {"canAcceptDirectInput": False},
                   {"canAcceptDirectInput": 1}, {"ephemeral": True}]
        for phase in (0, 1):
            for index, fields in enumerate(invalid):
                with self.subTest(phase=phase, case=index):
                    snapshots = [fields] if phase == 0 else [{}, fields]
                    code, sent, output = self.invoke(str(self.home), thread_snapshots=snapshots)
                    self.assert_pre_effect_failure(code, sent, output)
                    self.assertEqual(sum(item["method"] == "thread/queue/list" for item in sent), phase)

    def test_exact_native_version_required_before_thread_queries(self):
        original = FakeWebSocket.recv
        for version in ("codex-tui/0.162.0 PRIVATE", "codex-tui/0.162.10 PRIVATE", None, True):
            def metadata(ws, timeout):
                raw = original(ws, timeout)
                if ws.sent[-1]["method"] == "initialize":
                    value = json.loads(raw)
                    value["result"]["userAgent"] = version
                    return json.dumps(value)
                return raw
            with self.subTest(kind=type(version).__name__), mock.patch.object(FakeWebSocket, "recv", metadata):
                code, sent, output = self.invoke(str(self.home))
                self.assert_pre_effect_failure(code, sent, output)
                self.assertEqual([item["method"] for item in sent], ["initialize"])

    def test_loaded_thread_snapshot_is_complete_and_unambiguous(self):
        original = FakeWebSocket.recv
        for data in ([], "x", [None], [True], [""], ["one", "two"]):
            def metadata(ws, timeout):
                raw = original(ws, timeout)
                if ws.sent[-1]["method"] == "thread/loaded/list":
                    value = json.loads(raw)
                    value["result"]["data"] = data
                    return json.dumps(value)
                return raw
            with self.subTest(kind=type(data).__name__), mock.patch.object(FakeWebSocket, "recv", metadata):
                code, sent, output = self.invoke(str(self.home))
                self.assert_pre_effect_failure(code, sent, output)
                self.assertEqual(sent[-1]["method"], "thread/loaded/list")
        for result in ({"data": ["owned-thread"]}, {"data": ["owned-thread"], "nextCursor": "PRIVATE cursor"}):
            def metadata(ws, timeout):
                if ws.sent[-1]["method"] == "thread/loaded/list":
                    return json.dumps({"id": ws.sent[-1]["id"], "result": result})
                return original(ws, timeout)
            with self.subTest(keys=tuple(result)), mock.patch.object(FakeWebSocket, "recv", metadata):
                code, sent, output = self.invoke(str(self.home))
                self.assert_pre_effect_failure(code, sent, output)
                self.assertEqual(sent[-1]["method"], "thread/loaded/list")


if __name__ == "__main__":
    unittest.main()
