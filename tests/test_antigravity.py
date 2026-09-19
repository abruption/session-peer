"""Opt-in bridge protocol and adapter regressions; no model calls."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

import session_peer as p

THREAD = '3e92e583-6749-44ee-9339-7ac7d9c229d5'
GEN = '14177079-4d64-4256-a4b4-37bb1e87e0e9'
INFO = {'id': THREAD, 'generation': GEN, 'ownerPid': 12, 'ownerStart': 'born',
        'antigravityHome': '/fixture', '_key': 'a' * 32}


class Protocol(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(p, 'agy_owner_live', return_value=True)
        patch.start(); self.addCleanup(patch.stop)
        self.bridge = p.AgyBridge(INFO, Path('/fixture/bin/agentapi'), 2)

    def req(self, **changes):
        return {'op': 'send', 'generation': GEN, 'target': THREAD,
                'requestId': str(uuid.uuid4()), 'text': 'hello\n한국어', **changes}

    def test_submission_dedup_and_conflict(self):
        req = self.req()
        with mock.patch.object(p.subprocess, 'run', return_value=argparse.Namespace(returncode=0)) as run:
            result = self.bridge.handle(req)
            self.assertEqual(result['status'], 'submitted')
            self.assertFalse(result['consumptionConfirmed'])
            self.assertTrue(self.bridge.handle(req)['duplicateSuppressed'])
            with self.assertRaisesRegex(p.AdapterError, 'request_id_conflict'):
                self.bridge.handle({**req, 'text': 'changed'})
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], [
                str(Path('/fixture/bin/agentapi')), 'send-message', '--title=session-peer', THREAD, req['text']])
            self.assertEqual(run.call_args.args[0][-1], req['text'])
            self.assertEqual(run.call_args.kwargs['stdout'], subprocess.DEVNULL)

    def test_timeout_and_nonzero_remain_unknown_without_retry(self):
        for outcome in (subprocess.TimeoutExpired('api', 15), argparse.Namespace(returncode=1)):
            bridge = p.AgyBridge(INFO, Path('/api'), 2); req = self.req()
            with mock.patch.object(p.subprocess, 'run', side_effect=outcome if isinstance(outcome, Exception) else None,
                                   return_value=outcome) as run:
                result = bridge.handle(req)
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(result['retryAllowed'])
                bridge.handle(req)
                self.assertEqual(run.call_count, 1)

    def test_invalid_requests_do_not_invoke_native(self):
        with mock.patch.object(p.subprocess, 'run') as run:
            for req in (self.req(generation=str(uuid.uuid4())), self.req(target=str(uuid.uuid4())),
                        self.req(text=''), self.req(text='x'*32769), self.req(text='a\0b'),
                        self.req(requestId='../escape'), self.req(extra=True)):
                with self.subTest(req=list(req)), self.assertRaises(p.AdapterError):
                    self.bridge.handle(req)
            run.assert_not_called()

    def test_owner_death_and_request_limit(self):
        with mock.patch.object(p, 'agy_owner_live', return_value=False):
            with self.assertRaisesRegex(p.AdapterError, 'owner_not_live'):
                self.bridge.handle(self.req())
        with mock.patch.object(p.subprocess, 'run', return_value=argparse.Namespace(returncode=0)):
            self.bridge.handle(self.req()); self.bridge.handle(self.req())
            with self.assertRaisesRegex(p.AdapterError, 'request_limit'):
                self.bridge.handle(self.req())

    def test_fragmented_utf8_frame(self):
        a,b=socket.socketpair();self.addCleanup(a.close);self.addCleanup(b.close)
        data=json.dumps({'text':'안녕'},ensure_ascii=False).encode()+b'\n'
        def write():
            for ch in data:b.sendall(bytes([ch]))
        t=threading.Thread(target=write);t.start()
        self.assertEqual(p.agy_read_frame(a),{'text':'안녕'});t.join()

    def test_frame_size_invalid_and_incomplete(self):
        for data in (b'[]\n',b'bad\n',b'{}\ntrailing',b'{'):
            with contextlib.ExitStack() as stack:
                a,b=socket.socketpair();stack.callback(a.close);stack.callback(b.close)
                b.sendall(data);b.shutdown(socket.SHUT_WR)
                with self.assertRaises(p.AdapterError):p.agy_read_frame(a)
        a,b=socket.socketpair();self.addCleanup(a.close);self.addCleanup(b.close)
        t=threading.Thread(target=lambda:b.sendall(b'x'*(p.AGY_FRAME_BYTES+1)))
        t.start()
        with self.assertRaisesRegex(p.AdapterError,'frame_too_large'):p.agy_read_frame(a)
        t.join(timeout=2)
        self.assertFalse(t.is_alive())


class Adapter(unittest.TestCase):
    def setUp(self):
        self.args=p.build_parser().parse_args(['send','--to','antigravity:'+THREAD,'--no-from','--no-reply-to','-m','hello'])
        self.adapter=p.AntigravityAdapter();self.ctx=p.ExecutionContext('local',self.args)

    def test_missing_ambiguous_and_stale_registration(self):
        for rows,code in (([],'not_registered'),([INFO,INFO],'ambiguous_home')):
            with mock.patch.object(p,'agy_registrations',return_value=rows),self.assertRaisesRegex(p.AdapterError,code):
                self.adapter.submit(self.ctx,'hi')
        self.args.antigravity_generation=str(uuid.uuid4())
        with mock.patch.object(p,'agy_registrations',return_value=[INFO]),self.assertRaisesRegex(p.AdapterError,'stale_generation'):
            self.adapter.submit(self.ctx,'hi')

    def test_dry_run_and_connection_loss(self):
        with mock.patch.object(p,'agy_registrations',return_value=[INFO]),mock.patch.object(p,'agy_rpc',side_effect=OSError) as rpc:
            self.args.dry_run=True
            self.assertEqual(self.adapter.submit(self.ctx,'hi')['status'],'dry_run');rpc.assert_not_called()
            self.args.dry_run=False
            result=self.adapter.submit(self.ctx,'hi');self.assertEqual(result['status'],'unknown')
            self.assertFalse(result['retryAllowed']);self.assertEqual(rpc.call_count,1)

    def test_explicit_id_requires_pinned_generation_and_wake_refused(self):
        self.args.request_id=str(uuid.uuid4())
        with self.assertRaisesRegex(p.AdapterError,'request_id_requires_generation'):self.adapter.validate_send(self.args)
        self.args.antigravity_generation=GEN;self.adapter.validate_send(self.args)
        self.args.wake=True
        with self.assertRaises(p.CcPeerError):self.adapter.validate_send(self.args)

    def test_remote_options_and_reply_uri(self):
        self.args.antigravity_home='/path with spaces';self.args.antigravity_generation=GEN;self.args.request_id=str(uuid.uuid4())
        options=self.adapter.remote_options(self.args)
        self.assertEqual(options[:2],['--antigravity-home','/path with spaces'])
        uri=p.reply_address({'agent':'antigravity','id':THREAD},local=True)
        self.assertEqual(p.parse_reply_address(uri)['target'],'antigravity:'+THREAD)

    @unittest.skipUnless(os.name == "posix", "Unix ownership")
    def test_pid_reuse_fails_closed(self):
        with mock.patch.object(p,'agy_process',return_value={'pid':12,'uid':os.getuid(),'comm':'agy','start':'different'}),mock.patch.object(p,'agy_has_presence') as presence:
            self.assertFalse(p.agy_owner_live(INFO));presence.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "Unix ownership")
    def test_unsafe_runtime_permissions_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);file=root/'x';file.write_text('');file.chmod(0o644)
            with self.assertRaises(p.AdapterError):p.agy_private(file)
            file.chmod(0o600);p.agy_private(file)
            link=root/'link';link.symlink_to(file)
            with self.assertRaises(p.AdapterError):p.agy_private(link)

    def test_unregistered_list_and_doctor_are_optional(self):
        with mock.patch.object(p,'agy_registrations',return_value=[]):
            self.assertEqual(self.adapter.list(self.ctx)['sessions'],[])
            self.assertEqual(self.adapter.diagnose(self.ctx)['status'],'disabled')

    def test_process_start_identity_uses_stable_locale(self):
        completed = argparse.Namespace(returncode=0, stdout='Sat Sep 19 12:00:00 2026\n')
        with mock.patch.object(p.subprocess, 'run', return_value=completed) as run:
            self.assertEqual(p._process_start_time(12), 'Sat Sep 19 12:00:00 2026')
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')


@unittest.skipUnless(os.name=='posix','Unix bridge')
class Lifecycle(unittest.TestCase):
    def test_real_socket_signal_cleanup_and_stale_restart(self):
        with tempfile.TemporaryDirectory(prefix='sp85-', dir='/tmp') as d:
            root=Path(d);home=root/'home';runtime=root/'run';runtime.mkdir(mode=0o700)
            (home/'bin').mkdir(parents=True);api=home/'bin/agentapi'
            api.write_text('#!/bin/sh\nexit 0\n');api.chmod(0o700)
            script='''import argparse, pathlib, session_peer as p
p.agy_root=lambda create=False:pathlib.Path(RUNTIME)
p.agy_owner=lambda home,thread:{'pid':123,'start':'fixture'}
p.agy_owner_live=lambda info:True
p.cmd_agy_bridge(argparse.Namespace(action='serve',thread=THREAD,antigravity_home=HOME,ttl=20,max_requests=3))
'''.replace('RUNTIME',repr(str(runtime))).replace('THREAD',repr(THREAD)).replace('HOME',repr(str(home)))
            for i in range(2):
                proc=subprocess.Popen([sys.executable,'-u','-c',script],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=Path(p.__file__).parent)
                try:
                    import selectors
                    sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
                    self.assertTrue(sel.select(5));sel.close()
                    ready=json.loads(proc.stdout.readline());self.assertTrue(ready['ready'])
                    regpath=next(runtime.glob('*.json'));info=json.loads(regpath.read_text());info['_key']=regpath.stem
                    with mock.patch.object(p,'agy_root',return_value=runtime):
                        self.assertTrue(p.agy_rpc(info,{'op':'status','generation':info['generation']})['ready'])
                        req={'op':'send','generation':info['generation'],'target':THREAD,'requestId':str(uuid.uuid4()),'text':'fixture'}
                        self.assertEqual(p.agy_rpc(info,req)['status'],'submitted')
                    proc.send_signal(signal.SIGTERM);self.assertEqual(proc.wait(timeout=5),0)
                    self.assertFalse(list(runtime.glob('*.sock')));self.assertFalse(list(runtime.glob('*.json')))
                    # Simulate residue from an uncatchable termination.
                    sock=runtime/(info['_key']+'.sock');sock.touch();regpath.write_text('{}')
                finally:
                    if proc.poll() is None:proc.kill();proc.wait()
                    proc.stdout.close();proc.stderr.close()

class IntegrationContracts(unittest.TestCase):
    def test_remote_unknown_and_refusal_keep_structured_evidence(self):
        for status in ('unknown', 'refused'):
            result={'schemaVersion':1,'command':'send','agent':'antigravity','ok':False,
                    'status':status,'requestId':str(uuid.uuid4()),'retryAllowed':False,
                    'reason':'native_outcome_unknown'}
            with mock.patch.object(p,'ssh_user_metadata',return_value={}),mock.patch.object(p.subprocess,'run',return_value=argparse.Namespace(returncode=1,stdout=json.dumps(result),stderr='')):
                self.assertEqual(p.run_remote('host',['send','--to','antigravity:'+THREAD],[]),result)

    def test_sender_requires_unique_registered_ancestor(self):
        with mock.patch.object(p,'agy_registrations',return_value=[INFO]),mock.patch.object(p.os,'getppid',return_value=12):
            self.assertEqual(p.agy_sender()['target'],'antigravity:'+THREAD)
        with mock.patch.object(p,'agy_registrations',return_value=[INFO,INFO]),mock.patch.object(p.os,'getppid',return_value=12):
            self.assertIsNone(p.agy_sender())

    def test_mcp_does_not_discover_unapproved_third_agent(self):
        import asyncio
        import session_peer_mcp as m
        adapter=m.Adapter({'local':{'agents':['claude','codex'],'capabilities':['list'],'codexHome':'/fixture'}})
        adapter.invoke=mock.AsyncMock(side_effect=[{'ok':True,'sessions':[{'agent':'claude'}],'discovery':{'claude':{'status':'ok'}}},{'ok':True,'sessions':[{'agent':'codex'}],'discovery':{'codex':{'status':'ok'}}}])
        result=asyncio.run(adapter.list_sessions())
        self.assertEqual([x['agent'] for x in result['sessions']],['claude','codex'])
        self.assertEqual([call.args[0][-1] for call in adapter.invoke.call_args_list],['claude','codex'])
        with self.assertRaises(m.PolicyError):asyncio.run(adapter.send_message('local','antigravity:'+THREAD,'hi'))
