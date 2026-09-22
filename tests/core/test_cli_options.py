"""Explicit CLI input/output aliases preserve native dispatch and results."""
import argparse
import base64
import contextlib
import io
import json
import unittest
from unittest import mock

import session_peer as peer

THREAD = '01900000-0000-7000-8000-000000000001'


class CliOptions(unittest.TestCase):
    def invoke(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = peer.main(list(argv))
        return result, out.getvalue(), err.getvalue()

    def test_output_aliases_for_every_subcommand(self):
        for command in ('list','send','doctor','update'):
            for flags, expected in (([],False),(['--output-format','text'],False),
                                    (['--output-format','json'],True),(['--json'],True),
                                    (['--json','--output-format','json'],True),
                                    (['--output-format','json','--json'],True)):
                with self.subTest(command=command,flags=flags), \
                     mock.patch.object(peer,'cmd_'+command,return_value=0) as handler:
                    args=[command,*flags]
                    if command=='send':args+=['--to','worker','--message','hello']
                    code,_,_=self.invoke(*args)
                    self.assertEqual(code,0)
                    self.assertIs(handler.call_args.args[0].json,expected)

    def test_conflicting_and_invalid_output_formats_fail_before_dispatch(self):
        for flags in (['--json','--output-format','text'],['--output-format','text','--json'],
                      ['--output-format','yaml']):
            with self.subTest(flags=flags), mock.patch.object(peer,'cmd_list') as dispatch, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                peer.main(['list',*flags])
            self.assertEqual(error.exception.code,2)
            dispatch.assert_not_called()

    def test_claude_message_aliases_preserve_exact_utf8_text_and_output(self):
        text='안녕하세요\n"quotes" & $(literal) --json'
        session={'pid':42,'name':'worker','alive':True,'reachable':True,'socket':'/test.sock'}
        for inputs in ([text],['--message',text],['-m',text]):
            with self.subTest(inputs=inputs), mock.patch.object(peer,'discover',return_value=[session]), \
                 mock.patch.object(peer,'post_to_socket') as post:
                code,out,_=self.invoke('send','--to','worker','--no-from','--no-reply-to',
                                       '--output-format','json',*inputs)
                self.assertEqual(code,0)
                self.assertTrue(json.loads(out)['ok'])
                post.assert_called_once_with('/test.sock',text,pid=42)

    def test_codex_named_message_is_text_not_json_input(self):
        payload={'ok':True,'dryRun':False,'target':{'agent':'codex','id':THREAD},
                 'status':'queued','submitted':True,'consumptionConfirmed':False,'queueId':'test-queue'}
        with mock.patch.object(peer,'queue_codex',return_value=payload) as queue:
            code,out,_=self.invoke('send','--to','codex:'+THREAD,'--message','ordinary text',
                                   '--no-from','--no-reply-to','--output-format','json')
        self.assertEqual(code,0)
        self.assertEqual(queue.call_args.args[1],'ordinary text')
        self.assertEqual(json.loads(out)['queueId'],'test-queue')
        self.assertFalse(json.loads(out)['consumptionConfirmed'])

    def test_stdin_modes_preserve_body(self):
        for message,named in ((None,None),('-',None),(None,'-')):
            with self.subTest(message=message,named=named), mock.patch.object(peer.sys,'stdin',io.StringIO('다중\nline\n')):
                args=argparse.Namespace(message=message,message_option=named,b64=None)
                self.assertEqual(peer.read_message(args),'다중\nline\n')

    def test_stdin_named_mode_rejects_terminal(self):
        with mock.patch.object(peer.sys,'stdin') as stdin:
            stdin.isatty.return_value=True
            with self.assertRaisesRegex(peer.CcPeerError,'terminal'):
                peer.read_message(argparse.Namespace(message=None,message_option='-',b64=None))
            stdin.read.assert_not_called()

    def test_conflicting_inputs_fail_before_stdin_and_submission(self):
        for inputs in (['positional','--message','named'],['','--message',''],
                       ['-','-m','-'],['--b64','eA==','-m','hello'],['--b64','eA==','legacy']):
            with self.subTest(inputs=inputs), mock.patch.object(peer.sys,'stdin') as stdin, \
                 mock.patch.object(peer,'queue_codex') as queue, mock.patch.object(peer,'run_remote') as remote:
                code,out,_=self.invoke('send','--to','codex:'+THREAD,'--output-format','json',*inputs)
            self.assertEqual(code,1)
            self.assertFalse(json.loads(out)['ok'])
            self.assertIn('one message source',json.loads(out)['error'])
            stdin.read.assert_not_called();queue.assert_not_called();remote.assert_not_called()

    def test_empty_named_message_is_rejected_without_envelope(self):
        with mock.patch.object(peer,'queue_codex') as queue:
            code,out,_=self.invoke('send','--to','codex:'+THREAD,'-m','','--output-format','json')
        self.assertEqual(code,1)
        self.assertFalse(json.loads(out)['ok'])
        queue.assert_not_called()

    def test_remote_aliases_produce_same_encoded_text(self):
        text='remote\n한글 "text"'
        results=[]
        for inputs,output in (([text],['--json']),(['-m',text],['--output-format','json'])):
            with mock.patch.object(peer,'tailscale_status',return_value=None), \
                 mock.patch.object(peer,'run_remote',return_value={'target':{'pid':42,'name':'worker'}}) as remote:
                code,body,_=self.invoke('send','--host','user@worker','--to','worker','--no-from','--no-reply-to',*output,*inputs)
            self.assertEqual(code,0)
            argv=remote.call_args.args[1]
            self.assertEqual(base64.b64decode(argv[argv.index('--b64')+1]).decode(),text)
            results.append(json.loads(body))
        self.assertEqual(results[0],results[1])

    def test_human_dry_run_and_dash_prefixed_named_body(self):
        session={'pid':42,'name':'worker','alive':True,'reachable':True,'socket':'/test.sock'}
        with mock.patch.object(peer,'discover',return_value=[session]), mock.patch.object(peer,'post_to_socket') as post:
            code,out,_=self.invoke('send','--to','worker','--message=--json','--output-format','text',
                                   '--dry-run','--no-from','--no-reply-to')
        self.assertEqual(code,0)
        self.assertIn('Would post',out)
        post.assert_not_called()

    def test_help_explains_output_and_message_scope(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            peer.main(['send','--help'])
        text=' '.join(out.getvalue().split())
        self.assertIn('--output-format {text,json}',text)
        self.assertIn('--message',text)
        self.assertIn('-m TEXT',text)
        self.assertIn('does not change message input',text)
