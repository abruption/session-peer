"""Owner-terminal pairing UX; isolated PTYs/mocks, no native or hosted calls."""
import argparse
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import select
import signal
import sys
import threading
import tempfile
import unittest
from unittest import mock

if os.name != 'posix' or sys.version_info < (3, 11):
    raise unittest.SkipTest('POSIX relay terminal')
import termios

try:
    import cryptography
    import websockets
except ModuleNotFoundError as exc:
    if exc.name in ('cryptography', 'websockets'):
        raise unittest.SkipTest('optional relay dependencies unavailable') from None
    raise

from session_peer_relay import cli, pairing_ui as ui
from session_peer_relay.store import Rejected


class PairingLinkUI(unittest.TestCase):
    @contextlib.contextmanager
    def offer_setup(self):
        from session_peer_relay import setup
        with tempfile.TemporaryDirectory(prefix='codex-offer-reconcile-',
                dir=os.environ.get('SESSION_PEER_TEST_TMP')) as temporary:
            root = Path(temporary) / 'state'
            base = ['setup', '--mode', 'relay', '--state', str(root), '--apply']
            self.assertTrue(setup.run(self.core_parser().parse_args(base + ['--action', 'init']))['ok'])
            args = self.core_parser().parse_args(base + ['--action', 'offer', '--peer-key', 'c' * 64,
                '--direct', '127.0.0.1:3770', '--show-link'])
            yield setup, root, base, args

    def offer_action(self, setup, base, action, ident=None):
        return setup.run(self.core_parser().parse_args(base + ['--action', action] +
            (['--offer-id', ident] if ident is not None else [])))

    def core_parser(self):
        import session_peer as core
        namespace = dict(core.__dict__)
        exec(Path('session_peer_core/cli.py').read_text(), namespace)
        return namespace['build_parser']()

    def assert_terminal_restored(self, fd, saved):
        actual = termios.tcgetattr(fd)
        # Darwin may set its kernel-maintained PENDIN bit on tcsetattr.
        actual[3] &= ~getattr(termios, 'PENDIN', 0)
        saved = list(saved)
        saved[3] &= ~getattr(termios, 'PENDIN', 0)
        self.assertEqual(actual, saved)

    def store(self):
        store = mock.Mock(device='a' * 64, key_id='b' * 64, generation=0)
        store.offer_identity.return_value = {'principal': 'c' * 64,
            'keyFingerprint': 'c' * 64, 'generation': 0}
        store.receiver_offer_identity.return_value = store.offer_identity.return_value
        return store

    def terminal(self, *answers):
        terminal = mock.MagicMock()
        terminal.__enter__.return_value = terminal
        terminal.read.side_effect = answers
        return terminal

    def test_receiver_confirmation_and_link_are_terminal_only(self):
        store = self.store()
        store.create_offer.return_value = {'id': 'offer'}
        store.offer_status.return_value = {'ok': True, 'offerId': 'offer', 'status': 'open'}
        args = argparse.Namespace(peer_key='c' * 64, direct='127.0.0.1:3770', relay=None, show_link=True)
        terminal = self.terminal('yes')
        with mock.patch.object(ui, 'Terminal', return_value=terminal), \
                mock.patch.object(ui, 'encode_link', return_value='session-peer://pair/v1#PRIVATE'):
            result = ui.create_offer(store, args)
        self.assertNotIn('PRIVATE', str(result))
        self.assertTrue(any('PRIVATE' in str(call) for call in terminal.show.call_args_list))
        store.create_offer.assert_called_once_with({'direct': '127.0.0.1:3770'}, 'c' * 64,
            expected_identity=store.offer_identity.return_value, offer_id=mock.ANY)

    def test_receiver_refusal_never_creates_offer(self):
        args = argparse.Namespace(peer_key='c' * 64, direct='127.0.0.1:3770', relay=None, show_link=True)
        for unavailable in (False, True):
            terminal = self.terminal('no')
            store = self.store()
            if unavailable:
                terminal.__enter__.side_effect = Rejected('pairing_terminal_required')
            with mock.patch.object(ui, 'Terminal', return_value=terminal), self.assertRaises(Rejected):
                ui.create_offer(store, args)
            store.create_offer.assert_not_called()
        store = self.store()
        args.show_link = False
        with self.assertRaisesRegex(Rejected, 'explicit_link_display'):
            ui.create_offer(store, args)
        store.create_offer.assert_not_called()

    def test_manual_display_error_or_interrupt_reports_only_cancellable_public_id(self):
        from session_peer_relay.store import Store
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted), self.offer_setup() as (setup, root, base, args):
                terminal, private = self.terminal('yes'), []
                def fail_link(text):
                    if text.startswith('session-peer://pair/'):
                        private.append(text)
                        if interrupted:
                            raise KeyboardInterrupt()
                        raise OSError('untrusted fixture exception: ' + text)
                terminal.show.side_effect = fail_link
                output = io.StringIO()
                with mock.patch.object(ui, 'Terminal', return_value=terminal), contextlib.redirect_stdout(output):
                    code = cli.main('device', ['offer', '--state', str(root), '--peer-key', 'c' * 64,
                        '--direct', '127.0.0.1:3770', '--show-link'])
                result = json.loads(output.getvalue())
                self.assertEqual(code, 130 if interrupted else 1)
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(result['updated'])
                self.assertFalse(result['retryAllowed'])
                self.assertIn('offerId', result)
                self.assertNotIn(private[0], output.getvalue())
                invitation, unused = ui.decode_link(private[0])
                self.assertNotIn(invitation['secret'], output.getvalue())
                self.assertNotIn('untrusted fixture exception', output.getvalue())
                host = Store(root)
                try:
                    self.assertEqual(host.offer_status(result['offerId'])['status'], 'open')
                finally:
                    host.close()
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(cli.main('device', ['offer-cancel', '--state', str(root),
                        '--offer-id', result['offerId']]), 0)
                self.assertEqual(json.loads(output.getvalue())['status'], 'cancelled')

    def test_unknown_offer_metadata_accepts_only_exact_class_and_canonical_public_id(self):
        self.assertIsNone(ui.offer_failure(Rejected('fixture')))
        result = ui.offer_failure(ui.OfferOutcomeUnknown('session-peer://pair/v1#PRIVATE'))
        self.assertNotIn('offerId', result)
        self.assertNotIn('PRIVATE', str(result))

    def test_client_requires_own_key_and_independent_receiver_confirmation(self):
        invitation = {'device': 'c' * 64, 'certificate': 'public', 'routes': {'direct': '127.0.0.1:3770'}}
        for intended, answers, error in (
                ('d' * 64, ('private',), 'wrong_client_key'),
                ('b' * 64, ('private', 'd' * 64), 'receiver_identity_mismatch'),
                ('b' * 64, ('private', 'c' * 64, 'no'), 'identity_not_confirmed')):
            terminal = self.terminal(*answers)
            with mock.patch.object(ui, 'Terminal', return_value=terminal), \
                    mock.patch.object(ui, 'decode_link', return_value=(invitation, intended)), \
                    mock.patch.object(ui, 'link_digest', return_value='d' * 64), \
                    mock.patch.object(ui, 'fingerprint', return_value='c' * 64), \
                    self.assertRaisesRegex(Rejected, error):
                ui.receive_link(self.store(), 'direct')
            if error == 'receiver_identity_mismatch':
                self.assertNotIn('c' * 64, str(terminal.show.call_args_list))
                self.assertNotIn('receiverPrincipal', str(terminal.show.call_args_list))

    def test_offer_creation_rechecks_confirmed_identity_after_prompt(self):
        from session_peer_relay.store import Store
        with self.offer_setup() as (setup, root, base, args):
            host, client = Store(root), Store(root.parent / 'client')
            try:
                args.peer_key = client.key_id
                terminal = self.terminal()
                def changed_before_yes(*unused, **kwargs):
                    host.register_key('d' * 64, client.cert, 2)
                    return 'yes'
                terminal.read.side_effect = changed_before_yes
                with mock.patch.object(ui, 'Terminal', return_value=terminal), self.assertRaises(Rejected):
                    ui.create_offer(host, args)
                self.assertEqual(host.db.execute('SELECT COUNT(*) FROM pairing_offers').fetchone()[0], 0)
                self.assertEqual(host.db.execute('SELECT COUNT(*) FROM invites').fetchone()[0], 0)
            finally:
                client.close()
                host.close()

    def test_pty_receiver_identity_is_hidden_until_independent_fingerprint_match(self):
        import time
        master, slave = os.openpty()
        candidate = 'c' * 64
        link = 'session-peer://pair/v1#' + candidate
        invitation = {'device': candidate, 'certificate': 'public',
            'routes': {'direct': '127.0.0.1:3770'}}
        observed, errors, results = bytearray(), [], []
        def read_until(marker):
            cutoff = time.monotonic() + 2
            while marker not in observed:
                self.assertLess(time.monotonic(), cutoff)
                if select.select([master], [], [], .05)[0]:
                    observed.extend(os.read(master, 32768))
        def receive():
            try:
                results.append(ui.receive_link(self.store(), 'direct'))
            except BaseException as exc:
                errors.append(exc)
        try:
            with mock.patch.object(ui.os, 'open', return_value=os.dup(slave)), \
                    mock.patch.object(ui, 'decode_link', return_value=(invitation, 'b' * 64)), \
                    mock.patch.object(ui, 'link_digest', return_value='d' * 64), \
                    mock.patch.object(ui, 'fingerprint', return_value=candidate):
                thread = threading.Thread(target=receive)
                thread.start()
                read_until(b'Paste private pairing link')
                os.write(master, (link + '\n').encode())
                read_until(b'Enter receiver fingerprint obtained independently')
                self.assertNotIn(candidate.encode(), observed)
                self.assertNotIn(b'receiverPrincipal', observed)
                self.assertNotIn(b'127.0.0.1:3770', observed)
                os.write(master, (candidate + '\n').encode())
                read_until(b'Type yes to confirm your identity and pair')
                self.assertIn(candidate.encode(), observed)
                self.assertIn(b'receiverPrincipal', observed)
                self.assertIn(b'127.0.0.1:3770', observed)
                os.write(master, b'yes\n')
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 1)
        finally:
            os.close(master)
            os.close(slave)

    def test_cli_confirmation_precedes_credential_or_pair(self):
        args = cli.parser('device').parse_args(['pair', '--link', '--state', '/unused'])
        with mock.patch.object(cli, 'Store', return_value=self.store()), \
                mock.patch.object(ui, 'receive_link', side_effect=Rejected('pairing_identity_not_confirmed')), \
                mock.patch.object(cli, 'device_credential') as credential, \
                mock.patch.object(cli, 'pair') as pair, self.assertRaises(Rejected):
            asyncio.run(cli.manage('device', args))
        credential.assert_not_called()
        pair.assert_not_called()

    def test_accidental_link_argv_never_reaches_diagnostics(self):
        secret = 'session-peer://pair/v1#PRIVATE-CREDENTIAL'
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main('device', ['pair', '--link', secret]), 1)
        self.assertNotIn('PRIVATE-CREDENTIAL', output.getvalue())
        for argv in (['device', 'pair', '--link', secret],
                     ['setup', '--mode', 'relay', '--link', secret],
                     ['setup', '--route', secret]):
            error = io.StringIO()
            with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
                self.core_parser().parse_args(argv)
            self.assertNotIn('PRIVATE-CREDENTIAL', error.getvalue())

    def test_ordinary_send_payload_can_contain_literal_link_and_device_or_setup(self):
        payload = 'session-peer://pair/v1#LITERAL-MESSAGE'
        for target in ('device', 'setup', 'somebody'):
            args = self.core_parser().parse_args(['send', '--to', target, '--message', payload])
            self.assertEqual(args.message_option, payload)
            self.assertEqual(args.to, target)
        for word in ('device', 'setup'):
            message = payload + ' ' + word
            args = self.core_parser().parse_args(['send', '--to', 'somebody', '--message', message])
            self.assertEqual(args.message_option, message)

    def test_setup_offer_journal_contains_public_id_only_and_refusal_can_retry(self):
        from session_peer_relay import setup
        with tempfile.TemporaryDirectory(prefix='codex-link-setup-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as temporary:
            root = Path(temporary) / 'state'
            base = ['setup', '--mode', 'relay', '--state', str(root), '--apply']
            self.assertTrue(setup.run(self.core_parser().parse_args(base + ['--action', 'init']))['ok'])
            args = self.core_parser().parse_args(base + ['--action', 'offer', '--peer-key', 'c' * 64,
                '--direct', '127.0.0.1:3770', '--show-link'])
            with mock.patch.object(ui, 'Terminal', return_value=self.terminal('no')):
                refused = setup.run(args)
            self.assertFalse(refused['ok'])
            self.assertNotIn('offer', json.loads((root / 'setup.json').read_text())['phases'])
            terminal = self.terminal('yes')
            with mock.patch.object(ui, 'Terminal', return_value=terminal):
                result = setup.run(args)
            self.assertTrue(result['ok'], result)
            journal = (root / 'setup.json').read_text()
            self.assertNotIn('session-peer://', journal)
            self.assertNotIn('secret', journal)
            self.assertIn(result['offerId'], journal)
            self.assertEqual(json.loads(journal)['phases']['offer'], 'complete')

    def test_setup_link_uses_confirmed_input_before_pair_and_records_no_secret(self):
        from session_peer_relay import setup
        invitation = {'device': 'c' * 64, 'routes': {'direct': '127.0.0.1:3770'}}
        with tempfile.TemporaryDirectory(prefix='codex-link-setup-', dir=os.environ.get('SESSION_PEER_TEST_TMP')) as temporary:
            root = Path(temporary) / 'state'
            base = ['setup', '--mode', 'relay', '--state', str(root), '--apply']
            self.assertTrue(setup.run(self.core_parser().parse_args(base + ['--action', 'init']))['ok'])
            args = self.core_parser().parse_args(base + ['--action', 'pair', '--link'])
            with mock.patch.object(ui, 'receive_link', return_value=(invitation, 'b' * 64, 'd' * 64, 'direct')), \
                    mock.patch.object(setup, 'pair', new_callable=mock.AsyncMock, return_value={'ok': True}) as pair:
                result = setup.run(args)
            self.assertTrue(result['ok'], result)
            self.assertEqual(pair.call_args.kwargs, {'offer_digest': 'd' * 64, 'expected_client_key': 'b' * 64})
            self.assertEqual(args._paired_receiver, 'c' * 64)
            self.assertNotIn('secret', (root / 'setup.json').read_text())

    def test_definitive_creation_refusal_is_retryable_without_pending_wedge(self):
        from session_peer_relay.store import Store
        for reason in ('pairing_rate_limited', 'pairing_offer_capacity'):
            with self.subTest(reason=reason), self.offer_setup() as (setup, root, base, args):
                with mock.patch.object(ui, 'Terminal', return_value=self.terminal('yes')), \
                        mock.patch.object(Store, 'create_offer', side_effect=Rejected(reason)):
                    result = setup.run(args)
                self.assertEqual(result['reason'], reason)
                saved = json.loads((root / 'setup.json').read_text())
                self.assertEqual(saved['phases']['offer'], 'not_created')
                self.assertEqual(self.offer_action(setup, base, 'offer-status')['status'], 'not_created')
                with mock.patch.object(ui, 'Terminal', return_value=self.terminal('yes')):
                    self.assertTrue(setup.run(args)['ok'])

    def test_unknown_creation_failure_preserves_id_until_explicit_status(self):
        from session_peer_relay.store import Store
        with self.offer_setup() as (setup, root, base, args):
            with mock.patch.object(ui, 'Terminal', return_value=self.terminal('yes')), \
                    mock.patch.object(Store, 'create_offer', side_effect=OSError('fixture unavailable')):
                self.assertFalse(setup.run(args)['ok'])
            saved = json.loads((root / 'setup.json').read_text())
            self.assertEqual(saved['phases']['offer'], 'pending')
            self.assertEqual(setup.run(args)['reason'], 'setup_offer_reconcile_required')
            result = self.offer_action(setup, base, 'offer-status', saved['offerId'])
            self.assertFalse(result['ok'])
            self.assertEqual(result['status'], 'unknown')
            self.assertEqual(result['reason'], 'pairing_offer_history_unavailable')
            self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'pending')
            stopped = self.offer_action(setup, base, 'offer-cancel', saved['offerId'])
            self.assertFalse(stopped['ok'])
            self.assertEqual(stopped['offerId'], saved['offerId'])
            self.assertTrue(stopped['stoppedWaiting'])
            self.assertFalse(stopped['remoteCancellationConfirmed'])
            self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'stopped_unknown')
            with mock.patch.object(ui, 'Terminal', side_effect=AssertionError('status must not create')):
                self.assertEqual(self.offer_action(setup, base, 'offer-status')['status'], 'unknown')
            self.assertEqual(json.loads((root / 'setup.json').read_text())['offerId'], saved['offerId'])
            with mock.patch.object(ui, 'Terminal', return_value=self.terminal('yes')):
                fresh = setup.run(args)
            self.assertTrue(fresh['ok'], fresh)
            self.assertNotEqual(fresh['offerId'], saved['offerId'])
            self.assertEqual(json.loads((root / 'setup.json').read_text())['offerId'], fresh['offerId'])

    def test_committed_offer_survives_created_journal_callback_failure(self):
        with self.offer_setup() as (setup, root, base, args):
            save = setup.Workflow.save
            pending_saves = []
            def fail_created(work):
                if work.saved['phases'].get('offer') == 'pending':
                    pending_saves.append(True)
                    if len(pending_saves) == 2:
                        raise OSError('fixture journal failure after DB commit')
                return save(work)
            with mock.patch.object(ui, 'Terminal', return_value=self.terminal('yes')), \
                    mock.patch.object(setup.Workflow, 'save', new=fail_created):
                self.assertFalse(setup.run(args)['ok'])
            saved = json.loads((root / 'setup.json').read_text())
            self.assertEqual(saved['phases']['offer'], 'pending')
            self.assertEqual(self.offer_action(setup, base, 'offer-status', saved['offerId'])['status'], 'open')
            self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'pending')
            self.assertEqual(self.offer_action(setup, base, 'offer-cancel', saved['offerId'])['status'], 'cancelled')
            with mock.patch.object(ui, 'Terminal', return_value=self.terminal('yes')):
                fresh = setup.run(args)
            self.assertTrue(fresh['ok'], fresh)
            self.assertNotEqual(fresh['offerId'], saved['offerId'])

    def test_display_failure_requires_status_cancel_without_secret_reissue(self):
        from session_peer_relay.store import Store
        with self.offer_setup() as (setup, root, base, args):
            terminal = self.terminal('yes')
            def fail_link(text):
                if text.startswith('session-peer://pair/'):
                    raise OSError('fixture display failure')
            terminal.show.side_effect = fail_link
            with mock.patch.object(ui, 'Terminal', return_value=terminal):
                self.assertFalse(setup.run(args)['ok'])
            saved = json.loads((root / 'setup.json').read_text())
            self.assertEqual(saved['phases']['offer'], 'pending')
            host = Store(root)
            try:
                other = host.create_offer({'direct': '127.0.0.1:3770'}, 'd' * 64)
            finally:
                host.close()
            self.assertEqual(self.offer_action(setup, base, 'offer-cancel', other['id'])['status'], 'cancelled')
            self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'pending')
            self.assertEqual(self.offer_action(setup, base, 'offer-status')['status'], 'open')
            with mock.patch.object(ui, 'Terminal', side_effect=AssertionError('must not reemit credential')):
                self.assertEqual(self.offer_action(setup, base, 'offer-cancel')['status'], 'cancelled')
            self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'cancelled')

    def test_expired_status_resolves_pending_creation(self):
        import time
        with self.offer_setup() as (setup, root, base, args):
            terminal = self.terminal('yes')
            terminal.show.side_effect = lambda text: (_ for _ in ()).throw(OSError()) if text.startswith('session-peer://pair/') else None
            with mock.patch.object(ui, 'Terminal', return_value=terminal):
                self.assertFalse(setup.run(args)['ok'])
            with mock.patch('time.time', return_value=time.time() + 601):
                self.assertEqual(self.offer_action(setup, base, 'offer-status')['status'], 'expired')
            self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'expired')

    def test_reserved_status_preserves_pending_and_consumed_status_resolves_it(self):
        from session_peer_relay.store import Store
        with self.offer_setup() as (setup, root, base, args):
            client = Store(root.parent / 'client')
            try:
                args.peer_key = client.key_id
                terminal = self.terminal('yes')
                def fail_link(text):
                    if text.startswith('session-peer://pair/'):
                        raise OSError('fixture display failure')
                terminal.show.side_effect = fail_link
                with mock.patch.object(ui, 'Terminal', return_value=terminal):
                    self.assertFalse(setup.run(args)['ok'])
                link = next(call.args[0] for call in terminal.show.call_args_list
                    if call.args[0].startswith('session-peer://pair/'))
                invite, unused = ui.decode_link(link)
                host = Store(root)
                try:
                    host.prepare({'invitation': invite['id'], 'secret': invite['secret'],
                        'certificate': client.cert, 'offer': True})
                finally:
                    host.close()
                self.assertEqual(self.offer_action(setup, base, 'offer-status')['status'], 'reserved')
                self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'pending')
                host = Store(root)
                try:
                    host.commit(client.key_id, invite['id'], authenticated_key=client.key_id, offer=True)
                finally:
                    host.close()
                self.assertEqual(self.offer_action(setup, base, 'offer-status')['status'], 'consumed')
                self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'consumed')
            finally:
                client.close()

    def test_pruned_consumed_receipt_is_unknown_and_stop_never_revokes_pairing(self):
        import time
        from session_peer_relay.store import Store
        with self.offer_setup() as (setup, root, base, args):
            client = Store(root.parent / 'client')
            try:
                args.peer_key = client.key_id
                terminal = self.terminal('yes')
                def fail_link(text):
                    if text.startswith('session-peer://pair/'):
                        raise OSError('fixture display failure')
                terminal.show.side_effect = fail_link
                with mock.patch.object(ui, 'Terminal', return_value=terminal):
                    self.assertFalse(setup.run(args)['ok'])
                link = next(call.args[0] for call in terminal.show.call_args_list
                    if call.args[0].startswith('session-peer://pair/'))
                invite, unused = ui.decode_link(link)
                host = Store(root)
                try:
                    host.prepare({'invitation': invite['id'], 'secret': invite['secret'],
                        'certificate': client.cert, 'offer': True})
                    host.commit(client.key_id, invite['id'], authenticated_key=client.key_id, offer=True)
                    paired = host.peer(client.device)
                finally:
                    host.close()
                with mock.patch('time.time', return_value=time.time() + 7 * 86400 + 1):
                    missing = self.offer_action(setup, base, 'offer-status')
                    self.assertFalse(missing['ok'])
                    self.assertEqual(missing['status'], 'unknown')
                    self.assertEqual(missing['reason'], 'pairing_offer_history_unavailable')
                    self.assertEqual(json.loads((root / 'setup.json').read_text())['phases']['offer'], 'pending')
                    stopped = self.offer_action(setup, base, 'offer-cancel')
                self.assertFalse(stopped['ok'])
                self.assertTrue(stopped['stoppedWaiting'])
                self.assertFalse(stopped['remoteCancellationConfirmed'])
                journal = json.loads((root / 'setup.json').read_text())
                self.assertEqual(journal['offerId'], invite['id'])
                self.assertEqual(journal['phases']['offer'], 'stopped_unknown')
                host = Store(root)
                try:
                    self.assertEqual(host.peer(client.device), paired)
                finally:
                    host.close()
                with mock.patch.object(ui, 'Terminal', return_value=self.terminal('yes')):
                    duplicate = setup.run(args)
                self.assertFalse(duplicate['ok'])
                self.assertEqual(duplicate['reason'], 'principal_already_paired')
            finally:
                client.close()

    def test_historical_restored_status_does_not_resolve_setup_pending(self):
        from session_peer_relay.store import Store
        with self.offer_setup() as (setup, root, base, args):
            with mock.patch.object(ui, 'Terminal', return_value=self.terminal('yes')), \
                    mock.patch.object(Store, 'create_offer', side_effect=OSError('fixture unknown')):
                self.assertFalse(setup.run(args)['ok'])
            before = (root / 'setup.json').read_bytes()
            with mock.patch.object(Store, 'offer_status', return_value={'ok': True,
                    'status': 'consumed', 'recoveryRequired': True, 'historical': True}):
                result = self.offer_action(setup, base, 'offer-status')
            self.assertEqual(result['reason'], 'recovery_required')
            self.assertEqual((root / 'setup.json').read_bytes(), before)
            with mock.patch.object(Store, 'recovery_required', return_value=True), \
                    mock.patch.object(Store, 'cancel_offer', side_effect=AssertionError('no historical cancellation')):
                result = self.offer_action(setup, base, 'offer-cancel')
            self.assertEqual(result['reason'], 'recovery_required')
            self.assertEqual((root / 'setup.json').read_bytes(), before)

    def test_terminal_reads_beyond_canonical_limit_without_echo_and_restores(self):
        master, slave = os.openpty()
        saved = termios.tcgetattr(slave)
        result, errors = [], []
        def read():
            try:
                with ui.Terminal() as terminal:
                    result.append(terminal.read('hidden:', secret=True, limit=16384))
            except BaseException as exc:
                errors.append(exc)
        try:
            with mock.patch.object(ui.os, 'open', return_value=os.dup(slave)):
                thread = threading.Thread(target=read)
                thread.start()
                self.assertTrue(select.select([master], [], [], 2)[0])
                os.read(master, 1024)
                # Wait for the input mode switch, without relying on scheduling.
                import time
                cutoff = time.monotonic() + 2
                while termios.tcgetattr(slave)[3] & termios.ICANON:
                    self.assertLess(time.monotonic(), cutoff)
                    time.sleep(.001)
                raw = b'x' * 12000 + b'\n'
                while raw:
                    raw = raw[os.write(master, raw):]
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result, ['x' * 12000])
            self.assert_terminal_restored(slave, saved)
            self.assertNotIn(b'x', os.read(master, 1024))
        finally:
            os.close(master)
            os.close(slave)


