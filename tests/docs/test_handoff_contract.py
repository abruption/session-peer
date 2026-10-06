"""Synthetic proposal/fixture checks, NOT a shipped Handoff v1 validator.

These standard-library helpers exist only in tests. They do not exercise native
submission, collectors, durable fencing, receipt authentication, SSH or clocks.
Behavior vectors below check design coverage/consistency, not implementation.
"""

import base64
import copy
from decimal import Decimal
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/handoff-v1.json"
CONTRACT = ROOT / "docs/contracts/handoff-v1.md"
SAFE_INTEGER_MAX = 9007199254740991
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
ENUMS = {
    "state": {"validated", "refused", "submitted", "delivered", "acknowledged", "unknown", "timed_out_unknown"},
    "submission": {"not_attempted", "submitted", "refused", "unknown"},
    "observation": {"not_requested", "pending", "observed", "unsupported", "failed"},
    "ack": {"not_requested", "pending", "acknowledged", "unsupported"},
    "assurance": {"token_possession", "operator_confirmed"},
    "waitFor": {"none", "delivered", "acknowledged"},
    "waitStatus": {"not_requested", "pending", "satisfied", "timed_out_unknown", "stopped", "unsupported", "failed"},
    "turn": {"running", "completed", "failed", "interrupted", "unknown"},
    "waitReason": {"insufficient_budget", "deadline_before_effect", "evidence_unsupported", "evidence_failed", "history_unavailable", "stopped_by_operator", "invalid_handoff"},
    "nextActions": {"keep_waiting", "reconcile", "stop_waiting"},
}


class ProposalError(ValueError):
    pass


def require(condition, reason="schema"):
    if not condition:
        raise ProposalError(reason)


def closed(value, required, optional=()):
    require(type(value) is dict)
    require(set(required) <= value.keys())
    require(value.keys() <= set(required) | set(optional))


def integer(value):
    require(type(value) is int and 0 <= value <= SAFE_INTEGER_MAX)


def uuid4(value):
    require(type(value) is str and UUID4.fullmatch(value) is not None)


def identifier(value, limit=128):
    require(type(value) is str)
    require(all(not (ord(c) <= 31 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF) for c in value))
    require(1 <= len(value.encode("utf-8")) <= limit)


def enum(value, name):
    require(type(value) is str and value in ENUMS[name])


def strict_object(raw, limit):
    """Reject token ambiguity BEFORE converting any JSON number to a value."""
    if type(raw) is str:
        try:
            raw = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ProposalError("invalid_utf8") from error
    require(type(raw) is bytes, "invalid_utf8")
    require(len(raw) <= limit, "frame_size")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ProposalError("invalid_utf8") from error

    def pairs(items):
        obj = {}
        for key, value in items:
            require(key not in obj, "duplicate_key")
            obj[key] = value
        return obj

    def float_token(token):
        raise ProposalError("integer_token")

    def constant(token):
        raise ProposalError("nonfinite")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_float=float_token, parse_constant=constant)
    except json.JSONDecodeError as error:
        reason = "trailing_data" if error.msg == "Extra data" else "json_syntax"
        raise ProposalError(reason) from error
    require(type(value) is dict, "object_required")
    return value


