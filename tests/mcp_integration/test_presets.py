"""Approved MCP presets: synthetic secure snapshots, no real private store."""
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

import session_peer as core
import session_peer_mcp as peer

THREAD = '01900000-0000-7000-8000-000000000001'
PRIVATE_MARKER = 'nonreflected-fixture-value'
LOCAL = {'agent': 'claude', 'transport': 'local'}
REMOTE = {'agent': 'codex', 'transport': 'ssh', 'host': 'user@approved-host', 'codexHome': '/approved/home'}


def policy(route=LOCAL, *, capabilities=('presets', 'list', 'preflight', 'send'), names=('work',)):
    return {'agents': [route['agent']], 'capabilities': list(capabilities), 'presets': list(names),
            **({'host': route['host']} if 'host' in route else {}),
            **({'codexHome': route['codexHome']} if 'codexHome' in route else {})}


def preview(agent='claude'):
    args = argparse.Namespace(to='target' if agent == 'claude' else agent + ':target', wake=False)
    return core.structured_delivery_preflight(args, {'ok': True, 'dryRun': True})


class PresetPolicy(unittest.TestCase):
    def test_explicit_version_two_bounded_names_and_capability(self):
        with tempfile.TemporaryDirectory(prefix='codex-preset-policy-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            path = Path(folder) / 'policy.json'
            cases = [(1, policy(), False), (2, policy(), True),
                     (1, policy(capabilities=('list',)), False),
                     (2, policy(capabilities=('list',)), False),
                     (2, policy(names=()), False), (2, policy(names=('work', 'work')), False),
                     (2, policy(names=('INVALID',)), False), (2, policy(names=('a' * 65,)), False),
                     (2, policy(names=(PRIVATE_MARKER + '\n',)), False),
                     (2, policy(names=(None,)), False),
                     (2, policy(names=tuple('p' + str(i) for i in range(128))), True),
                     (2, policy(names=tuple('p' + str(i) for i in range(129))), False)]
            for version, entry, accepted in cases:
                with self.subTest(version=version, entry=entry):
                    path.write_text(json.dumps({'schemaVersion': version, 'destinations': {'local': entry}}))
                    if accepted:
                        self.assertEqual(peer.load_policy(str(path))['local'], entry)
                    else:
                        with self.assertRaises((peer.PolicyError, core.CcPeerError)) as caught:
                            peer.load_policy(str(path))
                        self.assertNotIn(PRIVATE_MARKER, str(caught.exception))
        self.assertNotIn('presets', peer.load_policy(None)['local']['capabilities'])


@unittest.skipUnless(os.name == 'posix' and sys.platform in ('darwin', 'linux'),
                     'Preset storage is macOS/Linux only')
class PresetSelection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = peer.Adapter({'local': policy(), 'remote': policy(REMOTE)})
        self.adapter.invoke = AsyncMock(return_value={'ok': True, 'command': 'list', 'sessions': []})
        self.lookup = patch.object(core, 'preset_lookup', side_effect=lambda name: (dict(LOCAL), core.preset_revision(name, LOCAL)))
        self.mock_lookup = self.lookup.start()
        self.addCleanup(self.lookup.stop)
        self.read = patch.object(core, 'preset_read', return_value={'work': dict(LOCAL)})
        self.mock_read = self.read.start()
        self.addCleanup(self.read.stop)

    async def test_denied_names_capabilities_and_agents_never_read_store_or_invoke(self):
        for entry in (policy(capabilities=('list',)), policy(capabilities=('presets',)),
                      policy(capabilities=('presets', 'list'), names=('other',))):
            self.adapter.destinations['local'] = entry
            with self.assertRaises(peer.PolicyError):
                await self.adapter.list_sessions('local', preset='work')
        self.adapter.destinations['local'] = policy()
        with self.assertRaises(peer.PolicyError):
            await self.adapter.list_sessions('local', agent='codex', preset='work')
        with self.assertRaises(peer.PolicyError):
            await self.adapter.list_presets('unknown')
        self.mock_read.assert_not_called()
        self.mock_lookup.assert_not_called()
        self.adapter.invoke.assert_not_called()

    async def test_metadata_only_approved_names_and_safe_route_projection(self):
        self.mock_read.return_value = {'work': dict(LOCAL), 'private': {
            'agent': 'codex', 'transport': 'ssh', 'host': PRIVATE_MARKER, 'codexHome': '/' + PRIVATE_MARKER}}
        with patch.object(core, 'preset_mutate', side_effect=AssertionError('write')), \
                patch.object(core.subprocess, 'Popen', side_effect=AssertionError('child')):
            value = await self.adapter.list_presets('local')
        self.assertEqual(value['presets'], [{'name': 'work', 'agent': 'claude', 'transport': 'local',
                                           'revision': core.preset_revision('work', LOCAL)}])
        self.assertEqual(value['schemaVersion'], 1)
        self.assertNotIn(PRIVATE_MARKER, json.dumps(value))
        self.mock_read.assert_called_once_with()
        self.mock_lookup.assert_not_called()
        self.adapter.invoke.assert_not_called()

    async def test_metadata_missing_or_mismatched_approved_route_refuses_atomically(self):
        for snapshot in ({}, {'work': REMOTE}, {'work': {'agent': 'codex', 'transport': 'local', 'codexHome': '/other'}}):
            self.mock_read.return_value = snapshot
            with self.assertRaises((peer.PolicyError, core.CcPeerError)):
                await self.adapter.list_presets('local')
        self.adapter.invoke.assert_not_called()

    async def test_listing_expands_one_approved_route_never_cli_preset(self):
        value = await self.adapter.list_sessions('local', include_inactive=True, preset='work')
        self.mock_lookup.assert_called_once_with('work')
        self.mock_read.assert_not_called()
        self.assertEqual(self.adapter.invoke.call_args.args[0], ['list', '--agent', 'claude', '--all'])
        self.assertEqual(value['preset']['revision'], core.preset_revision('work', LOCAL))
        self.assertEqual(value['preset']['transport'], 'local')
        self.assertEqual(value['command'], 'mcp.preset.sessions')

    async def test_remote_preflight_expands_exact_route_and_keeps_revision_metadata(self):
        self.mock_lookup.side_effect = lambda name: (dict(REMOTE), core.preset_revision(name, REMOTE))
        self.adapter.invoke.return_value = preview('codex')
        result = await self.adapter.preflight_send('remote', 'codex:' + THREAD, 'fixture message', preset='work')
        argv = self.adapter.invoke.call_args.args[0]
        self.assertTrue(result['ok'])
        self.assertEqual(argv[:5], ['send', '--host', REMOTE['host'], '--codex-home', REMOTE['codexHome']])
        self.assertIn('--dry-run', argv)
        self.assertIn('--explain-json', argv)
        self.assertNotIn('--preset', argv)
        self.assertNotIn(REMOTE['host'], json.dumps(result))
        self.assertNotIn(REMOTE['codexHome'], json.dumps(result))
        self.mock_lookup.assert_called_once_with('work')

    async def test_actual_send_requires_current_revision_and_explicit_target(self):
        with self.assertRaises(peer.PolicyError):
            await self.adapter.send_message('local', 'worker', 'fixture', preset='work')
        self.mock_lookup.assert_not_called()
        for revision in ('invalid', 'dp1:' + '0' * 64):
            with self.assertRaises(peer.PolicyError):
                await self.adapter.send_message('local', 'worker', 'fixture', preset='work', preset_revision=revision)
        self.adapter.invoke.assert_not_called()
        revision = core.preset_revision('work', LOCAL)
        value = await self.adapter.send_message('local', 'worker', 'fixture', preset='work', preset_revision=revision)
        argv = self.adapter.invoke.call_args.args[0]
        self.assertEqual(argv[argv.index('--to') + 1], 'worker')
        self.assertNotIn('--preset', argv)
        self.assertNotIn('--dry-run', argv)
        self.assertEqual(value['preset']['revision'], revision)
        self.assertEqual(value['command'], 'mcp.preset.send')

    async def test_dryrun_can_omit_revision_and_absent_selector_keeps_old_result(self):
        value = await self.adapter.send_message('local', 'worker', 'fixture', dry_run=True, preset='work')
        self.assertIn('--dry-run', self.adapter.invoke.call_args.args[0])
        self.assertIn('preset', value)
        self.mock_lookup.reset_mock()
        self.mock_read.reset_mock()
        ordinary = await self.adapter.list_sessions('local')
        self.assertEqual(ordinary, self.adapter.invoke.return_value)
        self.mock_lookup.assert_not_called()
        self.mock_read.assert_not_called()

    async def test_selected_send_post_invocation_failure_is_unknown_without_retry(self):
        revision = core.preset_revision('work', LOCAL)
        self.adapter.invoke.side_effect = OSError(PRIVATE_MARKER)
        value = await self.adapter.send_message('local', 'worker', 'fixture',
            preset='work', preset_revision=revision)
        self.assertEqual(value['status'], 'unknown')
        self.assertIsNone(value['submitted'])
        self.assertFalse(value['retryAllowed'])
        self.assertNotIn(PRIVATE_MARKER, json.dumps(value))
        self.adapter.invoke.assert_awaited_once()

    async def test_exact_alias_home_transport_and_agent_intersection_no_dns_or_fallback(self):
        cases = [dict(REMOTE, host='approved-host'), dict(REMOTE, codexHome='/approved/home/'),
                 {'agent': 'codex', 'transport': 'local', 'codexHome': REMOTE['codexHome']}, dict(LOCAL)]
        for route in cases:
            self.mock_lookup.side_effect = lambda name, selected=route: (dict(selected), core.preset_revision(name, selected))
            with self.subTest(route=route), patch.object(core, 'resolve_ssh_destination', side_effect=AssertionError('DNS')):
                with self.assertRaises(peer.PolicyError):
                    await self.adapter.list_sessions('remote', preset='work')
        self.adapter.invoke.assert_not_called()

    async def test_policy_is_rechecked_after_resolution_and_immediately_before_effect(self):
        revision = core.preset_revision('work', LOCAL)
        def change_policy(_):
            self.adapter.destinations['local']['capabilities'].remove('presets')
            return dict(LOCAL), revision
        self.mock_lookup.side_effect = change_policy
        with self.assertRaises(peer.PolicyError):
            await self.adapter.list_sessions('local', preset='work')
        self.adapter.invoke.assert_not_called()
        self.adapter.destinations['local'] = policy()
        self.mock_lookup.side_effect = lambda name: (dict(LOCAL), core.preset_revision(name, LOCAL))
        for mutate in (lambda e: e['capabilities'].remove('send'),
                       lambda e: e['presets'].clear(), lambda e: e.update(host='changed-host'),
                       lambda e: e.update(agents=['codex'])):
            self.adapter.destinations['local'] = policy()
            with patch.object(core, 'check_message', side_effect=lambda *a, **kw: mutate(self.adapter.destinations['local'])):
                with self.assertRaises(peer.PolicyError):
                    await self.adapter.send_message('local', 'worker', 'fixture', preset='work', preset_revision=revision)
        self.adapter.invoke.assert_not_called()

    async def test_snapshot_copy_survives_later_store_mutation_without_second_lookup(self):
        stored = dict(REMOTE)
        revision = core.preset_revision('work', stored)
        self.mock_lookup.side_effect = lambda name: (stored, revision)
        def mutate_store(*args, **kwargs):
            stored['host'] = 'changed-after-expansion'
        with patch.object(core, 'check_message', side_effect=mutate_store):
            value = await self.adapter.send_message('remote', 'codex:' + THREAD, 'fixture',
                preset='work', preset_revision=revision)
        argv = self.adapter.invoke.call_args.args[0]
        self.assertEqual(argv[argv.index('--host') + 1], REMOTE['host'])
        self.assertEqual(value['preset']['revision'], revision)
        self.mock_lookup.assert_called_once()

    async def test_wake_uri_revision_without_name_and_other_agent_rejected_before_lookup(self):
        for flags in ({'wake': True, 'preset': 'work'}, {'preset_revision': 'dp1:' + '0' * 64}):
            with self.assertRaises(peer.PolicyError):
                await self.adapter.send_message('local', 'worker', 'fixture', dry_run=True, **flags)
        uri = 'session-peer://v1/reply?agent=claude&session=42&transport=local'
        with self.assertRaises(peer.PolicyError):
            await self.adapter.send_message('local', uri, 'fixture', dry_run=True, preset='work')
        self.adapter.destinations['local']['agents'].append('antigravity')
        with self.assertRaises(peer.PolicyError):
            await self.adapter.send_message('local', 'antigravity:' + THREAD, 'fixture', dry_run=True, preset='work')
        self.mock_lookup.assert_not_called()
        self.adapter.invoke.assert_not_called()

    async def test_platform_is_not_broadened_even_with_mocked_store(self):
        with patch.object(core, 'IS_WINDOWS', True):
            for operation in (self.adapter.list_presets('local'), self.adapter.list_sessions('local', preset='work')):
                with self.assertRaises(core.CcPeerError):
                    await operation
        self.mock_lookup.assert_not_called()
        self.mock_read.assert_not_called()

    async def test_core_reader_guard_failures_are_not_repaired_or_replaced(self):
        for failure in (core._preset_error('preset_ownership_unenforced'), RuntimeError(PRIVATE_MARKER)):
            self.mock_lookup.side_effect = failure
            with patch.object(core, 'preset_mutate', side_effect=AssertionError('repair')):
                with self.assertRaises(peer.PolicyError) as caught:
                    await self.adapter.list_sessions('local', preset='work')
            self.assertNotIn(PRIVATE_MARKER, str(caught.exception))
        self.adapter.invoke.assert_not_called()

    async def test_cancellation_propagates_without_retry_or_store_repair(self):
        self.adapter.invoke.side_effect = asyncio.CancelledError
        with patch.object(core, 'preset_mutate', side_effect=AssertionError('write')):
            with self.assertRaises(asyncio.CancelledError):
                await self.adapter.list_sessions('local', preset='work')
        self.mock_lookup.assert_called_once()
        self.adapter.invoke.assert_awaited_once()


class SharedSecureReader(unittest.IsolatedAsyncioTestCase):
    async def test_missing_core_store_does_not_initialize_or_lock(self):
        adapter = peer.Adapter({'local': policy()})
        with patch.object(core, '_preset_directory', return_value=None) as directory, \
                patch.object(core.os, 'mkdir', side_effect=AssertionError('initialize')), \
                patch.object(core, '_preset_lock', side_effect=AssertionError('lock')), \
                patch.object(core, 'preset_mutate', side_effect=AssertionError('repair')):
            with self.assertRaises(peer.PolicyError):
                await adapter.list_presets('local')
        directory.assert_called_once_with()

    async def test_actual_core_lookup_preserves_snapshot_revision_once(self):
        adapter = peer.Adapter({'local': policy()})
        adapter.invoke = AsyncMock(return_value={'ok': True})
        with patch.object(core, 'preset_read', return_value={'work': dict(LOCAL)}) as read:
            value = await adapter.list_sessions('local', preset='work')
        self.assertEqual(value['preset']['revision'], core.preset_revision('work', LOCAL))
        read.assert_called_once_with()


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK')
@unittest.skipUnless(os.name == 'posix' and sys.platform in ('darwin', 'linux'),
                     'Preset storage is macOS/Linux only')
class PresetProtocol(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, folder, entry, *, snapshot=None, deny_read=False, tiny_budget=False,
                       native_result=None):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        import contextlib
        root = Path(folder)
        path = root / 'policy.json'
        path.write_text(json.dumps({'schemaVersion': 2, 'destinations': {'local': entry}}))
        wrapper = root / 'fixture.py'
        # A test-only validated snapshot replaces ownership I/O. This does NOT
        # establish private-store acceptance on an OwnersDisabled volume. Every
        # unexpected reader/invoker can terminate only this synthetic subprocess.
        wrapper.write_text('import sys, os\n'
            + 'sys.path.insert(0, ' + repr(str(Path(peer.__file__).resolve().parent)) + ')\n'
            + 'import session_peer_mcp as peer\n'
            + ('def snapshot():\n    os._exit(95)\n' if deny_read else
               'def snapshot():\n    return peer.core._preset_decode(' + repr(json.dumps(
                   {'schemaVersion': 1, 'presets': snapshot or {}}).encode()) + ')\n')
            + 'peer.core.preset_read = snapshot\n'
            + 'async def forbidden(*a, **k):\n    os._exit(94)\n'
            + ('peer.Adapter.invoke = forbidden\n' if native_result is None else
               'async def native_result(self, *a, **k):\n    return ' + repr(native_result) + '\n'
               + 'peer.Adapter.invoke = native_result\n')
            + ('peer.DESTINATION_METADATA_BYTES = 1\n' if tiny_budget else '')
            + 'raise SystemExit(peer.main())\n')
        params = StdioServerParameters(command=sys.executable, args=[str(wrapper), '--config', str(path)])
        @contextlib.asynccontextmanager
        async def session():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    yield client
        return session()

    async def test_real_stdio_query_is_versioned_filtered_and_has_explicit_selection_schema(self):
        with tempfile.TemporaryDirectory(prefix='codex-preset-stdio-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            session = await self.run_case(folder, policy(capabilities=('presets',)), snapshot={
                'work': dict(LOCAL), 'private': {'transport': 'ssh', 'agent': 'codex',
                    'host': PRIVATE_MARKER, 'codexHome': '/' + PRIVATE_MARKER}})
            async with session as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                self.assertTrue(tools['list_presets'].annotations.readOnlyHint)
                self.assertFalse(tools['list_presets'].annotations.openWorldHint)
                self.assertEqual(tools['list_presets'].inputSchema['required'], ['destination'])
                for name in ('list_sessions', 'send_message', 'preflight_send'):
                    self.assertIn('preset', tools[name].inputSchema['properties'])
                    self.assertIn('preset_revision', tools[name].inputSchema['properties'])
                result = await client.call_tool('list_presets', {'destination': 'local'})
                self.assertFalse(result.isError)
                self.assertEqual(result.structuredContent['schemaVersion'], 1)
                self.assertEqual(result.structuredContent['command'], 'mcp.presets')
                self.assertEqual(len(result.structuredContent['presets']), 1)
                self.assertEqual(result.structuredContent['presets'][0]['revision'], core.preset_revision('work', LOCAL))
                self.assertEqual(json.loads(result.content[0].text), result.structuredContent)
                self.assertNotIn(PRIVATE_MARKER, result.content[0].text)
                self.assertNotIn(folder, result.content[0].text)
                for tool, args in (('list_sessions', {'preset': 'work'}),
                                   ('send_message', {'preset': 'work', 'preset_revision': core.preset_revision('work', LOCAL),
                                                     'target': 'worker', 'message': 'fixture'}),
                                   ('preflight_send', {'preset': 'work', 'target': 'worker', 'message': 'fixture'})):
                    denied = await client.call_tool(tool, {'destination': 'local', **args})
                    self.assertTrue(denied.isError)
                    self.assertEqual(denied.structuredContent['schemaVersion'], 1)
                self.assertEqual(denied.structuredContent['reason'], 'policy_denied')

    async def test_real_stdio_denial_happens_before_store_or_cli(self):
        with tempfile.TemporaryDirectory(prefix='codex-preset-deny-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            entry = {'agents': ['claude'], 'capabilities': ['list', 'send', 'preflight']}
            session = await self.run_case(folder, entry, deny_read=True)
            async with session as client:
                for name, args in (('list_presets', {}), ('list_sessions', {'preset': 'work'}),
                                   ('send_message', {'preset': 'work', 'preset_revision': 'dp1:' + '0' * 64,
                                                     'target': 'worker', 'message': PRIVATE_MARKER}),
                                   ('preflight_send', {'preset': 'work', 'target': 'worker', 'message': PRIVATE_MARKER})):
                    value = await client.call_tool(name, {'destination': 'local', **args})
                    self.assertTrue(value.isError)
                    self.assertEqual(value.structuredContent['schemaVersion'], 1)
                    self.assertNotIn(PRIVATE_MARKER, value.content[0].text)

    async def test_real_stdio_route_mismatch_stale_revision_and_result_budget(self):
        with tempfile.TemporaryDirectory(prefix='codex-preset-race-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            session = await self.run_case(folder, policy(), snapshot={'work': dict(REMOTE)})
            async with session as client:
                for name, args in (('list_presets', {}), ('list_sessions', {'preset': 'work'})):
                    value = await client.call_tool(name, {'destination': 'local', **args})
                    self.assertTrue(value.isError)
                    self.assertNotIn(REMOTE['host'], value.content[0].text)
                    self.assertNotIn(REMOTE['codexHome'], value.content[0].text)
            session = await self.run_case(folder, policy(), snapshot={'work': dict(LOCAL)})
            async with session as client:
                value = await client.call_tool('send_message', {'destination': 'local', 'preset': 'work',
                    'preset_revision': 'dp1:' + '0' * 64, 'target': 'worker', 'message': 'fixture'})
                self.assertTrue(value.isError)
            session = await self.run_case(folder, policy(), snapshot={'work': dict(LOCAL)}, tiny_budget=True)
            async with session as client:
                value = await client.call_tool('list_presets', {'destination': 'local'})
                self.assertTrue(value.isError)
                self.assertEqual(value.structuredContent['command'], 'mcp.presets')
                self.assertEqual(value.structuredContent['schemaVersion'], 1)
                self.assertNotIn('presets', value.structuredContent)
                self.assertLessEqual(len(value.model_dump_json().encode()), 64 * 1024)

    async def test_maximum_approved_metadata_is_bounded_as_complete_tool_result(self):
        names = tuple('p' + 'x' * 60 + str(i).zfill(3) for i in range(128))
        with tempfile.TemporaryDirectory(prefix='codex-preset-max-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            session = await self.run_case(folder, policy(names=names), snapshot={name: dict(LOCAL) for name in names})
            async with session as client:
                value = await client.call_tool('list_presets', {'destination': 'local'})
                self.assertFalse(value.isError)
                self.assertEqual(len(value.structuredContent['presets']), 128)
                self.assertLessEqual(len(value.model_dump_json().encode()), 64 * 1024)

    async def test_large_native_submission_keeps_evidence_instead_of_size_refusal(self):
        with tempfile.TemporaryDirectory(prefix='codex-preset-proof-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            native = {'ok': True, 'status': 'queued', 'submitted': True,
                      'queueId': 'fixture-queue', 'target': {'pid': 42}, 'detail': 'x' * 40000}
            session = await self.run_case(folder, policy(), snapshot={'work': dict(LOCAL)}, native_result=native)
            async with session as client:
                value = await client.call_tool('send_message', {'destination': 'local',
                    'preset': 'work', 'preset_revision': core.preset_revision('work', LOCAL),
                    'target': 'worker', 'message': 'fixture'})
                self.assertFalse(value.isError)
                for key in ('submitted', 'status', 'queueId', 'target'):
                    self.assertEqual(value.structuredContent[key], native[key])
