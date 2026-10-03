"""Local SSH-updater fixtures: handled faults roll back; lost receipts are unknown.

Transfer interruption precedes publication and preserves the previous install.
Termination after publication need not roll back, even when staging is cleaned.
"""

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import session_peer


# These execute the POSIX SSH destination locally. Git sh plus native Windows
# Python has different paths, modes and process signals, so it is not a valid
# receiver fixture. Mocked client payload/receipt/version contracts below run
# on every platform, including native Windows clients.
@unittest.skipUnless(os.name == "posix", "local POSIX SSH receiver fixture")
class RemoteTransfer(unittest.TestCase):
    VERSION = "1.0.3"
    SOURCE = b'#!/usr/bin/env python3\nprint("session-peer 1.0.3")\n' + b'# padding\n' * 20_000

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="remote-update-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / "quoted ' home 한글"
        self.install = self.home / ".local/share/session-peer"
        self.install.mkdir(parents=True)
        self.target = self.install / "session_peer.py"
        self.old = b'#!/usr/bin/env python3\nprint("session-peer 1.0.2")\n'
        self.target.write_bytes(self.old)
        self.target.chmod(0o751)
        self.old_stat = self.target.stat()
        self.launcher = self.home / ".local/bin/session-peer"
        self.launcher.parent.mkdir(parents=True)
        self.launcher.symlink_to(self.target)
        self.link_inode = self.launcher.lstat().st_ino
        self.sentinel = self.install / ".session-peer-update.user-owned"
        self.sentinel.mkdir()
        (self.sentinel / "keep").write_text("user data")
        self.environment = {**os.environ, "HOME": str(self.home)}
        # Explicit local interpreter; fixtures never run ssh or a user CLI.
        self.environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.defpath

    def script(self, source=None):
        source = self.SOURCE if source is None else source
        completed = subprocess.CompletedProcess([], 0, f"session-peer {self.VERSION}\n", "")
        with mock.patch.object(session_peer.Path, "read_bytes", return_value=source), \
             mock.patch.object(session_peer, "__version__", self.VERSION), \
             mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run:
            session_peer.push_to_remote("fixture", [], {})
        self.assertEqual(run.call_args.args[0][:2], ["ssh", "fixture"])
        return run.call_args.args[0][-1], run.call_args.kwargs["input"]

    def execute(self, script, payload):
        return subprocess.run(["sh", "-c", script], input=payload, text=True,
                              capture_output=True, env=self.environment, timeout=15)

    def assert_preserved(self):
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o751)
        current = self.target.stat()
        self.assertEqual((current.st_ino, current.st_uid, current.st_gid),
                         (self.old_stat.st_ino, self.old_stat.st_uid, self.old_stat.st_gid))
        self.assertEqual(self.launcher.lstat().st_ino, self.link_inode)
        self.assertEqual(self.launcher.readlink(), self.target)
        usable = subprocess.run([str(self.launcher), "--version"], capture_output=True,
                                text=True, env=self.environment, timeout=5)
        self.assertEqual(usable.stdout.strip(), "session-peer 1.0.2")
        self.assertEqual(usable.returncode, 0)
        self.assert_clean()

    def assert_clean(self):
        self.assertEqual(list(self.install.glob(".session-peer-update.*")), [self.sentinel])
        self.assertEqual((self.sentinel / "keep").read_text(), "user data")

    def test_truncated_invalid_and_corrupted_transfers_preserve_old_installation(self):
        script, payload = self.script()
        changed = self.SOURCE.replace(b"padding", b"paddinx", 1)
        for label, transfer in (
            ("clean quartet truncation", payload[:4096]),
            ("invalid base64", payload[:4096] + "!" + payload[4097:]),
            ("changed exact-size bytes", base64.b64encode(changed).decode("ascii")),
            ("extra bytes", payload + "YQ=="),
        ):
            with self.subTest(label=label):
                result = self.execute(script, transfer)
                self.assertNotEqual(result.returncode, 0, result)
                self.assert_preserved()

    def test_invalid_artifacts_preserve_old_installation(self):
        for source in (b"# executable with no version\n", b'print("session-peer 9.9.9")\n',
                       b'raise SystemExit(7)\n', b"invalid python !\n"):
            with self.subTest(source=source):
                script, payload = self.script(source)
                result = self.execute(script, payload)
                self.assertNotEqual(result.returncode, 0, result)
                self.assert_preserved()

    def test_installed_path_version_failure_rolls_back_publication(self):
        source = (b"from pathlib import Path\n"
                  b"print('session-peer 1.0.3' if Path(__file__).parent.name.startswith("
                  b"'.session-peer-update.') else 'session-peer 9.9.9')\n")
        script, payload = self.script(source)
        result = self.execute(script, payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed version mismatch", result.stderr)
        self.assert_preserved()

    def test_atomic_replace_failure_preserves_old_installation(self):
        hooks = self.root / "hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "import os\n"
            "replace = os.replace\n"
            "def fail(source, target):\n"
            "    if '.session-peer-update.' in str(source) and str(source).endswith('/session_peer.py'):\n"
            "        raise OSError('fixture publication failure')\n"
            "    return replace(source, target)\n"
            "os.replace = fail\n")
        self.environment["PYTHONPATH"] = str(hooks)
        script, payload = self.script()
        result = self.execute(script, payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture publication failure", result.stderr)
        self.assert_preserved()

    def test_interrupted_transfer_preserves_old_installation(self):
        script, payload = self.script()
        process = subprocess.Popen(["sh", "-c", script], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=self.environment, start_new_session=True)
        try:
            process.stdin.write(payload[:4096])
            process.stdin.flush()
            deadline = time.monotonic() + 5
            while len(list(self.install.glob(".session-peer-update.*"))) == 1:
                if time.monotonic() >= deadline:
                    self.fail("receiver did not create owned staging")
                time.sleep(0.01)
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
        self.assert_preserved()

    def test_termination_after_publication_does_not_claim_rollback(self):
        source = (b"import os, time\nfrom pathlib import Path\n"
                  b"if not Path(__file__).parent.name.startswith('.session-peer-update.'):\n"
                  b"    (Path(os.environ['HOME']) / 'published-marker').touch()\n"
                  b"    time.sleep(30)\n"
                  b"print('session-peer 1.0.3')\n")
        script, payload = self.script(source)
        process = subprocess.Popen(["sh", "-c", script], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=self.environment, start_new_session=True)
        try:
            process.stdin.write(payload)
            process.stdin.close()
            process.stdin = None
            marker = self.home / "published-marker"
            deadline = time.monotonic() + 5
            while not marker.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    self.fail("receiver did not reach installed-path verification")
                time.sleep(0.01)
            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            # SIGTERM is outside the publisher's in-process exception rollback.
            self.assertEqual(self.target.read_bytes(), source)
            self.assertEqual(self.launcher.lstat().st_ino, self.link_inode)
            self.assert_clean()
            receipt = subprocess.CompletedProcess([], process.returncode, stdout, stderr)
            with mock.patch.object(session_peer.Path, "read_bytes", return_value=source), \
                 mock.patch.object(session_peer, "__version__", self.VERSION), \
                 mock.patch.object(session_peer.subprocess, "run", return_value=receipt), \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.push_to_remote("fixture", [], {})
            self.assertEqual(caught.exception.details["commitStatus"], "unknown")
            self.assertFalse(caught.exception.details["retryAllowed"])
            self.assertNotIn("updated", caught.exception.details)
            self.assertNotIn("submitted", caught.exception.details)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)

    def test_custom_launcher_and_symlink_directory_are_not_overwritten(self):
        script, payload = self.script()
        self.launcher.unlink()
        self.launcher.write_text("custom launcher")
        result = self.execute(script, payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.launcher.read_text(), "custom launcher")
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assert_clean()
        self.launcher.unlink()
        self.launcher.symlink_to(self.target)
        self.link_inode = self.launcher.lstat().st_ino
        real_bin = self.home / ".local/real-bin"
        self.launcher.parent.rename(real_bin)
        self.launcher.parent.symlink_to(real_bin, target_is_directory=True)
        result = self.execute(script, payload)
        self.assertNotEqual(result.returncode, 0)
        self.assert_preserved()

    def test_success_and_first_install_report_exact_version(self):
        for first in (False, True):
            with self.subTest(first_install=first):
                if first:
                    self.target.unlink()
                    self.launcher.unlink()
                script, payload = self.script()
                result = self.execute(script, payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "session-peer 1.0.3")
                self.assertEqual(self.target.read_bytes(), self.SOURCE)
                self.assertEqual(self.target.stat().st_mode & 0o777, 0o755)
                self.assertEqual(self.launcher.readlink(), self.target)
                self.assert_clean()

    def test_first_install_failure_removes_its_launcher(self):
        self.target.unlink()
        self.launcher.unlink()
        source = (b"from pathlib import Path\n"
                  b"print('session-peer 1.0.3' if Path(__file__).parent.name.startswith("
                  b"'.session-peer-update.') else 'session-peer 9.9.9')\n")
        script, payload = self.script(source)
        result = self.execute(script, payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.launcher.is_symlink())
        self.assert_clean()

    def test_installed_probe_distinguishes_absent_and_broken_programs_locally(self):
        local_run = subprocess.run

        def probe(command, **options):
            self.assertEqual(command[:2], ["ssh", "fixture"])
            return local_run(["sh", "-c", command[-1]], env=self.environment, **options)

        with mock.patch.object(session_peer.subprocess, "run", side_effect=probe):
            self.assertEqual(session_peer.remote_installed_version("fixture", [], {}), "1.0.2")
            self.target.write_text("raise SystemExit(3)\n")
            with self.assertRaises(session_peer.CcPeerError):
                session_peer.remote_installed_version("fixture", [], {})
            self.target.unlink()
            self.assertIsNone(session_peer.remote_installed_version("fixture", [], {}))


