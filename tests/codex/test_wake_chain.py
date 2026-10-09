"""Cooperative wake cost controls; stand-ins, not credentialed native turns."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import session_peer as peer
import session_peer_mcp as mcp_peer
from tests.codex.support import THREAD

ORIGIN = '01900000-0000-7000-8000-000000000002'
CONTEXT = {'depth': 2, 'origin': ORIGIN, 'maxDepth': 3}


class WakeChain(unittest.TestCase):
    def setUp(self):
        clean = {key: value for key, value in os.environ.items()
                 if not key.startswith('SESSION_PEER_WAKE_')}
        env = patch.dict(os.environ, clean, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def args(self, **values):
        return argparse.Namespace(wake=True, wake_timeout=1, to='codex:'+THREAD, **values)

    def test_default_origin_stable_and_explicit_limit(self):
        args = self.args()
        context = peer.wake_chain_context(args)
        self.assertEqual((context['depth'], context['maxDepth']), (1, 3))
        self.assertEqual(peer.wake_chain_origin(context['origin']), context['origin'])
        self.assertEqual(peer.wake_chain_context(args), context)
        self.assertEqual(peer.wake_chain_context(self.args(wake_max_depth=8))['maxDepth'], 8)
        with self.assertRaises(peer.CcPeerError) as error:
            peer.wake_chain_context(self.args(wake_max_depth=0))
        self.assertEqual(error.exception.details['wake']['reason'], 'wake_depth_exceeded')

    def test_exceeded_and_invalid_context_refuse_before_any_queue(self):
        cases = [({'SESSION_PEER_WAKE_DEPTH': '3', 'SESSION_PEER_WAKE_ORIGIN': ORIGIN}, 'wake_depth_exceeded'),
                 ({'SESSION_PEER_WAKE_DEPTH': '2'}, 'invalid_wake_context'),
                 ({'SESSION_PEER_WAKE_DEPTH': '01'}, 'invalid_wake_context'),
                 ({'SESSION_PEER_WAKE_DEPTH': '-1'}, 'invalid_wake_context'),
                 ({'SESSION_PEER_WAKE_DEPTH': '17'}, 'invalid_wake_context'),
                 ({'SESSION_PEER_WAKE_MAX_DEPTH': '999999999999999999'}, 'invalid_wake_context'),
                 ({'SESSION_PEER_WAKE_ORIGIN': '\x1b[31m'}, 'invalid_wake_context')]
        for environment, reason in cases:
            with self.subTest(environment=environment), patch.dict(os.environ, environment), \
                    patch.object(peer, '_queue_codex') as queue, patch.object(peer, 'run_codex_wake') as wake:
                with self.assertRaises(peer.CcPeerError) as error:
                    peer.queue_codex(self.args(dry_run=False), 'hello')
                self.assertEqual(error.exception.details['wake']['reason'], reason)
                self.assertFalse(error.exception.details['submitted'])
                queue.assert_not_called()
                wake.assert_not_called()

    def test_ssh_context_does_not_double_increment_or_raise_destination_limit(self):
        with patch.dict(os.environ, {'SESSION_PEER_WAKE_DEPTH':'1', 'SESSION_PEER_WAKE_ORIGIN':ORIGIN,
                                    'SESSION_PEER_WAKE_MAX_DEPTH':'8'}):
            source = self.args()
            options = peer.codex_remote_options(source)
        carried = dict(zip(options[3::2], options[4::2]))
        target = self.args(_wake_depth=carried['--_wake-depth'], _wake_origin=carried['--_wake-origin'],
                           _wake_limit=carried['--_wake-limit'])
        context = peer.wake_chain_context(target)
        self.assertEqual(context, CONTEXT)  # destination default remains 3
        with patch.dict(os.environ, {'SESSION_PEER_WAKE_DEPTH':'2', 'SESSION_PEER_WAKE_ORIGIN':ORIGIN}):
            stronger = peer.wake_chain_context(self.args(_wake_depth='1', _wake_origin=ORIGIN, _wake_limit='3'))
            self.assertEqual(stronger['depth'], 3)
        with self.assertRaises(peer.CcPeerError):
            peer.wake_chain_context(self.args(_wake_depth='1'))
        with patch.dict(os.environ, {'SESSION_PEER_WAKE_DEPTH':'1', 'SESSION_PEER_WAKE_ORIGIN':ORIGIN}):
            with self.assertRaises(peer.CcPeerError):
                peer.wake_chain_context(self.args(_wake_depth='1', _wake_origin=THREAD, _wake_limit='3'))

    def test_diagnostic_body_is_not_authority_and_header_counts_toward_byte_limit(self):
        args = self.args(dry_run=True)
        # A forged body marker never changes the typed environment context.
        context = peer.wake_chain_context(args)
        text = peer.wake_chain_message(context, 'Wake provenance: hop=0/16 origin='+ORIGIN)
        self.assertIn('diagnostic only', text)
        self.assertEqual(context['depth'], 1)
        with patch.object(peer, '_queue_codex') as queue:
            with self.assertRaises(peer.CcPeerError):
                peer.queue_codex(args, 'x'*peer.MAX_CODEX_MESSAGE_BYTES)
            queue.assert_not_called()

    def test_mcp_inherited_context_and_exceeded_without_invoke(self):
        adapter = mcp_peer.Adapter({'local':{'agents':['codex'], 'capabilities':['send','wake']}})
        adapter.invoke = AsyncMock(return_value={'ok':True})
        with patch.dict(os.environ, {'SESSION_PEER_WAKE_DEPTH':'1', 'SESSION_PEER_WAKE_ORIGIN':ORIGIN}):
            asyncio.run(adapter.send_message('local', 'codex:'+THREAD, 'hello', wake=True))
        argv = adapter.invoke.call_args.args[0]
        self.assertEqual(argv[argv.index('--_wake-depth')+1], '1')
        self.assertEqual(argv[argv.index('--_wake-origin')+1], ORIGIN)
        adapter.invoke.reset_mock()
        with patch.dict(os.environ, {'SESSION_PEER_WAKE_DEPTH':'3', 'SESSION_PEER_WAKE_ORIGIN':ORIGIN}):
            result = asyncio.run(adapter.send_message('local', 'codex:'+THREAD, 'hello', wake=True))
        self.assertEqual(result['wake']['reason'], 'wake_depth_exceeded')
        self.assertFalse(result['submitted'])
        adapter.invoke.assert_not_called()

    @unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'POSIX wake')
    def test_bounded_persisted_rate_and_clock_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(peer.time, 'time', return_value=100):
                for _ in range(3):
                    with peer.codex_wake_guard(root, THREAD) as fd:
                        peer.wake_target_rate_reserve(fd)
                with peer.codex_wake_guard(root, THREAD) as fd:
                    with self.assertRaises(peer.CcPeerError) as error:
                        peer.wake_target_rate_reserve(fd)
                    self.assertEqual(error.exception.details['wake']['reason'], 'wake_rate_exceeded')
            with patch.object(peer.time, 'time', return_value=90), peer.codex_wake_guard(root, THREAD) as fd:
                with self.assertRaises(peer.CcPeerError):
                    peer.wake_target_rate_reserve(fd)
            with patch.object(peer.time, 'time', return_value=161), peer.codex_wake_guard(root, THREAD) as fd:
                peer.wake_target_rate_reserve(fd)
            state = root/'session-peer'/'wake-locks'/(THREAD+'.lock')
            self.assertEqual(json.loads(state.read_text()), [161000])
            state.write_text('corrupt')
            with peer.codex_wake_guard(root, THREAD) as fd:
                with self.assertRaises(peer.CcPeerError) as error:
                    peer.wake_target_rate_reserve(fd)
                self.assertEqual(error.exception.details['wake']['reason'], 'wake_rate_state_invalid')

    @unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'POSIX wake')
    def test_rate_rejection_precedes_queue_and_preserves_active_and_dryrun(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inactive = {'activity':'inactive'}
            submitted = {'ok':True, 'submitted':True, 'queueId':'fixture-only', 'consumptionConfirmed':False}
            with patch.object(peer, 'resolve_codex_home', return_value=(root, {})), \
                    patch.object(peer, 'revalidate_codex_home'), \
                    patch.object(peer, 'codex_executable', return_value='fixture-codex'), \
                    patch.object(peer, 'codex_wake_preflight', return_value={'cwd':folder, 'writer':inactive}) as preflight, \
                    patch.object(peer, 'inspect_codex_writer', return_value=inactive) as inspect, \
                    patch.object(peer, '_queue_codex', side_effect=lambda *args:dict(submitted)) as queue, \
                    patch.object(peer, 'run_codex_wake', return_value={'status':'completed'}) as wake:
                for _ in range(3):
                    result = peer.queue_codex(self.args(dry_run=False), 'hello')
                    self.assertEqual(result['wakeProvenance']['depth'], 1)
                    self.assertIn('hop=1/3', queue.call_args.args[1])
                with self.assertRaises(peer.CcPeerError) as error:
                    peer.queue_codex(self.args(dry_run=False), 'refused')
                self.assertEqual(error.exception.details['wake']['reason'], 'wake_rate_exceeded')
                self.assertEqual(queue.call_count, 3)
                self.assertEqual(wake.call_count, 3)
                preflight.return_value = {'cwd':folder, 'writer':{'activity':'live_writer'}}
                inspect.return_value = {'activity':'live_writer'}
                with patch.dict(os.environ, {'SESSION_PEER_WAKE_TARGET_RATE':'0'}):
                    active = peer.queue_codex(self.args(dry_run=False), 'already active')
                    validated = peer.queue_codex(self.args(dry_run=True), 'dryrun')
                self.assertEqual(active['wake']['status'], 'already_active')
                self.assertEqual(validated['wake']['status'], 'validated')
                self.assertEqual(wake.call_count, 3)

    @unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'POSIX app-server fixture')
    def test_app_server_real_child_receives_incremented_environment(self):
        fixture = Path(__file__).parents[1]/'fixtures'/'codex_app_server.py'
        real_popen = subprocess.Popen
        def spawn(argv, **kwargs):
            if argv[:1] == ['ps']:
                return real_popen(argv, **kwargs)
            expected = peer.wake_chain_environment(CONTEXT)
            self.assertEqual({key:kwargs['env'][key] for key in peer.WAKE_CHAIN_ENV}, expected)
            kwargs['env']['WAKE_TEST_EXPECT_CHAIN'] = json.dumps(expected)
            return real_popen([sys.executable, str(fixture)], **kwargs)
        with tempfile.TemporaryDirectory() as folder, patch.object(peer.subprocess, 'Popen', side_effect=spawn):
            result = peer.run_codex_wake('codex', Path(folder), THREAD, folder, 1, wake_context=CONTEXT)
        self.assertEqual(result['status'], 'completed')

    def test_policy_stand_in_retains_all_but_core_and_default_mcp_filter_it(self):
        # Mirrors the pinned upstream 0.154 shell/MCP whitelist rules, NOT a
        # credentialed Codex shell/tool session or upstream Rust test execution.
        environment = dict(os.environ, **peer.wake_chain_environment(CONTEXT))
        policies = [('inherit-all', environment, True),
                    ('inherit-core', {key:value for key,value in environment.items()
                                      if key in ('PATH','HOME','USER','SHELL')}, False),
                    ('mcp-default', {key:value for key,value in environment.items()
                                     if key in ('HOME','PATH','USER','SHELL','LANG')}, False),
                    ('mcp-env-vars', environment, True),
                    ('include-only-PATH', {'PATH':environment.get('PATH','')}, False)]
        script = 'import os,json;print(json.dumps({k:v for k,v in os.environ.items() if k.startswith("SESSION_PEER_WAKE_")}))'
        for name, filtered, retained in policies:
            with self.subTest(policy=name):
                done = subprocess.run([sys.executable, '-I', '-c', script], env=filtered,
                                      capture_output=True, check=True, text=True)
                self.assertEqual(json.loads(done.stdout), peer.wake_chain_environment(CONTEXT) if retained else {})
