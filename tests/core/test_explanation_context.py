"""Offline facts-only explanation context and privacy boundaries."""
import argparse
import copy
import io
import unittest
from unittest import mock

import session_peer as peer


class ExplanationContextTests(unittest.TestCase):
    def args(self, **kwargs):
        return argparse.Namespace(**{**dict(to="worker", host=[], device=None, wake=False), **kwargs})

    def context(self, **kwargs):
        return {**dict(schemaVersion=1, agent="codex", target="codex:00000000-0000-4000-8000-000000000001", home="/receiver/home",
                       capabilities=dict(send=True, wake=True, wait=False, ack=False)), **kwargs}

    def test_context_closed_versioned_and_boolean_contract(self):
        valid = self.context()
        self.assertEqual(peer.validated_delivery_context(valid), valid)
        bad = [self.context(schemaVersion=True), self.context(schemaVersion=2), self.context(agent="other"),
               self.context(target="session-peer://secret"), self.context(home=1),
               self.context(capabilities={"send": 1, "wake": True, "wait": False, "ack": False}),
               {**valid, "capability": "SECRET"}]
        for value in bad:
            with self.subTest(value=value):
                self.assertIsNone(peer.validated_delivery_context(value))
        normalized = peer.validated_delivery_context(valid)
        normalized["capabilities"]["send"] = False
        self.assertTrue(valid["capabilities"]["send"])

    def test_paired_missing_context_never_guesses_from_alias_or_sender(self):
        args = self.args(device="fingerprint", to="codex:sender-alias", codex_home="/sender/home")
        result = {"dryRun": True, "codexHome": "/unvalidated/home", "target": {"id": "unvalidated"}}
        facts = peer.build_delivery_explanation(args, result)
        self.assertIsNone(facts["agent"])
        self.assertIsNone(facts["capabilities"])
        rendered = peer.render_delivery_explanation(args, result)
        for secret in ("/sender/home", "/unvalidated/home", "codex:sender-alias"):
            self.assertNotIn(secret, rendered)
        self.assertIn("Selected agent / home: unknown", rendered)
        self.assertIn("Receipt ACK: unknown", rendered)

    def test_paired_uses_only_receiver_declarations(self):
        args = self.args(device="fingerprint", to="opaque-alias", _delivery_explanation_context=self.context())
        rendered = peer.render_delivery_explanation(args, {"dryRun": True, "codexHome": "/wrong/home"})
        self.assertIn("codex:00000000-0000-4000-8000-000000000001", rendered)
        self.assertIn("/receiver/home", rendered)
        self.assertNotIn("/wrong/home", rendered)
        self.assertIn("Wake capability: supported (declared; eligibility unverified)", rendered)
        self.assertIn("Wake: not requested; eligibility not checked", rendered)

    def test_declarations_never_become_observed_eligibility(self):
        rendered = peer.render_delivery_explanation(self.args(to="codex:id"), {"ok": True})
        self.assertIn("Submission capability: supported (declared; eligibility unverified)", rendered)
        self.assertIn("Validation: not confirmed", rendered)
        self.assertIn("Task completion: unknown", rendered)
        self.assertIn("Last delivery observation: unknown", rendered)

    def test_paired_route_uses_only_existing_report_not_requested_auto(self):
        args = self.args(device="fingerprint", to="opaque-alias", device_route="auto")
        for route in ("direct", "relay", None, "auto"):
            output = peer.render_delivery_explanation(args, {"dryRun": True, "route": route})
            self.assertIn("Selected paired route: " + (route + " (reported)" if route in ("direct", "relay") else "unknown (not reported)"), output)

    def test_doctor_reuses_only_supplied_diagnostics(self):
        result = {"codex": {"status": "available", "selectedHome": "/receiver/\x1bhome"},
                  "claude": {"status": "PRIVATE-ERROR"},
                  "capabilities": {"agents": {"codex": {"send": True, "wake": True, "wait": False, "ack": False}}}}
        original = copy.deepcopy(result)
        with mock.patch.object(peer, "doctor_payload", side_effect=AssertionError("new diagnostic")), \
                mock.patch.object(peer, "collect_listing", side_effect=AssertionError("new discovery")), \
                mock.patch.object(peer.subprocess, "run", side_effect=AssertionError("new process")):
            rendered = peer.render_delivery_explanation(self.args(), result, mode="doctor", host="worker\n")
        self.assertIn("codex availability: available", rendered)
        self.assertIn("not per-target readiness", rendered)
        self.assertIn("Selected home: /receiver/\\x1bhome", rendered)
        self.assertNotIn("PRIVATE-ERROR", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertIn("Destination host: worker\\x0a", rendered)
        self.assertEqual(result, original)

    def test_doctor_unknown_capabilities_not_filled_from_local_registry(self):
        rendered = peer.render_delivery_explanation(self.args(), {"codex": {"status": "available"}}, mode="doctor")
        self.assertIn("Wake: unknown (not reported)", rendered)
        self.assertNotIn(": supported (declared", rendered)

    def test_existing_intent_keeps_receipt_latest_wait_and_completion_separate(self):
        result = {"handoff": {"submission": {"status": "submitted"},
                  "observation": {"status": "unsupported", "injectionObserved": False},
                  "ack": {"status": "acknowledged", "assurance": "token_possession", "receivedAtUtcMs": 12345, "late": True},
                  "wait": {"status": "satisfied", "for": "acknowledged"}}}
        rendered = peer.render_delivery_explanation(self.args(), result, mode="existing_intent")
        self.assertIn("Explicit receipt: acknowledged", rendered)
        self.assertIn("Latest stored wait: satisfied", rendered)
        self.assertIn("Receipt assurance: token_possession", rendered)
        self.assertIn("Receipt late relative to first wait: true", rendered)
        self.assertIn("UTC milliseconds): 12345", rendered)
        self.assertIn("Task completion: unknown", rendered)
        self.assertIn("Stored evidence may be stale", rendered)

    def test_non_acknowledged_timestamp_cannot_become_receipt_observation(self):
        result = {"handoff": {"ack": {"status": "unsupported", "receivedAtUtcMs": 12345, "late": True}}}
        rendered = peer.render_delivery_explanation(self.args(), result, mode="existing_intent")
        self.assertIn("Explicit receipt: unsupported", rendered)
        self.assertNotIn("12345", rendered)
        self.assertNotIn("late relative", rendered)

    def test_existing_intent_history_failure_is_unknown_not_new_observation(self):
        result = {"error": "SECRET", "handoffQuery": {"status": "unknown", "context": "history_unavailable"}}
        with mock.patch.object(peer, "HandoffLedger", side_effect=AssertionError("new ledger read")), \
                mock.patch.object(peer, "handoff_ensure_collector", side_effect=AssertionError("new collector")):
            rendered = peer.render_delivery_explanation(self.args(), result, mode="existing_intent", failed=True)
        self.assertIn("Submission: unknown", rendered)
        self.assertNotIn("SECRET", rendered)
        self.assertIn("Do not automatically resend", rendered)

    def test_private_fields_and_control_characters_never_escape_allowlist(self):
        result = {"handoff": {"capability": "SECRET", "targetGeneration": "SECRET", "native": "SECRET",
                              "ack": {"status": "pending", "receiptId": "SECRET", "assurance": "SECRET"}},
                  "message": "SECRET", "error": "SECRET", "reason": "SECRET"}
        rendered = peer.render_delivery_explanation(self.args(), result, mode="existing_intent")
        self.assertNotIn("SECRET", rendered)

    def test_emitter_mode_and_stream_are_backward_compatible(self):
        output = io.StringIO()
        peer.emit_delivery_explanation(self.args(), {}, stream=output, mode="doctor")
        self.assertIn("Delivery capabilities", output.getvalue())

    def test_malformed_status_values_are_unknown(self):
        rendered = peer.render_delivery_explanation(self.args(), {"codex": {"status": []}}, mode="doctor")
        self.assertIn("codex availability: unknown", rendered)
        rendered = peer.render_delivery_explanation(self.args(), {"handoff": {"ack": {"status": []}}}, mode="existing_intent")
        self.assertIn("Explicit receipt: unknown", rendered)


    def test_bidi_is_escaped_only_in_explanations(self):
        home = "/receiver/\u202eprofile"
        args = self.args(device="fingerprint", to="alias", _delivery_explanation_context=self.context(home=home))
        output = peer.render_delivery_explanation(args, {"dryRun": True})
        self.assertNotIn("\u202e", output)
        self.assertIn("\\u202e", output)
        self.assertEqual(args._delivery_explanation_context["home"], home)

    def test_unavailable_history_is_not_presented_as_read_observation(self):
        output = peer.render_delivery_explanation(self.args(), {"handoffQuery": {"context": "ledger_missing"}},
                                                  mode="existing_intent", failed=True)
        self.assertIn("history not read", output)
        self.assertIn("History query: ledger_missing", output)
        self.assertNotIn("stored observation", output)

    def test_receipt_time_is_recorded_not_assumed_physical_arrival(self):
        public = {"ack": {"status": "acknowledged", "assurance": "operator_confirmed",
                          "receivedAtUtcMs": 123, "late": True}}
        output = peer.render_delivery_explanation(self.args(), {"handoff": public}, mode="existing_intent")
        self.assertIn("Receipt recorded at (stored UTC milliseconds): 123", output)
        self.assertNotIn("Receipt observed at", output)
        stream = io.StringIO()
        with mock.patch.object(peer.time, "time", side_effect=OSError("private clock diagnostic")):
            peer.emit_delivery_explanation(self.args(), {"handoff": public}, mode="existing_intent", stream=stream)
        self.assertIn("Explicit receipt: acknowledged", stream.getvalue())
        self.assertNotIn("private clock", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
