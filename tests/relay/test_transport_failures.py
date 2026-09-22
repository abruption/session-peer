"""Transient route setup must not turn into application-message retries."""
import asyncio
import contextlib
import io
import json
import ssl
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.relay import test_native_relay as platform_guard
from session_peer_relay import app, cli, control, wire
from session_peer_relay.store import Rejected
from session_peer_relay.transport_errors import TransportFailure, NoAuthenticatedRoute, failure

SECRET = 'SECRET-TOKEN-COOKIE-PROOF-MESSAGE'


class TransportDiagnostics(unittest.TestCase):
    def test_untrusted_exception_messages_are_not_exposed(self):
        for exc in (RuntimeError(SECRET), ValueError(SECRET), Rejected(SECRET),
                    urllib.error.URLError(SECRET), ssl.SSLError(SECRET)):
            detail = failure('relay_websocket', exc)
            self.assertNotIn(SECRET, json.dumps(detail.diagnostic()))
            self.assertFalse(detail.transient)
        detail = failure('control_request', urllib.error.URLError(TimeoutError(SECRET)))
        self.assertEqual(detail.diagnostic(), {'stage':'control_request','reason':'timeout'})
        self.assertTrue(detail.transient)

    def test_control_body_timeout_closes_response_and_is_sanitized(self):
        response = Mock()
        response.code = 200
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = TimeoutError(SECRET)
        opener = Mock(); opener.open.return_value = response
        with patch.object(control.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(TransportFailure) as caught:
                control.call('https://relay.example.test', '/api/relay/admission', {'proof':SECRET}, SECRET)
        self.assertEqual(caught.exception.stage, 'control_response')
        self.assertTrue(caught.exception.transient)
        self.assertNotIn(SECRET, str(caught.exception))
        response.__exit__.assert_called_once()
        opener.open.assert_called_once()  # No automatic control-write retry.

    def test_refusal_body_timeout_is_not_retried(self):
        response = Mock(code=403)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = TimeoutError(SECRET)
        opener = Mock(); opener.open.return_value = response
        with patch.object(control.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(TransportFailure) as caught:
                control.call('https://relay.example.test', '/api/relay/admission', {})
        self.assertFalse(caught.exception.transient)
        self.assertEqual(caught.exception.http_status, 403)
        response.__exit__.assert_called_once()

    def test_control_open_timeout_and_http_rejection_are_distinct(self):
        opener=Mock(); opener.open.side_effect=urllib.error.URLError(TimeoutError(SECRET))
        with patch.object(control.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(TransportFailure) as caught:
                control.call('https://relay.example.test', '/api/relay/challenge', {})
        self.assertEqual(caught.exception.stage,'control_request')
        self.assertTrue(caught.exception.transient)
        response=urllib.error.HTTPError('https://secret.test/'+SECRET,403,SECRET,{},io.BytesIO(json.dumps({'error':SECRET}).encode()))
        opener.open.side_effect=response
        with patch.object(control.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(TransportFailure) as caught:
                control.call('https://relay.example.test', '/api/relay/challenge', {})
        self.assertEqual(caught.exception.http_status,403)
        self.assertEqual(str(caught.exception),'control_request_refused')
        self.assertFalse(caught.exception.transient)

    def test_relay_admission_refusal_is_status_only(self):
        response=urllib.error.HTTPError('https://secret.test/'+SECRET,401,SECRET,{},io.BytesIO(SECRET.encode()))
        opener=Mock();opener.open.side_effect=response
        with patch.object(wire.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(TransportFailure) as caught:
                wire.admission('wss://relay.example.test/v1/connect',SECRET)
        self.assertEqual(caught.exception.diagnostic(),{'stage':'relay_admission','reason':'http_rejected','httpStatus':401})
        self.assertFalse(caught.exception.transient)
        self.assertTrue(response.fp.closed)
        with self.assertRaises(ValueError):
            wire.admission('https://not-valid',SECRET)

    def test_cli_retains_failure_contract_and_safe_details(self):
        exc=NoAuthenticatedRoute([{'route':'relay','stage':'control_request','reason':'timeout','attempts':2}])
        args=SimpleNamespace(device='a'*64,command='list',json=True)
        output=io.StringIO()
        with patch.object(cli,'core_exchange',new=AsyncMock(side_effect=exc)),contextlib.redirect_stdout(output):
            self.assertEqual(cli.invoke_core(args),1)
        result=json.loads(output.getvalue())
        self.assertEqual(result['reason'],'no_authenticated_route')
        self.assertFalse(result['retryAllowed'])
        self.assertFalse(result['consumptionConfirmed'])
        self.assertEqual(result['routeFailures'],exc.route_failures)


class RouteSetup(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store=Mock()
        self.store.recovery_required.return_value=False
        self.store.device='a'*64
        self.peer='b'*64
        self.store.peer.return_value={'status':'paired','certificate':'fixture',
                                     'routes':{'direct':'127.0.0.1:1','relay':'ws://127.0.0.1:2/v1/connect'}}

    def channel(self, responses):
        return SimpleNamespace(send=AsyncMock(),recv=AsyncMock(side_effect=responses),close=AsyncMock())

    async def test_timeout_retries_setup_then_submits_exactly_once(self):
        channel=self.channel([{'ok':True,'device':self.peer},{'ok':True,'status':'queued','consumptionConfirmed':False}])
        with patch.object(app,'open_channel',new=AsyncMock(side_effect=[TransportFailure('relay_websocket','timeout',transient=True),channel])) as connect,patch.object(app.asyncio,'sleep',new=AsyncMock()):
            result=await app.exchange(self.store,self.peer,'send',{'target':'worker','message':SECRET},route='relay')
        self.assertTrue(result['ok']);self.assertFalse(result['consumptionConfirmed'])
        self.assertEqual(connect.await_count,2)
        self.assertEqual([call.args[0]['op'] for call in channel.send.await_args_list],['probe','send'])
        channel.close.assert_awaited_once()

    async def test_exhausted_timeout_reports_two_attempts_without_submission(self):
        exc=TransportFailure('control_response','timeout',transient=True)
        with patch.object(app,'open_channel',new=AsyncMock(side_effect=exc)) as connect,patch.object(app.asyncio,'sleep',new=AsyncMock()):
            with self.assertRaises(NoAuthenticatedRoute) as caught:
                await app.exchange(self.store,self.peer,'send',{'target':'worker','message':SECRET},route='relay')
        self.assertEqual(connect.await_count,2)
        self.assertEqual(caught.exception.route_failures,[{'route':'relay','stage':'control_response','reason':'timeout','attempts':2}])
        self.assertNotIn(SECRET,json.dumps(caught.exception.route_failures))

    async def test_auth_tls_and_other_errors_are_not_retried(self):
        for exc in (TransportFailure('relay_admission','http_rejected',http_status=401),
                    TransportFailure('relay_admission','http_rejected',http_status=403),
                    ssl.SSLError(SECRET),Rejected('login_expired'),RuntimeError(SECRET)):
            with self.subTest(kind=type(exc).__name__),patch.object(app,'open_channel',new=AsyncMock(side_effect=exc)) as connect:
                with self.assertRaises(NoAuthenticatedRoute) as caught:
                    await app.exchange(self.store,self.peer,'send',{'target':'worker','message':SECRET},route='relay')
                self.assertEqual(connect.await_count,1)
                self.assertEqual(caught.exception.route_failures[0]['attempts'],1)
                self.assertNotIn(SECRET,json.dumps(caught.exception.route_failures))

    async def test_lost_application_response_is_unknown_and_never_replayed(self):
        channel=self.channel([{'ok':True,'device':self.peer},TimeoutError(SECRET)])
        with patch.object(app,'open_channel',new=AsyncMock(return_value=channel)) as connect:
            result=await app.exchange(self.store,self.peer,'send',{'target':'worker','message':SECRET},route='relay')
        self.assertEqual(result['status'],'unknown');self.assertFalse(result['retryAllowed'])
        self.assertEqual(connect.await_count,1)
        self.assertEqual([call.args[0]['op'] for call in channel.send.await_args_list],['probe','send'])

    async def test_auto_direct_winner_cancels_slow_relay_without_send(self):
        direct=self.channel([{'ok':True,'device':self.peer},{'ok':True}])
        cancelled=asyncio.Event()
        async def connect(store,cert,routes,kind,credential):
            if kind=='direct':return direct
            try:await asyncio.sleep(60)
            except asyncio.CancelledError:cancelled.set();raise
        with patch.object(app,'open_channel',side_effect=connect):
            result=await app.exchange(self.store,self.peer,'send',{'target':'worker','message':SECRET})
        self.assertEqual(result['route'],'direct');self.assertTrue(cancelled.is_set())
        self.assertEqual([call.args[0]['op'] for call in direct.send.await_args_list],['probe','send'])

    async def test_websocket_timeout_and_attach_failure_close_safely(self):
        with patch.object(wire,'admission',return_value='session_peer='+SECRET),patch.object(wire,'PinnedConnect',new=AsyncMock(side_effect=TimeoutError(SECRET))):
            with self.assertRaises(TransportFailure) as caught:
                await wire.relay_stream('ws://127.0.0.1:2/v1/connect',SECRET)
        self.assertEqual(caught.exception.stage,'relay_websocket');self.assertTrue(caught.exception.transient)
        ws=SimpleNamespace(recv=AsyncMock(side_effect=TimeoutError(SECRET)),close=AsyncMock())
        with patch.object(wire,'admission',return_value='session_peer='+SECRET),patch.object(wire,'PinnedConnect',new=AsyncMock(return_value=ws)):
            with self.assertRaises(TransportFailure) as caught:
                await wire.relay_stream('ws://127.0.0.1:2/v1/connect',SECRET)
        self.assertEqual(caught.exception.stage,'relay_attach');ws.close.assert_awaited_once()

    async def test_receiver_diagnostics_are_rate_limited_and_secret_free(self):
        receiver=app.Receiver(self.store,{'targets':{'worker':{'agent':'claude','target':'worker'}},'peers':{}})
        outcomes=[TimeoutError(SECRET),RuntimeError(SECRET),TimeoutError(SECRET),asyncio.CancelledError()]
        with patch.object(app,'relay_stream',new=AsyncMock(side_effect=outcomes)), \
             patch.object(app.asyncio,'sleep',new=AsyncMock()), \
             patch.object(app,'time',SimpleNamespace(monotonic=Mock(side_effect=[0,1,61]))), \
             patch.object(app.logging,'getLogger') as logger:
            with self.assertRaises(asyncio.CancelledError):
                await receiver.relay_listener('wss://relay.example.test/v1/connect',SECRET)
        calls=logger.return_value.warning.call_args_list
        self.assertEqual(len(calls),2)
        self.assertNotIn(SECRET,str(calls))
