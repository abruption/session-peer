"""Focused offline CLI composition checks for the isolated integration tree."""
import contextlib
import io
import unittest
from unittest import mock

import session_peer as peer
from tests.core import test_address_flow as address_flow


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "controlled POSIX address fixture")
class CandidateIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Compose the fixture, rather than import/subclass its TestCase and
        # accidentally discover its existing test methods a second time.
        self.fixture = address_flow.AddressFlowTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def invoke(self, argv):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                code = peer.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_address_dry_run_explanation_reuses_exactly_one_selection(self):
        self.fixture.add()
        self.fixture.probe_mock.reset_mock()
        native = {"ok": True, "dryRun": True,
                  "target": {"pid": 42, "name": "worker"}, "chars": 1,
                  "targetGeneration": self.fixture.generation}
        with mock.patch.object(peer.LocalTransport, "execute", return_value=native) as execute:
            code, output, error = self.invoke(["send", "--address", "research", "--dry-run", "--explain",
                                               "--message", "fixture", "--no-from", "--no-reply-to"])
        self.assertEqual(code, 0, error)
        self.assertIn("Delivery preview", output)
        self.assertIn("Validation: passed for this dry run", output)
        self.assertIn("Resolved target: Claude PID 42", output)
        self.assertIn("Address research:", error)
        self.fixture.probe_mock.assert_called_once_with(self.fixture.route, ["claude:42"], None)
        execute.assert_called_once()
        self.assertTrue(execute.call_args.args[2].dry_run)
        self.assertEqual(execute.call_args.args[2].target_generation, self.fixture.generation)

    def test_address_explanation_json_refused_before_configuration_or_input(self):
        with mock.patch.object(peer, "address_lookup", side_effect=AssertionError("address read")), \
                mock.patch.object(peer, "read_message", side_effect=AssertionError("message read")):
            code, output, error = self.invoke(["send", "--address", "research", "--dry-run", "--explain", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("--explain requires text output", error)
        self.fixture.probe_mock.assert_not_called()

    def test_address_trusted_ssh_flags_refused_before_any_configuration_read(self):
        variants = (["--ssh-config", "/private/not-opened", "--trust-ssh-config"],
                    ["--ssh-config", "/private/not-opened"], ["--trust-ssh-config"])
        for flags in variants:
            with self.subTest(flags=flags), \
                    mock.patch.object(peer, "address_lookup", side_effect=AssertionError("address read")), \
                    mock.patch.object(peer, "select_trusted_ssh_config", side_effect=AssertionError("SSH config read")), \
                    mock.patch.object(peer, "read_message", side_effect=AssertionError("message read")):
                code, output, error = self.invoke(["send", "--address", "research", "--dry-run", *flags])
            self.assertEqual(code, 2)
            self.assertEqual(output, "")
            self.assertIn("--address conflicts with --", error)
        self.fixture.probe_mock.assert_not_called()

    def test_watch_and_status_explanation_keep_separate_parser_contracts(self):
        correlation = "00000000-0000-4000-8000-000000000001"
        watch = peer.build_parser().parse_args(["handoff", "watch", "--correlation-id", correlation,
                                               "--watch-timeout", "1", "--interval-ms", "1000", "--json"])
        status = peer.build_parser().parse_args(["handoff", "status", "--correlation-id", correlation, "--explain"])
        self.assertIs(watch.func, peer.cmd_handoff_watch)
        self.assertEqual(watch.watch_timeout, 1)
        self.assertIs(status.func, peer.cmd_handoff)
        self.assertTrue(status.explain)
        self.assertFalse(getattr(watch, "explain", False))

    def test_pairing_credential_argv_redaction_survives_explicit_option_tracking(self):
        secret = "session-peer://pair/PRIVATE-CREDENTIAL"
        code, output, error = self.invoke(["device", "pair", "--link", secret])
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("pairing_link_argv_forbidden", error)
        self.assertNotIn(secret, error)

    def test_routed_notice_preference_rejected_before_ssh_configuration_read(self):
        with mock.patch.object(peer, "select_trusted_ssh_config", side_effect=AssertionError("SSH config read")):
            code, output, error = self.invoke(["update", "--dismiss-runtime-notice", "2.0.0", "--host", "worker",
                                               "--ssh-config", "/private/not-opened", "--trust-ssh-config"])
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("Runtime notice preferences are local only", error)


if __name__ == "__main__":
    unittest.main()
