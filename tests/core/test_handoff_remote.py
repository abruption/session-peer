"""Private native protocol fixtures: no remote hosts, transcripts or models."""
import base64
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shlex
import sys
import unittest
import uuid
from unittest import mock

import session_peer as peer
from tests.core import test_handoff_codex as codex_fixtures


@unittest.skipIf(peer.IS_WINDOWS, "private source streaming is POSIX only")
class HandoffRemote(unittest.TestCase):
    def setUp(self):
        self.fixture = codex_fixtures.HandoffCodex()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.home = str(self.fixture.home)
        self.thread = self.fixture.thread
        self.body = "External user text\nDo not quote this line\n<session-peer-boundary>"
        self.anchor = {"boot": "owned-boot", "monotonicMs": 100000}
        self.generation = "tg1:" + "1" * 64
        self.session = {"pid": 4242, "name": "owned-fixture", "socket": "owned-endpoint", "reachable": True}

    def context(self, agent="claude", phase="probe"):
        return {"schemaVersion": 1, "phase": phase, "requestId": str(uuid.uuid4()),
                "agent": agent, "target": "4242" if agent == "claude" else self.thread,
                "home": None if agent == "claude" else self.home,
                "nativeContext": None, "generation": None,
                "anchor": None if phase == "probe" else dict(self.anchor),
                "remainingCutoffMs": None if phase == "probe" else 2000,
                "remainingTotalMs": None if phase == "probe" else 7000}

    def argv(self, context):
        encoded = base64.b64encode(peer.HandoffLedger.encode(context)).decode("ascii")
        argv = ["send", "--_handoff-native-context=" + encoded,
                "--to=" + ("codex:" + context["target"] if context["agent"] == "codex" else context["target"]),
                "--b64=" + base64.b64encode(self.body.encode()).decode(),
                "--no-from", "--no-reply-to", "--no-update-notice", "--json"]
        if context["agent"] == "codex":
            argv += ["--codex-home=" + context["home"], "--codex-bin=" + str(self.fixture.fake), "--allow-inactive-codex-home"]
        if context["phase"] == "probe":
            argv += ["--_handoff-native-cutoff-ms=2000", "--_handoff-native-total-ms=7000"]
        return argv

    def invoke(self, context, argv=None, post=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                mock.patch.object(peer, "discover", return_value=[self.session]) as discovery, \
                mock.patch.object(peer, "claude_generation", return_value=self.generation), \
                mock.patch.object(peer, "require_claude_generation") as generation, \
                mock.patch.object(peer, "post_to_socket", side_effect=post) as socket, \
                mock.patch.object(peer, "known_codex_homes", return_value=[self.fixture.home]), \
                mock.patch.object(peer, "handoff_remote_anchor", return_value=self.anchor), \
                mock.patch.object(peer, "handoff_now", return_value=100.1), \
                mock.patch.object(peer, "handoff_ensure_collector") as collector, \
                mock.patch.object(peer, "handoff_producer_command") as producer:
            code = peer.main(argv or self.argv(context))
        self.assertEqual(collector.call_count, 0)
        self.assertEqual(producer.call_count, 0)
        return code, json.loads(output.getvalue()), socket, discovery, generation

    def effect(self, agent="claude"):
        probe = self.context(agent)
        code, response, _, _, _ = self.invoke(probe)
        self.assertEqual(code, 0, response)
        peer.handoff_validate_remote_response(response, probe)
        effect = self.context(agent, "effect")
        effect["generation"] = response["handoffNative"]["generation"]
        effect["nativeContext"] = response["handoffNative"]["nativeContext"]
        return effect

    def test_probe_claude_has_no_effect_and_validated_original_generation(self):
        context = self.context()
        code, response, socket, _, _ = self.invoke(context)
        self.assertEqual(code, 0, response)
        socket.assert_not_called()
        native = peer.handoff_validate_remote_response(response, context)
        self.assertTrue(native["dryRun"])
        self.assertEqual(native["targetGeneration"], self.generation)
        for missing in ("status", "submitted", "consumptionConfirmed"):
            self.assertNotIn(missing, native)

    def test_effect_claude_quotes_every_line_once_without_receipt_authority(self):
        context = self.effect()
        code, response, socket, _, generation = self.invoke(context)
        self.assertEqual(code, 0, response)
        self.assertEqual(socket.call_count, 1)
        emitted = socket.call_args.args[1]
        self.assertEqual(emitted, peer.peer_delivery_message(self.body, "claude", None))
        self.assertEqual(response["handoffNative"]["native"]["chars"], len(emitted))
        self.assertEqual(socket.call_args.kwargs["expected_generation"], context["generation"])
        generation.assert_called_once()
        native = peer.handoff_validate_remote_response(response, context)
        self.assertNotIn("submitted", native)
        self.assertNotIn("capability", json.dumps(response))

    def test_codex_probe_and_effect_retain_original_context_and_queue_receipt(self):
        context = self.effect("codex")
        self.assertIsNone(context["generation"])
        self.assertEqual(context["nativeContext"]["resolution"]["status"], "explicit")
        self.assertFalse(self.fixture.log.exists())
        code, response, socket, _, _ = self.invoke(context)
        self.assertEqual(code, 0, response)
        socket.assert_not_called()
        native = peer.handoff_validate_remote_response(response, context)
        self.assertEqual(native["status"], "queued")
        self.assertIs(native["submitted"], True)
        self.assertIs(native["consumptionConfirmed"], False)
        self.assertEqual(native["queueId"], "owned-queue-01")
        self.assertEqual(native["codexHomeResolution"], context["nativeContext"]["resolution"])
        command = json.loads(self.fixture.log.read_text())
        self.assertEqual(command["argv"][-1], "--message=" + peer.peer_delivery_message(self.body, "codex", None))

    def test_agent_specific_malformed_requests_refuse_before_native_discovery(self):
        cases = []
        codex = self.effect("codex")
        cases.append({**codex, "generation": self.generation})
        cases.append({**codex, "nativeContext": {"root": self.home, "resolution": {}}})
        claude = self.effect()
        cases.append({**claude, "nativeContext": {"root": self.home, "resolution": {}}})
        cases.append({**claude, "home": self.home})
        cases.append({**claude, "generation": None})
        for context in cases:
            with self.subTest(context=context):
                code, response, socket, discovery, _ = self.invoke(context)
                self.assertEqual(code, 1)
                socket.assert_not_called()
                discovery.assert_not_called()
                self.assertNotIn("submitted", response)
        self.assertFalse(self.fixture.log.exists())

    def test_private_handler_does_not_invent_notice_disabled_flag(self):
        context = self.context()
        argv = self.argv(context)
        argv.remove("--no-update-notice")
        code, response, socket, discovery, _ = self.invoke(context, argv)
        self.assertEqual(code, 2, response)
        socket.assert_not_called()
        discovery.assert_not_called()

    def test_wrong_original_claude_generation_is_zero_write_refusal(self):
        context = self.effect()
        context["generation"] = "tg1:" + "2" * 64
        code, response, socket, _, _ = self.invoke(context)
        self.assertEqual(code, 1, response)
        socket.assert_not_called()
        native = peer.handoff_validate_remote_response(response, context)
        self.assertEqual(native["reason"], "native_submission_refused")

    def test_context_nonce_phase_target_and_native_facts_cannot_be_promoted(self):
        context = self.effect("codex")
        _, original, _, _, _ = self.invoke(context)
        cases = []
        for key, value in (("requestId", str(uuid.uuid4())), ("phase", "probe"), ("generation", self.generation)):
            changed = copy.deepcopy(original)
            changed["handoffNative"][key] = value
            cases.append(changed)
        for key, value in (("target", {"agent": "codex", "id": str(uuid.uuid4())}),
                           ("consumptionConfirmed", True), ("codexHome", self.home + "-wrong"),
                           ("capability", "CORRUPTION_SENTINEL")):
            changed = copy.deepcopy(original)
            changed["handoffNative"]["native"][key] = value
            cases.append(changed)
        for response in cases:
            with self.subTest(response=response), self.assertRaises(peer.CcPeerError):
                peer.handoff_validate_remote_response(response, context)

    def test_explicit_probe_cannot_claim_auto_selected_resolution(self):
        context = self.context("codex")
        _, response, _, _, _ = self.invoke(context)
        proof = response["handoffNative"]
        for resolution in (proof["nativeContext"]["resolution"], proof["native"]["codexHomeResolution"]):
            resolution.update(status="selected", reason="single_stable_live_writer")
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_validate_remote_response(response, context)

    def test_negative_proof_has_closed_context_and_no_arbitrary_values(self):
        context = self.effect("codex")
        _, response, _, _, _ = self.invoke(context)
        response["ok"] = False
        response["handoffNative"]["native"] = {"ok": False, "reason": "native_outcome_unknown", "retryAllowed": False}
        peer.handoff_validate_remote_response(response, context)
        for key, value in (("nativeContext", {"secret": "CORRUPTION_SENTINEL"}),
                           ("generation", "CORRUPTION_SENTINEL")):
            changed = copy.deepcopy(response)
            changed["handoffNative"][key] = value
            with self.subTest(key=key), self.assertRaises(peer.CcPeerError):
                peer.handoff_validate_remote_response(changed, context)

    def test_remote_anchor_does_not_reset_on_late_effect_startup(self):
        context = self.effect()
        with mock.patch.object(peer, "handoff_remote_anchor", return_value={"boot": "owned-boot", "monotonicMs": 101999}):
            self.assertEqual(peer.handoff_remote_deadlines(context), (102, 107))
        with mock.patch.object(peer, "handoff_remote_anchor", return_value={"boot": "owned-boot", "monotonicMs": 102000}), \
                self.assertRaises(peer.CcPeerError):
            peer.handoff_remote_deadlines(context)

    def test_reboot_future_anchor_or_expiry_has_zero_native_effect(self):
        for change in ({"boot": "new-boot", "monotonicMs": 100000},
                       {"boot": "owned-boot", "monotonicMs": 99999},
                       {"boot": "owned-boot", "monotonicMs": 102000}):
            context = self.effect()
            with mock.patch.object(peer, "handoff_remote_anchor", return_value=change), \
                    mock.patch.object(peer, "discover") as discovery, \
                    mock.patch.object(peer, "post_to_socket") as socket, contextlib.redirect_stdout(io.StringIO()):
                args = peer.build_parser().parse_args(self.argv(context))
                self.assertEqual(peer.cmd_handoff_remote_native(args), 1)
            socket.assert_not_called()
            discovery.assert_not_called()

    def test_private_argv_cannot_dispatch_ordinary_send_or_mismatched_context(self):
        context = self.context()
        argv = [arg for arg in self.argv(context) if arg != "--json"]
        peer.handoff_validate_remote_argv(argv, context)
        for changed in (["send", "--to=4242", "--message=body"], argv + ["--request-ack"],
                        [arg.replace("--to=4242", "--to=4243") for arg in argv]):
            with self.subTest(argv=changed), self.assertRaises(peer.CcPeerError):
                peer.handoff_validate_remote_argv(changed, context)

    def test_private_context_booleans_floats_and_overflow_fail_closed(self):
        for field, value in (("remainingCutoffMs", True), ("remainingTotalMs", 1.0),
                             ("remainingCutoffMs", 60001), ("schemaVersion", True)):
            context = self.effect()
            context[field] = value
            encoded = base64.b64encode(peer.HandoffLedger.encode(context)).decode()
            with self.subTest(field=field), self.assertRaises(peer.CcPeerError):
                peer.handoff_remote_decode(encoded)

    def test_wrong_explicit_probe_canonical_home_rejected_by_mapping(self):
        context = self.context("codex")
        _, response, _, _, _ = self.invoke(context)
        proof = response["handoffNative"]
        wrong = self.home + "-wrong"
        proof["nativeContext"]["root"] = wrong
        proof["native"]["codexHome"] = wrong
        for resolution in (proof["nativeContext"]["resolution"], proof["native"]["codexHomeResolution"]):
            resolution["selected"] = wrong
            for candidate in resolution["candidates"]:
                if candidate["codexHome"] == self.home:
                    candidate["codexHome"] = wrong
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_validate_remote_response(response, context)

    def test_explicit_symlink_home_mapping_is_validated_on_receiver(self):
        alias = self.fixture.root / "owned-home-alias"
        alias.symlink_to(self.fixture.home, target_is_directory=True)
        context = self.context("codex")
        context["home"] = str(alias)
        code, response, _, _, _ = self.invoke(context)
        self.assertEqual(code, 0, response)
        self.assertEqual(response["handoffNative"]["homeSelection"], {"requested": str(alias), "canonical": self.home})
        peer.handoff_validate_remote_response(response, context)
        self.assertFalse(self.fixture.log.exists())

    def test_exact_five_second_reserve_is_required_before_native_discovery(self):
        original = self.effect()
        for reserve in (0, 4999, 5000):
            context = {**original, "remainingTotalMs": original["remainingCutoffMs"] + reserve}
            code, response, socket, discovery, _ = self.invoke(context)
            if reserve == 5000:
                self.assertEqual(code, 0, response)
                self.assertEqual(socket.call_count, 1)
            else:
                self.assertEqual(code, 1, response)
                socket.assert_not_called()
                discovery.assert_not_called()

    def test_interrupt_after_complete_native_return_retains_valid_submission_only(self):
        context = self.effect()
        actual = peer.handoff_remote_context_native
        calls = [0]
        def interrupted(*args):
            calls[0] += 1
            if calls[0] == 1:
                raise KeyboardInterrupt
            return actual(*args)
        with mock.patch.object(peer, "handoff_remote_context_native", side_effect=interrupted):
            code, response, socket, _, _ = self.invoke(context)
        self.assertEqual(code, 0, response)
        self.assertEqual(socket.call_count, 1)
        self.assertTrue(response["handoffNative"]["native"]["ok"])
        code, response, socket, _, _ = self.invoke(context, post=KeyboardInterrupt())
        self.assertEqual(code, 130, response)
        self.assertEqual(socket.call_count, 1)
        self.assertFalse(response["handoffNative"]["native"]["ok"])
        self.assertEqual(response["handoffNative"]["native"]["reason"], "native_outcome_unknown")

    def test_actual_owned_source_streamed_codex_submission_is_fenced_and_stripped(self):
        script = self.fixture.root / "owned-fake-ssh.py"
        script.write_text("import os,shlex,sys\nsource=sys.stdin.buffer.read()\n"
            + "scope={'__name__':'owned_source','__file__':" + repr(str(Path(peer.__file__).resolve())) + "}\n"
            + "exec(compile(source,'owned_stream','exec'),scope)\n"
            + "scope['known_codex_homes']=lambda *a,**k:[scope['Path'](" + repr(self.home) + ")]\n"
            + "def forbidden(*a,**k): raise AssertionError('remote ledger/receipt authority forbidden')\n"
            + "scope['handoff_root']=forbidden\nscope['handoff_ensure_collector']=forbidden\nscope['handoff_producer_command']=forbidden\n"
            + "sys.argv=['owned_stream']+shlex.split(sys.argv[-1])[2:]\n"
            + "raise SystemExit(scope['main']())\n")
        actual = peer.handoff_stream_child
        effect_count = [0]
        def streamed(argv, source, cutoff, total, clock, **kwargs):
            if argv[:2] == ["ssh", "-G"]:
                return peer.HandoffProcessResult(b"user operator\nhostname fixture\nport 22\n", b"", 0, None, True, False, False, False, False)
            remote = shlex.split(argv[-1])[2:]
            encoded = next(value.split("=", 1)[1] for value in remote if value.startswith("--_handoff-native-context="))
            context = peer.handoff_remote_decode(encoded)
            if context["phase"] == "effect":
                effect_count[0] += 1
                with self.fixture.ledger.transaction() as state:
                    record = next(iter(state["records"].values()))
                    self.assertEqual(record["phase"], "attempted")
                    self.assertEqual(record["submission"], "unknown")
            return actual([sys.executable, "-I", str(script), argv[-1]], source, cutoff, total, clock,
                env={"PATH": "/usr/bin:/bin", "HOME": str(self.fixture.root), "LANG": "C.UTF-8"})
        metadata = {"to": "codex:" + self.thread, "host": ["operator@fixture"], "codexHome": self.home,
                    "body": self.body, "tailnet": {}, "address": None}
        argv = ["send", "--host=operator@fixture", "--to=codex:" + self.thread,
                "--message=" + self.body, "--codex-home=" + self.home,
                "--codex-bin=" + str(self.fixture.fake), "--allow-inactive-codex-home",
                "--request-ack", "--observe-delivery", "--no-from", "--no-reply-to", "--no-update-notice", "--json"]
        output = io.StringIO()
        with mock.patch.object(peer, "handoff_sender_preflight", return_value=metadata), \
                mock.patch.object(peer, "handoff_root", return_value=self.fixture.ledger.root), \
                mock.patch.object(peer, "handoff_stream_child", side_effect=streamed), \
                contextlib.redirect_stdout(output):
            code = peer.main(argv)
        response = json.loads(output.getvalue())
        self.assertEqual(code, 0, response)
        self.assertEqual(effect_count[0], 1)
        self.assertEqual(response["status"], "queued")
        self.assertTrue(response["submitted"])
        self.assertFalse(response["consumptionConfirmed"])
        self.assertEqual(response["queueId"], "owned-queue-01")
        self.assertIsNone(response["handoff"]["targetGeneration"])
        self.assertEqual(response["handoff"]["ack"]["status"], "unsupported")
        for secret in ("handoffNative", "nativeContext", "homeSelection", "monotonicMs", "capability"):
            self.assertNotIn(secret, json.dumps(response))
        _, record = self.fixture.ledger.record(response["handoff"]["correlationId"])
        self.assertIsNone(record["capability"])
        self.assertEqual(record["binding"]["destination"], ["operator@fixture"])
        output = io.StringIO()
        with mock.patch.object(peer, "handoff_root", return_value=self.fixture.ledger.root), \
                mock.patch.object(peer, "handoff_sender_preflight") as metadata_child, \
                mock.patch.object(peer, "handoff_stream_child") as native_child, contextlib.redirect_stdout(output):
            again = peer.main(argv + ["--correlation-id=" + response["handoff"]["correlationId"]])
        self.assertEqual(again, 1)
        metadata_child.assert_not_called()
        native_child.assert_not_called()

    def sender(self, extra=(), agent="codex", failure=None):
        target = "codex:" + self.thread if agent == "codex" else "4242"
        metadata = {"to": target, "host": ["operator@fixture"], "codexHome": self.home if agent == "codex" else None,
                    "body": self.body, "tailnet": {}, "address": None}
        argv = ["send", "--host=operator@fixture", "--to=" + target, "--message=" + self.body,
                "--request-ack", "--observe-delivery", "--no-from", "--no-reply-to", "--no-update-notice", "--json"]
        if agent == "codex":
            argv += ["--codex-home=" + self.home, "--codex-bin=" + str(self.fixture.fake), "--allow-inactive-codex-home"]
        stages = []
        def execute(transport, private_argv, *, handoff_budget, handoff_context):
            stages.append(handoff_context["phase"])
            self.assertEqual(handoff_budget[1] - handoff_budget[0], 5)
            if handoff_context["phase"] == "effect":
                _, record = self.fixture.ledger.record(next(iter(json.loads((self.fixture.ledger.root / "ledger.json").read_text())["records"])))
                self.assertEqual(record["phase"], "attempted")
                if failure:
                    return failure(handoff_context, private_argv)
            code, response, _, _, _ = self.invoke(handoff_context, private_argv + ["--json"])
            return peer.handoff_validate_remote_response(response, handoff_context)
        output = io.StringIO()
        with mock.patch.object(peer, "handoff_sender_preflight", return_value=metadata) as preflight, \
                mock.patch.object(peer, "handoff_root", return_value=self.fixture.ledger.root), \
                mock.patch.object(peer.SshTransport, "execute", new=execute), contextlib.redirect_stdout(output):
            code = peer.main(argv + list(extra))
        return code, json.loads(output.getvalue()), stages, preflight

    def test_required_remote_ack_or_delivered_refuses_before_any_metadata_or_ssh(self):
        for goal in ("acknowledged", "delivered"):
            code, response, stages, preflight = self.sender(["--wait-for=" + goal])
            self.assertEqual(code, 1, response)
            self.assertEqual(stages, [])
            preflight.assert_not_called()
            self.assertEqual(response["handoff"]["submission"]["status"], "refused")
            self.assertEqual(response["handoff"]["wait"]["status"], "unsupported")
            self.assertNotIn("submitted", response)

    def test_codex_generation_pin_is_not_silently_dropped(self):
        code, response, stages, preflight = self.sender(["--target-generation=" + self.generation])
        self.assertEqual(code, 1, response)
        self.assertEqual(stages, [])
        preflight.assert_not_called()
        self.assertEqual(response["reason"], "unsupported_target_generation")
        self.assertFalse(json.loads((self.fixture.ledger.root / "ledger.json").read_text())["records"])

    def test_sender_claude_preserves_legacy_optional_absence_without_remote_authority(self):
        code, response, stages, _ = self.sender(agent="claude")
        self.assertEqual(code, 0, response)
        self.assertEqual(stages, ["probe", "effect"])
        self.assertEqual(response["target"]["pid"], 4242)
        self.assertEqual(response["handoff"]["targetGeneration"], self.generation)
        self.assertEqual(response["handoff"]["ack"]["status"], "unsupported")
        for field in ("submitted", "status", "consumptionConfirmed", "handoffNative", "capability"):
            self.assertNotIn(field, response)

    def test_transport_unknown_is_fenced_and_never_produces_native_positive_facts(self):
        def failed(context, argv):
            raise peer.CcPeerError("private fixture diagnostic must not escape", {"spawned": None, "interrupted": True})
        code, response, stages, _ = self.sender(failure=failed)
        self.assertEqual(code, 130, response)
        self.assertEqual(stages, ["probe", "effect"])
        self.assertEqual(response["handoff"]["submission"]["status"], "unknown")
        self.assertFalse(response["handoff"]["retry"]["allowed"])
        self.assertNotIn("target", response)
        self.assertNotIn("private fixture", json.dumps(response))

    def test_identity_error_proof_revalidated_before_preserving_native_facts(self):
        def missing(context, argv):
            _, response, _, _, _ = self.invoke(context, argv + ["--json"])
            normalized = peer.handoff_validate_remote_response(response, context)
            raise peer.CcPeerError("missing connection receipt", {**normalized, "reason": "ssh_identity_evidence_unavailable"})
        code, response, stages, _ = self.sender(failure=missing)
        self.assertEqual(code, 0, response)
        self.assertTrue(response["submitted"])
        self.assertEqual(response["reason"], "ssh_identity_evidence_unavailable")
        self.assertNotIn("handoffNative", response)
        self.assertEqual(stages.count("effect"), 1)

    def test_post_submission_sender_validation_interrupt_retains_validated_facts(self):
        original = peer.handoff_remote_evidence
        calls = [0]
        def stopped(*args):
            calls[0] += 1
            if calls[0] == 1:
                raise KeyboardInterrupt
            return original(*args)
        with mock.patch.object(peer, "handoff_remote_evidence", side_effect=stopped):
            code, response, stages, _ = self.sender()
        self.assertEqual(code, 0, response)
        self.assertTrue(response["submitted"])
        self.assertEqual(stages, ["probe", "effect"])

    def test_sender_metadata_failure_is_before_ledger_or_remote_effect(self):
        args = peer.build_parser().parse_args(["send", "--host=operator@fixture", "--to=4242",
                    "--message=" + self.body, "--request-ack", "--no-from", "--no-reply-to", "--no-update-notice", "--json"])
        for failure, code in ((peer.handoff_error("sender_preflight_unavailable"), 1), (KeyboardInterrupt(), 130)):
            output = io.StringIO()
            with mock.patch.object(peer, "handoff_sender_preflight", side_effect=failure), \
                    mock.patch.object(peer, "handoff_root", return_value=self.fixture.ledger.root), \
                    mock.patch.object(peer.SshTransport, "execute") as remote, contextlib.redirect_stdout(output):
                if isinstance(failure, KeyboardInterrupt):
                    actual = peer.cmd_handoff_send(args)
                else:
                    with self.assertRaises(peer.CcPeerError):
                        peer.cmd_handoff_send(args)
                    actual = 1
            self.assertEqual(actual, code)
            remote.assert_not_called()
            self.assertFalse(json.loads((self.fixture.ledger.root / "ledger.json").read_text())["records"])

    def test_agent_specific_context_refuses_before_sender_config_or_source_child(self):
        for original in (self.effect(), self.effect("codex")):
            cases = [{**original, "remainingTotalMs": original["remainingCutoffMs"] + 4999}]
            if original["agent"] == "claude":
                cases += [{**original, "generation": None}, {**original, "home": self.home}]
            else:
                cases += [{**original, "generation": self.generation}, {**original, "nativeContext": {"root": self.home, "resolution": {}}}]
            for context in cases:
                argv = [value for value in self.argv(context) if value != "--json"]
                for pinned in (False, True):
                    with self.subTest(agent=context["agent"], pinned=pinned), \
                            mock.patch.object(peer, "ssh_identity_configuration") as configuration, \
                            mock.patch.object(peer, "ssh_user_metadata") as user, \
                            mock.patch.object(peer, "handoff_stream_child") as child, self.assertRaises(peer.CcPeerError):
                        runner = peer.run_remote_with_identity if pinned else peer.run_remote
                        runner("operator@fixture", argv, [], handoff_budget=(peer.handoff_now() + 10, peer.handoff_now() + 15), handoff_context=context)
                    configuration.assert_not_called()
                    user.assert_not_called()
                    child.assert_not_called()

    def test_prepared_ssh_self_uri_keeps_original_digest_deadline_and_local_ack_route(self):
        import hashlib
        uri = "session-peer://v1/reply?agent=claude&session=4242&transport=ssh&host=operator%40fixture"
        parsed = peer.parse_reply_address(uri)
        binding = {"agent": "claude", "destination": ["local"], "target": "4242", "home": None,
                   "payloadDigest": hashlib.sha256(self.body.encode()).hexdigest()}
        epoch, prepared = self.fixture.ledger.prepare(binding, self.generation)
        clock = str(uuid.uuid4())
        wrapped = "From: owned fixture\n\n" + self.body
        metadata = {"to": parsed["target"], "host": [], "codexHome": None, "body": wrapped, "tailnet": {},
                    "address": {**parsed, "transport": "local", "normalizedFrom": "ssh_self"},
                    "routing": {"addressResolution": {"uri": uri, "transport": "local", "normalizedFrom": "ssh_self"}}}
        def ipc(root, frame, *args):
            return peer.handoff_collect(self.fixture.ledger, clock, frame)
        def posted(path, text, **kwargs):
            # Owned direct collector fixture, not a model response or live TUI.
            raw = text.split("using this private JSON on stdin (never as argv):\n", 1)[1]
            peer.handoff_collect(self.fixture.ledger, clock, json.loads(raw))
            self.assertTrue(text.startswith(peer.peer_delivery_message(wrapped, "claude")))
            self.assertEqual(text.count("From: owned fixture"), 1)
        argv = ["send", "--to=" + uri, "--message=" + self.body, "--correlation-id=" + prepared["id"],
                "--request-ack", "--wait-for=acknowledged", "--wait-timeout=10", "--no-update-notice", "--json"]
        output = io.StringIO()
        with mock.patch.object(peer, "handoff_root", return_value=self.fixture.ledger.root), \
                mock.patch.object(peer, "handoff_sender_preflight", return_value=metadata) as preflight, \
                mock.patch.object(peer, "discover", return_value=[self.session]), \
                mock.patch.object(peer, "claude_generation", return_value=self.generation), \
                mock.patch.object(peer, "require_claude_generation"), \
                mock.patch.object(peer, "handoff_producer_command", return_value=["owned-receipt-handler"]), \
                mock.patch.object(peer, "handoff_ensure_collector"), \
                mock.patch.object(peer, "handoff_channel_epoch", return_value=clock), \
                mock.patch.object(peer, "handoff_ipc", side_effect=ipc), \
                mock.patch.object(peer, "post_to_socket", side_effect=posted) as post, \
                mock.patch.object(peer.SshTransport, "execute") as ssh, contextlib.redirect_stdout(output):
            code = peer.main(argv)
        response = json.loads(output.getvalue())
        self.assertEqual(code, 0, response)
        self.assertEqual(response["handoff"]["state"], "acknowledged")
        self.assertEqual(response["handoff"]["correlationId"], prepared["id"])
        self.assertEqual(response["addressResolution"]["normalizedFrom"], "ssh_self")
        self.assertEqual(preflight.call_count, 1)
        post.assert_called_once()
        ssh.assert_not_called()
        self.assertLessEqual(preflight.call_args.args[2] + 5, peer.handoff_now() + 10)

    def test_bounded_metadata_child_private_body_and_original_deadline(self):
        script = self.fixture.root / "owned-metadata-child.py"
        script.write_text("import sys\n"
            + "scope={'__name__':'owned_source','__file__':" + repr(str(Path(peer.__file__).resolve())) + "}\n"
            + "exec(compile(open(scope['__file__']).read(),'owned_source','exec'),scope)\n"
            + "scope['tailscale_status']=lambda:{}\n"
            + "raise SystemExit(scope['handoff_sender_preflight_child'](float(sys.argv[-1])))\n")
        actual, executable = peer.handoff_stream_child, sys.executable
        captured = []
        def child(argv, source, cutoff, total, clock):
            captured.append((argv, source, cutoff, total))
            return actual([executable, "-I", str(script), argv[-1]], source, cutoff, total, clock,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(self.fixture.root), "LANG": "C.UTF-8"})
        args = peer.build_parser().parse_args(["send", "--host=operator@fixture", "--to=4242",
                        "--message=" + self.body, "--no-from", "--no-reply-to", "--no-update-notice"])
        cutoff, total = peer.handoff_now() + 2, peer.handoff_now() + 7
        # Owned executable wrapper protects fixture bootstrap without relaxing
        # the production interpreter/source ownership check in hosted CI.
        with mock.patch.object(peer.sys, "executable", str(self.fixture.fake)), \
                mock.patch.object(peer, "handoff_stream_child", side_effect=child):
            result = peer.handoff_sender_preflight(args, self.body, cutoff, total)
        self.assertEqual(result["body"], self.body)
        self.assertEqual(result["host"], ["operator@fixture"])
        self.assertEqual(result["routing"], {})
        self.assertEqual(captured[0][2:], (cutoff, total))
        self.assertNotIn(self.body, " ".join(captured[0][0]))
        self.assertEqual(json.loads(captured[0][1])["body"], self.body)

    def test_missing_key_receipt_retains_closed_identity_and_native_snapshot(self):
        identity = {"schemaVersion": 1, "status": "unknown", "destination": "fixture", "port": 22, "keyLookupName": "fixture"}
        def failed(context, argv):
            _, response, _, _, _ = self.invoke(context, argv + ["--json"])
            normalized = peer.handoff_validate_remote_response(response, context)
            raise peer.CcPeerError("missing connection receipt", {**normalized, "sshIdentity": identity})
        code, response, _, _ = self.sender(failure=failed)
        self.assertEqual(code, 0, response)
        self.assertTrue(response["submitted"])
        self.assertEqual(response["sshIdentity"], identity)
        self.assertFalse(response["retryAllowed"])


if __name__ == "__main__":
    unittest.main()