class PairingLinkUILoopback(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from session_peer_relay import app
        from session_peer_relay.store import Store
        self.directory = tempfile.TemporaryDirectory(prefix='codex-link-ui-tls-',
            dir=os.environ.get('SESSION_PEER_TEST_TMP'))
        root = Path(self.directory.name)
        self.host, self.client = Store(root / 'host'), Store(root / 'client')
        self.receiver = app.Receiver(self.host, {'targets': {'unused': {
            'agent': 'claude', 'target': 'offline-fixture'}}, 'peers': {
            self.client.device: {'capabilities': ['list'], 'targets': ['unused']}}})
        self.listener = await self.receiver.listen('127.0.0.1', 0)
        routes = {'direct': '127.0.0.1:' + str(self.listener.sockets[0].getsockname()[1])}
        self.invitation = self.host.create_offer(routes, self.client.key_id)
        self.link = ui.encode_link(self.invitation, self.client.key_id)

    async def asyncTearDown(self):
        self.listener.close()
        await self.listener.wait_closed()
        await self.receiver.close()
        self.client.close()
        self.host.close()
        self.directory.cleanup()

    async def pair_through_ui(self):
        from session_peer_relay import app
        terminal = mock.MagicMock()
        terminal.__enter__.return_value = terminal
        terminal.read.side_effect = [self.link, self.host.key_id, 'yes']
        changes = self.client.db.total_changes
        with mock.patch.object(ui, 'Terminal', return_value=terminal):
            invitation, intended, digest, route = ui.receive_link(self.client, 'direct')
        self.assertEqual(self.client.db.total_changes, changes, 'confirmation mutated trust/intent')
        return await app.pair(self.client, invitation, route,
            offer_digest=digest, expected_client_key=intended)

    async def lose_response(self, pairing):
        from session_peer_relay.wire import Secure
        receive = Secure.recv
        async def lost(channel):
            value = await receive(channel)
            if value.get('pairing') == pairing:
                raise OSError('fixture lost response')
            return value
        with mock.patch.object(Secure, 'recv', new=lost), self.assertRaises(OSError):
            await self.pair_through_ui()
        self.assertEqual(self.client.peer(self.host.device)['status'], 'pending')

    async def test_ui_reentry_reconciles_lost_prepare_response(self):
        await self.lose_response('pending')
        self.assertEqual(self.host.offer_status(self.invitation['id'])['status'], 'reserved')
        result = await self.pair_through_ui()
        self.assertTrue(result['ok'])
        self.assertEqual(self.client.peer(self.host.device)['status'], 'paired')

    async def test_ui_reentry_reconciles_lost_commit_response_after_expiry(self):
        await self.lose_response('paired')
        self.assertEqual(self.host.offer_status(self.invitation['id'])['status'], 'consumed')
        with mock.patch('time.time', return_value=self.invitation['expires'] + 1), \
                mock.patch.object(self.host, 'prepare', side_effect=AssertionError('expired prepare')):
            result = await self.pair_through_ui()
        self.assertTrue(result['ok'])
        self.assertEqual(self.client.peer(self.host.device)['status'], 'paired')

    async def test_pending_ui_reentry_rejects_changed_link_without_writes_or_network(self):
        from session_peer_relay import app
        await self.lose_response('pending')
        self.link = ui.encode_link({**self.invitation,
            'routes': {'direct': '127.0.0.1:9'}}, self.client.key_id)
        changes = self.client.db.total_changes
        with mock.patch.object(app, 'open_channel', side_effect=AssertionError('unexpected network')), \
                self.assertRaisesRegex(Rejected, 'intent_conflict'):
            await self.pair_through_ui()
        self.assertEqual(self.client.db.total_changes, changes)

    async def test_cold_expired_ui_input_has_no_writes_or_network(self):
        from session_peer_relay import app
        changes = self.client.db.total_changes
        with mock.patch('time.time', return_value=self.invitation['expires'] + 1), \
                mock.patch.object(app, 'open_channel', side_effect=AssertionError('unexpected network')), \
                self.assertRaisesRegex(Rejected, 'invalid_invitation'):
            await self.pair_through_ui()
        self.assertEqual(self.client.db.total_changes, changes)


class PairingLinkUITerminal(unittest.TestCase):
    assert_terminal_restored = PairingLinkUI.assert_terminal_restored

    def test_terminal_interrupt_restores_input_mode(self):
        master, slave = os.openpty()
        saved = termios.tcgetattr(slave)
        try:
            with mock.patch.object(ui.os, 'open', return_value=os.dup(slave)), \
                    mock.patch.object(ui.os, 'read', side_effect=KeyboardInterrupt), \
                    self.assertRaises(KeyboardInterrupt):
                with ui.Terminal() as terminal:
                    terminal.read('hidden:', secret=True)
            self.assert_terminal_restored(slave, saved)
        finally:
            os.close(master)
            os.close(slave)

    def test_one_sigint_interrupts_synchronous_terminal_read_inside_asyncio(self):
        master, slave = os.openpty()
        saved = termios.tcgetattr(slave)
        original_handler = signal.getsignal(signal.SIGINT)
        timer = None
        async def read():
            with ui.Terminal() as terminal:
                terminal.read('hidden:', secret=True)
        try:
            with mock.patch.object(ui.os, 'open', return_value=os.dup(slave)):
                timer = threading.Timer(.03, lambda: os.kill(os.getpid(), signal.SIGINT))
                timer.start()
                with self.assertRaises(KeyboardInterrupt):
                    asyncio.run(read())
            self.assert_terminal_restored(slave, saved)
            self.assertEqual(signal.getsignal(signal.SIGINT), original_handler)
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            os.close(master)
            os.close(slave)
