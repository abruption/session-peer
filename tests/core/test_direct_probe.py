"""Experimental client's timeout remains structured on the Python 3.9 floor."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]


class DirectProbeTimeout(unittest.TestCase):
    def test_stalled_loopback_echo_returns_metadata_without_traceback(self):
        stop = threading.Event()
        errors = []
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(5)

            def stall():
                try:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(4)
                        connection.recv(64)
                        stop.wait(8)
                except OSError as exc:
                    errors.append(type(exc).__name__)

            worker = threading.Thread(target=stall, daemon=True)
            worker.start()
            try:
                result = subprocess.run([
                    sys.executable, str(ROOT / 'experiments/macos-direct-listener/tcp_probe.py'),
                    'client', '--selector', 'select', '--connect', '127.0.0.1',
                    '--port', str(listener.getsockname()[1]),
                ], cwd=ROOT, capture_output=True, text=True, timeout=10)
            finally:
                stop.set()
                worker.join(6)
            self.assertFalse(worker.is_alive(), 'loopback fixture did not stop')
            self.assertFalse(errors, 'loopback fixture failed')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual([json.loads(line) for line in result.stdout.splitlines()], [
            {'event': 'connected'},
            {'event': 'result', 'echo': False, 'error': 'TimeoutError'},
        ])
