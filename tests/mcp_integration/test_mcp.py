"""MCP routing policy and real stdio protocol tests (no model credentials)."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import session_peer_mcp as mcp_peer

THREAD = '01900000-0000-7000-8000-000000000001'


class PolicyLoading(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='codex-mcp-policy-')
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'policy.json'

    def load(self, destinations):
        self.path.write_text(json.dumps({'schemaVersion': 1, 'destinations': destinations}),
                             encoding='utf-8')
        return mcp_peer.load_policy(str(self.path))

    def test_remote_destinations_load_and_preserve_routes(self):
        for host in ('web-01', 'web.example.test', 'user@web-01',
                     '[::1]', 'user@[2001:db8::1]', '2001:db8::1'):
            for agent in ('claude', 'codex'):
                with self.subTest(host=host, agent=agent):
                    entry = {'host': host, 'agents': [agent], 'capabilities': ['list']}
                    route = ['--host', host]
                    if agent == 'codex':
                        entry['codexHome'] = '/custom codex/home'
                        route += ['--codex-home', '/custom codex/home']
                    loaded = self.load({'remote': entry})
                    self.assertEqual(loaded, {'remote': entry})
                    adapter = mcp_peer.Adapter(loaded)
                    self.assertEqual(adapter.route(adapter.authorize('remote', 'list', agent)), route)

    def test_invalid_hosts_rejected_from_policy_files(self):
        for host in ('-oProxyCommand=id', '-A', '-p22', '', 'web 01', 'web\t01',
                     'web\n01', 'web;id', 'web$(id)', 'web`id`', 'web|id', 'web\0', 123):
            with self.subTest(host=host):
                with self.assertRaises((mcp_peer.PolicyError, mcp_peer.core.CcPeerError)):
                    self.load({'remote': {'host': host, 'agents': ['claude'],
                                          'capabilities': ['list']}})

    def test_policy_cannot_supply_ssh_options(self):
        for options in (['-A'], ['-F', '/custom/config'], ['-oProxyCommand=id'],
                        ['-oLocalCommand=id'], ['-p22']):
            with self.subTest(options=options):
                with self.assertRaisesRegex(mcp_peer.PolicyError, 'Unknown settings'):
                    self.load({'remote': {'host': 'user@web-01', 'agents': ['claude'],
                                          'capabilities': ['list'], 'sshOpts': options}})

    def test_local_policy_preserves_configured_codex_home(self):
        destinations = {
            'claude': {'agents': ['claude'], 'capabilities': ['list', 'send']},
            'codex': {'agents': ['codex'], 'capabilities': ['list'],
                      'codexHome': '/custom codex/home'},
        }
        loaded = self.load(destinations)
        self.assertEqual(loaded, destinations)
        adapter = mcp_peer.Adapter(loaded)
        self.assertEqual(adapter.route(loaded['claude']), [])
        self.assertEqual(adapter.route(loaded['codex']), ['--codex-home', '/custom codex/home'])

    def test_default_policy_uses_environment_codex_home(self):
        with patch.dict(os.environ, {'CODEX_HOME': self.folder.name}):
            self.assertEqual(mcp_peer.load_policy(None), {
                'local': {'capabilities': ['list'], 'agents': list(mcp_peer.core.AGENTS.names()),
                          'codexHome': str(Path(self.folder.name).resolve())}})

    def test_remote_codex_still_requires_absolute_home(self):
        for home in (None, 'relative/home', '/custom\0home'):
            with self.subTest(home=home):
                with self.assertRaisesRegex(mcp_peer.PolicyError, 'absolute codexHome'):
                    self.load({'remote': {'host': 'user@web-01', 'agents': ['codex'],
                                          'capabilities': ['list'], 'codexHome': home}})


class Policy(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = mcp_peer.Adapter({
            'local': {'agents': ['claude', 'codex'], 'capabilities': ['list'], 'codexHome': '/codex'},
            'worker': {'host': 'ubuntu@worker', 'agents': ['codex'],
                       'capabilities': ['list', 'send'], 'codexHome': '/custom'},
            'claude': {'agents': ['claude'], 'capabilities': ['list', 'send']}})
        self.adapter.invoke = AsyncMock(return_value={'ok': True, 'status': 'queued'})

    async def test_default_cannot_send_or_access_other_destinations(self):
        for destination in ('local', 'unconfigured'):
            with self.assertRaises(mcp_peer.PolicyError):
                await self.adapter.send_message(destination, 'codex:' + THREAD, 'hello')
        self.adapter.invoke.assert_not_called()

    async def test_remote_uses_configured_home_and_does_not_advertise_launcher(self):
        await self.adapter.send_message('worker', 'codex:' + THREAD, '--host attacker\n안녕')
        argv, message = self.adapter.invoke.call_args.args
        self.assertEqual(argv, ['send', '--host', 'ubuntu@worker', '--codex-home', '/custom',
                                '--to', 'codex:' + THREAD, '--no-from', '--no-reply-to'])
        self.assertIn('--host attacker\n안녕', message)
        self.assertNotIn('Reply-To:', message)

    async def test_disallowed_agent_never_invokes_cli(self):
        with self.assertRaises(mcp_peer.PolicyError):
            await self.adapter.list_sessions('worker', 'claude')
        with self.assertRaises(mcp_peer.PolicyError):
            await self.adapter.send_message('claude', 'codex:' + THREAD, 'hello')
        self.adapter.invoke.assert_not_called()

    async def test_single_agent_listing_is_filtered(self):
        await self.adapter.list_sessions('worker', include_inactive=True)
        self.assertEqual(self.adapter.invoke.call_args.args[0],
                         ['list', '--host', 'ubuntu@worker', '--codex-home', '/custom', '--agent', 'codex', '--all'])

    async def test_reply_uri_cannot_override_route(self):
        base = 'session-peer://v1/reply?agent=codex&session=' + THREAD + '&transport=ssh&host='
        for uri in (base + 'attacker', base + 'ubuntu%40worker&codexHome=%2Fother'):
            with self.assertRaises(mcp_peer.PolicyError):
                await self.adapter.send_message('worker', uri, 'hello')
        self.adapter.invoke.assert_not_called()
        await self.adapter.send_message('worker', base + 'ubuntu%40worker&codexHome=%2Fcustom', 'hello')
        argv = self.adapter.invoke.call_args.args[0]
        self.assertNotIn('--host', argv)
        self.assertIn(base + 'ubuntu%40worker&codexHome=%2Fcustom', argv)

    async def test_claude_uri_cannot_smuggle_codex_target(self):
        uri = 'session-peer://v1/reply?agent=claude&session=codex:' + THREAD + '&transport=local'
        with self.assertRaises(mcp_peer.PolicyError):
            await self.adapter.send_message('claude', uri, 'hello')
        self.adapter.invoke.assert_not_called()

    async def test_blank_message_rejected_before_envelope(self):
        with self.assertRaises(mcp_peer.core.CcPeerError):
            await self.adapter.send_message('worker', 'codex:' + THREAD, '')
        self.adapter.invoke.assert_not_called()

    def test_invalid_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'policy.json'
            for entry in ({'agents':['codex'], 'capabilities':['send']},
                          {'agents':['claude'], 'capabilities':['shell']},
                          {'agents':['claude'], 'capabilities':['send'], 'host':'-oProxyCommand=x'},
                          {'agents':['claude'], 'capabilities':['send'], 'sshOpts':['-A']}):
                p.write_text(json.dumps({'schemaVersion':1,'destinations':{'test':entry}}))
                with self.assertRaises((mcp_peer.PolicyError, mcp_peer.core.CcPeerError)):
                    mcp_peer.load_policy(str(p))

    async def test_real_cli_partial_error_preserved(self):
        adapter = mcp_peer.Adapter({})
        result = await adapter.invoke(['list', '--agent', 'codex', '--codex-home', '/missing-session-peer-test'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['command'], 'list')
        self.assertIn('codex', result['discovery'])

    async def test_timeout_is_not_retried(self):
        adapter = mcp_peer.Adapter({})
        if os.name == 'posix':
            with patch.object(mcp_peer, 'invoke_posix', side_effect=asyncio.TimeoutError) as invoke:
                result = await adapter.invoke(['send'])
            self.assertEqual(result['reason'], 'outcome_unknown')
            invoke.assert_called_once()
            return
        process = AsyncMock()
        process.returncode = None
        from unittest.mock import Mock
        process.kill = Mock()
        process.terminate = Mock()
        process.communicate.side_effect = asyncio.TimeoutError
        with patch('asyncio.create_subprocess_exec', return_value=process) as spawn:
            result = await adapter.invoke(['send'])
        self.assertEqual(result['reason'], 'outcome_unknown')
        self.assertEqual(spawn.call_count, 1)
        process.terminate.assert_called_once()
        process.kill.assert_not_called()
        self.assertGreaterEqual(process.wait.await_count, 1)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK not installed')
class Protocol(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_tools_and_policy_errors(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'policy.json'
            p.write_text(json.dumps({'schemaVersion':1,'destinations':{
                'local':{'agents':['codex'],'capabilities':['list'],'codexHome':folder}}}))
            params = StdioServerParameters(command=sys.executable,
                args=[str(Path(mcp_peer.__file__).resolve()), '--config', str(p)])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = (await client.list_tools()).tools
                    self.assertEqual({t.name for t in tools}, {'list_sessions','send_message'})
                    listing = next(t for t in tools if t.name == 'list_sessions')
                    self.assertTrue(listing.annotations.readOnlyHint)
                    failed = await client.call_tool('send_message', {'destination':'local','target':'codex:'+THREAD,'message':'test'})
                    self.assertTrue(failed.isError)
                    self.assertEqual(failed.structuredContent['reason'], 'request_rejected')
                    missing = await client.call_tool('list_sessions', {})
                    self.assertTrue(missing.isError)
                    self.assertIn('discovery', missing.structuredContent)

    @unittest.skipIf(sys.platform == 'win32', 'Unix socket integration')
    async def test_real_stdio_send_reaches_unix_inbox_once(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory(dir='/tmp') as folder:
            root = Path(folder)
            sessions = root / 'sessions'
            sessions.mkdir()
            received = []
            async def inbox(reader, writer):
                received.append(json.loads(await reader.readline()))
                writer.close()
                await writer.wait_closed()
            sock = str(root / 'inbox.sock')
            server = await asyncio.start_unix_server(inbox, sock)
            try:
                (sessions / f'{os.getpid()}.json').write_text(json.dumps({
                    'pid':os.getpid(), 'name':'mcp-test-inbox', 'messagingSocketPath':sock}))
                policy = root / 'policy.json'
                policy.write_text(json.dumps({'schemaVersion':1,'destinations':{
                    'local':{'agents':['claude'],'capabilities':['list','send']}}}))
                params = StdioServerParameters(command=sys.executable,
                    args=[str(Path(mcp_peer.__file__).resolve()),'--config',str(policy)],
                    env={**os.environ,'CLAUDE_CONFIG_DIR':folder})
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        listing = await client.call_tool('list_sessions', {})
                        self.assertFalse(listing.isError)
                        sent = await client.call_tool('send_message', {
                            'destination':'local','target':'mcp-test-inbox','message':'안녕 MCP'})
                        self.assertFalse(sent.isError)
                        self.assertEqual(len(received), 1)
                        self.assertIn('안녕 MCP', received[0]['message']['content'])
                        self.assertNotIn('Reply-To:', received[0]['message']['content'])
            finally:
                server.close()
                await server.wait_closed()


class WakePolicy(unittest.IsolatedAsyncioTestCase):
    async def test_send_permission_does_not_grant_wake(self):
        adapter=mcp_peer.Adapter({'local':{'agents':['codex'],'capabilities':['send'],'codexHome':'/custom'}})
        adapter.invoke=AsyncMock()
        with self.assertRaises(mcp_peer.PolicyError):
            await adapter.send_message('local','codex:'+THREAD,'hello',wake=True)
        adapter.invoke.assert_not_called()

    async def test_wake_passes_only_bounded_native_options(self):
        adapter=mcp_peer.Adapter({'local':{'agents':['codex'],'capabilities':['send','wake'],'codexHome':'/custom'}})
        adapter.invoke=AsyncMock(return_value={'ok':True})
        await adapter.send_message('local','codex:'+THREAD,'hello',wake=True,wake_timeout=12)
        self.assertEqual(adapter.invoke.call_args.args[0][-3:],['--wake','--wake-timeout','12'])
        for timeout in (0,61):
            with self.assertRaises(mcp_peer.PolicyError):
                await adapter.send_message('local','codex:'+THREAD,'hello',wake=True,wake_timeout=timeout)
