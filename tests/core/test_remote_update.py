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
import shlex
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

    def script(self, source=None, version=None):
        source = self.SOURCE if source is None else source
        version = self.VERSION if version is None else version
        completed = subprocess.CompletedProcess([], 0, f"session-peer {version}\n", "")
        with mock.patch.object(session_peer.Path, "read_bytes", return_value=source), \
             mock.patch.object(session_peer, "__version__", version), \
             mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run:
            session_peer.push_to_remote("fixture", [], {})
        self.assertEqual(run.call_args.args[0][:2], ["ssh", "fixture"])
        return run.call_args.args[0][-1], run.call_args.kwargs["input"].decode("ascii")

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

    def wait_for(self, marker, process):
        deadline = time.monotonic() + 5
        while not marker.exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                self.fail("receiver did not reach fixture marker: " + str(marker))
            time.sleep(0.01)

    def start(self, script, payload):
        process = subprocess.Popen(["sh", "-c", script], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=self.environment, start_new_session=True)
        process.stdin.write(payload)
        process.stdin.close()
        process.stdin = None
        def cleanup():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        return process

    def mark_lock_attempt(self, script, marker):
        call = 'fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)'
        # Only instrument the generated receiver in the local fixture. This
        # marker proves the second publisher reached lock acquisition, without
        # depending on a scheduler delay to establish the interleaving.
        marked = ('open(os.path.join(os.environ["HOME"], "' + marker +
                  '"), "a").close(); ' + call)
        self.assertIn(call, script)
        return script.replace(call, marked)

    def test_interleaved_failed_update_cannot_roll_back_successful_different_version(self):
        first = (b"import os, time\nfrom pathlib import Path\n"
                 b"home = Path(os.environ['HOME'])\n"
                 b"if not Path(__file__).parent.name.startswith('.session-peer-update.'):\n"
                 b"    (home / 'first-installed').touch()\n"
                 b"    while not (home / 'release-first').exists(): time.sleep(0.01)\n"
                 b"    print('session-peer wrong')\n"
                 b"else: print('session-peer 1.0.3')\n")
        second = (b"import os\nfrom pathlib import Path\n"
                  b"if Path(__file__).parent.name.startswith('.session-peer-update.'):\n"
                  b"    (Path(os.environ['HOME']) / 'second-staged').touch()\n"
                  b"print('session-peer 1.0.4')\n")
        a = self.start(*self.script(first))
        self.wait_for(self.home / 'first-installed', a)
        second_script, second_payload = self.script(second, "1.0.4")
        b = self.start(self.mark_lock_attempt(second_script, 'second-lock-attempt'), second_payload)
        self.wait_for(self.home / 'second-staged', b)
        self.wait_for(self.home / 'second-lock-attempt', b)
        # B completed transfer and staging validation, but cannot snapshot or
        # publish until A's installed validation and rollback release the lock.
        self.assertIsNone(b.poll())
        self.assertEqual(self.target.read_bytes(), first)
        backups = list(self.install.glob('.session-peer-update.*/previous.py'))
        self.assertEqual(len(backups), 1)
        (self.home / 'release-first').touch()
        _, error = a.communicate(timeout=5)
        output, b_error = b.communicate(timeout=5)
        self.assertNotEqual(a.returncode, 0)
        self.assertIn('installed version mismatch', error)
        self.assertEqual(b.returncode, 0, b_error)
        self.assertEqual(output, 'session-peer 1.0.4\n')
        self.assertEqual(self.target.read_bytes(), second)
        self.assert_clean()

    def test_newer_client_finishes_first_then_stale_client_cannot_downgrade(self):
        local_run = subprocess.run
        def probe(command, **options):
            return local_run(['sh', '-c', command[-1]], env=self.environment, **options)
        # Both real installed probes succeed before either client publishes.
        with mock.patch.object(session_peer.subprocess, 'run', side_effect=probe):
            self.assertEqual(session_peer.remote_installed_version('fixture', [], {}), '1.0.2')
            self.assertEqual(session_peer.remote_installed_version('fixture', [], {}), '1.0.2')
        newer = (b"import os, time\nfrom pathlib import Path\n"
                 b"home = Path(os.environ['HOME'])\n"
                 b"if not Path(__file__).parent.name.startswith('.session-peer-update.'):\n"
                 b"    (home / 'newer-installed').touch()\n"
                 b"    while not (home / 'release-newer').exists(): time.sleep(0.01)\n"
                 b"print('session-peer 1.0.4')\n")
        a = self.start(*self.script(newer, '1.0.4'))
        self.wait_for(self.home / 'newer-installed', a)
        script, payload = self.script()
        b = self.start(self.mark_lock_attempt(script, 'older-lock-attempt'), payload)
        self.wait_for(self.home / 'older-lock-attempt', b)
        self.assertIsNone(b.poll())
        (self.home / 'release-newer').touch()
        newer_output, newer_error = a.communicate(timeout=5)
        output, error = b.communicate(timeout=5)
        self.assertEqual(a.returncode, 0, newer_error)
        self.assertEqual(newer_output, 'session-peer 1.0.4\n')
        self.assertNotEqual(b.returncode, 0, error)
        self.assertEqual(json.loads(output)['reason'], 'remote_not_older')
        self.assertEqual(json.loads(output)['remoteVersion'], '1.0.4')
        self.assertEqual(self.target.read_bytes(), newer)
        self.assertEqual(self.launcher.lstat().st_ino, self.link_inode)
        with mock.patch.object(session_peer.Path, 'read_bytes', return_value=self.SOURCE), \
             mock.patch.object(session_peer, '__version__', self.VERSION), \
             mock.patch.object(session_peer.subprocess, 'run', return_value=
                               subprocess.CompletedProcess([], b.returncode, output, error)) as run, \
             self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.push_to_remote('fixture', [], {})
        self.assertEqual(caught.exception.details['commitStatus'], 'not_started')
        self.assertFalse(caught.exception.details['retryAllowed'])
        self.assertEqual(caught.exception.details['reason'], 'remote_not_older')
        run.assert_called_once()
        self.assert_clean()

    def test_locked_version_check_rejects_unusable_equal_and_newer_releases(self):
        for installed, local in (
            ('unknown', '1.0.3'), ('1.0.3', '1.0.3'), ('1.0.4', '1.0.3'),
            ('1.0.3', '1.0.3rc1'), ('v1.0.3', '1.0.3'),
            ('1.0.3beta2', '1.0.3a9'), ('1.0.3preview2', '1.0.3rc1'),
            ('1.0.3', 'unknown'), ('1.0.3.1', '1.0.3'),
            (str(sys.maxsize + 1) + '.0.0', '1.0.3'),
        ):
            with self.subTest(installed=installed, local=local):
                previous = ('print(' + repr('session-peer ' + installed) + ')\n').encode()
                self.target.write_bytes(previous)
                original = self.target.stat()
                source = ('print(' + repr('session-peer ' + local) + ')\n').encode()
                result = self.execute(*self.script(source, local))
                self.assertNotEqual(result.returncode, 0, result.stderr)
                receipt = json.loads(result.stdout)
                wanted, current = session_peer.release_version(local), session_peer.release_version(installed)
                reason = ('local_version_unusable' if wanted is None else
                          'installed_version_unusable' if current is None else 'remote_not_older')
                self.assertEqual(receipt['reason'], reason)
                self.assertIsNotNone(session_peer.installed_update_rejection(result.stdout, local))
                self.assertEqual(self.target.read_bytes(), previous)
                self.assertEqual(self.target.stat().st_ino, original.st_ino)
                self.assertEqual(self.launcher.lstat().st_ino, self.link_inode)
                self.assert_clean()

    def test_locked_version_check_allows_stable_and_prerelease_upgrades(self):
        for installed, local in (('1.0.2', '1.0.3rc1'), ('1.0.3rc1', '1.0.3'),
                                 ('1.0.3a9', '1.0.3b1'), ('1.0.3beta1', '1.0.3preview1'),
                                 ('1.0.3pre1', '1.0.3RC-2')):
            with self.subTest(installed=installed, local=local):
                self.target.write_text('print(' + repr('session-peer ' + installed) + ')\n')
                source = ('print(' + repr('session-peer ' + local) + ')\n').encode()
                result = self.execute(*self.script(source, local))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'session-peer ' + local + '\n')
                self.assertEqual(self.target.read_bytes(), source)
                self.assert_clean()

    def test_publisher_release_parser_matches_client_release_ordering(self):
        script, _ = self.script()
        publisher = next(part for part in shlex.split(script) if 'def comparable_update_release' in part)
        helper = 'def comparable_update_release' + publisher.split('def comparable_update_release', 1)[1]
        helper = helper.split('def reject_update', 1)[0]
        namespace = {'re': session_peer.re, 'sys': sys}
        exec(helper, namespace)
        for version in ('1.0.3', 'v1.0.3', 'V1.0.3', '1.0.3a1', '1.0.3-alpha.2',
                        '1.0.3b1', '1.0.3-BETA-2', '1.0.3rc1', '1.0.3pre2',
                        '1.0.3-preview.3', '1.0.3rc999999999999999999999999',
                        str(sys.maxsize) + '.0.0', str(sys.maxsize + 1) + '.0.0',
                        ' 1.0.3 ', '1.0', '1.0.3.1', '01.0.3', '1.0.3rc01',
                        'unknown', '', '1.0.3+build'):
            with self.subTest(version=version):
                self.assertEqual(namespace['comparable_update_release'](version),
                                 session_peer.release_version(version))

    def test_rollback_preserves_target_replaced_or_modified_outside_lock(self):
        replacement = b"print('session-peer 1.0.4')\n"
        for method in ('replace', 'inplace'):
            with self.subTest(method=method):
                self.target.write_bytes(self.old)
                source = (
                    "from pathlib import Path\n"
                    "target = Path(__file__)\n"
                    "if target.parent.name.startswith('.session-peer-update.'):\n"
                    "    print('session-peer 1.0.3')\n"
                    "else:\n"
                    "    replacement = {!r}\n".format(replacement) +
                    ("    other = target.with_suffix('.replacement')\n"
                     "    other.write_bytes(replacement)\n"
                     "    other.replace(target)\n" if method == 'replace' else
                     "    target.write_bytes(replacement)\n") +
                    "    print('session-peer wrong')\n").encode()
                result = self.execute(*self.script(source))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('installed version mismatch', result.stderr)
                self.assertEqual(self.target.read_bytes(), replacement)
                self.assertEqual(self.launcher.lstat().st_ino, self.link_inode)
                self.assert_clean()

    def test_lock_contention_timeout_interrupt_and_stale_file_preserve_owned_scope(self):
        import fcntl
        lock = self.install / '.session-peer-install.lock'
        lock.write_text('user metadata must survive')
        inode = lock.stat().st_ino
        script, payload = self.script()
        with lock.open('rb') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            bounded = script.replace('deadline = time.monotonic() + 30',
                                     'deadline = time.monotonic() + 0.2')
            result = self.execute(bounded, payload)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('installation lock is busy', result.stderr)
            self.assert_preserved()
            waiting_source = (b"import os\nfrom pathlib import Path\n"
                              b"(Path(os.environ['HOME']) / 'waiting-staged').touch()\n"
                              b"print('session-peer 1.0.3')\n")
            waiting_script, waiting_payload = self.script(waiting_source)
            waiting = self.start(self.mark_lock_attempt(waiting_script, 'waiting-lock-attempt'),
                                 waiting_payload)
            self.wait_for(self.home / 'waiting-staged', waiting)
            self.wait_for(self.home / 'waiting-lock-attempt', waiting)
            self.assertIsNone(waiting.poll())
            os.killpg(waiting.pid, signal.SIGTERM)
            waiting.communicate(timeout=5)
            self.assertNotEqual(waiting.returncode, 0)
            self.assert_preserved()
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(lock.read_text(), 'user metadata must survive')
        # An unlocked file from an earlier process is reusable without deletion.
        result = self.execute(script, payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(lock.read_text(), 'user metadata must survive')
        self.assert_clean()

    def test_lock_symlink_and_hardlink_do_not_modify_user_files(self):
        lock = self.install / '.session-peer-install.lock'
        user = self.home / 'user-lock-data'
        user.write_text('keep')
        for kind in ('symlink', 'hardlink'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    lock.symlink_to(user)
                else:
                    os.link(user, lock)
                result = self.execute(*self.script())
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(user.read_text(), 'keep')
                self.assertTrue(lock.exists())
                self.assert_preserved()
                lock.unlink()

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
                  b"    while not (Path(os.environ['HOME']) / 'resume-version').exists(): time.sleep(0.01)\n"
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
            # A terminated lock holder releases its kernel lock; its retained
            # metadata file must not strand the next updater.
            (self.home / 'resume-version').touch()
            subsequent = self.execute(*self.script())
            self.assertNotEqual(subsequent.returncode, 0, subsequent.stderr)
            self.assertEqual(json.loads(subsequent.stdout)['reason'], 'remote_not_older')
            self.assertEqual(self.target.read_bytes(), source)
            self.assert_clean()
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


class RemoteRawSSH(unittest.TestCase):
    """Exercise real subprocess byte capture through an explicit local fake SSH."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='codex-fake-ssh-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fake = self.root / 'fake_ssh.py'
        self.local_run = subprocess.run

    def run_fake(self, command, **options):
        self.assertEqual(command[:2], ['ssh', 'fixture'])
        self.assertNotIn('encoding', options)
        self.assertNotIn('text', options)
        options['timeout'] = 10
        return self.local_run([sys.executable, str(self.fake)],
                              env={'HOME': str(self.root), 'PATH': os.defpath}, **options)

    def fake_output(self, output, status, with_input=False):
        self.fake.write_text('import base64, os, sys\n' +
                             ('base64.b64decode(sys.stdin.buffer.read(), validate=True)\n' if with_input else '') +
                             'os.write(1, ' + repr(output) + ')\n' +
                             "os.write(2, b'\\xff')\n" +
                             'raise SystemExit(' + str(status) + ')\n')

    def test_complete_push_receipt_survives_invalid_stderr_from_real_subprocess(self):
        for status in (0, 255):
            with self.subTest(status=status):
                self.fake_output(b'session-peer 1.0.3\n', status, with_input=True)
                with mock.patch.object(session_peer.Path, 'read_bytes', return_value=RemoteTransfer.SOURCE), \
                     mock.patch.object(session_peer, '__version__', '1.0.3'), \
                     mock.patch.object(session_peer.subprocess, 'run', side_effect=self.run_fake) as run:
                    self.assertEqual(session_peer.push_to_remote('fixture', [], {}), '1.0.3')
                run.assert_called_once()

    def test_incomplete_or_mismatched_push_stdout_remains_unknown(self):
        for output in (b'session-peer 1.0.4\n', b'session-peer 1.0.3',
                       b'session-peer 1.0.3\n\xff'):
            for status in (0, 255):
                with self.subTest(output=output, status=status):
                    self.fake_output(output, status, with_input=True)
                    with mock.patch.object(session_peer.Path, 'read_bytes', return_value=RemoteTransfer.SOURCE), \
                         mock.patch.object(session_peer, '__version__', '1.0.3'), \
                         mock.patch.object(session_peer.subprocess, 'run', side_effect=self.run_fake) as run, \
                         self.assertRaises(session_peer.CcPeerError) as caught:
                        session_peer.push_to_remote('fixture', [], {})
                    self.assertEqual(caught.exception.details['commitStatus'], 'unknown')
                    self.assertFalse(caught.exception.details['retryAllowed'])
                    run.assert_called_once()

    def test_installed_probe_decodes_stdout_strictly_and_stderr_as_diagnostic(self):
        for output, usable in ((b'session-peer 1.0.3\n', True),
                               (b'session-peer 1.0.3\xff\n', False)):
            with self.subTest(output=output):
                self.fake_output(output, 0)
                with mock.patch.object(session_peer.subprocess, 'run', side_effect=self.run_fake):
                    if usable:
                        self.assertEqual(session_peer.remote_installed_version('fixture', [], {}), '1.0.3')
                    else:
                        with self.assertRaises(session_peer.CcPeerError):
                            session_peer.remote_installed_version('fixture', [], {})
        self.fake_output(b'', 255)
        with mock.patch.object(session_peer.subprocess, 'run', side_effect=self.run_fake), \
             self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.remote_installed_version('fixture', [], {})
        self.assertEqual(caught.exception.details['sshFailure'], 'transport_failed')


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
        self.assertIsInstance(run.call_args.kwargs['input'], bytes)
        self.assertNotIn('encoding', run.call_args.kwargs)
        self.assertNotIn('text', run.call_args.kwargs)
        self.assertIn(f"{hashlib.sha256(source).hexdigest()} {len(source)};", run.call_args.args[0][-1])
        run.assert_called_once()

    def test_empty_or_wrong_remote_success_output_is_rejected(self):
        for output in ("", "session-peer unknown\n", "session-peer 9.9.9\n", "noise 1.0.3\n",
                       "session-peer 1.0.3", " session-peer 1.0.3\n", "session-peer 1.0.3\nnoise\n",
                       b"session-peer 1.0.3\n\xff"):
            with self.subTest(output=output), \
                 mock.patch.object(session_peer.Path, "read_bytes", return_value=self.SOURCE), \
                 mock.patch.object(session_peer, "__version__", self.VERSION), \
                 mock.patch.object(session_peer.subprocess, "run", return_value=
                                   subprocess.CompletedProcess([], 0, output, "")), \
                 self.assertRaises(session_peer.CcPeerError):
                session_peer.push_to_remote("fixture", [], {})

    def test_complete_receipt_survives_transport_exit_and_timeout_text_or_bytes(self):
        for output in ("session-peer 1.0.3\n", b"session-peer 1.0.3\n",
                       "session-peer 1.0.3\r\n"):
            for outcome in (subprocess.CompletedProcess([], 255, output, "Connection closed"),
                            subprocess.TimeoutExpired(["ssh"], 120, output=output)):
                with self.subTest(output=output, outcome=type(outcome).__name__), \
                     mock.patch.object(session_peer.Path, "read_bytes", return_value=self.SOURCE), \
                     mock.patch.object(session_peer, "__version__", self.VERSION), \
                     mock.patch.object(session_peer.subprocess, "run", side_effect=[outcome]) as run:
                    self.assertEqual(session_peer.push_to_remote("fixture", [], {}), self.VERSION)
                    run.assert_called_once()

    def test_partial_or_malformed_receipt_never_resolves_transport_uncertainty(self):
        for output in (None, "", b"", "session-peer 1.0.", b"session-peer 1.0.3",
                       "session-peer 1.0.3\nextra", b"session-peer 1.0.3\n\xff",
                       "session-peer 9.9.9\n", "session-peer 1.0.3\n\n"):
            for outcome, category in (
                (subprocess.CompletedProcess([], 255, output, "Connection closed"), "transport_failed"),
                (subprocess.TimeoutExpired(["ssh"], 120, output=output), "timeout"),
            ):
                with self.subTest(output=output, category=category), \
                     mock.patch.object(session_peer.Path, "read_bytes", return_value=self.SOURCE), \
                     mock.patch.object(session_peer, "__version__", self.VERSION), \
                     mock.patch.object(session_peer.subprocess, "run", side_effect=[outcome]) as run, \
                     self.assertRaises(session_peer.CcPeerError) as caught:
                    session_peer.push_to_remote("fixture", [], {})
                self.assertEqual(caught.exception.details["commitStatus"], "unknown")
                self.assertEqual(caught.exception.details["sshFailure"], category)
                self.assertFalse(caught.exception.details["retryAllowed"])
                self.assertNotIn('committed', caught.exception.details)
                run.assert_called_once()

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

    def test_only_complete_valid_rejections_resolve_uncertainty(self):
        receipt = json.dumps({'schemaVersion': 1, 'command': 'update', 'status': 'rejected',
                              'reason': 'remote_not_older', 'remoteVersion': '1.0.4'}) + '\n'
        for output in (receipt, receipt.encode()):
            for outcome in (subprocess.CompletedProcess([], 0, output, b'\xff'),
                            subprocess.CompletedProcess([], 255, output, b'\xff'),
                            subprocess.TimeoutExpired(['ssh'], 120, output=output)):
                with self.subTest(output=output, outcome=type(outcome).__name__), \
                     mock.patch.object(session_peer.Path, 'read_bytes', return_value=self.SOURCE), \
                     mock.patch.object(session_peer, '__version__', self.VERSION), \
                     mock.patch.object(session_peer.subprocess, 'run', side_effect=[outcome]) as run, \
                     self.assertRaises(session_peer.CcPeerError) as caught:
                    session_peer.push_to_remote('fixture', [], {})
                self.assertEqual(caught.exception.details['commitStatus'], 'not_started')
                self.assertFalse(caught.exception.details['retryAllowed'])
                self.assertEqual(caught.exception.details['remoteVersion'], '1.0.4')
                run.assert_called_once()
        for output in (receipt.rstrip(), receipt + '\n', receipt + 'noise\n',
                       receipt.replace('1.0.4', '1.0.2'), receipt.encode() + b'\xff'):
            with self.subTest(output=output):
                self.assertIsNone(session_peer.installed_update_rejection(output, self.VERSION))

    def test_invalid_json_rejections_preserve_unknown_commit_without_retry(self):
        receipt = json.dumps({'schemaVersion': 1, 'command': 'update', 'status': 'rejected',
                              'reason': 'installed_version_unusable', 'remoteVersion': None}) + '\n'
        malformed = [
            ('duplicate status', receipt.replace('"status": "rejected"',
                                                  '"status": "committed", "status": "rejected"')),
            ('duplicate schema', receipt.replace('"schemaVersion": 1',
                                                  '"schemaVersion": 1, "schemaVersion": 1')),
            ('oversized version', json.dumps({'schemaVersion': 1, 'command': 'update',
                                             'status': 'rejected', 'reason': 'remote_not_older',
                                             'remoteVersion': '1' + '0' * 5000 + '.0.0'}) + '\n'),
        ]
        for constant in ('NaN', 'Infinity', '-Infinity'):
            malformed.append((constant, receipt.replace('"remoteVersion": null',
                                '"remoteVersion": ' + constant + ', "remoteVersion": null')))
            malformed.append((constant + ' without duplicate',
                              receipt.replace('"remoteVersion": null', '"remoteVersion": ' + constant)))
        for label, text in malformed:
            for output in (text, text.encode()):
                for outcome in (subprocess.CompletedProcess([], 0, output, b'\xff'),
                                subprocess.CompletedProcess([], 255, output, b'\xff'),
                                subprocess.TimeoutExpired(['ssh'], 120, output=output)):
                    with self.subTest(case=label, output=type(output).__name__,
                                      outcome=type(outcome).__name__), \
                         mock.patch.object(session_peer.Path, 'read_bytes', return_value=self.SOURCE), \
                         mock.patch.object(session_peer, '__version__', self.VERSION), \
                         mock.patch.object(session_peer.subprocess, 'run', side_effect=[outcome]) as run, \
                         self.assertRaises(session_peer.CcPeerError) as caught:
                        session_peer.push_to_remote('fixture', [], {})
                    self.assertEqual(caught.exception.details['commitStatus'], 'unknown')
                    self.assertFalse(caught.exception.details['retryAllowed'])
                    self.assertNotIn('committed', caught.exception.details)
                    self.assertNotIn('updated', caught.exception.details)
                    run.assert_called_once()


class RemoteVersions(unittest.TestCase):
    def test_publication_rejection_is_an_error_without_success_or_resubmission(self):
        receipt = json.dumps({'schemaVersion': 1, 'command': 'update', 'status': 'rejected',
                              'reason': 'remote_not_older', 'remoteVersion': '1.0.4'}) + '\n'
        args = argparse.Namespace(host=['fixture'], ssh_opt=[], check=False, json=True)
        output = io.StringIO()
        with mock.patch.object(session_peer, '__version__', '1.0.3'), \
             mock.patch.object(session_peer, 'tailscale_status', return_value={}), \
             mock.patch.object(session_peer, 'ssh_user_metadata', return_value={}), \
             mock.patch.object(session_peer, 'remote_installed_version', return_value='1.0.2') as probe, \
             mock.patch.object(session_peer.Path, 'read_bytes', return_value=RemoteTransfer.SOURCE), \
             mock.patch.object(session_peer.subprocess, 'run', return_value=
                               subprocess.CompletedProcess([], 1, receipt.encode(), b'\xff')) as run, \
             contextlib.redirect_stdout(output):
            code = session_peer.cmd_update(args)
        result = json.loads(output.getvalue())
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertFalse(result['ok'])
        self.assertEqual(result['commitStatus'], 'not_started')
        self.assertEqual(result['remoteVersion'], '1.0.4')
        self.assertFalse(result['retryAllowed'])
        self.assertNotIn('updated', result)
        self.assertNotIn('committed', result)
        probe.assert_called_once()
        run.assert_called_once()

    def test_transport_receipt_still_requires_fresh_probe_and_preserves_probe_failure(self):
        for outcome in (
            subprocess.CompletedProcess([], 255, b"session-peer 1.0.3\n", "Connection closed"),
            subprocess.TimeoutExpired(["ssh"], 120, output=b"session-peer 1.0.3\n"),
        ):
            failure = session_peer.CcPeerError("fresh SSH probe timed out", {"sshFailure": "timeout"})
            for fresh in ("1.0.3", "1.0.4", failure):
                args = argparse.Namespace(host=["fixture"], ssh_opt=[], check=False, json=True)
                output = io.StringIO()
                with self.subTest(outcome=type(outcome).__name__, fresh=fresh), \
                     mock.patch.object(session_peer, "__version__", "1.0.3"), \
                     mock.patch.object(session_peer, "tailscale_status", return_value={}), \
                     mock.patch.object(session_peer, "ssh_user_metadata", return_value={}), \
                     mock.patch.object(session_peer, "remote_installed_version",
                                       side_effect=["1.0.2", fresh]) as probe, \
                     mock.patch.object(session_peer.Path, "read_bytes", return_value=RemoteTransfer.SOURCE), \
                     mock.patch.object(session_peer.subprocess, "run", side_effect=[outcome]) as run, \
                     contextlib.redirect_stdout(output):
                    code = session_peer.cmd_update(args)
                result = json.loads(output.getvalue())
                self.assertEqual(probe.call_count, 2)
                run.assert_called_once()
                if fresh == "1.0.3":
                    self.assertEqual(code, 0)
                    self.assertTrue(result["updated"])
                else:
                    self.assertEqual(code, session_peer.EXIT_ERROR)
                    self.assertTrue(result["committed"])
                    self.assertEqual(result["commitStatus"], "committed")
                    self.assertEqual(result["installedVersionVerified"], "1.0.3")
                    self.assertFalse(result["retryAllowed"])
                    self.assertNotIn("updated", result)
                    if isinstance(fresh, session_peer.CcPeerError):
                        self.assertEqual(result["verificationStatus"], "unknown")
                        self.assertEqual(result["sshFailure"], "timeout")
                    else:
                        self.assertEqual(result["verificationStatus"], "mismatch")
                        self.assertEqual(result["remoteVersion"], "1.0.4")

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
