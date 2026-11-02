"""Bounded diagnostics fixtures: no native agent, SSH, model or external service."""
import argparse
import asyncio
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import session_peer as core
import session_peer_mcp as peer

FIXTURE_MARKER = '/fixture/nonreflected-path'
ACTIVE_DIAGNOSTICS = os.name == 'posix' and sys.platform in ('darwin', 'linux')


def entry(capabilities=('diagnostics', 'diagnostics_probe'), agents=('codex',)):
    return {'capabilities': list(capabilities), 'agents': list(agents),
            'host': 'fixture-user@fixture-host', 'codexHome': FIXTURE_MARKER}


class Policy(unittest.TestCase):
    def test_new_permissions_only_schema_two_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'policy.json'
            for cap in ('diagnostics', 'diagnostics_probe'):
                for version in (1, 2):
                    path.write_text(json.dumps({'schemaVersion': version,
                                               'destinations': {'test': entry((cap,))}}))
                    if version == 1:
                        with self.assertRaises(peer.PolicyError):
                            peer.load_policy(str(path))
                    else:
                        self.assertEqual(peer.load_policy(str(path))['test']['capabilities'], [cap])
        self.assertNotIn('diagnostics', peer.load_policy(None)['local']['capabilities'])


class Diagnostics(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_has_no_invocations_or_discovery(self):
        adapter = peer.Adapter({'test': entry(('diagnostics',))})
        adapter.invoke = AsyncMock(side_effect=AssertionError('legacy CLI called'))
        adapter.invoke_diagnostic = AsyncMock(side_effect=AssertionError('probe called'))
        with patch.object(core, 'doctor_payload', side_effect=AssertionError('doctor called')):
            value = await adapter.diagnose_destination('test')
        self.assertEqual(value['mode'], 'metadata')
        row = value['agents']['codex']
        self.assertEqual(row['status'], 'not_checked')
        self.assertEqual(row['checks'], [])
        self.assertEqual(row['capabilityBasis'], 'adapter_declaration')
        self.assertEqual(set(row['declaredCapabilities']), {'send', 'wake', 'wait', 'ack'})
        self.assertTrue(all(type(item) is bool for item in row['declaredCapabilities'].values()))
        for stage in ('tcpAccept', 'tls', 'peerAuthentication'):
            self.assertEqual(value['limitations'][stage], 'not_checked')
        self.assertNotIn(FIXTURE_MARKER, json.dumps(value))
        self.assertNotIn('fixture-user', json.dumps(value))
        adapter.invoke.assert_not_called()
        adapter.invoke_diagnostic.assert_not_called()

    async def test_every_denial_precedes_any_effect(self):
        for caps, agent, active in (((), None, False), (('diagnostics_probe',), None, True),
                                    (('diagnostics',), None, True),
                                    (('diagnostics', 'diagnostics_probe'), 'claude', True)):
            adapter = peer.Adapter({'test': entry(caps)})
            adapter.invoke_diagnostic = AsyncMock()
            with self.assertRaises(peer.PolicyError):
                await adapter.diagnose_destination('test', agent, active)
            adapter.invoke_diagnostic.assert_not_called()
        for alias in ('x\n', 'x' * 129, '\ud800'):
            adapter = peer.Adapter({alias: entry()})
            adapter.invoke_diagnostic = AsyncMock()
            with self.assertRaises(peer.PolicyError):
                await adapter.diagnose_destination(alias, active_probe=True)
            adapter.invoke_diagnostic.assert_not_called()

    async def test_windows_active_fails_closed_before_process_or_network(self):
        adapter = peer.Adapter({'test': entry()})
        adapter.invoke_diagnostic = AsyncMock()
        with patch.object(peer.os, 'name', 'nt'):
            value = await adapter.diagnose_destination('test', active_probe=True)
            metadata = await adapter.diagnose_destination('test')
        self.assertFalse(value['ok'])
        self.assertEqual(value['reason'], 'diagnostics_platform_unsupported')
        self.assertTrue(metadata['ok'])
        adapter.invoke_diagnostic.assert_not_called()

    @unittest.skipUnless(ACTIVE_DIAGNOSTICS, 'Active diagnostics are macOS/Linux only')
    async def test_active_projects_poison_and_pins_each_scope(self):
        adapter = peer.Adapter({'test': entry(agents=('codex', 'claude'))})
        async def respond(argv, timeout):
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, peer.DIAGNOSTIC_TIMEOUT)
            self.assertIn('--selected-home-only', argv)
            self.assertNotIn('--check-return-route', argv)
            self.assertNotIn('--reply-to', argv)
            name = argv[argv.index('--agent') + 1]
            self.assertEqual('--codex-home' in argv, name == 'codex')
            self.assertEqual(argv[argv.index('--host') + 1], 'fixture-user@fixture-host')
            return {'ok': True, name: {'status': 'available', 'selectedHome': FIXTURE_MARKER,
                    'checks': [{'code': 'state_db_readable', 'status': 'ok', 'message': FIXTURE_MARKER},
                               {'code': FIXTURE_MARKER, 'status': 'error'},
                               {'code': 'adapter_failed', 'status': FIXTURE_MARKER}],
                    'homes': [FIXTURE_MARKER] * 10000}, 'error': FIXTURE_MARKER}
        adapter.invoke_diagnostic = AsyncMock(side_effect=respond)
        value = await adapter.diagnose_destination('test', active_probe=True)
        self.assertEqual(adapter.invoke_diagnostic.await_count, 2)
        self.assertEqual(set(value['agents']), {'codex', 'claude'})
        self.assertEqual(value['agents']['codex']['checks'], [{'code': 'state_db_readable', 'status': 'ok'}])
        self.assertNotIn(FIXTURE_MARKER, json.dumps(value))
        self.assertLess(len(json.dumps(value)), peer.DESTINATION_METADATA_BYTES)

    @unittest.skipUnless(ACTIVE_DIAGNOSTICS, 'Active diagnostics are macOS/Linux only')
    async def test_deadline_stops_further_calls_and_no_retry(self):
        adapter = peer.Adapter({'test': entry(agents=('codex', 'claude'))})
        async def respond(argv, timeout):
            await asyncio.sleep(.02)
            return {'ok': False, 'reason': 'diagnostic_timeout', 'error': FIXTURE_MARKER}
        adapter.invoke_diagnostic = AsyncMock(side_effect=respond)
        with patch.object(peer, 'DIAGNOSTIC_TIMEOUT', .001):
            value = await adapter.diagnose_destination('test', active_probe=True)
        self.assertEqual(adapter.invoke_diagnostic.await_count, 1)
        self.assertFalse(value['ok'])
        self.assertTrue(all(row['reason'] == 'diagnostic_timeout' for row in value['agents'].values()))
        self.assertNotIn(FIXTURE_MARKER, json.dumps(value))

    async def test_invocation_fixed_errors_no_reflection(self):
        adapter = peer.Adapter({})
        cases = [(b'{bad', 0), (b'[]', 0), (b'{}', 0), (b'[' * 2000 + b']' * 2000, 0),
                 (json.dumps({'ok': True, 'command': 'doctor', 'schemaVersion': 1}).encode(), 2)]
        for stdout, code in cases:
            with patch.object(peer, 'invoke_posix', AsyncMock(return_value=(stdout, code))):
                value = await adapter.invoke_diagnostic(['doctor'], .1)
            self.assertFalse(value['ok'])
            self.assertNotIn('error', value)
        for error, reason in ((asyncio.TimeoutError(), 'diagnostic_timeout'),
                              (peer.DiagnosticOutputLimit(), 'diagnostic_output_limit'),
                              (OSError(FIXTURE_MARKER), 'diagnostic_response_unavailable')):
            with patch.object(peer, 'invoke_posix', AsyncMock(side_effect=error)):
                self.assertEqual((await adapter.invoke_diagnostic(['doctor'], .1))['reason'], reason)
        with patch.object(peer, 'invoke_posix', AsyncMock(side_effect=asyncio.CancelledError())):
            with self.assertRaises(asyncio.CancelledError):
                await adapter.invoke_diagnostic(['doctor'], .1)

    @unittest.skipUnless(ACTIVE_DIAGNOSTICS, 'Active diagnostics are macOS/Linux only')
    async def test_check_and_unknown_status_bounds(self):
        adapter = peer.Adapter({'test': entry()})
        adapter.invoke_diagnostic = AsyncMock(return_value={'ok': True, 'codex': {
            'status': [FIXTURE_MARKER], 'checks': [{'code': 'adapter_failed', 'status': 'error'}] * 10000}})
        value = await adapter.diagnose_destination('test', active_probe=True)
        self.assertEqual(value['agents']['codex']['status'], 'unknown')
        self.assertEqual(len(value['agents']['codex']['checks']), 32)
        self.assertFalse(value['ok'])
        self.assertEqual(value['agents']['codex']['reason'], 'diagnostic_incomplete')
        self.assertTrue(value['agents']['codex']['truncated'])
        self.assertLess(len(json.dumps(value)), peer.DESTINATION_METADATA_BYTES)

    async def test_nonzero_ssh_failure_keeps_only_recognized_failure_category(self):
        adapter = peer.Adapter({})
        for category in ('authentication_failed', 'host_key_failed', 'timeout', 'transport_failed', FIXTURE_MARKER):
            raw = {'schemaVersion': 1, 'command': 'doctor', 'ok': False,
                   'sshFailure': category, 'error': FIXTURE_MARKER, 'host': FIXTURE_MARKER}
            with patch.object(peer, 'invoke_posix', AsyncMock(return_value=(json.dumps(raw).encode(), 1))):
                value = await adapter.invoke_diagnostic(['doctor'], .1)
            self.assertFalse(value['ok'])
            self.assertNotIn(FIXTURE_MARKER, json.dumps(value))
            if category != FIXTURE_MARKER:
                self.assertEqual(value['sshFailure'], category)
            else:
                self.assertNotIn('sshFailure', value)

    @unittest.skipUnless(ACTIVE_DIAGNOSTICS, 'Active diagnostics are macOS/Linux only')
    async def test_missing_or_malformed_checks_cannot_report_available(self):
        adapter = peer.Adapter({'test': entry()})
        for row in ({}, {'status': 'available'}, {'status': 'available', 'checks': 'invalid'},
                    {'status': 'available', 'checks': [None]}):
            adapter.invoke_diagnostic = AsyncMock(return_value={'ok': True, 'codex': row})
            value = await adapter.diagnose_destination('test', active_probe=True)
            self.assertFalse(value['ok'])
            self.assertEqual(value['agents']['codex']['status'], 'unknown')
            self.assertEqual(value['agents']['codex']['reason'], 'diagnostic_incomplete')

    @unittest.skipUnless(ACTIVE_DIAGNOSTICS, 'Active diagnostics are macOS/Linux only')
    async def test_required_codex_checks_and_producer_scan_completeness(self):
        adapter = peer.Adapter({'test': entry()})
        complete = {'status': 'available', 'unsavedWriterScanTruncated': False, 'checks': [
            {'code': 'codex_executable_found', 'status': 'ok'},
            {'code': 'state_db_readable', 'status': 'ok'}]}
        for row, accepted in ((complete, True), ({**complete, 'checks': []}, False),
                              ({**complete, 'checks': complete['checks'][:1]}, False),
                              ({**complete, 'unsavedWriterScanTruncated': True}, False),
                              ({**complete, 'unsavedWriterScanTruncated': None}, False),
                              ({**complete, 'unsavedWriterScanTruncated': 0}, False)):
            adapter.invoke_diagnostic = AsyncMock(return_value={'ok': True, 'codex': row})
            value = await adapter.diagnose_destination('test', active_probe=True)
            self.assertEqual(value['ok'], accepted)
            self.assertEqual(value['agents']['codex']['status'], 'available' if accepted else 'unknown')
            if not accepted:
                self.assertEqual(value['agents']['codex']['reason'], 'diagnostic_incomplete')


