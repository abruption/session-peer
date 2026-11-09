"""SDK-major startup, real negotiated clients, and legacy stdio wire contracts."""
import asyncio
import builtins
import importlib.util
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import session_peer_mcp as peer


def opposite_client_python():
    interpreter = os.environ.get('SESSION_PEER_MCP_CLIENT_PYTHON')
    if os.environ.get('SESSION_PEER_MCP_REQUIRE_CLIENT') == '1' and not interpreter:
        raise AssertionError('MCP CI requires an opposite-major client interpreter')
    if interpreter and not Path(interpreter).is_file():
        raise AssertionError('Opposite-major client interpreter does not exist')
    return interpreter


class SdkSelection(unittest.TestCase):
    def test_ci_required_client_cannot_silently_skip(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(opposite_client_python())
            os.environ['SESSION_PEER_MCP_REQUIRE_CLIENT'] = '1'
            with self.assertRaisesRegex(AssertionError, 'requires an opposite-major'):
                opposite_client_python()
            os.environ['SESSION_PEER_MCP_CLIENT_PYTHON'] = '/missing/synthetic-client/python'
            with self.assertRaisesRegex(AssertionError, 'does not exist'):
                opposite_client_python()
            os.environ['SESSION_PEER_MCP_CLIENT_PYTHON'] = sys.executable
            self.assertEqual(opposite_client_python(), sys.executable)

    def test_stable_pep440_metadata_preserves_supported_release(self):
        for text, expected in (('1.30', (1, 30, 0)), ('1.30.0.post1+vendor_1', (1, 30, 0)),
                               ('2.3.post1+Vendor-1', (2, 3, 0)), ('v0!2.3.0-1', (2, 3, 0)),
                               ('2.3.0.1', (2, 3, 0, 1)), ('2.3.0rc1', ()), ('2.3.1.dev1', ()),
                               ('1!2.3.0', ())):
            with self.subTest(installed=text):
                self.assertEqual(peer._sdk_release(text), expected)

    def test_unsupported_major_fails_explicitly(self):
        for installed in ('1.29.9', '2.0.0', '2.1.9', '2.2.9', '2.3.0rc1', '3.0.0'):
            with self.subTest(installed=installed), patch('importlib.metadata.version', return_value=installed):
                with self.assertRaisesRegex(ValueError, 'Unsupported MCP SDK version'):
                    peer._sdk_server_factory()

    def test_broken_sdk2_import_does_not_fall_back_to_sdk1(self):
        imported = []
        original = builtins.__import__

        def load(name, *args, **kwargs):
            imported.append(name)
            if name == 'mcp.server.mcpserver':
                raise ImportError('broken SDK dependency fixture')
            return original(name, *args, **kwargs)

        with patch('importlib.metadata.version', return_value='2.3.0'), \
                patch('builtins.__import__', side_effect=load):
            with self.assertRaisesRegex(ImportError, 'broken SDK dependency fixture'):
                peer._sdk_server_factory()
        self.assertNotIn('mcp.server.fastmcp', imported)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK not installed')
class NegotiatedWire(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='codex-mcp-sdk-contract-')
        self.addCleanup(self.folder.cleanup)
        self.policy = Path(self.folder.name) / 'policy.json'
        self.policy.write_text(json.dumps({'schemaVersion': 1, 'destinations': {
            'local': {'agents': ['claude'], 'capabilities': ['list']}}}))
        self.bounded_policy = Path(self.folder.name) / 'bounded-policy.json'
        self.bounded_policy.write_text(json.dumps({'schemaVersion': 1, 'destinations': {
            'x' * (peer.DESTINATION_ALIAS_BYTES + 1): {'agents': ['claude'], 'capabilities': ['list']}}}))

    async def probe(self, client_python):
        process = await asyncio.create_subprocess_exec(client_python,
            str(Path(__file__).with_name('client_probe.py')), sys.executable,
            str(Path(peer.__file__).resolve()), str(self.policy), str(self.bounded_policy),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        self.assertEqual(process.returncode, 0, stderr.decode())
        value = json.loads(stdout)
        self.assertIn(value['protocol'], ('2025-11-25', '2026-07-28'))
        capabilities = value['capabilities']
        expected_capabilities = {'tools', 'prompts', 'resources'}
        if version('mcp').startswith('1.'):
            expected_capabilities.add('experimental')
            self.assertEqual(capabilities['experimental'], {})
        self.assertEqual(set(capabilities), expected_capabilities)
        for kind in ('tools', 'prompts', 'resources'):
            self.assertIs(capabilities[kind]['listChanged'], False)
        self.assertIs(capabilities['resources']['subscribe'], False)
        if value['protocol'] == '2026-07-28':
            self.assertEqual(value['subscription_error'], -32601)
        tools = {tool['name']: tool for tool in value['tools']['tools']}
        self.assertEqual(set(tools), {'list_destinations', 'list_sessions', 'send_message',
            'preflight_send', 'diagnose_destination', 'list_presets'})
        self.assertEqual(set(tools['send_message']['inputSchema']['required']),
                         {'destination', 'target', 'message'})
        self.assertTrue(tools['list_destinations']['annotations']['readOnlyHint'])
        self.assertFalse(tools['send_message']['annotations']['readOnlyHint'])
        inventory = value['inventory']
        self.assertFalse(inventory['isError'])
        self.assertEqual(inventory['structuredContent'], json.loads(inventory['content'][0]['text']))
        self.assertEqual(inventory['structuredContent']['schemaVersion'], 1)
        self.assertEqual(inventory['structuredContent']['command'], 'mcp.destinations')
        self.assertEqual(inventory['structuredContent']['destinations'], [
            {'destination': 'local', 'transport': 'local', 'agents': ['claude'], 'capabilities': ['list']}])
        self.assertNotIn(str(self.policy.parent), inventory['content'][0]['text'])
        for name in ('refused', 'preflight'):
            result = value[name]
            self.assertTrue(result['isError'])
            self.assertEqual(result['structuredContent'], json.loads(result['content'][0]['text']))
            self.assertEqual(result['structuredContent']['reason'], 'request_rejected' if name == 'refused' else 'policy_denied')
        self.assertEqual(value['preflight']['structuredContent']['schemaVersion'], 1)
        self.assertEqual(value['preflight']['structuredContent']['checked']['validation'], 'not_run')
        self.assertEqual(value['preflight']['structuredContent']['limitations']['submission'], 'not_attempted')
        diagnostics = value['diagnostics']
        self.assertTrue(diagnostics['isError'])
        self.assertEqual(diagnostics['structuredContent']['schemaVersion'], 1)
        self.assertEqual(diagnostics['structuredContent']['command'], 'mcp.diagnostics')
        self.assertEqual(diagnostics['structuredContent']['reason'], 'request_rejected')
        self.assertIs(diagnostics['structuredContent']['retryAllowed'], False)
        bounded = value['bounded']
        self.assertEqual(value['bounded_protocol'], value['protocol'])
        self.assertTrue(bounded['isError'])
        self.assertEqual(bounded['structuredContent']['reason'], 'request_rejected')
        self.assertEqual(bounded['structuredContent']['schemaVersion'], 1)
        self.assertNotIn('destinations', bounded['structuredContent'])
        self.assertNotIn('x' * (peer.DESTINATION_ALIAS_BYTES + 1), bounded['content'][0]['text'])
        self.assertEqual(bounded['structuredContent'], json.loads(bounded['content'][0]['text']))
        return value

    async def test_installed_client_negotiates_real_server(self):
        value = await self.probe(sys.executable)
        if version('mcp').startswith('2.'):
            self.assertEqual(value['protocol'], '2026-07-28')
        else:
            self.assertEqual(value['protocol'], '2025-11-25')

    async def test_opposite_major_client_negotiates_real_server(self):
        interpreter = opposite_client_python()
        if interpreter is None:
            self.skipTest('optional opposite-major client interpreter not supplied locally')
        value = await self.probe(interpreter)
        self.assertNotEqual(value['sdk'].split('.')[0], version('mcp').split('.')[0])
        self.assertEqual(value['protocol'], '2025-11-25')

    async def test_legacy_wire_preserves_aliases_and_result_envelopes(self):
        # A raw older client checks actual bytes, rather than relying on either
        # SDK's model aliases to conceal accidental snake_case serialization.
        process = await asyncio.create_subprocess_exec(sys.executable,
            str(Path(peer.__file__).resolve()), '--config', str(self.policy),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)

        async def request(identifier, method, params=None):
            message = {'jsonrpc': '2.0', 'method': method}
            if identifier is not None:
                message['id'] = identifier
            if params is not None:
                message['params'] = params
            process.stdin.write(json.dumps(message).encode() + b'\n')
            await process.stdin.drain()
            if identifier is None:
                return
            while True:
                raw = await asyncio.wait_for(process.stdout.readline(), 10)
                self.assertTrue(raw, 'server exited before its response')
                value = json.loads(raw)
                if value.get('id') == identifier:
                    self.assertNotIn('error', value)
                    return value['result']

        try:
            initialized = await request(1, 'initialize', {'protocolVersion': '2025-11-25',
                'capabilities': {}, 'clientInfo': {'name': 'raw-legacy-fixture', 'version': '1'}})
            self.assertEqual(initialized['protocolVersion'], '2025-11-25')
            self.assertEqual(initialized['serverInfo']['name'], 'session-peer')
            for kind in ('tools', 'prompts', 'resources'):
                self.assertIs(initialized['capabilities'][kind]['listChanged'], False)
            self.assertIs(initialized['capabilities']['resources']['subscribe'], False)
            await request(None, 'notifications/initialized')
            listing = await request(2, 'tools/list')
            inventory = next(t for t in listing['tools'] if t['name'] == 'list_destinations')
            self.assertIn('inputSchema', inventory)
            self.assertNotIn('input_schema', inventory)
            self.assertTrue(inventory['annotations']['readOnlyHint'])
            result = await request(3, 'tools/call', {'name': 'list_destinations', 'arguments': {}})
            self.assertNotIn('_meta', result)
            self.assertEqual(set(result), {'content', 'structuredContent', 'isError'})
            self.assertFalse(result['isError'])
            self.assertEqual(result['structuredContent'], json.loads(result['content'][0]['text']))
            refused = await request(4, 'tools/call', {'name': 'preflight_send', 'arguments': {
                'destination': 'local', 'target': 'synthetic-fixture', 'message': 'never delivered'}})
            self.assertTrue(refused['isError'])
            self.assertEqual(refused['structuredContent']['reason'], 'policy_denied')
            self.assertNotIn('resultType', refused)
            self.assertNotIn('_meta', refused)
            self.assertLessEqual(len(json.dumps(refused).encode()), peer.DESTINATION_METADATA_BYTES)
        finally:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def test_raw_result_budget_includes_modern_server_identity_stamp(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.types import CallToolResult, TextContent

        modern = version('mcp').startswith('2.')
        # Learn the fixed candidate's identity from a real initialize response;
        # don't assume that an unversioned server reports a particular version.
        parameters = StdioServerParameters(command=sys.executable,
            args=[str(Path(peer.__file__).resolve()), '--config', str(self.policy)])
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                server_info = initialized.model_dump(mode='json', by_alias=True, exclude_none=True)['serverInfo']
        identity = {'io.modelcontextprotocol/serverInfo': server_info}

        def payload(length, padding):
            return {'ok': True, 'schemaVersion': 1, 'command': 'mcp.destinations',
                    'destinations': [], 'padding': padding * length}

        def measured(length, stamped, padding):
            value = payload(length, padding)
            result = CallToolResult(content=[TextContent(type='text', text=json.dumps(value, ensure_ascii=False))],
                                    structuredContent=value, isError=False)
            if stamped:
                result = result.model_copy(update={'meta': identity})
            return len(result.model_dump_json(by_alias=True).encode('utf-8'))

        def largest_fit(stamped, padding):
            low, high = 0, peer.DESTINATION_METADATA_BYTES
            while low < high:
                middle = (low + high + 1) // 2
                if measured(middle, stamped, padding) <= peer.DESTINATION_METADATA_BYTES:
                    low = middle
                else:
                    high = middle - 1
            return low

        wrapper = Path(self.folder.name) / 'bounded-server.py'
        wrapper.write_text(
            'import importlib.util, json, sys\n'
            f'sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})\n'
            f'spec = importlib.util.spec_from_file_location("bounded_peer", {str(Path(peer.__file__).resolve())!r})\n'
            'peer = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(peer)\n'
            'class Fixture(peer.Adapter):\n'
            '    async def list_destinations(self):\n'
            '        return {"ok": True, "schemaVersion": 1, "command": "mcp.destinations", '
            '"destinations": [], "padding": sys.argv[2] * int(sys.argv[1])}\n'
            'peer.create_server(Fixture({})).run(transport="stdio")\n')
        protocols = ['2025-11-25'] + (['2026-07-28'] if modern else [])
        for padding in ('a', '한', '😀'):
            fit = largest_fit(modern, padding)
            self.assertLessEqual(measured(fit, modern, padding), peer.DESTINATION_METADATA_BYTES)
            self.assertGreater(measured(fit + 1, modern, padding), peer.DESTINATION_METADATA_BYTES)
            cases = [(fit, False), (fit + 1, True)]
            if modern:
                unstamped_fit = largest_fit(False, padding)
                # This payload passed the former model-only check but its actual
                # modern result, including the SDK's identity stamp, exceeds 64 KiB.
                value = payload(unstamped_fit, padding)
                expected = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
                            'structuredContent': value, 'isError': False,
                            'resultType': 'complete', '_meta': identity}
                self.assertGreater(len(json.dumps(expected, ensure_ascii=False, separators=(',', ':')).encode()),
                                   peer.DESTINATION_METADATA_BYTES)
                cases.append((unstamped_fit, True))
            for protocol in protocols:
                for length, rejected in cases:
                    with self.subTest(protocol=protocol, padding=padding, length=length, rejected=rejected):
                        process = await asyncio.create_subprocess_exec(sys.executable, str(wrapper), str(length), padding,
                            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL, limit=2 * peer.DESTINATION_METADATA_BYTES)

                        async def request(identifier, method, params=None):
                            params = {} if params is None else params
                            if protocol == '2026-07-28':
                                params['_meta'] = {'io.modelcontextprotocol/protocolVersion': protocol,
                                                   'io.modelcontextprotocol/clientCapabilities': {}}
                            message = {'jsonrpc': '2.0', 'method': method, 'params': params}
                            if identifier is not None:
                                message['id'] = identifier
                            process.stdin.write(json.dumps(message).encode() + b'\n')
                            await process.stdin.drain()
                            if identifier is None:
                                return
                            while True:
                                raw = await asyncio.wait_for(process.stdout.readline(), 10)
                                self.assertTrue(raw, 'bounded server exited before response')
                                value = json.loads(raw)
                                if value.get('id') == identifier:
                                    self.assertNotIn('error', value)
                                    # Measure the exact result substring of the received
                                    # JSON-RPC line, including all SDK-added fields.
                                    text = raw.decode('utf-8')
                                    start = text.index('"result":') + len('"result":')
                                    _, end = json.JSONDecoder().raw_decode(text[start:])
                                    return value['result'], len(text[start:start + end].encode('utf-8'))

                        try:
                            if protocol == '2025-11-25':
                                await request(1, 'initialize', {'protocolVersion': protocol, 'capabilities': {},
                                    'clientInfo': {'name': 'raw-budget-fixture', 'version': '1'}})
                                await request(None, 'notifications/initialized')
                            else:
                                await request(1, 'server/discover')
                            result, size = await request(2, 'tools/call', {'name': 'list_destinations', 'arguments': {}})
                            self.assertLessEqual(size, peer.DESTINATION_METADATA_BYTES)
                            self.assertIs(result['isError'], rejected)
                            self.assertEqual(result['structuredContent'], json.loads(result['content'][0]['text']))
                            if rejected:
                                self.assertEqual(result['structuredContent']['error'], 'Destination metadata limit exceeded')
                                self.assertNotIn('padding', result['structuredContent'])
                            else:
                                self.assertEqual(result['structuredContent'], payload(length, padding))
                            if protocol == '2026-07-28':
                                self.assertEqual(result['resultType'], 'complete')
                                self.assertEqual(result['_meta'], identity)
                            else:
                                self.assertNotIn('resultType', result)
                                self.assertNotIn('_meta', result)
                        finally:
                            process.stdin.close()
                            try:
                                await asyncio.wait_for(process.wait(), 5)
                            except asyncio.TimeoutError:
                                process.kill()
                                await process.wait()
