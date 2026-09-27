import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tests.relay import test_native_relay as platform_guard
from session_peer_relay import control, cli
from session_peer_relay.guidance import with_guidance
from session_peer_relay.transport_errors import failure


class Guidance(unittest.TestCase):
    def test_control_device_not_found_keeps_old_reason_and_only_adds_allowlisted_hint(self):
        import io
        class Response(io.BytesIO):
            code = 404
            headers = {}
        for error, expected in [('device_not_found', 'device_not_found'), ('SECRET', None)]:
            with patch('urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = Response(('{"error":"' + error + '"}').encode())
                with self.assertRaises(Exception) as caught:
                    control.call('https://relay.example.test', '/api/relay/admission')
                self.assertEqual(str(caught.exception), 'control_request_refused')
                self.assertEqual(caught.exception.diagnostic().get('hint'), expected)

    def test_fixed_hints_preserve_delivery_contract(self):
        for reason, category in [('login_expired', 'login'), ('unpaired_device', 'pairing'),
                                 ('target_denied', 'policy'), ('codex_executable_not_found', 'native_target'),
                                 ('no_authenticated_route', 'unreachable'), ('native_outcome_unknown', 'unknown')]:
            original = {'ok': False, 'reason': reason, 'retryAllowed': False, 'status': 'unknown'}
            result = with_guidance(original)
            self.assertEqual(result['guidance']['category'], category)
            self.assertEqual({k: result[k] for k in original}, original)
        for reason in ('control_request_refused', 'FileNotFoundError', 'SECRET', None):
            self.assertNotIn('guidance', with_guidance({'ok': False, 'reason': reason}))
        self.assertNotIn('guidance', with_guidance({'ok': True, 'status': 'queued'}))
        diagnosed = with_guidance({'ok': False, 'reason': 'control_request_refused',
                                  'connectionFailure': {'hint': 'device_not_found', 'httpStatus': 404}})
        self.assertEqual(diagnosed['reason'], 'control_request_refused')
        self.assertEqual(diagnosed['guidance']['category'], 'enrollment')

    def test_missing_login_is_proven_not_inferred_from_arbitrary_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError) as caught:
                control.session(SimpleNamespace(root=Path(directory)))
            detail = failure('control_request', caught.exception).diagnostic()
            self.assertEqual(detail['reason'], 'connection_failed')
            result = with_guidance({'ok': False, 'reason': 'FileNotFoundError', **cli.connection_diagnostics(caught.exception)})
            self.assertEqual(result['guidance']['category'], 'login')
            route = with_guidance({'ok': False, 'reason': 'no_authenticated_route', 'routeFailures': {'relay': detail}})
            self.assertEqual(route['guidance']['category'], 'login')
            self.assertNotIn(directory, str(result))