def validate_handoff(handoff):
    """Test-only interpretation of the public proposal's static constraints.

    Channel liveness, history integrity, exact native binding and authentication
    are external evidence; this function cannot validate those acceptance gates.
    """
    closed(handoff, ("schemaVersion", "correlationId", "ledgerEpoch", "state", "submission", "observation", "ack", "wait", "targetGeneration", "decisionOwner", "retry", "nextActions"))
    integer(handoff["schemaVersion"])
    require(handoff["schemaVersion"] == 1)
    uuid4(handoff["correlationId"])
    uuid4(handoff["ledgerEpoch"])
    enum(handoff["state"], "state")
    submission = handoff["submission"]
    closed(submission, ("status",))
    enum(submission["status"], "submission")
    observation = handoff["observation"]
    closed(observation, ("status", "injectionObserved"), ("clientUserMessageId", "turn"))
    enum(observation["status"], "observation")
    require(type(observation["injectionObserved"]) is bool)
    if "clientUserMessageId" in observation:
        identifier(observation["clientUserMessageId"])
    generation = handoff["targetGeneration"]
    if generation is not None:
        identifier(generation, 256)
    injection = observation["injectionObserved"]
    if injection:
        require(submission["status"] == "submitted")
        require(observation["status"] == "observed")
        require("clientUserMessageId" in observation and generation is not None)
    if "turn" in observation:
        require(injection)
        closed(observation["turn"], ("id", "status"))
        identifier(observation["turn"]["id"])
        enum(observation["turn"]["status"], "turn")
    ack = handoff["ack"]
    closed(ack, ("status",), ("assurance", "receivedAtUtcMs", "late"))
    enum(ack["status"], "ack")
    if ack["status"] == "acknowledged":
        require(handoff["state"] == "acknowledged")
        require({"assurance", "receivedAtUtcMs", "late"} <= ack.keys())
        require(generation is not None and submission["status"] == "submitted")
        enum(ack["assurance"], "assurance")
        integer(ack["receivedAtUtcMs"])
        require(type(ack["late"]) is bool)
    else:
        require(set(ack) == {"status"})
    state_submissions = {
        "validated": {"not_attempted"}, "refused": {"refused"},
        "submitted": {"submitted"}, "delivered": {"submitted"},
        "acknowledged": {"submitted"}, "unknown": {"unknown"},
        "timed_out_unknown": {"submitted", "unknown"},
    }
    require(submission["status"] in state_submissions[handoff["state"]])
    if handoff["state"] == "delivered":
        require(injection)
    if handoff["state"] == "acknowledged":
        require(ack["status"] == "acknowledged")
    wait = handoff["wait"]
    closed(wait, ("for", "status"), ("operationId", "deadlineAtUtcMs", "reason"))
    enum(wait["for"], "waitFor")
    enum(wait["status"], "waitStatus")
    if "reason" in wait:
        enum(wait["reason"], "waitReason")
    if "operationId" in wait:
        uuid4(wait["operationId"])
    if "deadlineAtUtcMs" in wait:
        integer(wait["deadlineAtUtcMs"])
    if wait["for"] == "none":
        require(wait["status"] == "not_requested")
        require("operationId" not in wait and "deadlineAtUtcMs" not in wait)
    else:
        require({"operationId", "deadlineAtUtcMs"} <= wait.keys())
        require(wait["status"] != "not_requested")
    if wait["status"] == "satisfied":
        require(injection if wait["for"] == "delivered" else ack["status"] == "acknowledged")
    require(handoff["decisionOwner"] == "sender_operator")
    closed(handoff["retry"], ("allowed", "reason"))
    require(handoff["retry"]["allowed"] is False)
    require(handoff["retry"]["reason"] == "receiver_dedup_unavailable")
    actions = handoff["nextActions"]
    require(type(actions) is list)
    for action in actions:
        enum(action, "nextActions")
    require(len(actions) == len(set(actions)))
    if wait["status"] == "unsupported" or wait.get("reason") == "history_unavailable":
        require("keep_waiting" not in actions)


def validate_public_wire(raw):
    value = strict_object(raw, 8192)
    validate_handoff(value)
    return value


