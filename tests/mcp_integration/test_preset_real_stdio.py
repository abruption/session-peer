"""Real preset-reader/stdin protocol integration; synthetic owned Claude inbox only.

The positive secure-store cell may skip locally for verified external ancestor
or ownership-enforcement limitations. Supported CI cells must run it. No owner,
ACL, mount or symlink guard is patched.
Separate race cells explicitly use a validated synthetic snapshot and make no
claim that such a snapshot establishes private-store acceptance.
"""
import asyncio
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

import session_peer as core
import session_peer_mcp as peer

LOCAL_ROUTE = {'transport': 'local', 'agent': 'claude'}
STORE_DOCUMENT = {'schemaVersion': 1, 'presets': {'work': LOCAL_ROUTE}}
SUPPORTED = os.name == 'posix' and sys.platform in ('darwin', 'linux')


@unittest.skipUnless(importlib.util.find_spec('mcp') and SUPPORTED,
                     'optional MCP SDK and macOS/Linux Unix inbox required')
class RealPresetStdio(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='codex-359-', dir=os.environ.get('SESSION_PEER_TEST_TMP'))
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.root.chmod(0o700)
        self.home = self.root / 'h'
        self.home.mkdir(mode=0o700)
        self.xdg = self.root / 'x'
        self.xdg.mkdir(mode=0o700)
        self.app = self.xdg / 'session-peer'
        self.store = self.app / 'destinations.json'
        self.claude = self.root / 'c'
        self.claude.mkdir(mode=0o700)
        self.sessions = self.claude / 'sessions'
        self.sessions.mkdir(mode=0o700)
        self.policy = self.root / 'policy.json'
        self.policy.write_text(json.dumps({'schemaVersion': 2, 'destinations': {'local': {
            'agents': ['claude'], 'capabilities': ['presets', 'list', 'preflight', 'send'],
            'presets': ['work']}}}))
        self.policy.chmod(0o600)
        self.environment = {**os.environ, 'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.xdg),
                            'CLAUDE_CONFIG_DIR': str(self.claude)}
        # Do not let the synthetic source CLI inherit another agent's identity
        # or a collection of additional Claude profiles from this workstation.
        for key in ('CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'CLAUDE_SESSION_ID',
                    'CLAUDE_CODE_SESSION_ID', 'SESSION_PEER_REPLY_HOST', 'CC_PEER_REPLY_HOST'):
            self.environment.pop(key, None)

    def write_store(self):
        self.app.mkdir(mode=0o700)
        self.store.write_text(json.dumps(STORE_DOCUMENT))
        self.store.chmod(0o600)

    def read_real_store(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.xdg)}):
            return core.preset_read()

    @contextlib.asynccontextmanager
    async def client(self, wrapper=None):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        args = ([str(Path(peer.__file__).resolve()), '--config', str(self.policy)] if wrapper is None
                else [str(wrapper), str(self.policy)])
        params = StdioServerParameters(command=sys.executable, args=args,
                                       cwd=str(self.root), env=self.environment)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client

    @contextlib.asynccontextmanager
    async def inbox(self):
        received = []
        arrived = asyncio.Event()
        async def accept(reader, writer):
            try:
                received.append(json.loads(await reader.readline()))
                arrived.set()
            finally:
                writer.close()
                await writer.wait_closed()
        path = self.root / 'i'
        server = await asyncio.start_unix_server(accept, str(path))
        record = self.sessions / (str(os.getpid()) + '.json')
        record.write_text(json.dumps({'pid': os.getpid(), 'name': 'preset-fixture',
                                      'messagingSocketPath': str(path)}))
        record.chmod(0o600)
        try:
            yield received, arrived
        finally:
            server.close()
            await server.wait_closed()

    @staticmethod
    def storage_snapshot(root):
        # Never follow links while checking preservation of fixture storage.
        result = {}
        for path in [root, *root.rglob('*')]:
            info = path.lstat()
            value = (stat.S_IMODE(info.st_mode), info.st_ino, info.st_mtime_ns)
            if stat.S_ISLNK(info.st_mode):
                value += (os.readlink(path),)
            elif stat.S_ISREG(info.st_mode):
                value += (path.read_bytes(),)
            result[str(path.relative_to(root))] = value
        return result

    async def test_real_secure_store_and_stdio_selection_preserve_native_json_and_post_once(self):
        self.write_store()
        try:
            snapshot = self.read_real_store()
        except core.CcPeerError as error:
            # First prove that the private fixture itself meets the contract.
            # A local-volume classification never excuses a malformed fixture.
            for path in (self.root, self.xdg, self.app):
                info = path.lstat()
                self.assertTrue(stat.S_ISDIR(info.st_mode))
                self.assertEqual(stat.S_IMODE(info.st_mode), 0o700)
                self.assertEqual(info.st_uid, os.geteuid())
            info = self.store.lstat()
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertEqual(info.st_uid, os.geteuid())
            # Supported CI must exercise the real positive path; unexpected
            # native guard refusals fail there rather than becoming green skips.
            if os.environ.get('GITHUB_ACTIONS', '').lower() != 'true':
                reason = error.details.get('reason')
                if reason == 'preset_ownership_unenforced':
                    self.skipTest('local real secure-store positive unavailable: volume ownership disabled; guards unchanged')
                if reason == 'preset_unsafe_storage':
                    for ancestor in self.root.parents:
                        metadata = ancestor.stat()
                        unsafe = metadata.st_mode & 0o022
                        sticky_root = metadata.st_uid == 0 and metadata.st_mode & stat.S_ISVTX
                        if unsafe and not sticky_root:
                            self.skipTest('local real secure-store positive unavailable: external ancestor mode '
                                + oct(stat.S_IMODE(metadata.st_mode)) + ' is group/other-writable; guards unchanged')
            raise
        self.assertEqual(snapshot, {'work': LOCAL_ROUTE})
        revision = core.preset_revision('work', LOCAL_ROUTE)
        before = self.storage_snapshot(self.xdg)
        async with self.inbox() as (received, arrived), self.client() as client:
            metadata = await client.call_tool('list_presets', {'destination': 'local'})
            self.assertFalse(metadata.isError)
            self.assertEqual(metadata.structuredContent['presets'], [{'name': 'work', 'revision': revision,
                'transport': 'local', 'agent': 'claude'}])
            listing = await client.call_tool('list_sessions', {'destination': 'local', 'preset': 'work'})
            self.assertFalse(listing.isError)
            self.assertEqual(listing.structuredContent['command'], 'list')
            self.assertEqual(listing.structuredContent['schemaVersion'], 1)
            self.assertNotIn('preset', listing.structuredContent)
            self.assertTrue(any(row.get('pid') == os.getpid() for row in listing.structuredContent['sessions']))
            preflight = await client.call_tool('preflight_send', {'destination': 'local', 'preset': 'work',
                'target': 'preset-fixture', 'message': 'synthetic preflight body'})
            self.assertFalse(preflight.isError)
            self.assertEqual(preflight.structuredContent['preset']['revision'], revision)
            self.assertEqual(received, [])
            sent = await client.call_tool('send_message', {'destination': 'local', 'preset': 'work',
                'preset_revision': revision, 'target': 'preset-fixture', 'message': 'synthetic actual inbox body'})
            self.assertFalse(sent.isError)
            self.assertEqual(sent.structuredContent['command'], 'send')
            self.assertEqual(sent.structuredContent['schemaVersion'], 1)
            self.assertNotIn('preset', sent.structuredContent)
            await asyncio.wait_for(arrived.wait(), 2)
            self.assertEqual(len(received), 1)
            self.assertIn('synthetic actual inbox body', received[0]['message']['content'])
        self.assertEqual(self.storage_snapshot(self.xdg), before)

    async def test_real_negative_storage_refusals_preserve_missing_unsafe_and_symlink_cases(self):
        # An external ancestor or mount guard may refuse before the later
        # file-mode/symlink guards. Report the actual reason without claiming
        # those later guards were reached; internal CI can exercise them.
        observations = {}
        for case in ('missing', 'unsafe_file_mode', 'symlink'):
            with self.subTest(case=case):
                if self.app.exists():
                    if self.store.is_symlink() or self.store.exists():
                        self.store.unlink()
                    self.app.rmdir()
                target = self.root / 'target.json'
                if case != 'missing':
                    self.app.mkdir(mode=0o700)
                    if case == 'unsafe_file_mode':
                        self.store.write_text(json.dumps(STORE_DOCUMENT))
                        self.store.chmod(0o644)
                    else:
                        target.write_text(json.dumps(STORE_DOCUMENT))
                        target.chmod(0o600)
                        self.store.symlink_to(target)
                before = self.storage_snapshot(self.xdg)
                target_before = target.read_bytes() if target.exists() else None
                try:
                    self.assertEqual(self.read_real_store(), {})
                    self.assertEqual(case, 'missing', 'unsafe fixture must never be accepted')
                    observations[case] = 'missing_snapshot'
                except core.CcPeerError as error:
                    observations[case] = error.details.get('reason')
                    self.assertIn(observations[case], ('preset_ownership_unenforced', 'preset_unsafe_storage',
                        'preset_unsafe_acl', 'preset_acl_unverifiable', 'preset_mount_unverifiable'))
                async with self.client() as client:
                    value = await client.call_tool('list_presets', {'destination': 'local'})
                    self.assertTrue(value.isError)
                    self.assertEqual(value.structuredContent['reason'], 'preset_storage_unavailable')
                    self.assertNotIn(str(self.xdg), value.content[0].text)
                    self.assertNotIn(str(target), value.content[0].text)
                self.assertEqual(self.storage_snapshot(self.xdg), before)
                self.assertFalse((self.app / 'destinations.lock').exists())
                if target_before is not None:
                    self.assertEqual(target.read_bytes(), target_before)
        for case, reason in observations.items():
            detail = ('ownership-disabled mount refused; later file-specific guard not reached'
                      if reason == 'preset_ownership_unenforced' else
                      'observed ' + str(reason) + '; file preservation verified, internal refusal stage not asserted')
            print('preset integration ' + case + ': ' + detail, file=sys.stderr)

    def race_wrapper(self, *, revoke_policy):
        wrapper = self.root / 'race.py'
        # Validated synthetic read ONLY for race semantics on any volume. The
        # real secure-store positive/negative cells above never patch this path.
        wrapper.write_text('import sys, os\n'
            + 'sys.path.insert(0, ' + repr(str(Path(peer.__file__).resolve().parent)) + ')\n'
            + 'import session_peer_mcp as peer\n'
            + 'document = ' + repr(STORE_DOCUMENT) + '\n'
            + 'def snapshot():\n    return peer.core._preset_decode(peer.json.dumps(document).encode())\n'
            + 'peer.core.preset_read = snapshot\n'
            + 'original_lookup = peer.core.preset_lookup\n'
            + 'adapter = peer.Adapter(peer.load_policy(sys.argv[1]))\n'
            + 'def lookup(name):\n    result = original_lookup(name)\n'
            + ('    adapter.destinations["local"]["capabilities"].remove("send")\n' if revoke_policy else
               '    document["presets"]["work"] = {"transport":"ssh", "agent":"claude", "host":"never-connect.invalid"}\n')
            + '    return result\n'
            + 'peer.core.preset_lookup = lookup\n'
            + ('async def forbidden(*a, **k):\n    os._exit(94)\nadapter.invoke = forbidden\n' if revoke_policy else
               'original_invoke = adapter.invoke\nasync def local_only(argv, message=None):\n'
               '    if "--host" in argv or "--preset" in argv:\n        os._exit(94)\n'
               '    return await original_invoke(argv, message)\nadapter.invoke = local_only\n')
            + 'peer.create_server(adapter).run(transport="stdio")\n')
        wrapper.chmod(0o600)
        return wrapper

    async def test_stdio_policy_revocation_after_snapshot_denies_before_any_invoke(self):
        wrapper = self.race_wrapper(revoke_policy=True)
        async with self.client(wrapper) as client:
            value = await client.call_tool('send_message', {'destination': 'local', 'preset': 'work',
                'preset_revision': core.preset_revision('work', LOCAL_ROUTE), 'target': 'preset-fixture',
                'message': 'must never invoke'})
            self.assertTrue(value.isError)
            self.assertFalse(value.structuredContent['ok'])
            self.assertEqual(value.structuredContent['reason'], 'request_rejected')
            # The forbidden invoker exits the process; this second successful
            # exchange proves no invoke occurred and no process was replaced.
            inventory = await client.call_tool('list_destinations', {})
            self.assertFalse(inventory.isError)

    async def test_stdio_later_snapshot_mutation_does_not_cancel_expanded_local_route(self):
        wrapper = self.race_wrapper(revoke_policy=False)
        async with self.inbox() as (received, arrived), self.client(wrapper) as client:
            sent = await client.call_tool('send_message', {'destination': 'local', 'preset': 'work',
                'preset_revision': core.preset_revision('work', LOCAL_ROUTE), 'target': 'preset-fixture',
                'message': 'expanded local snapshot body'})
            self.assertFalse(sent.isError)
            self.assertEqual(sent.structuredContent['command'], 'send')
            self.assertEqual(sent.structuredContent['schemaVersion'], 1)
            self.assertNotIn('preset', sent.structuredContent)
            await asyncio.wait_for(arrived.wait(), 2)
            self.assertEqual(len(received), 1)
            self.assertIn('expanded local snapshot body', received[0]['message']['content'])
