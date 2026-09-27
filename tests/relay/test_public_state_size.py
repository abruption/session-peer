"""Reader-side byte boundary of the Control publication contract."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from tests.relay import test_native_relay as platform_guard
from session_peer_relay.auth import ControlAdmission, AdmissionDenied


class StateSize(unittest.TestCase):
    def test_utf8_limit_matches_writer_and_retains_revoked_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = ControlAdmission.__new__(ControlAdmission)
            reader.state_file = Path(directory)/'state.json'
            reader.issuer = 'https://relay.example.test'
            reader.highest_revision = 0
            reader.state_digest = None
            reader.persist = Mock()
            now = time.time()
            state = {'schemaVersion': 1, 'issuer': reader.issuer, 'audience': reader.issuer,
                     'revision': 1, 'issuedAt': now, 'expiresAt': now + 60,
                     'devices': {'fixture': {'revoked': True, 'userId': '한😀'}}, 'padding': ''}
            encode = lambda: json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode()
            base = len(encode())
            for delta in (-1, 0, 1):
                state['padding'] = 'x' * (1024 * 1024 - base + delta)
                raw = encode()
                self.assertEqual(len(raw), 1024 * 1024 + delta)
                reader.state_file.write_bytes(raw)
                if delta > 0:
                    with self.assertRaisesRegex(AdmissionDenied, 'auth_state_too_large'):
                        reader.state()
                else:
                    self.assertTrue(reader.state()['devices']['fixture']['revoked'])
