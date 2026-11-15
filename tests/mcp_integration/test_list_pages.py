"""Bounded snapshot, raw-wire and owned synthetic-process contracts (#393)."""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import session_peer_mcp as peer
import session_peer_mcp_pages as pages

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'mcp_list_pages.py'


def listing(count=1000, agent='codex'):
    return {'ok': True, 'sessions': [{'agent': agent, 'id': 'fixture-%04d' % index,
        'name': '한글🪼' * 200, 'codexHome': '/PRIVATE', 'cwd': '/PRIVATE',
        'transcript': 'PRIVATE'} for index in range(count)],
        'discovery': {agent: {'status': 'ok'}}}


def policy():
    return {'local': {'agents': ['codex'], 'capabilities': ['list'], 'codexHome': '/PRIVATE'},
            'other': {'agents': ['codex'], 'capabilities': ['list'], 'codexHome': '/OTHER'},
            'denied': {'agents': ['codex'], 'capabilities': ['send'], 'codexHome': '/PRIVATE'}}


def arguments(**kwargs):
    return {'destination': 'local', 'agent': 'codex', **kwargs}


def conservative_measure(value):
    # Unit tests add a generous envelope allowance; real-wire tests below measure
    # the exact SDK1/2 CallToolResult including modern metadata.
    return len(pages.serialized({'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
        'structuredContent': value, 'isError': not value['ok']})) + 512