def validate_private_wire(raw, confirmation=False):
    """Synthetic shape checks only; no capability authentication or persistence."""
    value = strict_object(raw, 4096)
    required = {"schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration"}
    required |= {"confirmed"} if confirmation else {"kind", "receiptId", "capability"}
    closed(value, required)
    integer(value["schemaVersion"])
    require(value["schemaVersion"] == 1)
    uuid4(value["ledgerEpoch"])
    uuid4(value["correlationId"])
    identifier(value["targetGeneration"], 256)
    if confirmation:
        require(value["confirmed"] is True)
    else:
        require(value["kind"] == "receipt")
        uuid4(value["receiptId"])
        capability = value["capability"]
        require(type(capability) is str and re.fullmatch(r"[A-Za-z0-9_-]{43}", capability) is not None)
        decoded = base64.urlsafe_b64decode(capability + "=")
        require(len(decoded) == 32)
        require(base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") == capability)
    return value


def timeout(lexeme):
    require(type(lexeme) is str and re.fullmatch(r"[1-9][0-9]?", lexeme, flags=re.ASCII) is not None)
    require(1 <= int(lexeme) <= 60)
    return int(lexeme)


def changed(base, mutations, removed=()):
    value = copy.deepcopy(base)
    for path, replacement in mutations.items():
        keys = path.split(".")
        node = value
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = replacement
    for path in removed:
        keys = path.split(".")
        node = value
        for key in keys[:-1]:
            node = node[key]
        del node[keys[-1]]
    return value


class HandoffProposalContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.accepted = {case["name"]: case for case in cls.fixture["accepted"]}

    def sample(self, name="queued_best_effort_observer_failed"):
        return copy.deepcopy(self.accepted[name]["result"]["handoff"])

    def test_unimplemented_provenance_bounds_and_enums(self):
        fixture = self.fixture
        self.assertEqual(fixture["schemaVersion"], 1)
        self.assertEqual(fixture["status"], "draft_unimplemented")
        self.assertEqual(fixture["provenance"]["exampleKind"], "synthetic_normalized_not_live")
        self.assertEqual(fixture["provenance"]["pythonRuntimeVersion"], "1.0.3")
        self.assertRegex(fixture["provenance"]["pythonRuntimeCommit"], r"\A[0-9a-f]{40}\Z")
        self.assertEqual({key: set(values) for key, values in fixture["enums"].items()}, ENUMS)
        self.assertEqual(fixture["bounds"], {
            "safeIntegerMax": SAFE_INTEGER_MAX, "nativeIdUtf8Bytes": 128,
            "generationUtf8Bytes": 256, "receiptFrameBytes": 4096,
            "handoffFrameBytes": 8192, "timeoutMinS": 1, "timeoutMaxS": 60,
            "defaultBudgetS": 30, "cleanupReserveS": 5, "ledgerIntentQuota": 10000,
            "ledgerByteQuota": 33554432, "detailRetentionDays": 30,
            "capabilityTtlHours": 24, "maxWaitsPerIntent": 64, "capabilityEntropyBytes": 32,
        })
        document = CONTRACT.read_text(encoding="utf-8")
        for marker in ("unimplemented design", "synthetic examples", "numeric token validation", "No local-only design", "strict parser"):
            self.assertIn(marker, document)
        self.assertEqual(len(self.accepted), len(fixture["accepted"]))

    def test_every_accepted_handoff_and_rejected_mutation(self):
        for case in self.fixture["accepted"]:
            with self.subTest(accepted=case["name"]):
                self.assertIs(case["valid"], True)
                validate_public_wire(json.dumps(case["result"]["handoff"], ensure_ascii=False))
        for case in self.fixture["rejected"]:
            with self.subTest(rejected=case["name"]):
                self.assertIs(case["valid"], False)
                handoff = changed(self.sample(case["base"]), case["set"], case.get("remove", ()))
                with self.assertRaises(ProposalError):
                    validate_handoff(handoff)

    def test_required_and_nested_closed_keys(self):
        sample = self.sample("delivered_ack_timeout")
        for key in sample:
            with self.subTest(missing=key), self.assertRaises(ProposalError):
                validate_handoff(changed(sample, {}, (key,)))
        for path in ("extra", "submission.extra", "observation.extra", "observation.turn.extra", "ack.extra", "wait.extra", "retry.extra"):
            with self.subTest(extra=path), self.assertRaises(ProposalError):
                validate_handoff(changed(sample, {path: "unexpected"}))

    def test_exact_boolean_and_safe_integer_boundaries(self):
        sample = self.sample("receipt_satisfies_wait_without_injection_claim")
        for path in ("wait.deadlineAtUtcMs", "ack.receivedAtUtcMs"):
            for valid in (0, SAFE_INTEGER_MAX):
                with self.subTest(path=path, valid=valid):
                    validate_handoff(changed(sample, {path: valid}))
            for invalid in (True, False, -1, SAFE_INTEGER_MAX + 1, 1.0, 1.5, "1", None):
                with self.subTest(path=path, invalid=invalid), self.assertRaises(ProposalError):
                    validate_handoff(changed(sample, {path: invalid}))
        for path in ("observation.injectionObserved", "ack.late", "retry.allowed"):
            for invalid in (0, 1, "false", None):
                with self.subTest(path=path, invalid=invalid), self.assertRaises(ProposalError):
                    validate_handoff(changed(sample, {path: invalid}))

    def test_all_public_uuid_fields_require_canonical_version_four(self):
        sample = self.sample("queued_explicit_ack_timeout")
        for path in ("correlationId", "ledgerEpoch", "wait.operationId"):
            for invalid in ("opaque-id", "22222222-2222-1222-8222-222222222222", "22222222-2222-4222-7222-222222222222", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", sample["correlationId"] + "\n", True):
                with self.subTest(path=path, invalid=invalid), self.assertRaises(ProposalError):
                    validate_handoff(changed(sample, {path: invalid}))

    def test_utf8_scalar_controls_and_byte_boundaries(self):
        sample = self.sample("delivered_ack_timeout")
        for path, limit in (("observation.clientUserMessageId", 128), ("observation.turn.id", 128), ("targetGeneration", 256)):
            for valid in ("x" * limit, "😀" * (limit // 4), "opaque:id/非UUID"):
                with self.subTest(path=path, valid=valid):
                    validate_handoff(changed(sample, {path: valid}))
            invalids = ("", "x" * (limit + 1), "😀" * (limit // 4) + "x", "\ud800", "\udfff")
            invalids += tuple("id" + chr(code) for code in list(range(32)) + list(range(127, 160)))
            for invalid in invalids:
                with self.subTest(path=path, invalid=ascii(invalid)), self.assertRaises(ProposalError):
                    validate_handoff(changed(sample, {path: invalid}))

    def test_state_submission_and_evidence_conditions(self):
        states = {"validated": {"not_attempted"}, "refused": {"refused"}, "submitted": {"submitted"}, "delivered": {"submitted"}, "acknowledged": {"submitted"}, "unknown": {"unknown"}, "timed_out_unknown": {"submitted", "unknown"}}
        bases = {"validated": "dry_run_preserves_codex_false", "refused": "deadline_before_effect", "delivered": "delivered_wait_satisfied", "acknowledged": "manual_operator_receipt", "unknown": "unknown_preserves_legacy_unknown_false", "timed_out_unknown": "queued_explicit_ack_timeout"}
        for state, allowed in states.items():
            base = self.sample(bases.get(state, "queued_best_effort_observer_failed"))
            for submission in ENUMS["submission"]:
                value = changed(base, {"submission.status": submission})
                with self.subTest(state=state, submission=submission):
                    if submission in allowed:
                        validate_handoff(value)
                    else:
                        with self.assertRaises(ProposalError):
                            validate_handoff(value)
        delivered = self.sample("delivered_wait_satisfied")
        for mutation, removed in (({"targetGeneration": None}, ()), ({"observation.injectionObserved": False}, ()), ({}, ("observation.clientUserMessageId",))):
            with self.subTest(mutation=mutation, removed=removed), self.assertRaises(ProposalError):
                validate_handoff(changed(delivered, mutation, removed))
        # Turn completion stays independent of ACK; unknown is a valid turn enum.
        for turn in ENUMS["turn"]:
            value = changed(self.sample("delivered_ack_timeout"), {"observation.turn.status": turn})
            validate_handoff(value)
            self.assertEqual(value["ack"]["status"], "pending")

    def test_ack_and_wait_conditions_without_rewriting_history(self):
        acked = self.sample("receipt_satisfies_wait_without_injection_claim")
        with self.assertRaises(ProposalError):
            validate_handoff(changed(acked, {"targetGeneration": None}))
        for key in ("assurance", "receivedAtUtcMs", "late"):
            with self.subTest(missing_ack=key), self.assertRaises(ProposalError):
                validate_handoff(changed(acked, {}, ("ack." + key,)))
        for status in ENUMS["ack"] - {"acknowledged"}:
            with self.subTest(status=status), self.assertRaises(ProposalError):
                validate_handoff(changed(acked, {"ack.status": status}))
        explicit = self.sample("queued_explicit_ack_timeout")
        for key in ("operationId", "deadlineAtUtcMs"):
            with self.subTest(missing_wait=key), self.assertRaises(ProposalError):
                validate_handoff(changed(explicit, {}, ("wait." + key,)))
        for path, value in (("wait.operationId", explicit["wait"]["operationId"]), ("wait.deadlineAtUtcMs", 0), ("wait.status", "pending")):
            with self.subTest(no_wait=path), self.assertRaises(ProposalError):
                validate_handoff(changed(self.sample(), {path: value}))
        for status in ("stopped", "failed", "unsupported"):
            value = changed(self.sample("delivered_ack_timeout"), {"wait.status": status})
            validate_handoff(value)
            self.assertIs(value["observation"]["injectionObserved"], True)
        with self.assertRaises(ProposalError):
            validate_handoff(changed(explicit, {"wait.status": "satisfied"}))
        with self.assertRaises(ProposalError):
            validate_handoff(changed(explicit, {"wait.for": "delivered", "wait.status": "satisfied"}))
        late = self.sample("late_receipt_preserves_timeout_history")
        validate_handoff(late)
        self.assertEqual(late["state"], "acknowledged")
        self.assertEqual(late["wait"]["status"], "timed_out_unknown")
        self.assertIs(late["ack"]["late"], True)
        with self.assertRaises(ProposalError):
            validate_handoff(changed(self.sample("required_ack_channel_unsupported"), {"nextActions": ["keep_waiting"]}))

    def test_every_wire_rejection_has_the_expected_parser_reason(self):
        for case in self.fixture["wireRejected"]:
            raw = bytes.fromhex(case["bytesHex"]) if "bytesHex" in case else case["raw"]
            with self.subTest(name=case["name"]), self.assertRaises(ProposalError) as raised:
                strict_object(raw, 8192)
            self.assertEqual(str(raised.exception), case["reason"])
        for raw in ('{"nested":{"a":1,"a":2}}', '{"x":Infinity}', '{"x":-Infinity}', '[]', '{}\x00', '{', '\ufeff{}'):
            with self.subTest(raw=raw), self.assertRaises(ProposalError):
                strict_object(raw, 8192)
        sample = json.dumps(self.sample(), separators=(",", ":"))
        for token in ("1.0", "1e0", "1E+0"):
            raw = sample.replace('"schemaVersion":1,', '"schemaVersion":' + token + ',', 1)
            with self.subTest(token=token), self.assertRaisesRegex(ProposalError, "integer_token"):
                validate_public_wire(raw)

    def test_private_receipt_confirmation_and_frame_byte_limits(self):
        sample = self.sample()
        receipt = {key: sample[key] for key in ("schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration")}
        receipt.update(kind="receipt", receiptId="33333333-3333-4333-8333-333333333333", capability=base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("="))
        confirmation = {key: sample[key] for key in ("schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration")}
        confirmation["confirmed"] = True
        for value, confirm in ((receipt, False), (confirmation, True)):
            validate_private_wire(json.dumps(value), confirmation=confirm)
            for key in value:
                with self.subTest(confirm=confirm, missing=key), self.assertRaises(ProposalError):
                    validate_private_wire(json.dumps(changed(value, {}, (key,))), confirmation=confirm)
            for key in ("body", "extra", "receivedAtUtcMs"):
                with self.subTest(confirm=confirm, extra=key), self.assertRaises(ProposalError):
                    validate_private_wire(json.dumps(changed(value, {key: "synthetic"})), confirmation=confirm)
        for capability in ("<PRIVATE_INPUT_ONLY>", "A" * 42, "A" * 44, "+" + "A" * 42, "A" * 42 + "B", True):
            with self.subTest(capability=capability), self.assertRaises(ProposalError):
                validate_private_wire(json.dumps(changed(receipt, {"capability": capability})))
        for mutations in ({"confirmed": 1}, {"confirmed": False}, {"capability": "A" * 43}, {"body": "synthetic"}):
            with self.subTest(confirmation=mutations), self.assertRaises(ProposalError):
                validate_private_wire(json.dumps(changed(confirmation, mutations)), confirmation=True)
        for value, limit, validator in ((sample, 8192, validate_public_wire), (receipt, 4096, validate_private_wire)):
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            padded = raw + b" " * (limit - len(raw))
            validator(padded)
            with self.assertRaisesRegex(ProposalError, "frame_size"):
                validator(padded + b" ")

    def test_cli_timeout_lexemes_and_synthetic_budget_arithmetic(self):
        for lexeme in self.fixture["timeoutLexemes"]["accepted"]:
            with self.subTest(accepted=lexeme):
                timeout(lexeme)
        for lexeme in self.fixture["timeoutLexemes"]["rejected"] + ["", "١", "1\n", "\t1", "0001", 1, True]:
            with self.subTest(rejected=lexeme), self.assertRaises(ProposalError):
                timeout(lexeme)
        for value in range(1, 61):
            self.assertEqual(timeout(str(value)), value)
        # This is vector arithmetic, not evidence of a bounded runtime/SSH wait.
        reserve = Decimal(self.fixture["bounds"]["cleanupReserveS"])
        for case in self.fixture["budgets"]:
            with self.subTest(budget=case["name"]):
                total = Decimal(str(case["totalS"]))
                elapsed = Decimal(str(case["elapsedS"]))
                allowed = total > reserve and elapsed < total - reserve
                self.assertIs(case["effectAllowed"], allowed)
                if "remainingS" in case:
                    self.assertEqual(Decimal(str(case["remainingS"])), total - elapsed)
                if not allowed:
                    self.assertEqual(case["submission"], "refused")
                    self.assertEqual(case["reason"], "insufficient_budget" if total <= reserve else "deadline_before_effect")
                    self.assertEqual(case["exit"], 1)

    def test_native_snapshots_preserve_optional_absence_and_evidence(self):
        for case in self.fixture["legacySnapshots"]:
            with self.subTest(snapshot=case["name"]):
                self.assertTrue(case["source"])
                for key in case["mustRemainAbsent"]:
                    self.assertNotIn(key, case["result"])
        legacy = {case["name"]: case for case in self.fixture["legacySnapshots"]}
        claude = self.accepted["claude_success_preserves_optional_absence"]["result"]
        self.assertEqual({key: value for key, value in claude.items() if key != "handoff" and key != "host"}, {key: value for key, value in legacy["python_claude_success"]["result"].items() if key != "host"})
        for name in ("queued_best_effort_observer_failed", "queued_explicit_ack_timeout", "delivered_ack_timeout", "delivered_wait_satisfied", "receipt_satisfies_wait_without_injection_claim"):
            with self.subTest(queued=name):
                result = self.accepted[name]["result"]
                for key in ("status", "submitted", "consumptionConfirmed", "queueId", "target"):
                    self.assertEqual(result[key], legacy["python_codex_queued"]["result"][key])
        self.assertIs(legacy["legacy_unknown_false_not_no_effect"]["noEffectProof"], False)
        dry = self.accepted["dry_run_preserves_codex_false"]["result"]
        self.assertNotIn("queueId", dry)
        self.assertIs(dry["submitted"], False)
        self.assertIs(dry["consumptionConfirmed"], False)
        for name in ("late_receipt_preserves_timeout_history", "manual_operator_receipt", "status_query_of_timeout_is_not_ack"):
            result = self.accepted[name]["result"]
            for key in ("status", "submitted", "consumptionConfirmed"):
                self.assertNotIn(key, result)
            self.assertIs(result["ok"], True)
            self.assertEqual(self.accepted[name]["exit"], 0)

    def test_accepted_example_wait_and_exit_tuples(self):
        # These are assertions about declared examples, not CLI execution.
        for name, case in self.accepted.items():
            with self.subTest(example=name):
                handoff = case["result"]["handoff"]
                if case["mode"] == "status":
                    self.assertEqual(case["exit"], 0)
                    self.assertIs(case["result"]["ok"], True)
                elif handoff["wait"]["status"] in {"timed_out_unknown", "unsupported", "failed"} or handoff["state"] == "unknown":
                    self.assertEqual(case["exit"], 1)
                    self.assertIs(case["result"]["ok"], False)
                else:
                    self.assertEqual(case["exit"], 0)
                    self.assertIs(case["result"]["ok"], True)
                if handoff["state"] == "refused":
                    for key in ("status", "submitted", "consumptionConfirmed"):
                        self.assertNotIn(key, case["result"])

    def test_behavior_fixture_coverage_only_not_a_receipt_or_crash_engine(self):
        expected = {
            "unknown_custom_uuid": {"nativeSubmissions": 0, "submission": "refused", "freshIdAllocated": False},
            "intent_crash_before_effect": {"nativeSubmissionsOnRecovery": 0, "submission": "unknown", "retryAllowed": False},
            "duplicate_valid_receipt": {"receiptCommitCount": 1, "state": "acknowledged"},
            "wrong_receipt_id_or_binding": {"stateAdvances": False, "nativeSubmissions": 0},
            "target_restart": {"newGenerationBound": False, "resubmit": False},
            "ledger_missing": {"state": "unknown", "resubmit": False, "autoInit": False},
            "ledger_restored": {"quarantined": True, "resubmit": False, "receiptAccept": False},
            "detail_expired": {"state": "unknown", "resubmit": False, "fenceRetained": True},
            "ledger_capacity_full": {"newEffect": False, "evictFence": False},
            "wait_quota_full": {"newWait": False, "submissionFactsPreserved": True},
            "late_receipt_new_wait": {"originalWait": "timed_out_unknown", "newWait": "satisfied", "ackLate": True, "nativeSubmissions": 0},
            "unsupported_no_keep_waiting": {"keepWaiting": False, "mintCapability": False},
            "utc_clock_jump": {"monotonicBudgetUnchanged": True},
            "collector_restart_without_raw_capability": {"capabilityRegenerated": False, "nativeSubmissions": 0},
            "fanout_reconcile": {"newIdsAllocated": False, "newSubmissions": 0},
            "malformed_flags_without_id": {"exit": 2, "handoffPresent": False, "synthesizeSubmitted": False},
            "opt_out_shape": {"handoffPresent": False, "legacyExitUnchanged": True},
        }
        cases = self.fixture["behaviorCases"]
        self.assertEqual({case["name"] for case in cases}, set(expected))
        self.assertEqual(len(cases), len(expected))
        for case in cases:
            with self.subTest(design_vector=case["name"]):
                self.assertTrue(case["given"].strip())
                self.assertEqual(case["expected"], expected[case["name"]])

    def test_ssh_fixture_coverage_only_not_transport_execution(self):
        expected = {
            "complete_queued_wait_timeout": {"preserveNativeSnapshot": True, "explicitWaitExit": 1, "additionalSubmission": False},
            "claude_reconstruction": {"preserveHandoff": True, "preserveLegacyAbsence": True},
            "malformed_handoff_valid_native": {"nativeEvidencePreserved": True, "ackPromoted": False, "explicitWaitExit": 1, "additionalSubmission": False},
            "incomplete_stdout": {"submission": "unknown", "additionalSubmission": False},
            "stderr_non_utf8": {"stdoutStrict": True, "stderrReplacement": True, "preserveNativeSnapshot": True},
        }
        cases = self.fixture["sshCases"]
        self.assertEqual({case["name"] for case in cases}, set(expected))
        self.assertEqual(len(cases), len(expected))
        for case in cases:
            with self.subTest(design_vector=case["name"]):
                self.assertEqual(case["expected"], expected[case["name"]])
                if "sample" in case:
                    self.assertIn(case["sample"], self.accepted)
        self.assertEqual(self.fixture["receiptSchema"]["required"], ["schemaVersion", "kind", "ledgerEpoch", "correlationId", "targetGeneration", "receiptId", "capability"])
        self.assertEqual(self.fixture["operatorConfirmationSchema"]["required"], ["schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration", "confirmed"])
        self.assertIs(self.fixture["receiptSchema"]["persistRawCapability"], False)
        for name in ("receiptSchema", "operatorConfirmationSchema"):
            self.assertIs(self.fixture[name]["unknownKeysAllowed"], False)
        self.assertIn("no live/runtime claims", self.fixture["freezeGates"])


if __name__ == "__main__":
    unittest.main()
