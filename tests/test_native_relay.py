"""Real transport + native Claude socket worker; no model credentials."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import time
import sys
import tempfile
import unittest
import uuid
from unittest import mock

if sys.version_info < (3, 11) or os.name != 'posix':
    raise unittest.SkipTest('optional native relay requires Unix Python 3.11+')
try:
    import websockets
    import cryptography
except ImportError:
    raise unittest.SkipTest('optional relay dependencies not installed')

from session_peer_relay.app import Receiver, exchange, pair, open_channel, request
from session_peer_relay.wire import relay_stream, direct_address
from session_peer_relay.native import Policy
from session_peer_relay.relay import Relay
from session_peer_relay.store import Store, Rejected
from session_peer_relay.identity import private_read, private_write


class NativeRelay(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='spr-', dir='/tmp')
        self.root = Path(self.temp.name)
        self.client, self.host = Store(self.root/'client'), Store(self.root/'host')
        self.effects=[]
        async def inbox(reader, writer):
            raw=await reader.readline()
            if raw:self.effects.append(json.loads(raw))
            writer.close();await writer.wait_closed()
        self.socket=self.root/'inbox.sock'
        self.inbox=await asyncio.start_unix_server(inbox,path=str(self.socket))
        config=self.root/'claude';(config/'sessions').mkdir(parents=True)
        (config/'sessions'/f'{os.getpid()}.json').write_text(json.dumps({'pid':os.getpid(),'name':'worker','cwd':'/fixture','messagingSocketPath':str(self.socket)}))
        self.env=mock.patch.dict(os.environ,{'CLAUDE_CONFIG_DIR':str(config)})
        self.env.start()
        self.policy={'targets':{'review':{'agent':'claude','target':'worker'},'other':{'agent':'claude','target':'elsewhere'}},
                     'peers':{self.client.device:{'capabilities':['list','send'],'targets':['review','other']}}}
        self.receiver=Receiver(self.host,self.policy)
        self.server=await self.receiver.listen('127.0.0.1',0)
        self.receiver_token,self.client_token=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        self.frames=[]
        relay=Relay([{'hash':hashlib.sha256(token.encode()).hexdigest(),'room':'test','role':role}
                     for token,role in ((self.receiver_token,'receiver'),(self.client_token,'client'))],capture=self.frames)
        self.relay=await relay.start('127.0.0.1',0)
        self.url='ws://127.0.0.1:'+str(self.relay.sockets[0].getsockname()[1])+'/v1/connect'
        self.listener=asyncio.create_task(self.receiver.relay_listener(self.url,self.receiver_token))
        self.invite=self.host.invite({'direct':'127.0.0.1:'+str(self.server.sockets[0].getsockname()[1]),'relay':self.url})
        await pair(self.client,self.invite,'direct')

    async def asyncTearDown(self):
        self.listener.cancel();await asyncio.gather(self.listener,return_exceptions=True)
        self.server.close();await self.server.wait_closed();await self.receiver.close()
        self.relay.close();await self.relay.wait_closed()
        self.inbox.close();await self.inbox.wait_closed()
        self.host.close();self.client.close();self.env.stop();self.temp.cleanup()

    async def call(self,op,body=None,ident=None,route='direct'):
        return await exchange(self.client,self.host.device,op,body,ident,route,self.client_token)

    async def test_route_update_preserves_pin_and_receipt(self):
        from types import SimpleNamespace
        from session_peer_relay.cli import manage
        ident = str(uuid.uuid4())
        body = {'target':'review','message':'route update'}
        await self.call('send', body, ident)
        before = self.client.peer(self.host.device)
        args = SimpleNamespace(group='device', action='routes', state=str(self.root/'client'),
                               peer=self.host.device, direct=None, relay=self.url)
        result = await manage('device', args)
        self.assertFalse(result['identityChanged'])
        after = self.client.peer(self.host.device)
        self.assertEqual(before['certificate'], after['certificate'])
        duplicate = await self.call('send', body, ident, route='relay')
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(self.effects), 1)
        self.client.revoke(self.host.device)
        with self.assertRaises(Rejected):
            await manage('device', args)

    async def test_certificate_substitution_and_unauthenticated_admission(self):
        stranger = Store(self.root/'stranger')
        try:
            with self.assertRaises(ssl.SSLError):
                await open_channel(self.client, stranger.cert, self.invite['routes'], 'direct', bootstrap=True)
        finally:
            stranger.close()
        with self.assertRaises(Exception):
            await relay_stream(self.url, 'invalid')
        self.assertEqual(self.effects, [])

    async def test_authenticated_envelope_and_tls_tamper_rejected(self):
        for field, value in [('sender', 'other'), ('receiver', 'other'), ('expires', time.time()-1), ('op', 'shell')]:
            value_dict = request(self.client, self.host.device, 'send', {'target':'review','message':'no'})
            value_dict[field] = value
            with self.assertRaises(Rejected):
                await self.receiver.dispatch(self.client.device, value_dict)
        channel = await open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        original = channel.raw.send
        async def corrupt(data):
            damaged = bytearray(data); damaged[-1] ^= 1
            await original(damaged)
        channel.raw.send = corrupt
        try:
            await channel.send(request(self.client, self.host.device, 'send', {'target':'review','message':'no'}))
            with self.assertRaises(Exception):
                await channel.recv()
        finally:
            await channel.close()
        self.assertEqual(self.effects, [])

    async def test_pairing_does_not_grant_unconfigured_native_access(self):
        self.receiver.policy.peers.clear()
        with self.assertRaises(Rejected):
            await self.call('send', {'target':'review','message':'deny'})
        self.assertEqual(self.effects, [])

    async def test_real_cli_device_list_and_send(self):
        import session_peer as core
        async def invoke(command, *extra):
            process = await asyncio.create_subprocess_exec(
                sys.executable, core.__file__, command, '--device', self.host.device,
                '--device-state', str(self.client.root), '--device-route', 'direct',
                '--json', '--no-update-notice', *extra,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(process.communicate(), 10)
            self.assertEqual(process.returncode, 0, err.decode())
            return json.loads(out)
        listed = await invoke('list')
        self.assertEqual(listed['sessions'][0]['target'], 'review')
        sent = await invoke('send', '--to', 'review', '--message', 'real CLI', '--no-from', '--no-reply-to')
        self.assertTrue(sent['submitted'])
        self.assertEqual(sent['transport'], 'paired_device')
        self.assertEqual(self.effects[0]['message']['content'], 'real CLI')

    async def test_direct_native_discovery_and_delivery(self):
        found=await self.call('list')
        self.assertTrue(found['ok']);self.assertEqual(found['sessions'][0]['target'],'review')
        result=await self.call('send',{'target':'review','message':'direct native'})
        self.assertEqual(result['status'],'submitted');self.assertFalse(result['consumptionConfirmed'])
        self.assertEqual(self.effects[0]['message']['content'],'direct native')

    async def test_relay_native_delivery_ciphertext_and_cross_route_dedup(self):
        ident=str(uuid.uuid4());body={'target':'review','message':'SP_NATIVE_RELAY_SENTINEL'}
        result=await self.call('send',body,ident,'relay');self.assertTrue(result['ok'])
        duplicate=await self.call('send',body,ident,'direct');self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(self.effects),1)
        self.assertNotIn(b'SP_NATIVE_RELAY_SENTINEL',b''.join(self.frames))
        status=await self.call('status',ident);self.assertEqual(status['messageId'],ident)

    async def test_dry_run_resolves_without_native_effect_or_journal(self):
        result = await self.call('resolve', {'target':'review','message':'dry'})
        self.assertTrue(result['ok']); self.assertFalse(result['submitted'])
        self.assertEqual(self.effects, [])
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 0)

    async def test_unauthorized_alias_cannot_reach_native(self):
        result=await self.call('send',{'target':'arbitrary','message':'deny'})
        self.assertEqual(result['reason'],'target_denied');self.assertEqual(self.effects,[])
        self.policy['peers'][self.client.device]['capabilities']=['list']
        result=await self.call('send',{'target':'review','message':'deny'})
        self.assertEqual(result['reason'],'operation_denied');self.assertEqual(self.effects,[])

    async def test_duplicate_id_cannot_change_target_or_message(self):
        ident=str(uuid.uuid4())
        await self.call('send',{'target':'review','message':'one'},ident)
        for body in ({'target':'review','message':'two'},{'target':'other','message':'one'}):
            result=await self.call('send',body,ident)
            self.assertEqual(result['reason'],'message_id_conflict')
        self.assertEqual(len(self.effects),1)

    async def test_revoked_device_cannot_reach_native(self):
        self.host.revoke(self.client.device)
        with self.assertRaises(Rejected):await self.call('send',{'target':'review','message':'deny'})
        self.assertEqual(self.effects,[])

    async def test_pending_intent_is_unknown_after_reopen(self):
        ident=str(uuid.uuid4());binding=self.policy['targets']['review']
        canonical=json.dumps({'binding':binding,'message':'one'},sort_keys=True,separators=(',',':'))
        self.assertIsNone(self.host.begin(self.client.device,ident,canonical))
        restarted=Store(self.root/'host')
        try:
            value=restarted.begin(self.client.device,ident,canonical)
            self.assertEqual(value['status'],'unknown');self.assertFalse(value['retryAllowed'])
        finally:restarted.close()
        result=await self.call('send',{'target':'review','message':'one'},ident)
        self.assertEqual(result['status'],'unknown');self.assertEqual(self.effects,[])

    async def test_fallback_selects_authenticated_relay_before_effect(self):
        self.server.close();await self.server.wait_closed()
        result=await self.call('send',{'target':'review','message':'fallback'},route='auto')
        self.assertEqual(result['route'],'relay');self.assertEqual(len(self.effects),1)

    async def test_native_error_and_size_checks(self):
        result=await self.call('send',{'target':'other','message':'absent'})
        self.assertFalse(result['ok']);self.assertFalse(result['consumptionConfirmed'])
        result=await self.call('send',{'target':'review','message':'x'*32769})
        self.assertEqual(result['reason'],'invalid_message');self.assertEqual(self.effects,[])


class PolicyTests(unittest.TestCase):
    def test_disallow_peer_controlled_command_home_and_wake(self):
        for binding in ({'agent':'codex','target':'codex:'+str(uuid.uuid4())},
                        {'agent':'claude','target':'worker','command':'sh'},
                        {'agent':'claude','target':'worker','wake':True},
                        {'agent':'claude','target':'codex:'+str(uuid.uuid4())}):
            with self.assertRaises((Rejected,ValueError)):Policy({'targets':{'a':binding},'peers':{}})

    def test_native_queue_exception_is_unknown_not_refused(self):
        import contextlib, io
        from types import SimpleNamespace
        from session_peer_relay import worker
        binding = {'agent':'codex','target':'codex:'+str(uuid.uuid4()),'codexHome':'/fixture'}
        payload = json.dumps({'binding':binding,'operation':'send','text':'hello'}).encode()
        out = io.StringIO()
        with mock.patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(payload))), \
             mock.patch.object(worker.core.LocalTransport, 'execute', side_effect=worker.core.CcPeerError('queue timeout')), \
             contextlib.redirect_stdout(out):
            worker.main()
        result = json.loads(out.getvalue())
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['retryAllowed'])

    def test_direct_route_validation(self):
        self.assertEqual(direct_address('[::1]:443'), ('::1',443))
        for route in ('user@host:443','host:443/path','host:0','host:443?token=secret'):
            with self.assertRaises(ValueError): direct_address(route)

    def test_private_file_permissions_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'token';private_write(path,'secret')
            self.assertEqual(private_read(path),'secret')
            path.chmod(0o644)
            with self.assertRaises(ValueError):private_read(path)
            path.chmod(0o600);link=Path(d)/'link';link.symlink_to(path)
            with self.assertRaises(ValueError):private_write(link,'replacement')
            self.assertEqual(private_read(path),'secret')