class Snapshots(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Exercise pure snapshot/authorization logic on every platform without
        # mutating os.name or widening production platform support.
        supported = patch.object(peer, '_listing_pages_supported', return_value=True)
        supported.start()
        self.addCleanup(supported.stop)
        self.adapter = peer.Adapter(policy())
        self.adapter.collect_sessions_page = AsyncMock(return_value=(listing(), 0))

    async def page(self, **kwargs):
        return await self.adapter.list_sessions_page(arguments(**kwargs), measure=conservative_measure)

    async def test_1000_ids_no_duplicates_or_continuation_collection(self):
        ids, cursor = [], None
        while True:
            value = await self.page(limit=37, cursor=cursor)
            self.assertTrue(value['ok'])
            self.assertTrue(value['complete'])
            self.assertLessEqual(conservative_measure(value), pages.PAGE_OUTPUT_BYTES)
            ids.extend(row['id'] for row in value['sessions'])
            cursor = value['nextCursor']
            if cursor is None:
                break
        self.assertEqual(ids, ['fixture-%04d' % index for index in range(1000)])
        self.assertEqual(len(set(ids)), 1000)
        self.adapter.collect_sessions_page.assert_awaited_once()

    async def test_projection_exact_identity_unicode_and_label(self):
        value = await self.page()
        self.assertTrue(value['sessions'][0]['nameTruncated'])
        self.assertLessEqual(len(value['sessions'][0]['name'].encode()), pages.PAGE_LABEL_BYTES)
        self.assertNotIn('PRIVATE', json.dumps(value))
        self.assertEqual(set(value['sessions'][0]), {'agent', 'id', 'name', 'nameTruncated'})
        for field in ('cwd', 'codexHome', 'stateDb', 'transcript', 'host'):
            self.assertNotIn(field, json.dumps(value))

    async def test_invalid_optional_label_omitted_without_losing_ids(self):
        raw = listing(1000)
        raw['sessions'][500]['name'] = 'invalid\ud800label'
        self.adapter.collect_sessions_page.return_value = raw, 0
        ids, cursor, omitted = [], None, []
        while True:
            value = await self.page(cursor=cursor)
            self.assertTrue(value['complete'])
            self.assertLessEqual(conservative_measure(value), pages.PAGE_OUTPUT_BYTES)
            ids.extend(row['id'] for row in value['sessions'])
            omitted.extend(row for row in value['sessions'] if row.get('nameOmitted'))
            cursor = value['nextCursor']
            if cursor is None:
                break
        self.assertEqual(ids, ['fixture-%04d' % i for i in range(1000)])
        self.assertEqual(omitted, [{'agent': 'codex', 'id': 'fixture-0500', 'nameOmitted': True}])
        self.adapter.collect_sessions_page.assert_awaited_once()

    async def test_claude_source_pid_shape_and_antigravity_identity(self):
        self.adapter.destinations['local']['agents'] = ['claude', 'antigravity']
        for agent, row, expected in (('claude', {'agent': 'claude', 'pid': 1234, 'name': 'name'}, '1234'),
                ('antigravity', {'agent': 'antigravity', 'id': 'registered-bridge', 'name': 'name'}, 'registered-bridge')):
            raw = {'ok': True, 'sessions': [row], 'discovery': {agent: {'status': 'ok'}}}
            self.adapter.collect_sessions_page.return_value = raw, 0
            value = await self.page(agent=agent)
            self.assertTrue(value['complete'])
            self.assertEqual(value['sessions'][0]['id'], expected)
        for pid in (True, '1234', 1, -1, 2 ** 63):
            self.adapter.collect_sessions_page.return_value = {'ok': True,
                'sessions': [{'agent': 'claude', 'pid': pid}], 'discovery': {'claude': {'status': 'ok'}}}, 0
            self.assertEqual((await self.page(agent='claude'))['reason'], 'identity_unrepresentable')

    async def test_strict_json_arguments_and_unknown_keys_no_collection(self):
        invalid = [{}, {'destination': 'local'}, arguments(limit=True), arguments(limit=1.0),
            arguments(limit='2'), arguments(limit=0), arguments(limit=51), arguments(include_inactive=0),
            arguments(include_inactive='false'), arguments(agent=None), arguments(cursor=[]),
            arguments(cursor='x' * 64), arguments(destination=['local'])]
        for key in ('preset', 'preset_revision', 'host', 'codex_home', 'codexHome', 'binary', 'device'):
            invalid.append(arguments(**{key: 'PRIVATE'}))
        for args in invalid:
            value = await self.adapter.list_sessions_page(args, measure=conservative_measure)
            self.assertEqual(value['reason'], 'invalid_arguments', args)
            self.assertNotIn('PRIVATE', json.dumps(value))
        self.adapter.collect_sessions_page.assert_not_called()

    async def test_authorization_before_cache_platform_or_collection(self):
        with patch.object(self.adapter.listing_pages, '_expire', side_effect=AssertionError('cache touched')):
            for change in ({'destination': 'denied'}, {'destination': 'missing'}, {'agent': 'claude'}):
                value = await self.page(cursor='f' * 64, **change)
                self.assertEqual(value['reason'], 'policy_denied')
        self.adapter.collect_sessions_page.assert_not_called()

    async def test_platform_pre_effect(self):
        with patch.object(peer, '_listing_pages_supported', return_value=False):
            value = await self.page()
        self.assertEqual(value['reason'], 'platform_unsupported')
        self.adapter.collect_sessions_page.assert_not_called()

    async def test_cursor_tamper_filters_route_revocation_and_restart(self):
        token = (await self.page(limit=1))['nextCursor']
        for changes in ({'cursor': 'f' * 64}, {'limit': 2}, {'include_inactive': True}, {'destination': 'other'}):
            opts = {'limit': 1, 'cursor': token, **changes}
            self.assertEqual((await self.page(**opts))['reason'], 'cursor_unavailable')
        self.adapter.destinations['local']['codexHome'] = '/CHANGED'
        self.assertEqual((await self.page(limit=1, cursor=token))['reason'], 'cursor_unavailable')
        self.adapter.destinations['local']['capabilities'] = []
        self.assertEqual((await self.page(limit=1, cursor=token))['reason'], 'policy_denied')
        restarted = peer.Adapter(policy())
        restarted.collect_sessions_page = AsyncMock()
        self.assertEqual((await restarted.list_sessions_page(arguments(limit=1, cursor=token),
            measure=conservative_measure))['reason'], 'cursor_unavailable')
        restarted.collect_sessions_page.assert_not_called()
        self.adapter.collect_sessions_page.assert_awaited_once()

    async def test_replay_ttl_count_and_memory_bounds(self):
        now = [0]
        self.adapter.listing_pages.clock = lambda: now[0]
        first = await self.page(limit=1)
        token = first['nextCursor']
        second = await self.page(limit=1, cursor=token)
        count = len(self.adapter.listing_pages.cursors)
        self.assertEqual(second, await self.page(limit=1, cursor=token))
        self.assertEqual(len(self.adapter.listing_pages.cursors), count)
        for _ in range(pages.PAGE_CACHE_COUNT):
            await self.page()
        self.assertEqual((await self.page(limit=1, cursor=token))['reason'], 'cursor_unavailable')
        self.assertLessEqual(len(self.adapter.listing_pages.snapshots), pages.PAGE_CACHE_COUNT)
        self.assertLessEqual(self.adapter.listing_pages.charged_bytes, pages.PAGE_CACHE_BYTES)
        now[0] = pages.PAGE_TTL_SECONDS + 1
        self.assertEqual((await self.page(limit=1, cursor=token))['reason'], 'cursor_unavailable')
        self.assertEqual(self.adapter.listing_pages.charged_bytes, 0)
        self.assertFalse(self.adapter.listing_pages.cursors)

    async def test_idle_renewal_completes_1386_rows_in_28_pages(self):
        now = [0]
        self.adapter.listing_pages.clock = lambda: now[0]
        self.adapter.collect_sessions_page.return_value = listing(1386), 0
        ids, cursor, count = [], None, 0
        while True:
            value = await self.page(limit=50, cursor=cursor)
            self.assertTrue(value['complete'])
            count += 1
            ids.extend(row['id'] for row in value['sessions'])
            cursor = value['nextCursor']
            if cursor is None:
                break
            now[0] += 2
        self.assertEqual(count, 28)
        self.assertEqual(ids, ['fixture-%04d' % i for i in range(1386)])
        self.assertEqual(now[0], 54)
        self.adapter.collect_sessions_page.assert_awaited_once()

    async def test_idle_and_absolute_expiry_cannot_be_revived(self):
        now = [0]
        self.adapter.listing_pages.clock = lambda: now[0]
        token = (await self.page())['nextCursor']
        now[0] = 29
        self.assertEqual((await self.page(limit=49, cursor=token))['reason'], 'cursor_unavailable')
        now[0] = 31
        self.assertEqual((await self.page(cursor=token))['reason'], 'cursor_unavailable')
        now[0] = 20
        self.assertEqual((await self.page(cursor=token))['reason'], 'cursor_unavailable')
        now[0] = 0
        token = (await self.page())['nextCursor']
        for timestamp in [*range(29, 600, 29), 599]:
            now[0] = timestamp
            self.assertTrue((await self.page(cursor=token))['ok'])
        now[0] = pages.PAGE_MAX_LIFETIME_SECONDS
        self.assertEqual((await self.page(cursor=token))['reason'], 'cursor_unavailable')
        self.assertEqual(self.adapter.collect_sessions_page.await_count, 2)

    async def test_expiry_during_page_formation_does_not_renew(self):
        now = [0]
        self.adapter.listing_pages.clock = lambda: now[0]
        token = (await self.page())['nextCursor']
        def expires(value):
            now[0] = 31
            return conservative_measure(value)
        value = await self.adapter.list_sessions_page(arguments(cursor=token), measure=expires)
        self.assertEqual(value['reason'], 'cursor_unavailable')
        self.assertFalse(self.adapter.listing_pages.snapshots)
        self.adapter.collect_sessions_page.assert_awaited_once()

    async def test_charged_bytes_and_row_limits(self):
        with patch.object(pages, 'PAGE_CACHE_BYTES', 1000):
            self.assertEqual((await self.page())['reason'], 'snapshot_cache_limit')
        self.assertFalse(self.adapter.listing_pages.snapshots)
        with patch.object(pages, 'PAGE_MAX_ROWS', 999):
            self.assertEqual((await self.page())['reason'], 'collection_row_limit')

    async def test_identity_and_scope_refuse_without_truncating_or_merging(self):
        for update, reason in (({'id': 'x' * (pages.PAGE_ID_BYTES + 1)}, 'identity_unrepresentable'),
                ({'id': 1}, 'identity_unrepresentable'), ({'id': '\ud800'}, 'identity_unrepresentable'),
                ({'agent': 'claude'}, 'collection_scope_mismatch')):
            raw = listing(1)
            raw['sessions'][0].update(update)
            self.adapter.collect_sessions_page.return_value = raw, 0
            self.assertEqual((await self.page())['reason'], reason)
        raw = listing(2)
        raw['sessions'][1]['id'] = raw['sessions'][0]['id']
        self.adapter.collect_sessions_page.return_value = raw, 0
        self.assertEqual((await self.page())['reason'], 'duplicate_identity')

    async def test_later_single_row_encoded_budget_refuses_before_any_page(self):
        raw = listing(100)
        raw['sessions'][-1]['id'] = '\x01' * pages.PAGE_ID_BYTES
        self.adapter.collect_sessions_page.return_value = raw, 0
        self.assertEqual((await self.page(limit=1))['reason'], 'identity_unrepresentable')
        self.assertFalse(self.adapter.listing_pages.snapshots)

    async def test_unknown_evidence_is_incomplete_but_known_advisories_are_not(self):
        for extra in ({'partial': True}, {'discovery': {'codex': {'status': 'ok', 'skipped': 3}}},
                {'discovery': {'codex': {'status': 'ok', 'homes': [{'status': 'ok', 'skipped': 3}]}}}):
            self.adapter.collect_sessions_page.return_value = {**listing(2), **extra}, 0
            value = await self.page(limit=1)
            self.assertTrue(value['ok'])
            self.assertFalse(value['complete'])
            self.assertEqual(len(value['sessions']), 1)
            self.assertIsNotNone(value['nextCursor'])
        raw = {**listing(2), 'schemaVersion': 1, 'command': 'list', 'host': 'PRIVATE',
            'sshHost': 'PRIVATE', 'sshUser': 'PRIVATE', 'sshUserSource': 'explicit', 'sshIdentity': {},
            'version': 'fixture', 'remoteVersion': 'fixture', 'remoteVersionProbe': {'status': 'unknown'},
            'codexHome': 'PRIVATE', 'clientUpdate': {}, 'skillUpdates': []}
        self.adapter.collect_sessions_page.return_value = raw, 0
        value = await self.page()
        self.assertTrue(value['complete'])
        self.assertNotIn('PRIVATE', json.dumps(value))

    async def test_partial_nonzero_unknown_nested_truncation_keep_rows(self):
        changes = [{'ok': False, 'error': 'PRIVATE'}, {'errors': ['PRIVATE']}, {'truncated': True},
            {'truncated': 'true'}, {'error': {}}, {'errors': 'PRIVATE'},
            {'discovery': None}, {'discovery': {}}, {'discovery': {'codex': {'status': []}}},
            {'discovery': {'codex': {'status': {}}}},
            {'discovery': {'codex': {'status': 'ok', 'error': 'PRIVATE'}}},
            {'discovery': {'codex': {'status': 'ok', 'homes': [{'status': 'error', 'error': 'PRIVATE'}]}}},
            {'discovery': {'codex': {'status': 'ok', 'truncated': True}}}]
        for change in changes:
            self.adapter.collect_sessions_page.return_value = {**listing(), **change}, 0
            value = await self.page(limit=1)
            self.assertTrue(value['ok'])
            self.assertFalse(value['complete'])
            self.assertTrue(value['evidence']['incomplete'])
            self.assertEqual(len(value['sessions']), 1)
            self.assertIsNotNone(value['nextCursor'])
            self.assertNotIn('PRIVATE', json.dumps(value))
        self.adapter.collect_sessions_page.return_value = listing(), 1
        value = await self.page()
        self.assertFalse(value['complete'])
        self.assertTrue(value['evidence']['collectionExitNonzero'])
        for status in ('ok', 'not_installed'):
            self.adapter.collect_sessions_page.return_value = {'ok': True, 'sessions': [],
                'discovery': {'codex': {'status': status}}}, 0
            self.assertTrue((await self.page())['complete'])
        self.adapter.collect_sessions_page.return_value = {'ok': False, 'sessions': [],
            'error': 'PRIVATE', 'discovery': {'codex': {'status': 'error', 'error': 'PRIVATE'}}}, 1
        empty_partial = await self.page()
        self.assertTrue(empty_partial['ok'])
        self.assertFalse(empty_partial['complete'])
        self.assertEqual(empty_partial['sessions'], [])
        self.assertIsNone(empty_partial['nextCursor'])
        self.assertTrue(empty_partial['evidence']['incomplete'])

    async def test_malformed_schema_refusal(self):
        for raw in ([], None, {'ok': 1, 'sessions': []}, {'ok': True, 'sessions': {}}, {'sessions': []}):
            self.adapter.collect_sessions_page.return_value = raw, 0
            self.assertEqual((await self.page())['reason'], 'collection_schema_unavailable')

    async def test_nested_home_evidence_malformed_retains_rows_as_incomplete(self):
        homes = [{'status': []}, {'status': {}}, {}, {'status': 'future'},
            {'status': 'ok', 'truncated': 'true'}, {'status': 'ok', 'error': {}},
            {'status': 'ok', 'errors': 'PRIVATE'}, {'status': 'ok', 'errors': ['PRIVATE']},
            {'status': 'ok', 'errors': [{}]}, {'status': 'ok', 'truncated': True}, None]
        for home in homes:
            raw = listing(2)
            raw['discovery']['codex']['homes'] = [home]
            self.adapter.collect_sessions_page.return_value = raw, 0
            value = await self.page(limit=1)
            self.assertTrue(value['ok'])
            self.assertFalse(value['complete'], home)
            self.assertTrue(value['evidence']['incomplete'])
            self.assertEqual(len(value['sessions']), 1)
            self.assertIsNotNone(value['nextCursor'])
            self.assertNotIn('PRIVATE', json.dumps(value))
        for errors in (['PRIVATE'], [{}], [None]):
            raw = listing(2)
            raw['discovery']['codex'].update(homes=[{'status': 'ok'}], errors=errors)
            self.adapter.collect_sessions_page.return_value = raw, 0
            self.assertFalse((await self.page())['complete'])
        for status in ('ok', 'absent'):
            raw = listing(2)
            raw['discovery']['codex']['homes'] = [{'status': status}]
            self.adapter.collect_sessions_page.return_value = raw, 0
            self.assertTrue((await self.page())['complete'])

    async def test_busy_no_queue_policy_change_and_cancel_release(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def pending(*args):
            entered.set()
            await release.wait()
            return listing(), 0
        self.adapter.collect_sessions_page.side_effect = pending
        task = asyncio.create_task(self.page())
        await entered.wait()
        value = await self.page()
        self.assertEqual(value['reason'], 'collection_busy')
        self.assertEqual(self.adapter.collect_sessions_page.await_count, 1)
        self.adapter.destinations['local']['codexHome'] = '/CHANGED'
        release.set()
        self.assertEqual((await task)['reason'], 'policy_changed')
        self.assertFalse(self.adapter.listing_pages.collecting)
        release.clear()
        entered.clear()
        task = asyncio.create_task(self.page())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.adapter.listing_pages.collecting)
        self.adapter.collect_sessions_page.side_effect = None
        self.assertTrue((await self.page())['ok'])

    async def test_exception_redaction_and_admission_release(self):
        for error in (OSError('/PRIVATE'), ValueError('/PRIVATE'), TypeError('/PRIVATE'),
                      RecursionError('/PRIVATE'), RuntimeError('/PRIVATE')):
            self.adapter.collect_sessions_page.side_effect = error
            value = await self.page()
            self.assertEqual(value['reason'], 'collection_unavailable')
            self.assertNotIn('PRIVATE', json.dumps(value))
            self.assertFalse(self.adapter.listing_pages.collecting)


@unittest.skipUnless(os.name == 'posix' and sys.platform in ('darwin', 'linux'), 'POSIX collector')
class Collector(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='codex-page-collector-')
        self.addCleanup(self.folder.cleanup)
        self.marker = Path(self.folder.name) / 'started'
        self.adapter = peer.Adapter(policy())

    async def page(self):
        with patch.object(peer.core, '__file__', str(FIXTURE)):
            return await self.adapter.list_sessions_page(arguments(), measure=conservative_measure)

    async def test_explicit_route_argv_reuses_bounded_collector(self):
        entry = {'host': 'fixture@example.invalid', 'agents': ['codex'],
                 'capabilities': ['list'], 'codexHome': '/PINNED_HOME'}
        bounded = AsyncMock(return_value=(json.dumps(listing(1)).encode(), 0))
        with patch.object(peer, 'invoke_bounded_diagnostic', bounded):
            await self.adapter.collect_sessions_page(entry, 'codex', True)
        argv = bounded.call_args.args[0]
        self.assertEqual(argv[2:], ['list', '--host', 'fixture@example.invalid', '--codex-home',
            '/PINNED_HOME', '--agent', 'codex', '--all', '--json', '--no-update-notice'])
        self.assertEqual(bounded.call_args.kwargs, {'timeout': 10,
            'output_limit': 4 * 1024 * 1024, 'stderr_output_limit': 64 * 1024})

    async def test_actual_local_cli_with_owned_sqlite_and_claude_registry(self):
        # Execute the real standalone list command against owned fixture data.
        # No native Codex executable/model or Claude session/socket is started.
        root = Path(self.folder.name)
        codex_home, claude_home = root / 'codex', root / 'claude'
        codex_home.mkdir()
        (claude_home / 'sessions').mkdir(parents=True)
        with sqlite3.connect(codex_home / 'state_5.sqlite') as connection:
            connection.execute('CREATE TABLE threads(id TEXT,title TEXT,name TEXT,cwd TEXT,updated_at INTEGER,archived INTEGER,rollout_path TEXT)')
            connection.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?)',
                ('owned-saved-thread', 'fallback title', 'native saved name\nsecond line', '/private-fixture', 1, 0, '/private-rollout'))
        (claude_home / 'sessions' / (str(os.getpid()) + '.json')).write_text(json.dumps({
            'pid': os.getpid(), 'name': 'owned-registry-fixture', 'messagingSocketPath': ''}))
        adapter = peer.Adapter({'fixture': {'agents': ['codex', 'claude'], 'capabilities': ['list'],
                                           'codexHome': str(codex_home)}})
        with patch.dict(os.environ, {'CODEX_HOME': str(codex_home), 'CLAUDE_CONFIG_DIR': str(claude_home)}):
            for agent, identifier in (('codex', 'owned-saved-thread'), ('claude', str(os.getpid()))):
                value = await adapter.list_sessions_page({'destination': 'fixture', 'agent': agent,
                    'include_inactive': True}, measure=conservative_measure)
                self.assertTrue(value['ok'], value)
                self.assertTrue(value['complete'], value)
                self.assertEqual([row['id'] for row in value['sessions']], [identifier])
                if agent == 'codex':
                    self.assertEqual(value['sessions'][0]['name'], 'native saved name')
                self.assertNotIn(str(root), json.dumps(value))

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'chmod000 is readable by root')
    async def test_selected_claude_unreadable_record_preserves_incomplete_page(self):
        # The #394 adapter fix projects the existing internal read-failure count
        # into its established error contract while preserving healthy rows.
        home = Path(self.folder.name) / 'claude-unreadable'
        records = home / 'sessions'
        records.mkdir(parents=True)
        healthy = records / (str(os.getpid()) + '.json')
        healthy.write_text(json.dumps({'pid': os.getpid(), 'name': 'owned-healthy', 'messagingSocketPath': ''}))
        unreadable = records / (str(os.getpid() + 1) + '.json')
        unreadable.write_text(json.dumps({'pid': os.getpid() + 1, 'name': 'unreadable-owned'}))
        unreadable.chmod(0)
        adapter = peer.Adapter({'fixture': {'agents': ['claude'], 'capabilities': ['list']}})
        try:
            with self.assertRaises(PermissionError):
                unreadable.read_bytes()
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(home)}):
                records_result = peer.core.discover(include_unreachable=True)
                self.assertEqual(records_result.permission_failures, 1)
                self.assertEqual(records_result.errors, [])
                raw, code = await adapter.collect_sessions_page(adapter.destinations['fixture'], 'claude', True)
                value = await adapter.list_sessions_page({'destination': 'fixture', 'agent': 'claude',
                    'include_inactive': True}, measure=conservative_measure)
            self.assertEqual(code, 1)
            self.assertFalse(raw['ok'])
            self.assertEqual(raw['discovery']['claude']['status'], 'error')
            self.assertIn('session_record_unavailable', raw['discovery']['claude']['error'])
            self.assertEqual([row['pid'] for row in raw['sessions']], [os.getpid()])
            self.assertTrue(value['ok'])
            self.assertFalse(value['complete'])
            self.assertTrue(value['evidence']['incomplete'])
            self.assertTrue(value['evidence']['collectionExitNonzero'])
            self.assertEqual([row['id'] for row in value['sessions']], [str(os.getpid())])
            self.assertNotIn(str(home), json.dumps(value))
        finally:
            unreadable.chmod(0o600)

    async def test_real_synthetic_nonzero_and_output_limits(self):
        for mode, expected in (('nonzero', None), ('stdout', 'collection_output_limit'),
                               ('stderr', 'collection_output_limit'), ('invalid', 'collection_unavailable')):
            with patch.dict(os.environ, {'SESSION_PEER_PAGE_FIXTURE': mode}):
                value = await self.page()
            if expected:
                self.assertEqual(value['reason'], expected)
            else:
                self.assertTrue(value['ok'])
                self.assertFalse(value['complete'])
                self.assertTrue(value['evidence']['collectionExitNonzero'])
            self.assertFalse(self.adapter.listing_pages.collecting)

    async def test_timeout_reaps_child_and_releases_admission(self):
        with patch.dict(os.environ, {'SESSION_PEER_PAGE_FIXTURE': 'sleep',
                'SESSION_PEER_PAGE_MARKER': str(self.marker)}), patch.object(peer, 'PAGE_COLLECTION_SECONDS', .1):
            before = time.monotonic()
            value = await self.page()
        self.assertEqual(value['reason'], 'collection_timeout')
        self.assertLess(time.monotonic() - before, 3)
        self.assertFalse(self.adapter.listing_pages.collecting)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(self.marker.read_text().strip()), 0)

    async def test_cancellation_cleans_readers_and_owned_descendant(self):
        with patch.dict(os.environ, {'SESSION_PEER_PAGE_FIXTURE': 'descendant',
                'SESSION_PEER_PAGE_MARKER': str(self.marker)}):
            task = asyncio.create_task(self.page())
            deadline = time.monotonic() + 3
            child_marker = Path(str(self.marker) + '.child')
            while not child_marker.exists() and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            self.assertTrue(child_marker.exists())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(self.adapter.listing_pages.collecting)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(self.marker.read_text().strip()), 0)
        probe = await asyncio.create_subprocess_exec('ps', '-o', 'stat=', '-p', child_marker.read_text(),
            stdout=asyncio.subprocess.PIPE)
        out, _ = await probe.communicate()
        self.assertTrue(not out.strip() or out.strip().startswith(b'Z'), out)
        active = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()
                  and not task.done() and '_read_diagnostic_pipe' in repr(task.get_coro())]
        self.assertFalse(active)

    async def test_spawn_io_cleanup_failure_sanitized(self):
        for error in (OSError('/PRIVATE_SPAWN'), ValueError('/PRIVATE_IO')):
            with patch.object(peer, 'invoke_bounded_diagnostic', side_effect=error):
                value = await self.page()
            self.assertEqual(value['reason'], 'collection_unavailable')
            self.assertNotIn('PRIVATE', json.dumps(value))
            self.assertFalse(self.adapter.listing_pages.collecting)
        original = peer.core.stop_codex_wake
        def cleanup(process, grace):
            original(process, grace)
            raise OSError('/PRIVATE_CLEANUP')
        with patch.object(peer.core, 'stop_codex_wake', side_effect=cleanup):
            value = await self.page()
        self.assertEqual(value['reason'], 'collection_unavailable')
        self.assertFalse(self.adapter.listing_pages.collecting)