class RemotePushContract(unittest.TestCase):
    VERSION = RemoteTransfer.VERSION
    SOURCE = RemoteTransfer.SOURCE

    def test_command_and_payload_preserve_exact_sender_bytes(self):
        source = '#!/usr/bin/env python3\n# quoted \' 한글 payload\n'.encode("utf-8")
        completed = subprocess.CompletedProcess([], 0, f"session-peer {self.VERSION}\n", "")
        with mock.patch.object(session_peer.Path, "read_bytes", return_value=source), \
             mock.patch.object(session_peer, "__version__", self.VERSION), \
             mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run:
            version = session_peer.push_to_remote("fixture", ["-p", "2222"], {})
        self.assertEqual(version, self.VERSION)
        self.assertEqual(run.call_args.args[0][:-1], ["ssh", "-p", "2222", "fixture"])
        self.assertEqual(base64.b64decode(run.call_args.kwargs["input"], validate=True), source)
        self.assertIn(f"{hashlib.sha256(source).hexdigest()} {len(source)};", run.call_args.args[0][-1])
        run.assert_called_once()

    def test_empty_or_wrong_remote_success_output_is_rejected(self):
        for output in ("", "session-peer unknown\n", "session-peer 9.9.9\n", "noise 1.0.3\n"):
            with self.subTest(output=output), \
                 mock.patch.object(session_peer.Path, "read_bytes", return_value=self.SOURCE), \
                 mock.patch.object(session_peer, "__version__", self.VERSION), \
                 mock.patch.object(session_peer.subprocess, "run", return_value=
                                   subprocess.CompletedProcess([], 0, output, "")), \
                 self.assertRaises(session_peer.CcPeerError):
                session_peer.push_to_remote("fixture", [], {})

    def test_started_push_failures_report_unknown_without_retry(self):
        for outcome, category in (
            (subprocess.TimeoutExpired(["ssh"], 120), "timeout"),
            (OSError("connection interrupted"), "transport_failed"),
            (subprocess.CompletedProcess([], 255, "", "Connection closed"), "transport_failed"),
            (subprocess.CompletedProcess([], 255, "", "Permission denied (publickey)."), "authentication_failed"),
            (subprocess.CompletedProcess([], 0, "untrusted receipt\n", ""), None),
            (subprocess.CompletedProcess([], 1, "", "publisher terminated"), None),
        ):
            with self.subTest(outcome=outcome), \
                 mock.patch.object(session_peer.Path, "read_bytes", return_value=self.SOURCE), \
                 mock.patch.object(session_peer.subprocess, "run", side_effect=[outcome]) as run, \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.push_to_remote("fixture", [], {})
            details = caught.exception.details
            self.assertEqual(details["commitStatus"], "unknown")
            self.assertFalse(details["retryAllowed"])
            self.assertEqual(details.get("sshFailure"), category)
            self.assertNotIn("updated", details)
            self.assertNotIn("submitted", details)
            run.assert_called_once()

    def test_missing_ssh_is_known_not_started(self):
        with mock.patch.object(session_peer.Path, "read_bytes", return_value=self.SOURCE), \
             mock.patch.object(session_peer.subprocess, "run", side_effect=FileNotFoundError("ssh")) as run, \
             self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.push_to_remote("fixture", [], {})
        self.assertEqual(caught.exception.details["commitStatus"], "not_started")
        self.assertTrue(caught.exception.details["retryAllowed"])
        run.assert_called_once()