class OwnedChildren(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.name == 'posix', 'POSIX owned process groups')
    async def test_each_raw_pipe_overflow_terminates_owned_child(self):
        original = subprocess.Popen
        for fd in (1, 2):
            children = []
            def spawn(*args, **kwargs):
                child = original(*args, **kwargs)
                children.append(child)
                return child
            with patch.object(peer.subprocess, 'Popen', side_effect=spawn):
                with self.assertRaises(peer.DiagnosticOutputLimit):
                    await peer.invoke_posix([sys.executable, '-c',
                        f'import os,time; os.write({fd}, b"x" * 1000000); time.sleep(30)'], None,
                        timeout=2, output_limit=1024)
            self.assertIsNotNone(children[0].returncode)
            self.assertTrue(children[0].stdout.closed)
            self.assertTrue(children[0].stderr.closed)

    @unittest.skipUnless(os.name == 'posix', 'POSIX owned process groups')
    async def test_timeout_and_repeated_cancellation_reap_child(self):
        original = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(peer.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaises(asyncio.TimeoutError):
                await peer.invoke_posix([sys.executable, '-c', 'import time; time.sleep(30)'], None,
                                       timeout=.02, output_limit=1024)
            task = asyncio.create_task(peer.invoke_posix(
                [sys.executable, '-c', 'import time; time.sleep(30)'], None,
                timeout=2, output_limit=1024))
            await asyncio.sleep(.02)
            task.cancel()
            await asyncio.sleep(.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(all(child.returncode is not None for child in children))


class DoctorScope(unittest.TestCase):
    def test_selected_disabled_agent_is_not_healthy(self):
        args = argparse.Namespace(agent='antigravity', _return_host=None)
        with patch.object(core, 'agy_registrations', return_value=[]), \
                patch.object(core, 'installed_skills') as skills:
            value = core.doctor_payload(args)
        self.assertEqual(value['antigravity']['status'], 'disabled')
        self.assertEqual(value['status'], 'issues_found')
        skills.assert_not_called()

    def test_agent_selection_and_legacy_all_agents(self):
        for selected in ('claude', 'codex', 'antigravity', None):
            calls = []
            def diagnose(command, adapter, args):
                calls.append(adapter.name)
                return {'status': 'available', 'checks': []}
            args = argparse.Namespace(agent=selected, _return_host=None)
            with patch.object(core.LocalTransport, 'execute', side_effect=diagnose), \
                 patch.object(core, 'installed_skills', return_value=[]) as skills:
                value = core.doctor_payload(args)
            expected = [selected] if selected else list(core.AGENTS.names())
            self.assertEqual(calls, expected)
            self.assertEqual(set(value['capabilities']['agents']), set(expected))
            facts = core.build_delivery_explanation(args, value, mode='doctor')
            self.assertEqual([row['agent'] for row in facts['agents']], expected)
            if selected:
                skills.assert_not_called()
                self.assertEqual(value['skill'], {'status': 'not_checked', 'checks': []})
            else:
                skills.assert_called_once()

    def test_selected_home_only_never_inventories_other_homes(self):
        args = argparse.Namespace(codex_home=FIXTURE_MARKER, codex_bin=None, selected_home_only=True)
        with patch.object(core, 'known_codex_homes', side_effect=AssertionError('inventory')), \
             patch.object(core, 'count_unsaved_codex_writers', return_value=(0, False)), \
             patch.object(core, 'diagnose_codex_home', return_value={
                 'codexHome': FIXTURE_MARKER, 'status': 'available', 'code': 'state_db_readable'}), \
             patch.object(core.shutil, 'which', return_value='/fixture/codex'):
            value = core.diagnose_codex(args)
        self.assertEqual(len(value['homes']), 1)

    def test_ssh_forwards_both_scope_flags_without_other_options(self):
        response = {'ok': True, 'schemaVersion': 1, 'command': 'doctor', 'status': 'healthy',
                    'claude': {'status': 'available', 'checks': []}}
        with patch.object(core, 'tailscale_status', return_value={}), \
             patch.object(core, 'run_remote', return_value=response) as remote, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(core.main(['doctor', '--host', 'fixture-host', '--agent', 'claude',
                                        '--selected-home-only', '--json']), 0)
        argv = remote.call_args.args[1]
        self.assertEqual(argv[argv.index('--agent') + 1], 'claude')
        self.assertIn('--selected-home-only', argv)
        self.assertNotIn('--_return-host', argv)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK')
class Protocol(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.name == 'posix' and sys.platform in ('darwin', 'linux'),
                         'Active diagnostics are macOS/Linux only')
    async def test_stdio_active_executes_real_scoped_cli_against_empty_fixture_home(self):
        import sqlite3
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory(prefix='codex-diag-active-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as folder:
            root = Path(folder)
            binary = root / 'codex'
            import shlex
            invoked = root / 'native-called'
            binary.write_text('#!/bin/sh\nprintf called > ' + shlex.quote(str(invoked)) + '\nexit 97\n')
            binary.chmod(0o700)
            sessions = root / 'sessions'
            sessions.mkdir()
            connections = []
            async def inbox(reader, writer):
                connections.append(True)
                writer.close()
                await writer.wait_closed()
            sock = root / 'inbox.sock'
            server = await asyncio.start_unix_server(inbox, str(sock))
            self.addAsyncCleanup(server.wait_closed)
            self.addCleanup(server.close)
            (sessions / (str(os.getpid()) + '.json')).write_text(json.dumps({
                'pid': os.getpid(), 'name': 'diagnostic-fixture', 'messagingSocketPath': str(sock)}))
            with contextlib.closing(sqlite3.connect(root / 'state_5.sqlite')) as db:
                db.execute('CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)')
                db.commit()
            policy = root / 'policy.json'
            policy.write_text(json.dumps({'schemaVersion': 2, 'destinations': {
                'fixture': {'agents': ['claude', 'codex'], 'codexHome': folder,
                            'capabilities': ['diagnostics', 'diagnostics_probe']}}}))
            params = StdioServerParameters(command=sys.executable,
                args=[str(Path(peer.__file__).resolve()), '--config', str(policy)],
                env={**os.environ, 'PATH': folder + os.pathsep + os.defpath, 'CODEX_HOME': folder,
                     'CLAUDE_CONFIG_DIR': folder, 'XDG_CONFIG_HOME': folder})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    value = await client.call_tool('diagnose_destination', {
                        'destination': 'fixture', 'active_probe': True})
                    self.assertFalse(value.isError, value.structuredContent)
                    row = value.structuredContent['agents']['codex']
                    self.assertEqual(row['status'], 'available')
                    self.assertIn({'code': 'state_db_readable', 'status': 'ok'}, row['checks'])
                    self.assertEqual(value.structuredContent['agents']['claude']['status'], 'available')
                    self.assertFalse(invoked.exists())
                    self.assertEqual(connections, [])
                    self.assertNotIn(folder, value.content[0].text)
                    self.assertEqual(value.structuredContent['limitations']['submission'], 'not_attempted')

    async def test_stdio_schema_metadata_and_probe_denials(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'policy.json'
            # Nonexistent host/home ensures successful metadata cannot depend on
            # route reachability or filesystem inspection.
            path.write_text(json.dumps({'schemaVersion': 2, 'destinations': {
                'test': entry(('diagnostics',))}}))
            params = StdioServerParameters(command=sys.executable,
                args=[str(Path(peer.__file__).resolve()), '--config', str(path)])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = (await client.list_tools()).tools
                    tool = next(t for t in tools if t.name == 'diagnose_destination')
                    self.assertEqual(set(tool.inputSchema['properties']),
                                     {'destination', 'agent', 'active_probe'})
                    self.assertFalse(tool.annotations.readOnlyHint)
                    self.assertFalse(tool.annotations.idempotentHint)
                    self.assertTrue(tool.annotations.openWorldHint)
                    value = await client.call_tool('diagnose_destination', {'destination': 'test'})
                    self.assertFalse(value.isError)
                    self.assertEqual(value.structuredContent['mode'], 'metadata')
                    self.assertEqual(json.loads(value.content[0].text), value.structuredContent)
                    self.assertNotIn(FIXTURE_MARKER, value.content[0].text)
                    self.assertLess(len(value.model_dump_json().encode()), peer.DESTINATION_METADATA_BYTES)
                    for request in ({'destination': 'test', 'active_probe': True},
                                    {'destination': 'test', 'agent': 'claude'},
                                    {'destination': 'unknown'}):
                        value = await client.call_tool('diagnose_destination', request)
                        self.assertTrue(value.isError)
                        self.assertEqual(value.structuredContent['command'], 'mcp.diagnostics')
                        self.assertEqual(value.structuredContent['reason'], 'request_rejected')
                        self.assertNotIn('error', value.structuredContent)
