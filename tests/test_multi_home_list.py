"""Multi-home inventory, partial discovery and authorization boundaries."""
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
import session_peer_mcp as adapter

THREAD = '01900000-0000-7000-8000-000000000001'


class MultiHome(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.default = self.root/'.codex'
        self.orca = self.root/'Library/Application Support/orca/codex-accounts'
        self.args = argparse.Namespace(codex_home=None, agent='codex', all=False)
        for patcher in (mock.patch.object(Path,'home',return_value=self.root),
                        mock.patch.dict(os.environ),
                        mock.patch.object(peer,'agy_registrations',return_value=[])):
            patcher.start(); self.addCleanup(patcher.stop)
        os.environ.pop('CODEX_HOME',None)
        os.environ.pop('SESSION_PEER_CODEX_HOMES',None)

    def database(self, home, updated=1, archived=0):
        home.mkdir(parents=True,exist_ok=True)
        with contextlib.closing(sqlite3.connect(home/'state_5.sqlite')) as conn:
            conn.execute('CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)')
            conn.execute('INSERT INTO threads VALUES (?,?,?,?,?,?)',(THREAD,'test','/project',updated,archived,'/unused'))
            conn.commit()
        return home

    def listing(self):
        return peer.collect_listing(self.args)

    def test_all_sources_duplicate_uuids_and_deterministic_sort(self):
        default=self.database(self.default,2)
        env=self.database(self.root/'environment',4)
        orca=self.database(self.orca/'account'/'home',3)
        extra=self.database(self.root/'extra',2)
        os.environ['CODEX_HOME']=str(env)
        os.environ['SESSION_PEER_CODEX_HOMES']=json.dumps([str(extra)])
        with mock.patch.object(peer.sys,'platform','darwin'):
            result=self.listing()
        self.assertTrue(result['ok'])
        self.assertEqual([r['codexHome'] for r in result['sessions']],
                         [str(env),str(orca),*sorted([str(default),str(extra)])])
        self.assertEqual(len(result['sessions']),4)
        for row in result['sessions']:
            self.assertEqual(row['id'],THREAD)
            self.assertEqual(row['agent'],'codex')
            self.assertEqual(row['stateDb'],str(Path(row['codexHome'])/'state_5.sqlite'))
            self.assertNotIn('alive',row)
        self.assertNotIn('codexHome',result)

    def test_aliases_merge_sources_but_configured_missing_is_required(self):
        self.database(self.default)
        alias=self.root/'alias'
        try:alias.symlink_to(self.default,target_is_directory=True)
        except OSError:self.skipTest('symlinks unavailable')
        os.environ['CODEX_HOME']=str(alias)
        os.environ['SESSION_PEER_CODEX_HOMES']=json.dumps([str(alias),str(self.default)])
        result=self.listing()
        self.assertEqual(len(result['sessions']),1)
        self.assertEqual(result['discovery']['codex']['homes'][0]['sources'],
                         ['default','environment','configured'])
        self.assertEqual(result['codexHome'],str(self.default))

    def test_explicit_bypasses_inventory_and_invalid_config(self):
        selected=self.database(self.root/'selected')
        self.database(self.default)
        self.args.codex_home=str(selected)
        os.environ['SESSION_PEER_CODEX_HOMES']='invalid json'
        with mock.patch.object(Path,'iterdir',side_effect=PermissionError('must not enumerate')):
            result=self.listing()
        self.assertTrue(result['ok'])
        self.assertEqual([r['codexHome'] for r in result['sessions']],[str(selected)])

    def test_not_installed_is_success_but_explicit_missing_is_error(self):
        result=self.listing()
        self.assertTrue(result['ok'])
        self.assertEqual(result['discovery']['codex']['status'],'not_installed')
        self.assertEqual(result['sessions'],[])
        for mode in ('argument','environment','configured'):
            with self.subTest(mode=mode), mock.patch.dict(os.environ):
                self.args.codex_home=None
                if mode=='argument':self.args.codex_home=str(self.default)
                elif mode=='environment':os.environ['CODEX_HOME']=str(self.default)
                else:os.environ['SESSION_PEER_CODEX_HOMES']=json.dumps([str(self.default)])
                result=self.listing()
                self.assertFalse(result['ok'])
                self.assertEqual(result['discovery']['codex']['homes'][0]['code'],'state_db_missing')

    def test_corrupt_schema_and_invalid_timestamp_keep_good_rows(self):
        self.database(self.default)
        corrupt=self.root/'corrupt';corrupt.mkdir();(corrupt/'state_5.sqlite').write_bytes(b'not sqlite')
        schema=self.root/'schema';schema.mkdir();sqlite3.connect(schema/'state_5.sqlite').close()
        invalid=self.database(self.root/'invalid',updated='bad timestamp')
        os.environ['SESSION_PEER_CODEX_HOMES']=json.dumps([str(corrupt),str(schema),str(invalid)])
        result=self.listing()
        self.assertFalse(result['ok'])
        self.assertEqual(len(result['sessions']),1)
        self.assertEqual([h['status'] for h in result['discovery']['codex']['homes']],['ok','error','error','error'])

    def test_orca_enumeration_failure_and_invalid_config_preserve_default(self):
        self.database(self.default)
        os.environ['SESSION_PEER_CODEX_HOMES']='{"not":"array"}'
        with mock.patch.object(peer.sys,'platform','darwin'), \
             mock.patch.object(Path,'iterdir',side_effect=PermissionError('denied')):
            result=self.listing()
        self.assertFalse(result['ok'])
        self.assertEqual(len(result['sessions']),1)
        self.assertEqual({e['code'] for e in result['discovery']['codex']['errors']},
                         {'candidate_enumeration_failed','invalid_home_configuration'})

    def test_permission_failure_in_one_db_keeps_other_and_claude(self):
        self.database(self.default)
        blocked=self.database(self.root/'blocked')
        os.environ['SESSION_PEER_CODEX_HOMES']=json.dumps([str(blocked)])
        original=Path.stat
        def stat(path,*args,**kwargs):
            if path==blocked/'state_5.sqlite':raise PermissionError('denied')
            return original(path,*args,**kwargs)
        self.args.agent=None
        with mock.patch.object(Path,'stat',stat), mock.patch.object(peer,'discover',return_value=[{'pid':7, 'reachable':True, 'alive':True, 'name':'worker'}]):
            result=self.listing()
        self.assertEqual([s['agent'] for s in result['sessions']],['claude','codex'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['discovery']['codex']['homes'][1]['code'],'permission_denied')

    def test_path_resolution_failure_is_partial_and_not_canonicalized_falsely(self):
        self.database(self.default)
        bad=self.root/'bad'
        os.environ['SESSION_PEER_CODEX_HOMES']=json.dumps([str(bad)])
        original=Path.resolve
        def resolve(path,*args,**kwargs):
            if path==bad:raise RuntimeError('symlink loop')
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'resolve',resolve):result=self.listing()
        self.assertFalse(result['ok'])
        self.assertEqual(len(result['sessions']),1)
        self.assertEqual(result['discovery']['codex']['errors'][0]['code'],'home_resolution_failed')

    def test_archived_filter_and_optional_absent_orca_home(self):
        self.database(self.default,archived=1)
        (self.orca/'unused'/'home').mkdir(parents=True)
        with mock.patch.object(peer.sys,'platform','darwin'):
            result=self.listing()
            self.assertEqual(result['sessions'],[])
            self.assertEqual(result['discovery']['codex']['status'],'ok')
            self.assertEqual(result['discovery']['codex']['homes'][1]['status'],'absent')
            self.args.all=True
            self.assertEqual(len(self.listing()['sessions']),1)

    def test_claude_filter_never_inventories_codex(self):
        self.args.agent='claude'
        with mock.patch.object(peer,'codex_listing_candidates') as inventory, \
             mock.patch.object(peer,'discover',return_value=[]):
            result=self.listing()
        inventory.assert_not_called();self.assertTrue(result['ok'])

    def test_remote_source_runs_using_destination_environment(self):
        self.database(self.default)
        remote_home=self.database(self.root/'remote-user'/'codex')
        env=dict(os.environ,CODEX_HOME=str(remote_home),SESSION_PEER_CODEX_HOMES=json.dumps([str(self.default)]))
        # Execute exactly the source-stream entry point used over SSH, with a
        # destination environment. Pin its HOME/USERPROFILE, not the caller's.
        env.update(HOME=str(self.root/'remote-user'),USERPROFILE=str(self.root/'remote-user'))
        done=subprocess.run([sys.executable,'-','list','--agent','codex','--json','--no-update-notice'],
                            input=Path(peer.__file__).read_text(),capture_output=True,text=True,env=env,timeout=10)
        result=json.loads(done.stdout)
        self.assertEqual(done.returncode,0,done.stdout)
        self.assertEqual({s['codexHome'] for s in result['sessions']},{str(remote_home),str(self.default)})

    def test_remote_envelope_keeps_home_diagnostics(self):
        self.database(self.default)
        listing=self.listing()
        payload=peer.json_result('list',listing)
        output=io.StringIO()
        with mock.patch.object(peer,'tailscale_status',return_value=None), \
             mock.patch.object(peer,'run_remote',return_value=payload), \
             mock.patch.object(peer,'remote_installed_version',return_value=peer.__version__), \
             contextlib.redirect_stdout(output):
            code=peer.main(['list','--host','user@a','--host','other@b','--json','--no-update-notice'])
        self.assertEqual(code,0)
        results=json.loads(output.getvalue())
        self.assertEqual(len(results),2)
        for result in results:
            self.assertEqual(result['discovery'],listing['discovery'])
            self.assertEqual(result['sessions'],listing['sessions'])


class McpBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_mcp_destination_cannot_expand_to_other_homes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            for name in ('allowed','outside'):
                home=root/name;home.mkdir()
                with contextlib.closing(sqlite3.connect(home/'state_5.sqlite')) as conn:
                    conn.execute('CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)')
                    conn.execute('INSERT INTO threads VALUES (?,?,?,?,?,?)',(THREAD,name,'/project',1,0,'/unused'))
                    conn.commit()
            server=adapter.Adapter({'local':{'agents':['codex'],'capabilities':['list'],'codexHome':str(root/'allowed')}})
            with mock.patch.dict(os.environ,{'CODEX_HOME':str(root/'outside'),'SESSION_PEER_CODEX_HOMES':json.dumps([str(root/'outside')])}):
                result=await server.list_sessions()
            self.assertTrue(result['ok'])
            self.assertEqual([s['codexHome'] for s in result['sessions']],[str(root/'allowed')])
            self.assertEqual(len(result['discovery']['codex']['homes']),1)
