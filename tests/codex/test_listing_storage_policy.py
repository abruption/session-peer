"""Metadata-only listing policy fixtures; no native CLI, CF or model is used."""
import argparse
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import session_peer as peer
from tests.codex.support import THREAD, OTHER, isolate_native_layers


class ListingStoragePolicy(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.user = Path(temporary.name).resolve()
        self.default = self.user / ".codex"
        self.account = self.user / "Library/Application Support/orca/codex-accounts/account-a/home"
        self.make_home(self.default, THREAD)
        self.make_home(self.account, OTHER)
        isolate_native_layers(self, self.user)
        self.patch(mock.patch.object(Path, "home", return_value=self.user))
        self.patch(mock.patch.dict(os.environ, {}, clear=True))
        self.patch(mock.patch.object(peer.sys, "platform", "darwin"))
        self.ordinary = False
        self.preferences = self.patch(mock.patch.object(peer, "codex_managed_preference_values",
                                                        side_effect=self.preference_values))
        self.args = argparse.Namespace(codex_home=str(self.default), codex_bin=None,
                                       all=False, agent="codex")

    def patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def make_home(self, home, thread):
        home.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(home / "state_5.sqlite")) as conn:
            conn.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)")
            conn.execute("INSERT INTO threads VALUES (?, 'fixture', ?, 1, 0, '/missing-rollout')",
                         (thread, str(self.user / "missing-project")))
            conn.commit()

    def preference_values(self, *, forced_only=True):
        if self.ordinary and not forced_only:
            return [base64.b64encode(b'sqlite_home="private-listing-location"').decode("ascii")]
        return []

    @contextlib.contextmanager
    def no_native(self):
        # Listing must remain usable without a CLI installation and must not
        # run either a normal subprocess or the owned version-query primitive.
        with mock.patch.object(peer.subprocess, "run") as run, \
             mock.patch.object(peer.subprocess, "Popen") as start, \
             mock.patch.object(peer, "codex_executable") as executable, \
             mock.patch.object(peer, "codex_queue_preference_policy") as policy, \
             mock.patch.object(peer, "handoff_stream_child") as owned:
            yield
            for operation in (run, start, executable, policy, owned):
                operation.assert_not_called()

    def assert_diagnostic(self, value):
        text = str(value)
        for marker in ("metadata-only", "0.162.1", "operator", "com.openai.codex",
                       "config_toml_base64", "requirements_toml_base64",
                       "intended home and storage", "--codex-home alone",
                       "Do not automatically remove preferences or switch databases"):
            self.assertIn(marker.lower(), text.lower())
        self.assertNotIn("private-listing-location", text)
        self.assertNotIn(base64.b64encode(b'sqlite_home="private-listing-location"').decode("ascii"), text)

    def cli(self, *options):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = peer.main(["list", "--no-update-notice", *options])
        return code, output.getvalue(), errors.getvalue()

    def test_direct_discovery_refuses_ordinary_storage_before_opening_stale_db(self):
        self.ordinary = True
        # Labels represent the two loader scenarios, not a claimed executable
        # version proof: metadata-only listing does not execute either binary.
        for requested in ("fixture-codex-0.154.0", "fixture-codex-0.162.1"):
            self.args.codex_bin = requested
            with self.subTest(requested=requested), self.no_native(), \
                 mock.patch.object(peer.sqlite3, "connect") as connect:
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.discover_codex(self.args)
                self.assertEqual(caught.exception.details["reason"], "sqlite_home_managed_configuration")
                self.assert_diagnostic(caught.exception)
                connect.assert_not_called()

    def test_collect_refuses_all_ambiguous_homes_without_database_fallback(self):
        self.ordinary = True
        self.args.codex_home = None
        with self.no_native(), mock.patch.object(peer.sqlite3, "connect") as connect:
            result = peer.collect_codex_listing(self.args)
        self.assertEqual(result["sessions"], [])
        self.assertEqual(result["discovery"]["status"], "error")
        self.assertEqual(len(result["discovery"]["homes"]), 2)
        for home in result["discovery"]["homes"]:
            self.assertEqual(home["status"], "error")
            self.assert_diagnostic(home["error"])
        connect.assert_not_called()

    def test_malformed_ordinary_preference_refuses_before_db_with_operator_guidance(self):
        def malformed(*, forced_only=True):
            return [] if forced_only else ["private-invalid-base64!"]

        with self.no_native(), \
             mock.patch.object(peer, "codex_managed_preference_values", side_effect=malformed), \
             mock.patch.object(peer.sqlite3, "connect") as connect:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.discover_codex(self.args)
        self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")
        self.assert_diagnostic(caught.exception)
        self.assertNotIn("private-invalid-base64!", str(caught.exception))
        connect.assert_not_called()

    def test_malformed_home_configuration_does_not_misidentify_preferences_as_cause(self):
        (self.default / "config.toml").write_text(
            'sqlite_home="private-listing-location\n', encoding="utf-8")
        with self.no_native(), mock.patch.object(peer.sqlite3, "connect") as connect:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.discover_codex(self.args)
        self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")
        self.assert_diagnostic(caught.exception)
        self.assertIn("A known storage configuration layer could not be classified", str(caught.exception))
        self.assertIn("this need not originate in preferences", str(caught.exception))
        self.assertNotIn("macOS preference values contain an unsupported sqlite_home setting", str(caught.exception))
        self.preferences.assert_not_called()
        connect.assert_not_called()

    def test_internal_true_policy_does_not_deny_an_enclosing_version_query(self):
        self.ordinary = True
        # Represents an enclosing send that already established a loader policy;
        # this discovery step must not imply that the enclosing probe never ran.
        self.args._codex_discovery_include_ordinary_preferences = True
        with self.no_native(), mock.patch.object(peer.sqlite3, "connect") as connect:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.discover_codex(self.args)
        self.assertEqual(caught.exception.details["reason"], "sqlite_home_managed_configuration")
        self.assert_diagnostic(caught.exception)
        self.assertIn("macOS preference values contain an unsupported sqlite_home setting", str(caught.exception))
        self.assertIn("This discovery step performs no additional native version query", str(caught.exception))
        self.assertNotIn("Metadata-only discovery does not determine the native Codex version", str(caught.exception))
        connect.assert_not_called()

    def test_collect_does_not_accept_a_caller_supplied_internal_policy_override(self):
        self.ordinary = True
        self.args._codex_discovery_include_ordinary_preferences = False
        with self.no_native(), mock.patch.object(peer.sqlite3, "connect") as connect:
            result = peer.collect_codex_listing(self.args)
        self.assertEqual(result["discovery"]["status"], "error")
        self.assertEqual(result["sessions"], [])
        connect.assert_not_called()

    def test_invalid_internal_discovery_policy_remains_conservative(self):
        self.ordinary = True
        for value in (None, 0, "false", []):
            self.args._codex_discovery_include_ordinary_preferences = value
            with self.subTest(kind=type(value).__name__), self.no_native(), \
                 mock.patch.object(peer.sqlite3, "connect") as connect:
                with self.assertRaises(peer.CcPeerError):
                    peer.discover_codex(self.args)
                connect.assert_not_called()

    def test_cli_json_is_failure_not_empty_success(self):
        self.ordinary = True
        with self.no_native(), mock.patch.object(peer.sqlite3, "connect") as connect:
            code, output, _ = self.cli("--agent", "codex", "--json")
        result = json.loads(output)
        self.assertEqual(code, 1)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["sessions"], [])
        self.assertEqual(result["discovery"]["codex"]["status"], "error")
        self.assert_diagnostic(output)
        connect.assert_not_called()

    def test_cli_text_explains_cause_and_operator_remedy(self):
        self.ordinary = True
        with self.no_native(), mock.patch.object(peer.sqlite3, "connect") as connect:
            code, output, errors = self.cli("--agent", "codex", "--codex-home", str(self.account))
        self.assertEqual(code, 1)
        self.assertIn("discovery failed", output)
        self.assert_diagnostic(output + errors)
        connect.assert_not_called()

    def test_explicit_codex_bin_does_not_enable_a_listing_version_probe(self):
        self.ordinary = True
        for output_options in (("--json",), ()):
            with self.subTest(json_output=bool(output_options)), self.no_native(), \
                 mock.patch.object(peer.sqlite3, "connect") as connect:
                code, output, errors = self.cli("--agent", "codex", "--codex-bin",
                                                "fixture-codex-0.162.1", *output_options)
            self.assertEqual(code, 1)
            self.assert_diagnostic(output + errors)
            if output_options:
                self.assertIs(json.loads(output)["ok"], False)
            connect.assert_not_called()

    def test_failed_codex_discovery_preserves_healthy_claude_rows(self):
        self.ordinary = True
        row = {"pid": 4242, "name": "fixture-claude", "cwd": str(self.user),
               "alive": True, "reachable": True}
        with self.no_native(), mock.patch.object(peer.sqlite3, "connect") as connect, \
             mock.patch.object(peer.AGENTS, "names", return_value=["claude", "codex"]), \
             mock.patch.object(peer, "discover", return_value=[row]):
            code, output, _ = self.cli("--json")
        result = json.loads(output)
        self.assertEqual(code, 1)
        self.assertIs(result["ok"], False)
        self.assertEqual([entry["agent"] for entry in result["sessions"]], ["claude"])
        self.assertEqual(result["discovery"]["claude"]["status"], "ok")
        self.assertEqual(result["discovery"]["codex"]["status"], "error")
        connect.assert_not_called()

    def test_no_ambiguous_preference_preserves_missing_cli_multi_home_metadata(self):
        self.args.codex_home = None
        with self.no_native(), mock.patch.object(peer.shutil, "which", return_value=None):
            result = peer.collect_codex_listing(self.args)
        self.assertEqual(result["discovery"]["status"], "ok")
        self.assertEqual({row["id"] for row in result["sessions"]}, {THREAD, OTHER})
        self.assertTrue(all(home["status"] == "ok" for home in result["discovery"]["homes"]))

    def test_absent_default_home_does_not_hide_healthy_orca_metadata(self):
        (self.default / "state_5.sqlite").unlink()
        self.args.codex_home = None
        with self.no_native():
            result = peer.collect_codex_listing(self.args)
        self.assertEqual(result["discovery"]["status"], "ok")
        self.assertEqual([row["id"] for row in result["sessions"]], [OTHER])
        self.assertEqual([home["status"] for home in result["discovery"]["homes"]], ["absent", "ok"])

    def test_one_home_config_refusal_keeps_other_home_rows_when_no_global_ambiguity(self):
        (self.default / "config.toml").write_text('sqlite_home="private-listing-location"\n', encoding="utf-8")
        self.args.codex_home = None
        with self.no_native():
            result = peer.collect_codex_listing(self.args)
        self.assertEqual(result["discovery"]["status"], "error")
        self.assertEqual([row["id"] for row in result["sessions"]], [OTHER])
        self.assertEqual([home["status"] for home in result["discovery"]["homes"]], ["error", "ok"])
        self.assertNotIn("private-listing-location", json.dumps(result))

    def test_internal_queue_dry_run_reuses_its_proven_policy_without_second_probe(self):
        self.ordinary = True
        self.args.to = "codex:" + THREAD
        self.args.dry_run = True
        self.args.allow_inactive_codex_home = True
        self.args.wake = False
        with mock.patch.object(peer, "resolve_codex_home", return_value=(self.default, {})), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer, "codex_queue_preference_policy", return_value=False) as policy, \
             mock.patch.object(peer.subprocess, "run") as run, \
             mock.patch.object(peer.subprocess, "Popen") as start, \
             mock.patch.object(peer, "handoff_stream_child") as owned:
            result = peer._queue_codex(self.args, "fixture")
        self.assertEqual(result["status"], "validated")
        self.assertIs(result["submitted"], False)
        self.assertEqual(policy.call_count, 1)
        run.assert_not_called()
        start.assert_not_called()
        owned.assert_not_called()
        self.assertTrue(all(call.kwargs.get("forced_only", True) for call in self.preferences.call_args_list))
