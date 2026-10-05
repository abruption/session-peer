"""SSH argument boundary regressions; no network connections."""
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import session_peer as cli


class SshSecurity(unittest.TestCase):
    def test_every_ssh_entrypoint_rejects_config_and_execution_options(self):
        cases = [
            ['-F', '/fixture/config'], ['-F/fixture/config'],
            ['-o', 'KnownHostsCommand=echo ignored'],
            ['-okNoWnHoStScOmMaNd=echo ignored'],
            ['-o', 'PKCS11Provider=/fixture/provider'],
            ['-oSecurityKeyProvider=/fixture/provider'],
            ['-oInclude=/fixture/config'], ['-oMatch=exec true'],
            ['-oProxyCommand=true'], ['-oLocalCommand=true'],
            ['-oPermitLocalCommand=yes'], ['-oProxyUseFdpass=yes'],
            ['-S', '/fixture/socket'], ['-E', '/fixture/log'],
            ['-oControlPath=/fixture/socket'], ['-oControlMaster=auto'],
            ['-oRemoteCommand=true'], ['-L8080:localhost:80'],
            ['-o', 'UserKnownHostsFile=/fixture/target'],
            ['-oUsErKnOwNhOsTsFiLe=/fixture/target'],
            ['-oStrictHostKeyChecking=no'], ['-o', 'StrictHostKeyChecking=OFF'],
            ['-oBatchMode=yes\nKnownHostsCommand=true'],
            ['-J', 'host;true'], ['-p'], ['-o'], ['fixture'],
        ]
        for host in ('fixture.invalid', 'user@fixture.invalid'):
            for options in cases:
                operations = (
                    lambda: cli.ssh_user_metadata(host, options),
                    lambda: cli.run_remote(host, ['list'], options),
                    lambda: cli.push_to_remote(host, options),
                    lambda: cli.remote_installed_version(host, options),
                    lambda: cli.push_to_remote(host, options, {}),
                    lambda: cli.remote_installed_version(host, options, {}),
                )
                for operation in operations:
                    with self.subTest(host=host, options=options), mock.patch.object(cli.subprocess, 'run') as run:
                        with self.assertRaises(cli.CcPeerError):
                            operation()
                        run.assert_not_called()

    def test_allowlist_preserves_split_and_attached_connection_options(self):
        options = ['-4', '-6', '-p', '2222', '-p2222', '-l', 'user', '-luser',
                   '-i', '/fixture/key with spaces', '-i/fixture/key',
                   '-J', 'user@bastion:22,[::1]:2222', '-Jbastion',
                   '-o', 'BatchMode=yes', '-oConnectTimeout=8',
                   '-oServerAliveInterval=20', '-oServerAliveCountMax=3',
                   '-oStrictHostKeyChecking=accept-new', '-oIdentitiesOnly=yes',
                   '-oHostName=100.64.0.1',
                   '-oHostKeyAlias=fixture', '-oProxyJump=bastion']
        cli.check_ssh_options(options)

    def test_known_hosts_target_is_unchanged_when_write_options_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / 'target'
            target.write_bytes(b'existing fixture contents\n')
            options = ['-oUserKnownHostsFile='+str(target),
                       '-oStrictHostKeyChecking=accept-new', '-oHostKeyAlias=chosenword']
            with mock.patch.object(cli.subprocess, 'run') as run:
                with self.assertRaises(cli.CcPeerError):
                    cli.run_remote('nobody-x@127.0.0.1', ['list'], options)
                run.assert_not_called()
            self.assertEqual(target.read_bytes(), b'existing fixture contents\n')

    def test_explicit_host_key_checking_preserves_verification(self):
        for value in ('yes', 'ask', 'accept-new', 'YES'):
            with self.subTest(value=value):
                cli.check_ssh_options(['-o', 'StrictHostKeyChecking='+value])

    @unittest.skipUnless(shutil.which('ssh'), 'requires OpenSSH for offline -G regression')
    def test_config_match_exec_cannot_run_during_metadata_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            marker = root / 'executed'
            config = root / 'config'
            config.write_text('Match exec "touch ' + str(marker) + '"\n  User fixture\n')
            blocked = False
            try:
                cli.ssh_user_metadata('fixture.invalid', ['-F', str(config)])
            except cli.CcPeerError:
                blocked = True
            self.assertFalse(marker.exists())
            self.assertTrue(blocked)

    def test_host_is_a_single_destination_not_option_or_shell_syntax(self):
        for host in ('', '-Fconfig', 'host other', 'host\nother', 'host;true', 'host`true`', 'host$(true)'):
            with self.subTest(host=host), mock.patch.object(cli.subprocess, 'run') as run:
                with self.assertRaises(cli.CcPeerError):
                    cli.ssh_user_metadata(host, [])
                run.assert_not_called()
