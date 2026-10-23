"""Offline lifecycle I/O with controlled metadata, not native-volume certification."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import session_peer as peer


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "POSIX address storage")
class AddressFlowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-address-flow-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)})
        patch.start()
        self.addCleanup(patch.stop)
        # The prescribed external-volume ancestors are group writable and may
        # ignore ownership. Model those pre-existing ancestors for lifecycle
        # tests; production refuses them and separate native guard tests remain.
        ownership = mock.patch.object(peer, "_preset_check_ownership")
        ownership.start()
        self.addCleanup(ownership.stop)
        real_fstat = os.fstat
        modeled = {(p.stat().st_dev, p.stat().st_ino) for p in self.root.parents
                   if p.stat().st_uid == os.geteuid() and p.stat().st_mode & 0o022}
        def metadata(fd):
            info = real_fstat(fd)
            if (info.st_dev, info.st_ino) in modeled:
                fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                fields["st_mode"] &= ~0o022
                return SimpleNamespace(**fields)
            return info
        metadata_patch = mock.patch.object(peer.os, "fstat", side_effect=metadata)
        metadata_patch.start()
        self.addCleanup(metadata_patch.stop)
        self.route = {"transport": "local", "agent": "claude"}
        self.preset = peer.preset_mutate("add", "work", self.route)
        self.generation = "tg1:" + "a" * 64
        self.probe = mock.patch.object(peer, "address_probe_route", side_effect=self.probe_route)
        self.probe_mock = self.probe.start()
        self.addCleanup(self.probe.stop)

    def probe_route(self, route, targets, expected_ssh_key=None):
        return {"sshHostKey": "SHA256:" + "A" * 43 if route["transport"] == "ssh" else None,
            "selections": [{"requestedTarget": target, "ok": True,
            "recipient": {"agent": "claude", "target": "claude:42", "home": None},
            "selection": {"generationStatus": "available", "targetGeneration": self.generation,
                          "writerRevision": None, "observationRevision": None}} for target in targets]}

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = peer.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()

    def add(self, name="research"):
        code, resolved, _ = self.invoke(["address", "resolve", "--preset", "work", "--to", "worker", "--json"])
        self.assertEqual(code, 0)
        code, added, _ = self.invoke(["address", "add", name, "--preset", "work", "--to", "worker",
            "--expect-selection", resolved["selection"]["observationRevision"], "--json"])
        self.assertEqual(code, 0, added)
        return added

    def test_resolve_add_show_and_real_send_uses_saved_canonical_target(self):
        added = self.add()
        with mock.patch.object(peer.LocalTransport, "execute", return_value={"ok": True, "dryRun": False,
                "target": {"pid": 42, "name": "worker"}, "chars": 1}) as submission:
            code, _, _ = self.invoke(["send", "--address", "research", "--address-revision", added["revision"],
                "--confirm-target", "claude:42", "--message", "x", "--json", "--no-from", "--no-reply-to"])
        self.assertEqual(code, 0)
        args = submission.call_args.args[2]
        self.assertEqual(args.to, "42")
        self.assertEqual(args.target_generation, self.generation)

    def test_invalid_label_and_selection_revision_never_probe(self):
        for extra in (["--label", "bad\u202elabel", "--expect-selection", "as1:" + "a" * 64],
                      ["--label", "Worker", "--expect-selection", "invalid"]):
            self.probe_mock.reset_mock()
            code, result, _ = self.invoke(["address", "add", "new", "--preset", "work", "--to", "worker", "--json", *extra])
            self.assertEqual(code, 1)
            self.assertFalse(result["ok"])
            self.probe_mock.assert_not_called()

    def test_invalid_send_revision_fails_before_storage_or_message_input(self):
        with mock.patch.object(peer, "address_lookup", side_effect=AssertionError("store")), \
                mock.patch.object(peer, "read_message", side_effect=AssertionError("body")):
            code, _, _ = self.invoke(["send", "--address", "research", "--address-revision", "invalid",
                                     "--confirm-target", "claude:42", "--message", "fixture", "--json"])
        self.assertEqual(code, 2)

    def test_preview_needs_no_confirmation_and_reads_no_body_before_selection(self):
        self.add()
        self.generation = "tg1:" + "b" * 64
        with mock.patch.object(peer, "read_message", side_effect=AssertionError("body")), \
                mock.patch.object(peer.LocalTransport, "execute", side_effect=AssertionError("send")):
            code, payload, _ = self.invoke(["send", "--address", "research", "--dry-run", "--message", "x", "--json"])
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["reason"], "address_selection_changed")

    def test_stale_route_never_queries_saved_route(self):
        self.add()
        peer.preset_mutate("replace", "work", {"transport": "ssh", "agent": "claude", "host": "other"}, self.preset["revision"])
        self.probe_mock.reset_mock()
        code, payload, _ = self.invoke(["address", "discover", "--address", "research", "--json"])
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["addresses"][0]["status"], "stale")
        self.probe_mock.assert_not_called()

    def test_deleted_preset_is_stale_and_send_never_uses_saved_route(self):
        self.add()
        peer.preset_mutate("remove", "work", expected_revision=self.preset["revision"])
        self.probe_mock.reset_mock()
        code, payload, _ = self.invoke(["address", "discover", "--address", "research", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["addresses"][0]["status"], "stale")
        self.assertEqual(payload["addresses"][0]["reason"], "address_preset_changed")
        with mock.patch.object(peer, "read_message", side_effect=AssertionError("body")):
            code, payload, _ = self.invoke(["send", "--address", "research", "--dry-run", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["reason"], "address_preset_changed")
        self.probe_mock.assert_not_called()

    def test_metadata_transport_errors_never_escape_text_or_json_lifecycle(self):
        self.route = {"transport": "ssh", "agent": "claude", "host": "fixture"}
        self.preset = peer.preset_mutate("replace", "work", self.route, self.preset["revision"])
        added = self.add()
        self.probe.stop()
        commands = [
            ["address", "resolve", "--preset", "work", "--to", "worker"],
            ["address", "add", "new", "--preset", "work", "--to", "worker", "--expect-selection", "as1:" + "a" * 64],
            ["address", "reselect", "research", "--to", "worker", "--expect-revision", added["revision"],
             "--expect-selection", "as1:" + "a" * 64],
            ["send", "--address", "research", "--dry-run", "--message", "fixture"]]
        for command in commands:
            for encoded in (False, True):
                output, error = io.StringIO(), io.StringIO()
                argv = command + (["--json"] if encoded else [])
                with mock.patch.object(peer, "tailscale_status", return_value={}), \
                        mock.patch.object(peer, "SshTransport") as transport, \
                        mock.patch.object(peer, "read_message", side_effect=AssertionError("body")), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    transport.return_value.execute.side_effect = peer.CcPeerError(
                        "PRIVATE remote stderr", {"error": "PRIVATE path", "reason": "PRIVATE reason"})
                    self.assertEqual(peer.main(argv), 1)
                rendered = output.getvalue() + error.getvalue()
                self.assertNotIn("PRIVATE", rendered)
                self.assertIn("address_selection_unavailable", rendered)
                if encoded:
                    self.assertEqual(json.loads(output.getvalue())["reason"], "address_selection_unavailable")

    def test_ssh_address_send_pins_saved_key_and_forwards_generation_or_writer(self):
        key = "SHA256:" + "A" * 43
        thread = "00000000-0000-4000-8000-000000000001"
        for agent in ("claude", "codex"):
            name = "saved" + agent
            preset = "route" + agent
            route = {"transport": "ssh", "agent": agent, "host": "fixture"}
            if agent == "codex":
                route["codexHome"] = "/fixture/home"
            saved_preset = peer.preset_mutate("add", preset, route)
            recipient = {"agent": agent, "target": "claude:42" if agent == "claude" else "codex:" + thread,
                         "home": None if agent == "claude" else "/fixture/home"}
            selection = {"generationStatus": "available" if agent == "claude" else "unsupported",
                         "targetGeneration": self.generation if agent == "claude" else None,
                         "writerRevision": "aw1:" + "a" * 64 if agent == "codex" else None,
                         "observationRevision": None}
            selection["observationRevision"] = peer.address_selection_revision(
                preset, saved_preset["revision"], route, recipient, selection, key)
            added = peer.address_mutate("add", name, {"label": name, "preset": preset,
                "presetRevision": saved_preset["revision"], "route": route, "recipient": recipient,
                "selection": selection, "sshHostKey": key})
            probe_selection = {**selection, "observationRevision": None}
            probe = {"sshHostKey": key, "selections": [{"requestedTarget": recipient["target"], "ok": True,
                "recipient": recipient, "selection": probe_selection}]}
            native = {"ok": True, "dryRun": False, "target": {"pid": 42, "name": "worker"} if agent == "claude" else
                      {"agent": "codex", "id": thread}, "chars": 1}
            if agent == "claude":
                native["targetGeneration"] = self.generation
            command = ["send", "--address", name, "--address-revision", added["revision"],
                       "--confirm-target", recipient["target"], "--message", "x", "--json", "--no-from", "--no-reply-to"]
            with mock.patch.object(peer, "address_probe_route", return_value=probe) as metadata, \
                    mock.patch.object(peer, "tailscale_status", return_value={}), \
                    mock.patch.object(peer, "SshTransport") as transport:
                transport.return_value.host = "fixture"
                transport.return_value.ssh_opts = []
                transport.return_value.execute.return_value = native
                code, payload, error = self.invoke(command)
            self.assertEqual(code, 0, (agent, payload, error))
            metadata.assert_called_once_with(route, [recipient["target"]], key)
            options = transport.call_args.args[1]
            self.assertEqual(options.require_ssh_host_key, key)
            self.assertTrue(options.ssh_identity)
            argv = transport.return_value.execute.call_args.args[0]
            parsed = peer.build_parser().parse_args(argv)
            if agent == "claude":
                self.assertEqual(parsed.target_generation, self.generation)
            else:
                self.assertEqual(parsed._address_expected_writer, selection["writerRevision"])
                self.assertEqual(parsed.codex_home, "/fixture/home")
            with mock.patch.object(peer, "address_probe_route", return_value={**probe, "sshHostKey": "SHA256:" + "B" * 42 + "A"}), \
                    mock.patch.object(peer, "SshTransport") as transport, \
                    mock.patch.object(peer, "read_message", side_effect=AssertionError("body")):
                code, refused, _ = self.invoke(command)
            self.assertEqual(code, 1)
            self.assertEqual(refused["reason"], "address_selection_changed")
            transport.assert_not_called()

    def test_same_route_discovery_is_grouped_and_explicit_only(self):
        self.add("research")
        self.add("review")
        self.add("ignored")
        self.probe_mock.reset_mock()
        code, payload, _ = self.invoke(["address", "discover", "--address", "research", "--address", "review", "--json"])
        self.assertEqual(code, 0)
        self.probe_mock.assert_called_once_with(self.route, ["claude:42"], None)
        self.assertEqual([row["name"] for row in payload["addresses"]], ["research", "review"])

    def test_partial_discovery_preserves_success(self):
        self.add()
        code, payload, _ = self.invoke(["address", "discover", "--address", "research", "--address", "missing", "--json"])
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["addresses"][0]["status"], "matched")
        self.assertEqual(payload["addresses"][1]["status"], "unverified")

    def test_changed_selection_requires_explicit_reselect(self):
        added = self.add()
        self.generation = "tg1:" + "b" * 64
        _, resolved, _ = self.invoke(["address", "resolve", "--preset", "work", "--to", "worker", "--json"])
        code, changed, _ = self.invoke(["address", "reselect", "research", "--expect-revision", added["revision"],
            "--to", "worker", "--expect-selection", resolved["selection"]["observationRevision"], "--json"])
        self.assertEqual(code, 0)
        self.assertNotEqual(changed["revision"], added["revision"])
        self.assertNotEqual(changed["entry"]["bindingId"], added["entry"]["bindingId"])

    def test_conflicting_override_rejected_before_store_or_probe(self):
        for extra in (["--to", "42"], ["--host", "fixture"], ["--codex-home", "/home/other"], ["--wake"]):
            with self.subTest(extra=extra), mock.patch.object(peer, "address_lookup", side_effect=AssertionError("store")):
                code, _, error = self.invoke(["send", "--address", "research", "--dry-run", "--message", "x", *extra])
            self.assertEqual(code, 2)
            self.assertIn("--address conflicts", error)

    def test_actual_send_requires_revision_and_current_target_confirmation(self):
        with mock.patch.object(peer, "address_lookup", side_effect=AssertionError("store")):
            code, _, error = self.invoke(["send", "--address", "research", "--message", "x"])
        self.assertEqual(code, 2)
        self.assertIn("require --address-revision and --confirm-target", error)

    def test_no_address_means_no_address_store_io(self):
        with mock.patch.object(peer, "address_lookup", side_effect=AssertionError("store")), \
                mock.patch.object(peer, "address_read", side_effect=AssertionError("store")), \
                mock.patch.object(peer, "cmd_list", return_value=0):
            code, _, _ = self.invoke(["list"])
        self.assertEqual(code, 0)