class SupportedPlatforms(unittest.TestCase):
    def test_actual_predicate_matrix_without_mutating_global_os_name(self):
        for name, platform, expected in (('posix', 'darwin', True), ('posix', 'linux', True),
                ('nt', 'win32', False), ('nt', 'linux', False), ('posix', 'win32', False),
                ('posix', 'freebsd', False)):
            with patch.object(peer, 'os', SimpleNamespace(name=name)), \
                    patch.object(peer, 'sys', SimpleNamespace(platform=platform)):
                self.assertIs(peer._listing_pages_supported(), expected)


@unittest.skipUnless(os.name == 'posix' and sys.platform in ('darwin', 'linux'), 'POSIX page collection')
@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK not installed')
class Wire(unittest.IsolatedAsyncioTestCase):
    async def test_all_six_legacy_dispatch_results_byte_equivalent(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        results = []
        for flags in ([], ['--legacy-baseline']):
            params = StdioServerParameters(command=sys.executable,
                args=[str(FIXTURE), '--fixture-server', *flags],
                env={**os.environ, 'SESSION_PEER_PAGE_FIXTURE': 'normal'})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    batch = []
                    for name, args in (('list_destinations', {}), ('list_sessions', arguments()),
                        ('list_presets', {'destination': 'local'}),
                        ('diagnose_destination', {'destination': 'local'}),
                        ('preflight_send', {'destination': 'local', 'target': 'codex:fixture', 'message': 'fixture'}),
                        ('send_message', {'destination': 'local', 'target': 'codex:fixture', 'message': 'fixture'})):
                        result = await client.call_tool(name, args)
                        batch.append(result.model_dump_json(by_alias=True))
                    results.append(batch)
        self.assertEqual(results[0], results[1])

    async def test_stdio_pages_bounds_types_unknown_args_and_legacy(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from tests.mcp_integration.sdk_wire import wire_field
        for mode in ('normal', 'huge', 'partial'):
            with tempfile.TemporaryDirectory(prefix='codex-page-wire-') as folder:
                marker = Path(folder) / 'starts'
                env = {**os.environ, 'SESSION_PEER_PAGE_FIXTURE': mode, 'SESSION_PEER_PAGE_MARKER': str(marker)}
                params = StdioServerParameters(command=sys.executable, args=[str(FIXTURE), '--fixture-server'], env=env)
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        tools = (await client.list_tools()).tools
                        tool = next(t for t in tools if t.name == 'list_sessions_page')
                        schema = wire_field(tool, 'inputSchema')
                        self.assertEqual(set(schema['required']), {'destination', 'agent'})
                        self.assertIs(schema['additionalProperties'], False)
                        self.assertEqual(schema['properties']['limit']['minimum'], 1)
                        self.assertEqual(schema['properties']['limit']['maximum'], 50)
                        self.assertEqual(schema['properties']['destination']['minLength'], 1)
                        self.assertEqual(schema['properties']['destination']['maxLength'], 128)
                        self.assertIn('64', json.dumps(schema['properties']['cursor']))
                        self.assertFalse(wire_field(tool, 'annotations')['readOnlyHint'])
                        bad = [arguments(limit=True), arguments(include_inactive=1), arguments(limit='2'),
                               arguments(include_inactive='false'), arguments(limit=1.0), {},
                               arguments(host='/PRIVATE'), arguments(codexHome='/PRIVATE'),
                               arguments(preset='/PRIVATE'), arguments(device='/PRIVATE')]
                        for args in bad:
                            response = await client.call_tool('list_sessions_page', args)
                            value = wire_field(response, 'structuredContent')
                            self.assertTrue(wire_field(response, 'isError'))
                            self.assertEqual(value['reason'], 'invalid_arguments')
                            self.assertNotIn('PRIVATE', json.dumps(value))
                        self.assertFalse(marker.exists(), 'invalid arguments spawned discovery')
                        legacy = await client.call_tool('list_sessions', {'destination': 'local', 'agent': 'codex'})
                        legacy_bytes = legacy.model_dump_json(by_alias=True)
                        ids, cursor = [], None
                        while True:
                            response = await client.call_tool('list_sessions_page', arguments(cursor=cursor))
                            value = wire_field(response, 'structuredContent')
                            self.assertFalse(wire_field(response, 'isError'))
                            self.assertLessEqual(len(response.model_dump_json(by_alias=True).encode()), pages.PAGE_OUTPUT_BYTES)
                            self.assertEqual(value, json.loads(response.content[0].text))
                            self.assertEqual(value['complete'], mode != 'partial')
                            self.assertNotIn('PRIVATE', json.dumps(value))
                            ids.extend(row['id'] for row in value['sessions'])
                            cursor = value['nextCursor']
                            if not cursor:
                                break
                        expected = ([str(i) + '🪼' * 1900 for i in range(50)] if mode == 'huge'
                                    else ['fixture-%04d' % i for i in range(1000)])
                        self.assertEqual(ids, expected)
                        self.assertEqual(len(set(ids)), len(ids))
                        self.assertEqual(len(marker.read_text().splitlines()), 2)  # legacy + page1 only
                        again = await client.call_tool('list_sessions', {'destination': 'local', 'agent': 'codex'})
                        self.assertEqual(again.model_dump_json(by_alias=True), legacy_bytes)
                        if mode == 'normal':
                            claude = await client.call_tool('list_sessions_page', arguments(agent='claude'))
                            source = wire_field(claude, 'structuredContent')
                            self.assertTrue(source['complete'])
                            self.assertEqual([row['id'] for row in source['sessions']], [str(i) for i in range(1000, 1050)])


@unittest.skipUnless(os.name == 'nt', 'actual Windows refusal path')
class ActualWindowsPlatform(unittest.IsolatedAsyncioTestCase):
    async def test_real_windows_refuses_before_collection_without_platform_patch(self):
        adapter = peer.Adapter(policy())
        adapter.collect_sessions_page = AsyncMock(side_effect=AssertionError('unexpected collection'))
        value = await adapter.list_sessions_page(arguments(), measure=conservative_measure)
        self.assertEqual(value['reason'], 'platform_unsupported')
        self.assertFalse(value['ok'])
        adapter.collect_sessions_page.assert_not_called()
        self.assertEqual(adapter.listing_pages.snapshots, {})


if __name__ == '__main__':
    unittest.main()
