"""Real private preset storage with mocked ordinary native/SSH transports."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import session_peer as peer


THREAD = "00000000-0000-4000-8000-000000000001"


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "POSIX route preset storage")
class PresetFlow(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-preset-flow-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.environment = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def invoke(self, argv, *, entrypoint=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if entrypoint:
                with mock.patch.object(peer.sys, "argv", ["session-peer", *argv]):
                    code = peer.main()
            else:
                code = peer.main(argv)
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_management_preview_changed_revision_and_single_remote_send(self):
        with mock.patch.object(peer.subprocess, "Popen") as child, \
                mock.patch.object(peer, "prepare_client_update") as notice, \
                mock.patch.object(peer, "prepare_skill_updates") as skills:
            code, added, _ = self.invoke(["preset", "add", "work", "--agent", "claude", "--json"], entrypoint=True)
            self.assertEqual(code, 0)
            old = added["revision"]
            code, shown, _ = self.invoke(["preset", "show", "work", "--json"], entrypoint=True)
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
                "--host", "user@fixture", "--agent", "codex", "--codex-home", "/fixture/home", "--json"], entrypoint=True)
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

    @unittest.skipUnless(sys.platform == "darwin", "Darwin native deny-only ancestor")
    def test_native_darwin_deny_only_ancestor_allows_private_child_storage(self):
        ancestor = self.root / "deny-ancestor"
        ancestor.mkdir(mode=0o700)
        subprocess.run(["/bin/chmod", "+a", "everyone deny delete", str(ancestor)],
                       check=True, capture_output=True)
        try:
            fd = os.open(ancestor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                self.assertEqual(peer._preset_darwin_acl_tags(fd), (2,))
                peer._preset_check_acl(fd, private=False, directory=True)
                with self.assertRaises(peer.CcPeerError) as refused:
                    peer._preset_check_acl(fd, private=True, directory=True)
                self.assertEqual(refused.exception.details["reason"], "preset_unsafe_acl")
            finally:
                os.close(fd)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(ancestor / "config")}):
                result = peer.preset_mutate("add", "work", {"transport": "local", "agent": "claude"})
                self.assertEqual(peer.preset_lookup("work")[1], result["revision"])
        finally:
            subprocess.run(["/bin/chmod", "-N", str(ancestor)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
