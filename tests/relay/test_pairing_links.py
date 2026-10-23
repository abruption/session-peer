"""Offline pairing envelope validation; no link or secret enters diagnostics."""
import base64
import copy
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import unittest

if os.name != 'posix' or sys.version_info < (3, 11):
    raise unittest.SkipTest('optional relay requires POSIX and Python 3.11+')
try:
    import cryptography
    import websockets
except ModuleNotFoundError as exc:
    if exc.name not in ('cryptography', 'websockets'):
        raise
    raise unittest.SkipTest('optional relay dependencies unavailable') from None

from session_peer_relay.pairing_links import (
    PREFIX, MAX_LINK_BYTES, MAX_DECODED_BYTES, encode_link, decode_link, link_digest,
)
from session_peer_relay.store import Store


class PairingLinks(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='codex-pair-link-', dir=os.environ.get('SESSION_PEER_TEST_TMP'))
        self.addCleanup(directory.cleanup)
        self.receiver = Store(pathlib.Path(directory.name) / 'receiver')
        self.addCleanup(self.receiver.close)
        self.invite = self.receiver.invite({'direct': '127.0.0.1:12345',
                                          'relay': 'wss://relay.example/v1/connect'})
        self.key = 'a' * 64

    def envelope(self, invitation=None, **extra):
        return dict(v=1, invitation=self.invite if invitation is None else invitation,
                    clientKeyFingerprint=self.key, **extra)

    def raw_link(self, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip('=')

    def rejected(self, link):
        with self.assertRaisesRegex(ValueError, '^invalid_pairing_link$') as error:
            decode_link(link)
        self.assertIsNone(error.exception.__cause__)
        self.assertNotIn(self.invite['secret'], str(error.exception))

    def test_round_trip_and_digest_of_original_link(self):
        link = encode_link(self.invite, self.key)
        self.assertEqual(decode_link(link), (self.invite, self.key))
        self.assertEqual(link_digest(link), hashlib.sha256(link.encode()).hexdigest())
        formatted = self.raw_link(self.envelope())
        self.assertEqual(decode_link(formatted), (self.invite, self.key))
        self.assertNotEqual(link_digest(link), link_digest(formatted))

    def test_rotated_invitation_checks_key_not_principal(self):
        invite = dict(self.invite, v=2, device='b'*64,
                      keyFingerprint=self.receiver.key_id, keyGeneration=2)
        self.assertEqual(decode_link(encode_link(invite, self.key)), (invite, self.key))
        invite['keyFingerprint'] = invite['device']
        self.rejected(self.raw_link(self.envelope(invite)))

    def test_expired_invitation_remains_decodable_for_reconciliation(self):
        invite = dict(self.invite, expires=0)
        self.assertEqual(decode_link(encode_link(invite, self.key))[0], invite)

    def test_prefix_ascii_padding_and_alphabet_are_strict(self):
        link = encode_link(self.invite, self.key)
        for bad in (link+'=', link+'\n', link+'é', link.replace('pair/v1', 'pair/v2'),
                    link.replace('session-peer:', 'https:', 1), PREFIX, None,
                    PREFIX+'a', PREFIX+'abc+', PREFIX+'abc/'):
            with self.subTest(bad_type=type(bad).__name__):
                self.rejected(bad)
        # Nonzero unused padding bits must not alias a canonical encoding.
        self.rejected(PREFIX+'Zh')

    def test_bounds_apply_to_decoded_bytes_and_whole_ascii_link(self):
        self.rejected(PREFIX + 'a' * MAX_LINK_BYTES)
        self.rejected(self.raw_link(b' ' * (MAX_DECODED_BYTES+1)))
        invite = dict(self.invite, certificate='x' * MAX_DECODED_BYTES)
        with self.assertRaisesRegex(ValueError, '^invalid_pairing_link$'):
            encode_link(invite, self.key)

    def test_duplicate_fields_rejected_at_all_depths(self):
        raw = json.dumps(self.envelope())
        for bad in (raw.replace('"v": 1', '"v": 1, "v": 1', 1),
                    raw.replace('"secret":', '"v": 1, "secret":', 1),
                    raw.replace('"direct":', '"direct":"localhost:1", "direct":', 1)):
            self.rejected(self.raw_link(bad.encode()))

    def test_exact_wrapper_and_invitation_fields(self):
        for envelope in (self.envelope(extra='secret'),
                         {'v': 1, 'invitation': self.invite},
                         dict(self.envelope(), v=True), dict(self.envelope(), v=2), []):
            self.rejected(self.raw_link(envelope))
        for invite in (dict(self.invite, extra='secret'), dict(self.invite, v=True),
                       dict(self.invite, v=2), dict(self.invite, keyGeneration=0)):
            self.rejected(self.raw_link(self.envelope(invite)))

    def test_invalid_ids_secret_certificate_and_route_are_sanitized(self):
        for field, bad in (
            ('id', self.invite['id'].upper()), ('id', '0'*36),
            ('device', self.receiver.device.upper()), ('device', self.key),
            ('secret', 'a'*43), ('secret', self.invite['secret']+'='),
            ('certificate', 'PRIVATE SECRET'), ('routes', {}), ('routes', {'unknown': 'value'}),
            ('routes', {'direct': 'user:pass@localhost:1'}),
            ('routes', {'relay': 'https://relay.example/v1/connect'}),
            ('routes', {'relay': 'wss://relay.example/v1/connect?secret=value'}),
            ('routes', {'direct': 'localhost:1\n'}), ('routes', []),
        ):
            with self.subTest(field=field):
                self.rejected(self.raw_link(self.envelope(dict(self.invite, **{field: bad}))))
        for bad in (self.key.upper(), 'a'*63, None):
            self.rejected(self.raw_link(dict(self.envelope(), clientKeyFingerprint=bad)))

    def test_numeric_diagnostics_and_generation_are_finite_exact_types(self):
        for expires in (True, '1', float('nan'), float('inf'), -float('inf')):
            self.rejected(self.raw_link(self.envelope(dict(self.invite, expires=expires))))
        # An exponent overflowing float is not handled by parse_constant.
        raw = json.dumps(self.envelope()).replace(str(self.invite['expires']), '1e9999')
        self.rejected(self.raw_link(raw.encode()))
        for generation in (True, 0, -1, 1.0, '1'):
            invite = dict(self.invite, v=2, keyFingerprint=self.receiver.key_id,
                          keyGeneration=generation)
            self.rejected(self.raw_link(self.envelope(invite)))

    def test_malformed_json_unicode_and_deep_input_have_fixed_errors(self):
        for raw in (b'{', b'\xff', b'[]', b'null', b'['*1100+b']'*1100):
            self.rejected(self.raw_link(raw))

    def test_encoding_does_not_mutate_invitation_and_sanitizes_errors(self):
        original = copy.deepcopy(self.invite)
        encode_link(self.invite, self.key)
        self.assertEqual(original, self.invite)
        for invite in (None, dict(self.invite, expires=float('nan'))):
            with self.assertRaisesRegex(ValueError, '^invalid_pairing_link$'):
                encode_link(invite, self.key)
        with self.assertRaisesRegex(ValueError, '^invalid_pairing_link$'):
            link_digest('secret-bad-link')
