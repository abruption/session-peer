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
        process = AsyncMock()
        process.returncode = None
        from unittest.mock import Mock
        process.kill = Mock()
        process.communicate.side_effect = asyncio.TimeoutError
        with patch('asyncio.create_subprocess_exec', return_value=process) as spawn:
            result = await adapter.invoke(['send'])
        self.assertEqual(result['reason'], 'outcome_unknown')
        self.assertEqual(spawn.call_count, 1)
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()


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
