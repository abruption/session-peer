"""Opt-in actual Codex 0.154.0 environment builders, without models or wakes.

Set SESSION_PEER_CODEX154_ENV_BINARY to the pre-provisioned macOS arm64 binary.
No download/install occurs. An explicit wrong binary fails rather than skips.
The only RPCs are initialize, command/exec (env metadata), mcpServerStatus/list.
No user home, credentials, thread, turn, prompt, model or MCP tool call is used.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE_COMMIT = "6b9826e3aa83b1a5947db50f4332cb9c65f1b340"
RELEASE_ARCHIVE_SHA256 = "344310a0a591c1b192e04feff304321a69907c9498baaac331ca7e16ebcef9d7"
BINARY_SHA256 = "4f85982624b3898c8991cb80c0981b2aa71070e3537046c9a95950318a95afcc"
BINARY_OPTION = "SESSION_PEER_CODEX154_ENV_BINARY"
MARKERS = {"SESSION_PEER_WAKE_DEPTH": "1", "SESSION_PEER_WAKE_MAX_DEPTH": "3",
           "SESSION_PEER_WAKE_ORIGIN": "00000000-0000-4000-8000-000000000001"}


@unittest.skipUnless(os.environ.get(BINARY_OPTION), "explicit pinned native environment fixture not configured")
class NativeWakeEnvironment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "darwin" or platform.machine() != "arm64":
            raise AssertionError("this executable proof is pinned to macOS arm64, not other platforms")
        cls.binary = Path(os.environ[BINARY_OPTION]).resolve(strict=True)
        info = cls.binary.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in (0, os.getuid()):
            raise AssertionError("unsafe explicitly selected native fixture binary")
        with cls.binary.open("rb") as source:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != BINARY_SHA256:
            raise AssertionError("explicit native binary does not match pinned release asset")

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="codex-native-wake-env-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "CODEX_HOME": str(self.home),
                            "ORDINARY_TEST": "ordinary", "NODE_REPL_AUTH_TOKEN": "synthetic-not-a-token", **MARKERS}

    def request(self, process, request, buffers):
        process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        process.stdin.flush()
        deadline = time.monotonic() + 10
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while time.monotonic() < deadline:
                while b"\n" in buffers["stdout"]:
                    line, _, rest = buffers["stdout"].partition(b"\n")
                    buffers["stdout"] = bytearray(rest)
                    response = json.loads(line.decode("utf-8"))
                    if response.get("id") == request["id"]:
                        self.assertNotIn("error", response)
                        return response["result"]
                for key, _ in selector.select(max(0, deadline - time.monotonic())):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffers[key.data].extend(chunk)
                    self.assertLessEqual(len(buffers[key.data]), 1024 * 1024, "bounded fixture output exceeded")
                if not selector.get_map():
                    break
        self.fail("bounded native RPC failed: " + bytes(buffers["stderr"][:2048]).decode("utf-8", "replace"))

    def run_native(self, config, *, mcp=False):
        argv = [str(self.binary), "app-server", "-c", "analytics.enabled=false",
                "-c", 'sandbox_mode="danger-full-access"']
        for override in config:
            argv.extend(["-c", override])
        process = subprocess.Popen(argv, cwd=self.root, env=self.environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            self.request(process, {"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "private-environment-fixture", "version": "1"},
                "capabilities": {"experimentalApi": True}}}, buffers)
            process.stdin.write(b'{"method":"initialized"}\n')
            process.stdin.flush()
            if mcp:
                result = self.request(process, {"id": 2, "method": "mcpServerStatus/list", "params": {"limit": 10}}, buffers)
                row = next(item for item in result["data"] if item["name"] == "fixture")
                tool = next(iter(row["tools"].values()))
                values = json.loads(tool["description"])
            else:
                result = self.request(process, {"id": 2, "method": "command/exec", "params": {
                    "command": ["/usr/bin/env"], "cwd": str(self.root), "timeoutMs": 3000,
                    "outputBytesCap": 32768}}, buffers)
                self.assertEqual(result["exitCode"], 0)
                values = dict(line.split("=", 1) for line in result["stdout"].splitlines() if "=" in line)
            self.assertNotIn("NODE_REPL_AUTH_TOKEN", values)
            return {key: values[key] for key in (*MARKERS, "ORDINARY_TEST") if key in values}
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
            process.stdout.close()
            process.stderr.close()

    def test_actual_shell_policy_builder(self):
        cases = [("all", [], {**MARKERS, "ORDINARY_TEST": "ordinary"}), ("core", [], {}), ("none", [], {}),
                 ("all", ['include_only=["SESSION_PEER_WAKE_*"]'], MARKERS),
                 ("all", ['exclude=["SESSION_PEER_WAKE_*"]'], {"ORDINARY_TEST": "ordinary"}),
                 ("none", ['include_only=["SESSION_PEER_WAKE_*"]'], {})]
        for inherit, filters, expected in cases:
            with self.subTest(inherit=inherit, filters=filters):
                config = ['shell_environment_policy.inherit=' + json.dumps(inherit)]
                config += ["shell_environment_policy." + item for item in filters]
                self.assertEqual(self.run_native(config), expected)

    def test_actual_mcp_startup_builder(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "codex_mcp_environment.py"
        for inherit, opt_in in [("all", False), ("core", False), ("all", True), ("none", True)]:
            with self.subTest(inherit=inherit, env_vars=opt_in):
                config = ['shell_environment_policy.inherit=' + json.dumps(inherit),
                          'mcp_servers.fixture.command=' + json.dumps(sys.executable),
                          'mcp_servers.fixture.args=' + json.dumps([str(fixture)]),
                          'mcp_servers.fixture.startup_timeout_sec=3']
                if opt_in:
                    config.append('mcp_servers.fixture.env_vars=' + json.dumps([*MARKERS, "NODE_REPL_AUTH_TOKEN"]))
                self.assertEqual(self.run_native(config, mcp=True), MARKERS if opt_in else {})
