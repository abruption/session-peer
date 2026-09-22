"""Codex contract tests: fixture DBs and process boundaries, no live agents."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

import session_peer as peer

from tests.codex.support import OTHER, THREAD


class CodexWriterEvidence(unittest.TestCase):
    def test_parses_nul_delimited_lsof_processes(self):
        self.assertEqual(peer.parse_lsof_processes("p42\0ccodex\0u501\0\np7\0cnode\0u502\0"), [
            {"pid": 7, "command": "node", "uid": 502},
            {"pid": 42, "command": "codex", "uid": 501},
        ])

    def test_missing_lock_is_inactive_even_when_flock_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(peer, "fcntl", None):
            lock = Path(directory) / "missing.lock"
            self.assertEqual(peer.probe_codex_writer_lock(lock),
                             ("absent", "lock_absent"))
            lock.write_text("fixture", encoding="utf-8")
            self.assertEqual(peer.probe_codex_writer_lock(lock),
                             ("unknown", "lock_probe_unsupported"))

    @unittest.skipIf(peer.fcntl is None, "POSIX flock is unavailable")
    def test_probes_a_real_advisory_lock_without_changing_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "thread.lock"
            lock.write_text("unchanged", encoding="utf-8")
            child = subprocess.Popen([
                peer.sys.executable, "-c",
                "import fcntl,sys,time; f=open(sys.argv[1],'r+'); "
                "fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); time.sleep(60)",
                str(lock),
            ], stdout=subprocess.PIPE, text=True)

            def cleanup():
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                if child.stdout and not child.stdout.closed:
                    child.stdout.close()

            self.addCleanup(cleanup)
            self.assertEqual(child.stdout.readline().strip(), "ready")
            self.assertEqual(peer.probe_codex_writer_lock(lock),
                             ("held", "kernel_lock_held"))
            self.assertEqual(lock.read_text(encoding="utf-8"), "unchanged")
            child.terminate()
            child.wait(timeout=5)
            self.assertEqual(peer.probe_codex_writer_lock(lock),
                             ("free", "kernel_lock_free"))

    @unittest.skipIf(peer.fcntl is None, "POSIX flock is unavailable")
    @unittest.skipIf(peer._lsof_executable() is None, "lsof is unavailable")
    def test_correlates_a_real_lock_opener_without_reading_process_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "thread.lock"
            lock.write_text("unchanged", encoding="utf-8")
            child = subprocess.Popen([
                peer.sys.executable, "-c",
                "import fcntl,sys,time; f=open(sys.argv[1],'r+'); "
                "fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); time.sleep(60)",
                str(lock),
            ], stdout=subprocess.PIPE, text=True)

            def cleanup():
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                if child.stdout and not child.stdout.closed:
                    child.stdout.close()

            self.addCleanup(cleanup)
            self.assertEqual(child.stdout.readline().strip(), "ready")
            openers, error = peer._codex_lock_openers(lock)
            self.assertIsNone(error)
            self.assertEqual([process["pid"] for process in openers], [child.pid])
            self.assertNotIn("args", openers[0])

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX UID is unavailable")
    def test_stable_same_user_codex_owner_is_live(self):
        sample = {
            "snapshot": (1, 2, 0, 3), "writerLock": "held",
            "probeReason": "kernel_lock_held", "openerError": None,
            "openers": [{"pid": 42, "uid": os.getuid(), "command": "codex",
                         "startTime": "stable"}],
        }
        with mock.patch.object(peer, "_codex_lock_sample", side_effect=[sample, sample]), \
             mock.patch.object(peer.time, "sleep"):
            result = peer.inspect_codex_writer(Path("/home"), THREAD)
        self.assertEqual(result["activity"], "live_writer")
        self.assertEqual(result["ownerPid"], 42)
        self.assertEqual(result["ownerStartTime"], "stable")
        self.assertNotIn("command", result)
        self.assertNotIn("startTime", result)

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX UID is unavailable")
    def test_pid_change_is_unknown(self):
        def sample(pid):
            return {
                "snapshot": (1, 2, 0, 3), "writerLock": "held",
                "probeReason": "kernel_lock_held", "openerError": None,
                "openers": [{"pid": pid, "uid": os.getuid(), "command": "codex",
                             "startTime": "stable"}],
            }
        with mock.patch.object(peer, "_codex_lock_sample",
                               side_effect=[sample(42), sample(43)]), \
             mock.patch.object(peer.time, "sleep"):
            result = peer.inspect_codex_writer(Path("/home"), THREAD)
        self.assertEqual(result["activity"], "unknown")
        self.assertEqual(result["reason"], "lock_owner_changed")