class RemoteVersions(unittest.TestCase):
    def update(self, local, remote, check=False, pushed=None):
        args = argparse.Namespace(host=["fixture"], ssh_opt=[], check=check, json=True)
        output = io.StringIO()
        versions = remote if isinstance(remote, list) else [remote]
        with mock.patch.object(session_peer, "__version__", local), \
             mock.patch.object(session_peer, "tailscale_status", return_value={}), \
             mock.patch.object(session_peer, "ssh_user_metadata", return_value={}), \
             mock.patch.object(session_peer, "remote_installed_version", side_effect=versions) as probe, \
             mock.patch.object(session_peer, "push_to_remote", return_value=pushed or local) as push, \
             contextlib.redirect_stdout(output):
            code = session_peer.cmd_update(args)
        return code, json.loads(output.getvalue()), push, probe

    def test_ordered_check_for_stable_and_prerelease_versions(self):
        for local, remote, outdated in (
            ("1.0.2", "1.0.3", False), ("1.0.2", "1.0.2", False),
            ("1.0.2", "1.0.1", True), ("1.0.2", None, True),
            ("1.0.3rc1", "1.0.3", False), ("1.0.3", "1.0.3rc1", True),
            ("1.0.3a1", "1.0.3b1", False), ("1.0.3", "v1.0.3", False),
        ):
            with self.subTest(local=local, remote=remote):
                code, result, push, _ = self.update(local, remote, check=True)
                self.assertEqual(code, 0)
                self.assertEqual(result["outdated"], outdated)
                push.assert_not_called()

    def test_current_or_newer_remote_is_never_downgraded(self):
        for local, remote in (("1.0.2", "1.0.3"), ("1.0.2", "1.0.2"),
                              ("1.0.3rc1", "1.0.3"), ("1.0.3", "v1.0.3")):
            with self.subTest(local=local, remote=remote):
                code, result, push, _ = self.update(local, remote)
                self.assertEqual(code, 0)
                self.assertFalse(result["updated"])
                push.assert_not_called()

    def test_uncomparable_remote_refuses_check_and_update(self):
        for check in (True, False):
            code, result, push, _ = self.update("1.0.3", "unknown", check=check)
            self.assertEqual(code, session_peer.EXIT_ERROR)
            self.assertFalse(result["ok"])
            push.assert_not_called()

    def test_updated_true_requires_independent_exact_installed_probe(self):
        for previous in ("1.0.2", None):
            code, result, push, probe = self.update("1.0.3", [previous, "1.0.3"])
            self.assertEqual(code, 0)
            self.assertTrue(result["updated"])
            self.assertEqual(result["remoteVersion"], "1.0.3")
            self.assertEqual(result["previous"], previous)
            self.assertEqual(probe.call_count, 2)
            push.assert_called_once()
        for installed in (None, "1.0.2", "1.0.4", "v1.0.3"):
            with self.subTest(installed=installed):
                code, result, _, _ = self.update("1.0.3", ["1.0.2", installed])
                self.assertEqual(code, session_peer.EXIT_ERROR)
                self.assertFalse(result["ok"])
                self.assertNotIn("updated", result)
        code, result, _, _ = self.update("1.0.3", ["1.0.2", "1.0.3"], pushed="unknown")
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertFalse(result["ok"])

    def test_probe_failure_after_verified_commit_preserves_commit_evidence(self):
        failure = session_peer.CcPeerError("SSH timed out", {"sshFailure": "timeout"})
        code, result, push, probe = self.update("1.0.3", ["1.0.2", failure])
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertFalse(result["ok"])
        self.assertTrue(result["committed"])
        self.assertEqual(result["commitStatus"], "committed")
        self.assertFalse(result["retryAllowed"])
        self.assertEqual(result["installedVersionVerified"], "1.0.3")
        self.assertEqual(result["verificationStatus"], "unknown")
        self.assertEqual(result["sshFailure"], "timeout")
        self.assertNotIn("updated", result)
        push.assert_called_once()
        self.assertEqual(probe.call_count, 2)


if __name__ == "__main__":
    unittest.main()
