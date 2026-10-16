"""Wake lifecycle, queue preservation and native process cleanup tests."""
import argparse
import base64
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
from tests.codex.support import THREAD, isolate_native_layers


@unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'POSIX wake')
class Wake(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        isolate_native_layers(self, self.root)
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

    def ordinary_preferences(self, *, forced_only=True):
        # Synthetic ordinary (not forced) preference; never access CF/user state.
        return [] if forced_only else [base64.b64encode(b'sqlite_home="fixture"').decode('ascii')]

    def test_wake154_ordinary_preference_refuses_before_queue_and_budget(self):
        for dry_run in (False, True):
            self.args.dry_run = dry_run
            with self.subTest(dry_run=dry_run), \
                 mock.patch.object(peer, 'codex_managed_preference_values', side_effect=self.ordinary_preferences), \
                 mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'codex-cli 0.154.0', '')), \
                 mock.patch.object(peer, '_queue_codex') as queue, \
                 mock.patch.object(peer, 'wake_target_rate_reserve') as reserve, \
                 mock.patch.object(peer.subprocess, 'Popen') as start:
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.queue_codex(self.args, 'fixture')
                self.assertEqual(caught.exception.details['reason'], 'sqlite_home_managed_configuration')
                self.assertNotIn('fixture', str(caught.exception))
                queue.assert_not_called()
                reserve.assert_not_called()
                start.assert_not_called()

    def test_unsupported_wake_never_reads_ordinary_preferences(self):
        def read(*, forced_only=True):
            self.assertTrue(forced_only)
            return []
        with mock.patch.object(peer, 'codex_managed_preference_values', side_effect=read), \
             mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'codex-cli 0.999.0', '')):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.queue_codex(self.args, 'fixture')
        self.assertEqual(caught.exception.details['wake']['reason'], 'unsupported_version')

    def test_ordinary_preference_mode_is_wake_only_and_rechecked_before_budget(self):
        with mock.patch.object(peer, 'codex_managed_preference_values', side_effect=self.ordinary_preferences):
            peer.check_codex_storage(self.root, cwd=self.root)
            peer.codex_process_environment(self.root, cwd=self.root)
            with self.assertRaises(peer.CcPeerError):
                peer.codex_queue_storage_preflight(self.args, self.root, THREAD)
            self.args.wake = False
            peer.codex_queue_storage_preflight(self.args, self.root, THREAD)

    def test_wake_queue_effect_rechecks_new_ordinary_preference(self):
        self.args.allow_inactive_codex_home = True
        with mock.patch.object(peer, 'resolve_codex_home', return_value=(self.root, {})), \
             mock.patch.object(peer, 'codex_queue_storage_preflight', return_value=self.root), \
             mock.patch.object(peer, 'revalidate_codex_home'), \
             mock.patch.object(peer, 'codex_managed_preference_values', side_effect=self.ordinary_preferences), \
             mock.patch.object(peer.subprocess, 'run') as run:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer._queue_codex(self.args, 'fixture')
        self.assertEqual(caught.exception.details['reason'], 'sqlite_home_managed_configuration')
        run.assert_not_called()

    def test_active_wake_also_checks_154_queue_preferences(self):
        active = {'activity': 'live_writer', 'ownerStable': True}
        with mock.patch.object(peer, 'codex_managed_preference_values', side_effect=self.ordinary_preferences), \
             mock.patch.object(peer, 'inspect_codex_writer', return_value=active), \
             mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'codex-cli 0.154.0', '')), \
             mock.patch.object(peer, '_queue_codex') as post, \
             mock.patch.object(peer, 'wake_target_rate_reserve') as reserve:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.queue_codex(self.args, 'fixture')
        self.assertEqual(caught.exception.details['reason'], 'sqlite_home_managed_configuration')
        post.assert_not_called()
        reserve.assert_not_called()

    def test_ordinary_preference_appearing_after_guarded_preflight_does_not_reserve(self):
        calls = {'n': 0}
        def preflight(*unused):
            calls['n'] += 1
            if calls['n'] == 2:
                reader.side_effect = self.ordinary_preferences
            return {'cwd': str(self.root), 'writer': {'activity': 'inactive'}}
        with mock.patch.object(peer, 'codex_wake_preflight', side_effect=preflight), \
             mock.patch.object(peer, 'codex_managed_preference_values', return_value=[]) as reader, \
             mock.patch.object(peer, '_queue_codex') as post, \
             mock.patch.object(peer, 'wake_target_rate_reserve') as reserve:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.queue_codex(self.args, 'fixture')
        self.assertEqual(caught.exception.details['reason'], 'sqlite_home_managed_configuration')
        self.assertEqual(calls['n'], 2)
        post.assert_not_called()
        reserve.assert_not_called()

    def test_wake154_allows_ordinary_preference_without_storage(self):
        encoded = base64.b64encode(b'model="fixture"').decode('ascii')
        with mock.patch.object(peer, 'codex_managed_preference_values', return_value=[encoded]):
            result = self.preflight()
            environment = peer.codex_process_environment(self.root, cwd=self.root, include_ordinary_preferences=True)
        self.assertEqual(result['version'], 'codex-cli 0.154.0')
        self.assertEqual(environment['CODEX_HOME'], str(self.root))

    def test_ordinary_preference_appearing_after_queue_prevents_wake_child_without_resend(self):
        def queue(*unused):
            reader.side_effect = self.ordinary_preferences
            return dict(self.submitted)
        with mock.patch.object(peer, 'codex_wake_preflight', return_value={'cwd': str(self.root)}), \
             mock.patch.object(peer, '_queue_codex', side_effect=queue) as post, \
             mock.patch.object(peer, 'codex_managed_preference_values', return_value=[]) as reader, \
             mock.patch.object(peer.subprocess, 'Popen') as start:
            result = peer.queue_codex(self.args, 'fixture')
        self.assertTrue(result['submitted'])
        self.assertEqual(result['queueId'], 'queue-test')
        self.assertFalse(result['ok'])
        self.assertEqual(result['wake']['status'], 'unknown')
        post.assert_called_once()
        start.assert_not_called()

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
        wake.assert_called_once_with('codex', self.root, THREAD, str(self.root), 1,
                                     wake_context=result['wakeProvenance'])

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
        fixture = Path(__file__).parents[1] / 'fixtures' / 'codex_app_server.py'
        real_popen = subprocess.Popen
        processes = []
        def spawn(argv, **kwargs):
            if argv[:1] == ['ps']:
                return real_popen(argv, **kwargs)
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
