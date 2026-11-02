"""Least-privilege structured preflight, synthetic targets and real stdio only."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import session_peer_mcp as peer

THREAD = '01900000-0000-7000-8000-000000000001'
NONREFLECTED_VALUE = 'PRIVATE-host-home-body-error'


def preview(agent='claude', *, wake=False, result=None):
    args = argparse.Namespace(to=agent + ':target' if agent != 'claude' else 'target', wake=wake)
    return peer.core.structured_delivery_preflight(args, {'ok': True, 'dryRun': True} if result is None else result)


class PreflightPolicy(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = peer.Adapter({
            'local': {'agents': ['claude'], 'capabilities': ['preflight']},
            'remote': {'agents': ['codex'], 'capabilities': ['preflight'], 'host': NONREFLECTED_VALUE,
                       'codexHome': '/' + NONREFLECTED_VALUE},
            'wake': {'agents': ['codex'], 'capabilities': ['preflight', 'wake'], 'codexHome': '/' + NONREFLECTED_VALUE}})
        self.adapter.invoke = AsyncMock(return_value=preview())

    async def test_preflight_only_policy_cannot_send_or_wake(self):
        value = await self.adapter.preflight_send('local', 'fixture', 'message')
        self.assertTrue(value['ok'])
        for operation in (self.adapter.send_message('local', 'fixture', 'message'),
                          self.adapter.preflight_send('remote', 'codex:' + THREAD, 'message', wake=True)):
            with self.assertRaises(peer.PolicyError):
                await operation
        self.assertEqual(self.adapter.invoke.await_count, 1)
        argv, body = self.adapter.invoke.call_args.args
        self.assertIn('--dry-run', argv)
        self.assertIn('--explain-json', argv)
        self.assertIn('--no-from', argv)
        self.assertIn('--no-reply-to', argv)
        self.assertNotIn('--wake', argv)
        self.assertIn('message', body)
        self.assertNotIn('message', json.dumps(value))

    async def test_uri_host_home_mismatch_rejected_before_invoke(self):
        base = 'session-peer://v1/reply?agent=codex&session=' + THREAD + '&transport=ssh&host='
        for tail in ('other&codexHome=%2F' + NONREFLECTED_VALUE, NONREFLECTED_VALUE + '&codexHome=%2Fother'):
            with self.assertRaises(peer.PolicyError):
                await self.adapter.preflight_send('remote', base + tail, 'message')
        self.adapter.invoke.assert_not_called()

    async def test_matching_uri_and_ssh_preserve_policy_route(self):
        uri = ('session-peer://v1/reply?agent=codex&session=' + THREAD +
               '&transport=ssh&host=' + NONREFLECTED_VALUE + '&codexHome=%2F' + NONREFLECTED_VALUE)
        self.adapter.invoke.return_value = preview('codex')
        value = await self.adapter.preflight_send('remote', uri, 'message')
        self.assertTrue(value['ok'])
        self.assertEqual(value['checked']['agent'], 'codex')
        argv = self.adapter.invoke.call_args.args[0]
        self.assertNotIn('--host', argv)
        self.assertEqual(argv[argv.index('--to') + 1], uri)
        self.assertNotIn(NONREFLECTED_VALUE, json.dumps(value))

    async def test_response_allowlist_unknown_and_conflicting_evidence(self):
        for native, expected in (({'submitted': True, 'dryRun': True}, 'unexpected_submission'),
                                 ({'status': 'unknown', 'dryRun': True}, 'unknown'),
                                 ({'submitted': None}, 'unknown'), ({}, 'not_confirmed')):
            value = preview(result=native)
            value.update(error=NONREFLECTED_VALUE, path=NONREFLECTED_VALUE, raw=NONREFLECTED_VALUE)
            self.adapter.invoke.return_value = value
            output = await self.adapter.preflight_send('local', 'fixture', NONREFLECTED_VALUE)
            self.assertFalse(output['ok'])
            self.assertEqual(output['checked']['validation'], expected)
            self.assertFalse(output['retryAllowed'])
            self.assertNotIn(NONREFLECTED_VALUE, json.dumps(output))
        malformed = preview()
        malformed['checked']['validation'] = []
        self.adapter.invoke.return_value = malformed
        self.assertFalse((await self.adapter.preflight_send('local', 'fixture', 'message'))['ok'])
        self.adapter.invoke.return_value = {'ok': True, 'dryRun': True, 'raw': NONREFLECTED_VALUE}
        output = await self.adapter.preflight_send('local', 'fixture', 'message')
        self.assertFalse(output['ok'])
        self.assertEqual(output['reason'], 'preflight_response_unavailable')

    async def test_contradictory_or_missing_projection_evidence_fails_closed(self):
        for field, replacement in (
                ('limitations', {**preview()['limitations'], 'submission': 'unknown'}),
                ('limitations', {**preview()['limitations'], 'submission': 'reported_submission'}),
                ('limitations', None), ('retryAllowed', True), ('retryAllowed', 0),
                ('declaredCapabilities', {}), ('reason', 'untrusted reason'),
                ('operatorActions', ['grant_all_permissions'])):
            value = preview()
            value[field] = replacement
            self.adapter.invoke.return_value = value
            output = await self.adapter.preflight_send('local', 'fixture', 'message')
            self.assertFalse(output['ok'])
            self.assertEqual(output['checked']['validation'], 'unknown')
            self.assertEqual(output['limitations']['submission'], 'unknown')
            self.assertFalse(output['retryAllowed'])
        missing = preview()
        del missing['limitations']
        self.adapter.invoke.return_value = missing
        self.assertFalse((await self.adapter.preflight_send('local', 'fixture', 'message'))['ok'])

    async def test_missing_wake_evidence_cannot_pass(self):
        self.adapter.invoke.return_value = preview('codex', wake=True)
        output = await self.adapter.preflight_send('wake', 'codex:' + THREAD, 'message', wake=True)
        self.assertFalse(output['ok'])
        self.assertEqual(output['reason'], 'wake_preflight_not_confirmed')

    async def test_body_limits_refuse_before_cli_invocation(self):
        for body in ('', 'x' * (peer.core.MAX_MESSAGE_CHARS + 1)):
            with self.assertRaises(peer.core.CcPeerError):
                await self.adapter.preflight_send('local', 'fixture', body)
        self.adapter.invoke.assert_not_called()

    async def test_timeout_unknown_and_cancellation_never_retry(self):
        self.adapter.invoke.return_value = {'ok': False, 'reason': 'outcome_unknown', 'error': NONREFLECTED_VALUE}
        output = await self.adapter.preflight_send('local', 'fixture', 'message')
        self.assertFalse(output['ok'])
        self.assertNotIn(NONREFLECTED_VALUE, json.dumps(output))
        self.adapter.invoke.assert_awaited_once()
        self.adapter.invoke.reset_mock()
        self.adapter.invoke.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.adapter.preflight_send('local', 'fixture', 'message')
        self.adapter.invoke.assert_awaited_once()

    async def test_wake_preflight_requires_explicit_permission_and_fixed_dryrun(self):
        self.adapter.invoke.return_value = preview('codex', wake=True,
            result={'dryRun': True, 'wake': {'status': 'validated', 'cwd': NONREFLECTED_VALUE}})
        output = await self.adapter.preflight_send('wake', 'codex:' + THREAD, 'message', wake=True)
        self.assertTrue(output['ok'])
        self.assertEqual(output['checked']['wake'], 'validated')
        argv = self.adapter.invoke.call_args.args[0]
        self.assertIn('--dry-run', argv)
        self.assertIn('--wake', argv)
        self.assertNotIn(NONREFLECTED_VALUE, json.dumps(output))

    def test_schema_v1_stays_closed_and_v2_requires_explicit_grant(self):
        with tempfile.TemporaryDirectory(prefix='codex-preflight-policy-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            path = Path(folder) / 'policy.json'
            for version, caps, accepted in ((1, ['preflight'], False), (2, ['preflight'], True),
                                            (1, ['list', 'send', 'wake'], True), (2, ['unknown'], False),
                                            (True, ['list'], False)):
                path.write_text(json.dumps({'schemaVersion': version, 'destinations': {
                    'fixture': {'agents': ['claude'], 'capabilities': caps}}}))
                if accepted:
                    self.assertEqual(peer.load_policy(str(path))['fixture']['capabilities'], caps)
                else:
                    with self.assertRaises(peer.PolicyError):
                        peer.load_policy(str(path))
            self.assertEqual(peer.load_policy(None)['local']['capabilities'], ['list'])


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK')
class PreflightProtocol(unittest.IsolatedAsyncioTestCase):
    @unittest.skipIf(sys.platform == 'win32', 'Unix inbox fixture')
    async def test_stdio_schema_synthetic_claude_preflight_and_policy_errors(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory(prefix='codex-pf-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            root = Path(folder)
            sessions = root / 'sessions'
            sessions.mkdir()
            received = []
            async def inbox(reader, writer):
                received.append(await reader.readline())
                writer.close()
                await writer.wait_closed()
            server = await asyncio.start_unix_server(inbox, str(root / 'i.sock'))
            self.addAsyncCleanup(server.wait_closed)
            self.addCleanup(server.close)
            # A dedicated synthetic inbox exists, but preview must never post.
            (sessions / (str(os.getpid()) + '.json')).write_text(json.dumps({
                'pid': os.getpid(), 'name': 'fixture', 'messagingSocketPath': str(root / 'i.sock')}))
            policy = root / 'policy.json'
            policy.write_text(json.dumps({'schemaVersion': 2, 'destinations': {
                'local': {'agents': ['claude'], 'capabilities': ['preflight']}}}))
            params = StdioServerParameters(command=sys.executable,
                args=[str(Path(peer.__file__).resolve()), '--config', str(policy)],
                env={**os.environ, 'CLAUDE_CONFIG_DIR': folder})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tool = next(t for t in (await client.list_tools()).tools if t.name == 'preflight_send')
                    self.assertFalse(tool.annotations.readOnlyHint)
                    self.assertTrue(tool.annotations.openWorldHint)
                    self.assertEqual(set(tool.inputSchema['required']), {'destination', 'target', 'message'})
                    value = await client.call_tool('preflight_send', {'destination': 'local', 'target': 'fixture', 'message': NONREFLECTED_VALUE})
                    self.assertFalse(value.isError)
                    self.assertTrue(value.structuredContent['ok'])
                    self.assertEqual(received, [])
                    self.assertEqual(value.structuredContent['schemaVersion'], 1)
                    self.assertEqual(json.loads(value.content[0].text), value.structuredContent)
                    self.assertNotIn(NONREFLECTED_VALUE, value.content[0].text)
                    self.assertNotIn(folder, value.content[0].text)
                    refused = await client.call_tool('preflight_send', {'destination': 'local', 'target': 'fixture', 'message': NONREFLECTED_VALUE, 'wake': True})
                    self.assertTrue(refused.isError)
                    self.assertEqual(refused.structuredContent['reason'], 'request_rejected')
                    self.assertNotIn(NONREFLECTED_VALUE, refused.content[0].text)
                    sent = await client.call_tool('send_message', {'destination': 'local', 'target': 'fixture', 'message': NONREFLECTED_VALUE})
                    self.assertTrue(sent.isError)
