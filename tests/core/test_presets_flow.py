"""Real private preset storage with mocked ordinary native/SSH transports."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import session_peer as peer


THREAD = "00000000-0000-4000-8000-000000000001"


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "POSIX route preset storage")
class PresetFlow(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-preset-flow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.environment = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = peer.main(argv)
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_management_preview_changed_revision_and_single_remote_send(self):
        with mock.patch.object(peer.subprocess, "Popen") as child, \
                mock.patch.object(peer, "prepare_client_update") as notice, \
                mock.patch.object(peer, "prepare_skill_updates") as skills:
            code, added, _ = self.invoke(["preset", "add", "work", "--agent", "claude", "--json"])
            self.assertEqual(code, 0)
            old = added["revision"]
            code, shown, _ = self.invoke(["preset", "show", "work", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(shown["revision"], old)
            self.assertEqual(shown["route"], {"agent": "claude", "transport": "local"})
            native = {"ok": True, "target": {"pid": 42, "name": "worker"}, "dryRun": True, "chars": 1}
            with mock.patch.object(peer.LocalTransport, "execute", return_value=native) as local:
                code, preview, error = self.invoke([
                    "send", "--preset", "work", "--to", "worker", "--message", "x",
                    "--dry-run", "--json", "--no-from", "--no-reply-to"])
            self.assertEqual(code, 0)
            self.assertEqual(error, "")
            self.assertNotIn("preset", preview)
            self.assertNotIn("submitted", preview)
            self.assertEqual(local.call_args.args[2].host, [])
            self.assertTrue(local.call_args.args[2].dry_run)

            code, changed, _ = self.invoke([
                "preset", "replace", "work", "--expect-revision", old,
                "--host", "user@fixture", "--agent", "codex", "--codex-home", "/fixture/home", "--json"])
            self.assertEqual(code, 0)
            current = changed["revision"]
            self.assertNotEqual(old, current)
            send = ["send", "--preset", "work", "--to", "codex:" + THREAD,
                    "--message", "x", "--json", "--no-from", "--no-reply-to"]
            with mock.patch.object(peer, "SshTransport") as remote, \
                    mock.patch.object(peer.LocalTransport, "execute") as local:
                code, stale, _ = self.invoke([*send, "--preset-revision", old])
            self.assertEqual(code, 1)
            self.assertEqual(stale["reason"], "preset_revision_mismatch")
            self.assertNotIn("submitted", stale)
            remote.assert_not_called()
            local.assert_not_called()
            transport = mock.Mock(host="fixture", ssh_opts=[])
            transport.execute.return_value = {
                "ok": True, "target": {"agent": "codex", "id": THREAD},
                "chars": 1, "dryRun": False, "status": "queued", "submitted": True,
                "queueId": "fixture-queue", "consumptionConfirmed": False}
            with mock.patch.object(peer, "tailscale_status", return_value={}), \
                    mock.patch.object(peer, "SshTransport", return_value=transport) as remote:
                code, result, error = self.invoke([*send, "--preset-revision", current])
            self.assertEqual(code, 0)
            self.assertEqual(error, "")
            self.assertTrue(result["submitted"])
            self.assertFalse(result["consumptionConfirmed"])
            self.assertEqual(result["queueId"], "fixture-queue")
            self.assertNotIn("preset", result)
            remote.assert_called_once()
            transport.execute.assert_called_once()
            argv = transport.execute.call_args.args[0]
            for excluded in ("--preset", "--preset-revision", current, str(self.root)):
                self.assertNotIn(excluded, argv)
            child.assert_not_called()
            notice.assert_not_called()
            skills.assert_not_called()

    def test_route_change_after_lookup_does_not_rebind_current_invocation(self):
        added = peer.preset_mutate("add", "work", {"transport": "local", "agent": "claude"})
        original = added["revision"]

        def change_after_snapshot(args):
            peer.preset_mutate("replace", "work", {
                "transport": "ssh", "agent": "claude", "host": "user@other"}, original)
            return "x"

        native = {"ok": True, "target": {"pid": 42, "name": "worker"}, "chars": 1, "dryRun": False}
        with mock.patch.object(peer, "read_message", side_effect=change_after_snapshot), \
                mock.patch.object(peer.LocalTransport, "execute", return_value=native) as local, \
                mock.patch.object(peer, "SshTransport") as remote:
            code, result, _ = self.invoke([
                "send", "--preset", "work", "--preset-revision", original,
                "--to", "worker", "--message", "x", "--json", "--no-from", "--no-reply-to"])
        self.assertEqual(code, 0)
        self.assertEqual(local.call_args.args[2].host, [])
        remote.assert_not_called()
        self.assertNotIn("submitted", result)
        route, revision = peer.preset_lookup("work")
        self.assertEqual(route["host"], "user@other")
        self.assertNotEqual(revision, original)


if __name__ == "__main__":
    unittest.main()
