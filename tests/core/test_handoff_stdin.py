"""Owned raw input fixtures only; no ledger, target or native agent calls."""

import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from unittest.mock import patch

from session_peer import HandoffStdinError, read_handoff_stdin
import session_peer as peer


@unittest.skipUnless(os.name == "posix", "bounded raw POSIX descriptor fixture")
class HandoffStdin(unittest.TestCase):
    def pipe_read(self, chunks, delay=0, timeout=.5, **limits):
        read_fd, write_fd = os.pipe()
        failures = []

        def write():
            try:
                for chunk in chunks:
                    if delay:
                        time.sleep(delay)
                    view = memoryview(chunk)
                    while view:
                        n = os.write(write_fd, view)
                        view = view[n:]
            except BrokenPipeError:
                pass
            except BaseException as exc:
                failures.append(exc)
            finally:
                os.close(write_fd)

        worker = threading.Thread(target=write)
        worker.start()
        try:
            with os.fdopen(read_fd, "rb") as stream:
                before = os.get_blocking(stream.fileno())
                try:
                    return read_handoff_stdin(stream, time.monotonic() + timeout,
                                             time.monotonic, **limits)
                finally:
                    self.assertEqual(os.get_blocking(stream.fileno()), before)
        finally:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])

    def assert_reason(self, reason, callback):
        with self.assertRaises(HandoffStdinError) as caught:
            callback()
        error = caught.exception
        self.assertEqual(error.reason, reason)
        self.assertEqual(error.exit_code, 1)
        self.assertEqual(error.details, {"reason": reason, "retryAllowed": False})
        self.assertNotIn("handoff", error.details)
        self.assertNotIn("ledgerEpoch", error.details)
        self.assertNotIn("correlationId", error.details)
        return error

    def test_unicode_split_chunks_and_lf_are_preserved(self):
        raw = "  한글🙂\n\r\n".encode("utf-8")
        self.assertEqual(self.pipe_read([bytes([byte]) for byte in raw], delay=.002), raw.decode())

    def test_empty_eof_is_returned_for_existing_nonempty_validator(self):
        self.assertEqual(self.pipe_read([]), "")

    def test_raw_and_character_limits_accept_exact_boundary(self):
        self.assertEqual(self.pipe_read(["🙂".encode()], max_bytes=4, max_chars=1), "🙂")

    def test_one_byte_chunks_retain_one_bounded_aggregate(self):
        # Deterministic producer/readiness stubs avoid 20,000 real scheduling
        # waits. A per-read string/list implementation exceeds this small
        # allocation bound; a single raw buffer + final string stays below it.
        count = 0
        size = 20_000
        def one_byte(fd, limit):
            nonlocal count
            count += 1
            return b"x" if count <= size else b""
        class Ready:
            def register(self, fd, events):
                pass
            def select(self, timeout):
                return [(None, None)]
            def close(self):
                pass
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        with os.fdopen(read_fd, "rb") as stream:
            with patch("session_peer.os.read", new=one_byte), patch("session_peer.selectors.SelectSelector", new=Ready):
                tracemalloc.start()
                try:
                    result = read_handoff_stdin(stream, 10, lambda: 0)
                    _, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
            self.assertEqual(result, "x" * size)
            self.assertLess(peak, 100_000)
            self.assertTrue(os.get_blocking(stream.fileno()))

    def test_raw_overflow_refuses_without_reflecting_body(self):
        error = self.assert_reason("handoff_stdin_too_large",
                                  lambda: self.pipe_read([b"private-test-body"], max_bytes=4))
        self.assertNotIn("private-test-body", str(error))

    def test_codepoint_overflow_refuses(self):
        self.assert_reason("handoff_stdin_too_large", lambda: self.pipe_read([b"abc"], max_chars=2))

    def test_full_default_byte_budget_is_bounded(self):
        self.assert_reason("handoff_stdin_too_large", lambda: self.pipe_read([b"a" * 4_000_001], max_chars=5_000_000))

    def test_bad_utf8_and_incomplete_scalar_are_rejected(self):
        for raw in (b"x\xff", b"\xf0\x9f", b"\xc0\xaf", b"\xed\xa0\x80"):
            self.assert_reason("handoff_stdin_invalid_utf8", lambda: self.pipe_read([raw]))

    def test_never_eof_pipe_has_one_deadline_and_restores_flags(self):
        read_fd, write_fd = os.pipe()
        started = time.monotonic()
        try:
            with os.fdopen(read_fd, "rb") as stream:
                self.assert_reason("handoff_stdin_deadline", lambda: read_handoff_stdin(stream, started + .06, time.monotonic))
                self.assertTrue(os.get_blocking(stream.fileno()))
            self.assertLess(time.monotonic() - started, .5)
        finally:
            os.close(write_fd)

    def test_slow_chunks_do_not_renew_original_budget(self):
        self.assert_reason("handoff_stdin_deadline", lambda: self.pipe_read([b"x"] * 10, delay=.015, timeout=.045))

    def test_expired_cutoff_does_not_access_stream(self):
        class NoAccess:
            def isatty(self):
                raise AssertionError("expired input must not inspect descriptor")
        self.assert_reason("handoff_stdin_deadline", lambda: read_handoff_stdin(NoAccess(), 10, lambda: 10))

    def test_regular_file_and_text_wrapper_read_raw_utf8_not_locale(self):
        with tempfile.TemporaryFile() as binary:
            binary.write("試験\n".encode()); binary.seek(0)
            text = io.TextIOWrapper(binary, encoding="ascii")
            self.assertEqual(read_handoff_stdin(text, time.monotonic() + 1, time.monotonic), "試験\n")
            text.detach()

    def test_unsupported_descriptor_and_terminal_have_fixed_errors(self):
        self.assert_reason("handoff_stdin_unavailable", lambda: read_handoff_stdin(io.BytesIO(b"x"), time.monotonic() + 1, time.monotonic))
        class Terminal:
            def isatty(self):
                return True
        self.assert_reason("handoff_stdin_terminal", lambda: read_handoff_stdin(Terminal(), time.monotonic() + 1, time.monotonic))

    def test_windows_is_explicitly_unsupported_before_stream_access(self):
        with patch("session_peer.os.name", "nt"):
            self.assert_reason("handoff_stdin_platform_unsupported", lambda: read_handoff_stdin(None, 1, lambda: 0))

    def test_cleanup_flag_restore_failure_is_typed_pre_effect(self):
        read_fd, write_fd = os.pipe(); os.close(write_fd)
        try:
            with os.fdopen(read_fd, "rb") as stream:
                original = os.set_blocking
                calls = []
                def flags(fd, value):
                    calls.append(value)
                    if len(calls) == 2:
                        raise OSError("untrusted-diagnostic-do-not-reflect")
                    return original(fd, value)
                with patch("session_peer.os.set_blocking", side_effect=flags):
                    self.assert_reason("handoff_stdin_unavailable", lambda: read_handoff_stdin(stream, time.monotonic() + 1, time.monotonic))
        finally:
            # fd belongs only to this fixture and is closed by its stream.
            pass

    def test_sigint_is_metadata_only_130_without_fabricated_context(self):
        source = '''import json, sys, time
from session_peer import HandoffStdinError, read_handoff_stdin
print("READY", flush=True)
try:
    read_handoff_stdin(sys.stdin, time.monotonic()+2, time.monotonic)
except HandoffStdinError as exc:
    print(json.dumps({"ok":False, **exc.details}), flush=True)
    raise SystemExit(exc.exit_code)
'''
        with subprocess.Popen([sys.executable, "-c", source], cwd=Path(peer.__file__).parent,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) as child:
            self.assertEqual(child.stdout.readline().strip(), "READY")
            child.send_signal(signal.SIGINT)
            stdout, stderr = child.communicate(timeout=2)
            self.assertEqual(child.returncode, 130)
            self.assertEqual(stderr, "")
            self.assertEqual(json.loads(stdout), {"ok":False, "reason":"handoff_stdin_interrupted", "retryAllowed":False})


if __name__ == "__main__":
    unittest.main()
