"""Offline paired explanation negotiation; no native or model submission."""
import contextlib
import copy
import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.relay import test_native_relay as platform_guard
from session_peer_relay import app, cli, worker
from session_peer_relay.framing import valid_delivery_context, worker_frame

UUID = '01900000-0000-7000-8000-000000000001'
CONTEXT = {'schemaVersion': 1, 'agent': 'codex', 'target': 'codex:' + UUID,
           'home': '/actual', 'capabilities': {'send': True, 'wake': True, 'wait': False, 'ack': False}}


class ContextValidation(unittest.TestCase):
    def test_strict_bounded_optional_context(self):
        self.assertTrue(valid_delivery_context(CONTEXT))
        self.assertTrue(valid_delivery_context({**CONTEXT, 'target': None, 'home': None}))
        for change in ({'schemaVersion': True}, {'schemaVersion': 2}, {'agent': 'other'},
                       {'home': 'relative'}, {'home': '/' + 'x' * 4096}, {'home': '/\ud800'},
                       {'target': 'claude:1'}, {'target': 'codex:alias'},
                       {'capabilities': {**CONTEXT['capabilities'], 'wake': 1}}, {'extra': True}):
            self.assertFalse(valid_delivery_context({**CONTEXT, **change}), change)

    def test_context_only_explicit_resolve_and_actual_returned_facts(self):
        binding = {'agent': 'codex', 'target': 'codex:' + UUID, 'codexHome': '/guessed'}
        for explain in (False, True):
            output = io.StringIO()
            native = {'ok': True, 'target': {'agent': 'codex', 'id': UUID}, 'codexHome': '/actual'}
            with mock.patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(
                    worker_frame(binding, 'resolve', 'fixture', explain=explain)))), \
                    mock.patch.object(worker.core, 'codex_executable', return_value='fixture'), \
                    mock.patch.object(worker.core.LocalTransport, 'execute', return_value=native) as execute, \
                    contextlib.redirect_stdout(output):
                worker.main()
            result = json.loads(output.getvalue())
            self.assertEqual(execute.call_count, 1)
            if explain:
                self.assertEqual(result['deliveryContext'], CONTEXT)
            else:
                self.assertNotIn('deliveryContext', result)
        no_facts = worker.delivery_context(binding, worker.core.AGENTS.get('codex'), {'ok': False})
        self.assertIsNone(no_facts['target'])
        self.assertIsNone(no_facts['home'])
        agy = worker.delivery_context({'agent': 'antigravity', 'target': 'antigravity:' + UUID},
                                     worker.core.AGENTS.get('antigravity'),
                                     {'ok': True, 'antigravityHome': '/actual'})
        self.assertIsNone(agy['target'])
        self.assertEqual(agy['home'], '/actual')
        claude = worker.delivery_context({'agent': 'claude', 'target': 'worker'},
                                        worker.core.AGENTS.get('claude'),
                                        {'ok': True, 'target': {'pid': 42, 'name': 'worker'}})
        self.assertEqual(claude['target'], 'claude:42')
        self.assertIsNone(claude['home'])

    def test_invoke_strips_context_and_preserves_native_facts(self):
        for explain in (False, True):
            for context in (CONTEXT, {**CONTEXT, 'schemaVersion': 99}, None):
                args = SimpleNamespace(device='a' * 64, command='send', dry_run=True, json=True, explain=explain)
                native = {'ok': True, 'target': {'id': UUID}, 'codexHome': '/actual',
                          'route': 'direct', 'deliveryContext': copy.deepcopy(context)}
                with mock.patch.object(cli, 'core_exchange', mock.AsyncMock(return_value=native)), \
                        mock.patch.object(cli.core, 'emit') as emit, \
                        mock.patch.object(cli.core, 'emit_delivery_explanation') as explanation:
                    self.assertEqual(cli.invoke_core(args), 0)
                emitted = emit.call_args.args[1]
                self.assertNotIn('deliveryContext', emitted)
                self.assertEqual(emitted['target'], {'id': UUID})
                self.assertEqual(emitted['codexHome'], '/actual')
                self.assertEqual(hasattr(args, '_delivery_explanation_context'), explain and context == CONTEXT)
                if explain:
                    explanation.assert_called_once_with(args, emitted, failed=False)
                else:
                    explanation.assert_not_called()

    def test_optional_worker_context_cannot_displace_valid_native_result_at_cap(self):
        binding = {'agent': 'codex', 'target': 'codex:' + UUID, 'codexHome': '/configured'}
        native = {'ok': True, 'target': {'agent': 'codex', 'id': UUID}, 'codexHome': '/actual',
                  'padding': 'x' * (60 * 1024 - 280)}
        output = io.StringIO()
        with mock.patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(
                worker_frame(binding, 'resolve', 'fixture', explain=True)))), \
                mock.patch.object(worker.core, 'codex_executable', return_value='fixture'), \
                mock.patch.object(worker.core.LocalTransport, 'execute', return_value=native), \
                contextlib.redirect_stdout(output):
            worker.main()
        result = json.loads(output.getvalue())
        self.assertTrue(result['ok'])
        self.assertEqual(result['target']['id'], UUID)
        self.assertEqual(result['padding'], native['padding'])
        self.assertNotIn('deliveryContext', result)

    def test_default_json_has_no_context_or_extra_output(self):
        args = SimpleNamespace(device='a' * 64, command='send', dry_run=True, json=True)
        native = {'ok': True, 'target': {'id': UUID}, 'codexHome': '/actual',
                  'deliveryContext': CONTEXT}
        output = io.StringIO()
        with mock.patch.object(cli, 'core_exchange', mock.AsyncMock(return_value=native)), \
                mock.patch.object(cli.core, 'emit_delivery_explanation') as explanation, \
                contextlib.redirect_stdout(output):
            self.assertEqual(cli.invoke_core(args), 0)
        result = json.loads(output.getvalue())
        self.assertNotIn('deliveryContext', result)
        self.assertEqual(result['target'], {'id': UUID})
        self.assertEqual(result['codexHome'], '/actual')
        self.assertFalse(hasattr(args, '_delivery_explanation_context'))
        explanation.assert_not_called()

    def test_real_cli_reports_device_validation_stage(self):
        # Exercise main -> cmd_send -> relay -> actual explanation renderer.
        argv = ['send', '--device', 'a' * 64, '--to', 'alias', '--message', 'fixture',
                '--dry-run', '--explain', '--no-from', '--no-update-notice']
        for result, expected in (({'ok': True, 'status': 'validated', 'dryRun': True,
                                  'deliveryContext': CONTEXT}, 'Validation: passed for this dry run'),
                                 ({'ok': False, 'status': 'unknown', 'retryAllowed': False},
                                  'Validation: result unknown')):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(cli, 'Store'), \
                    mock.patch.object(cli, 'device_credential', return_value=None), \
                    mock.patch.object(cli, 'exchange', mock.AsyncMock(return_value=result)) as exchange, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.core.main(argv)
            self.assertEqual(code, 0 if result['ok'] else 1)
            self.assertIn(expected, out.getvalue() + err.getvalue())
            self.assertNotIn('Destination checks: not run', out.getvalue() + err.getvalue())
            exchange.assert_awaited_once()
        for rejected in ('message', 'credential', 'options'):
            out, err = io.StringIO(), io.StringIO()
            options = [*argv, '--codex-home', '/sender'] if rejected == 'options' else argv
            with mock.patch.object(cli, 'Store'), \
                    mock.patch.object(cli.core, 'check_message',
                                      side_effect=cli.Rejected('invalid_message') if rejected == 'message' else None), \
                    mock.patch.object(cli, 'device_credential',
                                      side_effect=cli.Rejected('login_missing') if rejected == 'credential' else None), \
                    mock.patch.object(cli, 'exchange', mock.AsyncMock()) as exchange, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(cli.core.main(options), 1)
            self.assertIn('Destination checks: not run', out.getvalue() + err.getvalue())
            exchange.assert_not_awaited()


