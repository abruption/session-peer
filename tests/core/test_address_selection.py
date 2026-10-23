"""Address snapshots use existing metadata, never native delivery probes."""
import argparse
import copy
from pathlib import Path
import unittest
from unittest import mock

import session_peer as peer


THREAD = "00000000-0000-4000-8000-000000000001"


class AddressSelectionTests(unittest.TestCase):
    def setUp(self):
        # Pure metadata fixtures model a supported platform explicitly.
        self.real_platform = peer.address_platform
        platform = mock.patch.object(peer, "address_platform")
        platform.start()
        self.addCleanup(platform.stop)

    def test_real_unsupported_platform_refuses_before_discovery(self):
        args = argparse.Namespace(agent="claude", to=["worker"], codex_home=None)
        with mock.patch.object(peer, "address_platform", self.real_platform), \
                mock.patch.object(peer, "IS_WINDOWS", True), \
                mock.patch.object(peer, "discover") as discover:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.address_inspect_selection(args)
        self.assertEqual(caught.exception.details["reason"], "address_platform_unsupported")
        discover.assert_not_called()

    def resolution(self):
        return {"selected": "/fixture/home", "candidates": [{"codexHome": "/fixture/home",
            "activity": "live_writer", "writerLock": "held", "ownerStable": True,
            "ownerPid": 42, "ownerStartTime": 123456}]}

    def test_writer_revision_changes_with_owner_and_thread(self):
        original = self.resolution()
        first = peer.address_codex_writer_revision("/fixture/home", THREAD, original)
        self.assertRegex(first, r"^aw1:[0-9a-f]{64}$")
        changed = copy.deepcopy(original)
        changed["candidates"][0]["ownerStartTime"] += 1
        self.assertNotEqual(first, peer.address_codex_writer_revision("/fixture/home", THREAD, changed))
        self.assertNotEqual(first, peer.address_codex_writer_revision("/fixture/home", "another", original))

    def test_invalid_writer_evidence_refuses(self):
        for key, value in [("ownerPid", True), ("ownerPid", 1), ("ownerStable", False),
                           ("ownerStartTime", float("nan")), ("ownerStartTime", "\x1bsecret"),
                           ("activity", "inactive"), ("writerLock", "unknown")]:
            with self.subTest(key=key, value=value):
                resolution = self.resolution()
                resolution["candidates"][0][key] = value
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.address_codex_writer_revision("/fixture/home", THREAD, resolution)
                self.assertFalse(caught.exception.details["submitted"])

    def test_require_writer_optout_does_not_inspect(self):
        with mock.patch.object(peer, "address_codex_writer_revision", side_effect=AssertionError("probe")):
            peer.require_address_writer(argparse.Namespace(), None, None, None)

    def test_changed_writer_refuses_without_retry(self):
        args = argparse.Namespace(_address_expected_writer="aw1:" + "0" * 64)
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.require_address_writer(args, "/fixture/home", THREAD, self.resolution())
        self.assertEqual(caught.exception.details["reason"], "address_writer_changed")
        self.assertFalse(caught.exception.details["retryAllowed"])

    def test_claude_inspection_discovers_once_and_never_submits(self):
        args = argparse.Namespace(agent="claude", to=["worker", "claude:42"], codex_home=None)
        row = {"pid": 42}
        with mock.patch.object(peer, "discover", return_value=[row]) as discovery, \
                mock.patch.object(peer, "resolve_target", return_value=row), \
                mock.patch.object(peer, "claude_generation", return_value="tg1:" + "a" * 64), \
                mock.patch.object(peer, "codex_executable", side_effect=AssertionError("native")), \
                mock.patch.object(peer, "read_message", side_effect=AssertionError("body")):
            result = peer.address_inspect_selection(args)
        discovery.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["selections"][0]["recipient"], {"agent": "claude", "target": "claude:42", "home": None})

    def test_claude_missing_generation_is_closed(self):
        args = argparse.Namespace(agent="claude", to=["worker"], codex_home=None)
        with mock.patch.object(peer, "discover", return_value=[]), \
                mock.patch.object(peer, "resolve_target", return_value={"pid": 42}), \
                mock.patch.object(peer, "claude_generation", return_value=None):
            result = peer.address_inspect_selection(args)
        self.assertFalse(result["ok"])
        self.assertNotIn("recipient", result["selections"][0])

    def test_partial_profile_discovery_refuses_names_but_preserves_literal_pid(self):
        class Rows(list):
            errors = ["PRIVATE unreadable profile"]
        args = argparse.Namespace(agent="claude", to=["worker", "claude:42", "42"], codex_home=None)
        with mock.patch.object(peer, "discover", return_value=Rows([{"pid": 42}])), \
                mock.patch.object(peer, "resolve_target", return_value={"pid": 42}) as resolve, \
                mock.patch.object(peer, "claude_generation", return_value="tg1:" + "a" * 64):
            result = peer.address_inspect_selection(args)
        self.assertEqual([row["ok"] for row in result["selections"]], [False, True, True])
        self.assertEqual(resolve.call_count, 2)
        self.assertNotIn("PRIVATE", repr(result))

    def test_codex_inspection_never_fabricates_generation(self):
        args = argparse.Namespace(agent="codex", to=["codex:" + THREAD], codex_home="/fixture/home")
        with mock.patch.object(peer, "codex_home", return_value=peer.PurePosixPath("/fixture/home")), \
                mock.patch.object(peer, "resolve_codex_home", return_value=(peer.PurePosixPath("/fixture/home"), self.resolution())), \
                mock.patch.object(peer, "codex_executable", side_effect=AssertionError("native")), \
                mock.patch.object(peer.subprocess, "run", side_effect=AssertionError("effect")):
            result = peer.address_inspect_selection(args)
        self.assertTrue(result["ok"])
        selection = result["selections"][0]["selection"]
        self.assertEqual(selection["generationStatus"], "unsupported")
        self.assertIsNone(selection["targetGeneration"])
        self.assertNotIn("ownerPid", repr(result))

    def wire(self):
        return {"selectionSchemaVersion": 1, "homeSelector": None, "ok": True, "selections": [{
            "requestedTarget": "worker", "ok": True,
            "recipient": {"agent": "claude", "target": "claude:42", "home": None},
            "selection": {"generationStatus": "available", "targetGeneration": "tg1:" + "a" * 64,
                          "writerRevision": None, "observationRevision": None}}]}

    def test_probe_rejects_missing_connection_identity(self):
        route = {"agent": "claude", "transport": "ssh", "host": "fixture"}
        with mock.patch.object(peer, "_preset_platform"), \
                mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport") as transport:
            transport.return_value.execute.return_value = self.wire()
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.address_probe_route(route, ["worker"])
        self.assertEqual(caught.exception.details["reason"], "address_ssh_identity_unverified")

    def test_probe_single_metadata_ssh_operation(self):
        route = {"agent": "claude", "transport": "ssh", "host": "fixture"}
        result = self.wire()
        key = "SHA256:" + "a" * 43
        result["sshIdentity"] = {"status": "verified", "fingerprint": key}
        with mock.patch.object(peer, "_preset_platform"), \
                mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "remote_installed_version", side_effect=AssertionError("version")), \
                mock.patch.object(peer, "SshTransport") as transport:
            transport.return_value.execute.return_value = result
            probe = peer.address_probe_route(route, ["worker"], key)
        self.assertEqual(probe["sshHostKey"], key)
        transport.return_value.execute.assert_called_once_with(["address", "_inspect", "--agent", "claude", "--json", "--to=worker"])

    def test_dash_prefixed_remote_selector_uses_equals_argument(self):
        route = {"agent": "claude", "transport": "ssh", "host": "fixture"}
        result = self.wire()
        result["selections"][0]["requestedTarget"] = "-worker"
        result["sshIdentity"] = {"status": "verified", "fingerprint": "SHA256:" + "A" * 43}
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport") as transport:
            transport.return_value.execute.return_value = result
            peer.address_probe_route(route, ["-worker"])
        argv = transport.return_value.execute.call_args.args[0]
        parsed = peer.build_parser().parse_args(argv)
        self.assertEqual(parsed.to, ["-worker"])

    def test_transport_metadata_errors_are_fixed_refusals(self):
        route = {"agent": "claude", "transport": "ssh", "host": "fixture"}
        errors = [peer.CcPeerError("PRIVATE stderr", {"error": "PRIVATE remote", "reason": "PRIVATE reason"}),
                  OSError("PRIVATE path")]
        for error in errors:
            for stage in ("constructor", "execute", "tailscale"):
                with mock.patch.object(peer, "tailscale_status", return_value={}) as status, \
                        mock.patch.object(peer, "SshTransport") as transport:
                    if stage == "constructor":
                        transport.side_effect = error
                    elif stage == "execute":
                        transport.return_value.execute.side_effect = error
                    else:
                        status.side_effect = error
                    with self.assertRaises(peer.CcPeerError) as caught:
                        peer.address_probe_route(route, ["worker"])
                self.assertEqual(caught.exception.details, {"reason": "address_selection_unavailable",
                    "status": "refused", "submitted": False, "retryAllowed": False})
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_shared_storage_limits_cannot_silently_diverge(self):
        source = (Path(peer.__file__).parent / "session_peer_core" / "addresses.py").read_text()
        for changed in ("PRESET_MAX_BYTES", "PRESET_MAX_ENTRIES"):
            namespace = {**peer.__dict__, changed: getattr(peer, changed) + 1}
            with self.assertRaisesRegex(AssertionError, "storage limits differ"):
                exec(compile(source, "addresses.py", "exec"), namespace)

    def test_closed_wire_rejects_extra_recipient_fields(self):
        value = self.wire()
        value["selections"][0]["recipient"]["credential"] = "private"
        with self.assertRaises(peer.CcPeerError):
            peer._address_validate_probe(value, {"agent": "claude", "transport": "local"}, ["worker"])

    def test_canonical_home_alias_is_valid_only_with_explicit_selector_echo(self):
        route = {"agent": "codex", "transport": "local", "codexHome": "/alias/home"}
        target = "codex:" + THREAD
        value = {"selectionSchemaVersion": 1, "homeSelector": "/alias/home", "ok": True,
            "selections": [{"requestedTarget": target, "ok": True,
                "recipient": {"agent": "codex", "target": target, "home": "/actual/home"},
                "selection": {"generationStatus": "unsupported", "targetGeneration": None,
                    "writerRevision": "aw1:" + "a" * 64, "observationRevision": None}}]}
        self.assertEqual(peer._address_validate_probe(value, route, [target])[0]["recipient"]["home"], "/actual/home")
        for selector in (None, "/wrong/home"):
            value["homeSelector"] = selector
            with self.assertRaises(peer.CcPeerError):
                peer._address_validate_probe(value, route, [target])
        del value["homeSelector"]
        with self.assertRaises(peer.CcPeerError):
            peer._address_validate_probe(value, route, [target])

    def test_literal_claude_pid_cannot_be_replaced_in_metadata_response(self):
        route = {"agent": "claude", "transport": "local"}
        for requested in ("claude:42", "42"):
            value = self.wire()
            value["selections"][0]["requestedTarget"] = requested
            value["selections"][0]["recipient"]["target"] = "claude:43"
            with self.assertRaises(peer.CcPeerError):
                peer._address_validate_probe(value, route, [requested])
            value["selections"][0]["recipient"]["target"] = "claude:42"
            self.assertEqual(peer._address_validate_probe(value, route, [requested])[0]["recipient"]["target"], "claude:42")

    def test_inspection_partial_failure_does_not_expose_diagnostics(self):
        args = argparse.Namespace(agent="claude", to=["worker", "missing"], codex_home=None)
        with mock.patch.object(peer, "discover", return_value=[]), \
                mock.patch.object(peer, "resolve_target", side_effect=[{"pid": 42}, peer.CcPeerError("secret path")]), \
                mock.patch.object(peer, "claude_generation", return_value="tg1:" + "a" * 64):
            result = peer.address_inspect_selection(args)
        self.assertFalse(result["ok"])
        self.assertTrue(result["selections"][0]["ok"])
        self.assertNotIn("secret", repr(result))
