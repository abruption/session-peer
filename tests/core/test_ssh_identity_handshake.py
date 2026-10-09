"""Optional native OpenSSH handshake against an owned in-memory fixture.

No real accounts/configuration/agents. Fixture host private keys live in memory
only. Paramiko is a test-only optional dependency, never a runtime requirement.
"""
import base64
import hashlib
import json
import os
import shutil
import socket
import threading
import unittest
from unittest import mock

import session_peer as peer
try:
    import paramiko
except ImportError:
    paramiko = None


@unittest.skipUnless(paramiko is not None and shutil.which("ssh") and not peer.IS_WINDOWS,
                     "optional Paramiko + POSIX OpenSSH handshake fixture")
class NativeSshIdentity(unittest.TestCase):
    def connect(self, expected):
        key = paramiko.RSAKey.generate(2048)
        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        required = fingerprint if expected == "correct" else "SHA256:" + "A" * 43
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(15)
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        facts = {"auth": 0, "exec": 0, "completed": False}
        errors = []
        started = threading.Event()
        class Fixture(paramiko.ServerInterface):
            def check_auth_none(self, username):
                facts["auth"] += 1
                return paramiko.AUTH_SUCCESSFUL
            def check_channel_request(self, kind, channel_id):
                return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            def check_channel_exec_request(self, channel, command):
                facts["exec"] += 1
                started.set()
                return True
        def serve():
            transport = None
            try:
                connection, _ = listener.accept()
                with connection:
                    transport = paramiko.Transport(connection)
                    transport.add_server_key(key)
                    transport.start_server(server=Fixture())
                    channel = transport.accept(10)
                    if channel is not None:
                        with channel:
                            if not started.wait(10):
                                raise RuntimeError("fixture exec deadline")
                            channel.settimeout(10)
                            while channel.recv(32768):
                                pass  # Discard streamed source; NEVER execute it.
                            response = {"schemaVersion": 1, "command": "send", "ok": True,
                                        "target": {"pid": 123, "name": "fixture"}, "chars": 4}
                            channel.sendall(json.dumps(response).encode() + b"\n")
                            channel.send_exit_status(0)
                            facts["completed"] = True
            except (EOFError, paramiko.SSHException, ConnectionResetError):
                pass  # Expected when strict host-key pin refuses before auth.
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                if transport is not None:
                    transport.close()
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        original = peer._run_remote_dispatch
        def isolated_dispatch(host, argv, options, *, identity_options):
            fixed = ["-F", os.devnull, "-oPreferredAuthentications=none",
                     "-oIdentityAgent=none", "-oIdentityFile=none", "-oBatchMode=yes",
                     "-oConnectTimeout=5", "-oLogLevel=ERROR", *identity_options]
            return original(host, argv, options, identity_options=fixed)
        result = error = None
        # Paramiko's expected disconnect diagnostics do not need stdout.
        with mock.patch.object(peer, "ssh_identity_configuration",
                               return_value={"destination": "127.0.0.1", "port": port, "keyLookupName": "fixture"}), \
                mock.patch.object(peer, "ssh_user_metadata", return_value={"sshUser": "fixture", "sshUserSource": "fixture"}), \
                mock.patch.object(peer, "_run_remote_dispatch", side_effect=isolated_dispatch):
            try:
                result = peer.run_remote_with_identity("fixture@127.0.0.1", ["send"], ["-p", str(port)], required)
            except peer.CcPeerError as exc:
                error = exc
        worker.join(16)
        self.assertFalse(worker.is_alive(), "owned fixture did not stop")
        self.assertEqual(errors, [])
        return result, error, facts, fingerprint

    def test_actual_callback_same_key_and_changed_key_before_remote_exec(self):
        result, error, facts, fingerprint = self.connect("correct")
        self.assertIsNone(error, str(error))
        self.assertEqual(result["sshIdentity"]["fingerprint"], fingerprint)
        self.assertEqual(result["sshIdentity"]["status"], "verified")
        self.assertEqual(facts, {"auth": 1, "exec": 1, "completed": True})
        result, error, facts, _ = self.connect("wrong")
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertEqual(error.details["sshIdentity"]["status"], "refused")
        self.assertEqual(error.details["reason"], "ssh_host_key_mismatch")
        self.assertEqual(error.details["status"], "refused")
        self.assertFalse(error.details["submitted"])
        self.assertEqual(facts, {"auth": 0, "exec": 0, "completed": False})


if __name__ == "__main__":
    unittest.main()