class Negotiation(unittest.IsolatedAsyncioTestCase):
    async def test_core_exchange_requests_context_only_for_explicit_dry_run(self):
        for command, dry_run, explain in (('send', True, True), ('send', True, False),
                                          ('send', False, True), ('list', False, True)):
            args = SimpleNamespace(command=command, dry_run=dry_run, explain=explain,
                                   device='a' * 64, host=None, wake=False, reply_to=None,
                                   b64=False, no_from=True, to='alias', device_state=None,
                                   device_route='auto', agent=None)
            store = mock.Mock()
            with mock.patch.object(cli, 'Store', return_value=store), \
                    mock.patch.object(cli.core, 'read_message', return_value='fixture'), \
                    mock.patch.object(cli.core, 'check_message'), \
                    mock.patch.object(cli, 'device_credential', return_value=None), \
                    mock.patch.object(cli, 'exchange', mock.AsyncMock(return_value={'ok': True})) as exchange:
                await cli.core_exchange(args)
            self.assertEqual(exchange.call_args.kwargs,
                             {'explain': True} if command == 'send' and dry_run and explain else {})
            store.close.assert_called_once()

    async def test_only_explicit_resolve_on_advertising_receiver_gets_flag(self):
        store = mock.Mock(device='a' * 64)
        store.recovery_required.return_value = False
        store.peer.return_value = {'status': 'paired', 'certificate': 'fixture',
                                   'routes': {'direct': '127.0.0.1:1'}}
        peer = 'b' * 64
        for op in ('resolve', 'send', 'list'):
            for explain in (False, True, 1):
                for feature in (False, True):
                    probe = {'ok': True, 'device': peer}
                    if feature:
                        probe['features'] = ['delivery-explanation-v1']
                    native = {'ok': True, 'target': {'id': UUID}, 'codexHome': '/actual',
                              'deliveryContext': CONTEXT}
                    channel = SimpleNamespace(send=mock.AsyncMock(), close=mock.AsyncMock(),
                                              recv=mock.AsyncMock(side_effect=[probe, native]))
                    body = None if op == 'list' else {'target': 'alias', 'message': 'fixture'}
                    with mock.patch.object(app, 'open_channel', mock.AsyncMock(return_value=channel)) as connect:
                        result = await app.exchange(store, peer, op, body, route='direct', explain=explain)
                    connect.assert_awaited_once()
                    sent = [call.args[0] for call in channel.send.await_args_list]
                    self.assertEqual([item['op'] for item in sent], ['probe', op])
                    expected = {**body, 'explain': True} if op == 'resolve' and explain is True and feature else body
                    self.assertEqual(sent[1]['body'], expected)
                    self.assertEqual(result['target'], {'id': UUID})
                    self.assertEqual(result['codexHome'], '/actual')
                    negotiated = op == 'resolve' and explain is True and feature
                    self.assertEqual('deliveryContext' in result, negotiated)
                    if negotiated:
                        self.assertEqual(result['deliveryContext'], CONTEXT)

    async def test_receiver_resolve_only_optional_flag(self):
        from tests.relay.test_message_framing import EffectBoundaries, SENDER, PEER, IDENT
        fixture = EffectBoundaries()
        for op, flag, accepted in (('resolve', True, True), ('resolve', False, False), ('send', True, False)):
            receiver = fixture.receiver()
            body = {'target': 'fixture', 'message': 'fixture', 'explain': flag}
            value = app.request(fixture.store(), PEER, op, body, IDENT)
            if accepted:
                await receiver.dispatch(SENDER, value)
                self.assertTrue(receiver.native.invoke.call_args.kwargs['explain'])
            else:
                with self.assertRaisesRegex(app.Rejected, 'invalid_body'):
                    await receiver.dispatch(SENDER, value)
                receiver.native.invoke.assert_not_called()
