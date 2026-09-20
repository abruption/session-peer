"""Wake lifecycle, queue preservation and native process cleanup tests."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import session_peer as peer
from tests.test_codex import THREAD


@unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'POSIX wake')
class Wake(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.rollout = self.root / 'rollout.jsonl'
        self.rollout.write_text('initialized\n')
        with contextlib.closing(sqlite3.connect(self.root / 'state_5.sqlite')) as conn:
            conn.execute('CREATE TABLE threads (id TEXT, cwd TEXT, archived INTEGER, rollout_path TEXT)')
            conn.execute('INSERT INTO threads VALUES (?,?,?,?)', (THREAD, str(self.root), 0, str(self.rollout)))
            conn.commit()
        patcher = mock.patch.object(peer, "codex_executable", return_value="codex")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.args = argparse.Namespace(to='codex:'+THREAD, codex_home=str(self.root), codex_bin='codex',
                                       wake=True, wake_timeout=1, dry_run=False)
        self.submitted = {'ok': True, 'submitted':True, 'queueId':'queue-test', 'codexHome':str(self.root),
                          'consumptionConfirmed':False, 'status':'queued'}

    def preflight(self):
        with mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'codex-cli 0.154.0\n','')):
            return peer.codex_wake_preflight(self.root, THREAD, 'codex')

    def test_original_cwd_and_stale_lock_are_accepted(self):
        directory = self.root / 'thread-writer-locks'
        directory.mkdir()
        (directory / (THREAD+'.lock')).touch()
        self.assertEqual(self.preflight()['cwd'], str(self.root))
        self.assertEqual(self.preflight()['writer']['activity'], 'inactive')

    def test_archived_uninitialized_missing_and_unknown_refused(self):
        with contextlib.closing(sqlite3.connect(self.root/'state_5.sqlite')) as conn:
            conn.execute('UPDATE threads SET archived=1'); conn.commit()
        with self.assertRaises(peer.CcPeerError) as error:
            self.preflight()
        self.assertEqual(error.exception.details['wake']['reason'], 'archived_thread')
        with contextlib.closing(sqlite3.connect(self.root/'state_5.sqlite')) as conn:
            conn.execute('UPDATE threads SET archived=0'); conn.commit()
        self.rollout.unlink()
        with self.assertRaises(peer.CcPeerError) as error:
            self.preflight()
        self.assertEqual(error.exception.details['wake']['reason'], 'uninitialized_thread')
        with contextlib.closing(sqlite3.connect(self.root/'state_5.sqlite')) as conn:
            conn.execute('DELETE FROM threads'); conn.commit()
        with self.assertRaises(peer.CcPeerError) as error:
            self.preflight()
        self.assertEqual(error.exception.details['wake']['reason'], 'missing_thread')

    def test_unsupported_version_never_submits(self):
        with mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'codex-cli 0.999.0','')):
            with mock.patch.object(peer, '_queue_codex') as queue:
                with self.assertRaises(peer.CcPeerError) as error:
                    peer.queue_codex(self.args, 'test')
        self.assertEqual(error.exception.details['wake']['reason'], 'unsupported_version')
        queue.assert_not_called()

    def test_guard_blocks_second_submission(self):
        with peer.codex_wake_guard(self.root, THREAD):
            with self.assertRaises(peer.CcPeerError) as error:
                with peer.codex_wake_guard(self.root, THREAD):
                    self.fail('concurrent guard accepted')
        self.assertEqual(error.exception.details['wake']['reason'], 'wake_in_progress')

    def test_queue_id_survives_wake_failure_without_retry(self):
        with mock.patch.object(peer, 'codex_wake_preflight', return_value={'cwd':str(self.root)}), \
             mock.patch.object(peer, '_queue_codex', return_value=dict(self.submitted)) as queue, \
             mock.patch.object(peer, 'run_codex_wake', return_value={'status':'timed_out','reason':'deadline'}) as wake:
            result = peer.queue_codex(self.args, 'one message')
        self.assertFalse(result['ok'])
        self.assertEqual(result['queueId'], 'queue-test')
        self.assertTrue(result['submitted'])
        self.assertFalse(result['consumptionConfirmed'])
        queue.assert_called_once()
        wake.assert_called_once_with('codex', self.root, THREAD, str(self.root), 1)

    def test_active_writer_only_queues(self):
        active = {'activity':'live_writer', 'writerLock':'held', 'ownerPid':42,
                  'ownerStartTime':'stable', 'ownerStable':True,
                  'reason':'stable_live_writer'}
        with mock.patch.object(peer, 'codex_wake_preflight', return_value={'cwd':str(self.root)}), \
             mock.patch.object(peer, 'inspect_codex_writer', return_value=active), \
             mock.patch.object(peer, '_queue_codex', return_value=dict(self.submitted)) as queue, \
             mock.patch.object(peer, 'run_codex_wake') as wake:
            result = peer.queue_codex(self.args, 'test')
        self.assertEqual(result['wake']['status'], 'already_active')
        queue.assert_called_once();wake.assert_not_called()

    def test_plain_send_never_preflights_or_wakes(self):
        self.args.wake = False
        with mock.patch.object(peer, '_queue_codex', return_value=self.submitted), \
             mock.patch.object(peer, 'codex_wake_preflight') as preflight:
            self.assertEqual(peer.queue_codex(self.args, 'test'), self.submitted)
        preflight.assert_not_called()

    def test_native_process_contract_and_deadline(self):
        fixture = Path(__file__).parent/'fixtures'/'codex_app_server.py'
        real_popen = subprocess.Popen
        processes = []
        def spawn(argv, **kwargs):
            self.assertEqual(argv, ['codex', 'app-server'])
            self.assertEqual(kwargs['cwd'], str(self.root))
            self.assertEqual(kwargs['env']['CODEX_HOME'], str(self.root))
            process = real_popen([sys.executable, str(fixture)], **kwargs)
            processes.append(process)
            return process
        for mode, status, reason in [('complete','completed','native_turn_completed'),
                                     ('reject','failed','native_resume_rejected'),
                                     ('approval','failed','approval_required'),
                                     ('malformed','failed','native_transport_failed'),
                                     ('timeout','timed_out','activation_deadline_exceeded')]:
            with self.subTest(mode=mode), mock.patch.dict(os.environ, {'WAKE_TEST_MODE':mode}), \
                 mock.patch.object(peer.subprocess,'Popen',side_effect=spawn):
                result = peer.run_codex_wake('codex',self.root,THREAD,str(self.root),0.4)
                self.assertEqual((result['status'],result['reason']),(status,reason))
                self.assertIsNotNone(processes[-1].poll())

    def test_remote_wake_failure_preserves_result(self):
        payload = peer.json_result('send', {**self.submitted, 'ok':False,
                                           'wake':{'status':'failed','reason':'native_resume_rejected'}})
        with mock.patch.object(peer,'ssh_user_metadata',return_value={}), \
             mock.patch.object(peer.subprocess,'run',return_value=subprocess.CompletedProcess([],1,json.dumps(payload),'')):
            result = peer.run_remote('worker', ['send','--wake'], [])
        self.assertEqual(result['queueId'],'queue-test')
        self.assertFalse(result['ok'])

    def test_claude_wake_rejected_before_send(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(peer,'post_to_socket') as send:
            code=peer.main(['send','--wake','--to','claude-name','--json','hello'])
        self.assertEqual(code,1)
        self.assertEqual(json.loads(output.getvalue())['wake']['reason'],'unsupported_agent')
        send.assert_not_called()

    def test_interrupt_after_submission_preserves_queue_id(self):
        with mock.patch.object(peer, 'codex_wake_preflight', return_value={'cwd':str(self.root)}), \
             mock.patch.object(peer, '_queue_codex', return_value=dict(self.submitted)), \
             mock.patch.object(peer, 'run_codex_wake', side_effect=KeyboardInterrupt):
            result = peer.queue_codex(self.args, 'test')
        self.assertEqual(result['queueId'], 'queue-test')
        self.assertEqual(result['wake']['reason'], 'activation_interrupted')

    def test_unknown_writer_blocks_before_queue(self):
        with mock.patch.object(peer.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'codex-cli 0.154.0','')), \
             mock.patch.object(peer,'inspect_codex_writer',return_value={'activity':'unknown'}), \
             mock.patch.object(peer,'_queue_codex') as queue:
            with self.assertRaises(peer.CcPeerError) as error:
                peer.queue_codex(self.args,'test')
        self.assertEqual(error.exception.details['wake']['reason'],'writer_unknown')
        queue.assert_not_called()

    def test_dry_run_never_starts_native_process(self):
        self.args.dry_run=True
        with mock.patch.object(peer,'codex_wake_preflight',return_value={'cwd':str(self.root)}), \
             mock.patch.object(peer,'_queue_codex',return_value={'ok':True,'submitted':False}), \
             mock.patch.object(peer,'run_codex_wake') as wake:
            result=peer.queue_codex(self.args,'test')
        self.assertEqual(result['wake']['status'],'validated')
        self.assertFalse(result['submitted'])
        wake.assert_not_called()

    def test_local_cli_partial_failure_exits_nonzero_with_queue_id(self):
        payload={**self.submitted,'ok':False,'dryRun':False,'target':{'id':THREAD},
                 'wake':{'status':'failed','reason':'native_turn_failed','error':'authentication required'}}
        output=io.StringIO()
        with mock.patch.object(peer,'queue_codex',return_value=payload), contextlib.redirect_stdout(output):
            code=peer.main(['send','--to','codex:'+THREAD,'--wake','--json','--no-from','--no-reply-to','hello'])
        self.assertEqual(code,1)
        result=json.loads(output.getvalue())
        self.assertEqual(result['queueId'],'queue-test')
        self.assertTrue(result['submitted'])
        self.assertFalse(result['ok'])

    def test_signal_handlers_restored_after_native_failure(self):
        import signal
        handlers={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGHUP)}
        with mock.patch.object(peer.subprocess,'Popen',side_effect=OSError('cannot start')):
            result=peer.run_codex_wake('codex',self.root,THREAD,str(self.root),1)
        self.assertEqual(result['reason'],'native_transport_failed')
        self.assertEqual(handlers,{sig:signal.getsignal(sig) for sig in handlers})

    def test_remote_preflight_refusal_renders_without_submission_fields(self):
        error=peer.wake_refused('unsupported_version','Unsupported CLI version')
        result={'ok':False,'error':str(error),**error.details}
        text=peer.codex_submission_text(result,'worker')
        self.assertIn('Unsupported CLI version',text)
        self.assertIn('nothing queued',text)
