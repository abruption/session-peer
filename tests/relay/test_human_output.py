"""Offline Receiver-response fixtures; no live receiver or destination."""
import contextlib
import copy
import io
import json
import unittest
from unittest import mock

from tests.relay import test_native_relay as platform_guard
import session_peer as core
from session_peer_relay import cli


EXTERNAL = "이름 café " + "".join(chr(code) for code in (*range(32), *range(127, 160))) + (
    "\x1b]52;c;Zml4dHVyZQ==\x07\x1b]8;;https://example.invalid\x1b\\link\x1b]8;;\x1b\\"
)
DEVICE = "a" * 64


class DeviceHumanOutput(unittest.TestCase):
    def invoke(self, command, payload, json_mode=False):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = [command, "--device", DEVICE, "--no-update-notice"]
        if command == "send":
            argv += ["--to", "fixture", "--message", EXTERNAL, "--no-from", "--no-reply-to"]
        if json_mode:
            argv += ["--json"]
        # Exercise core_exchange's message-body construction while replacing
        # persistence and authenticated transport entirely with read-only mocks.
        with mock.patch.object(cli, "Store"), \
             mock.patch.object(cli, "device_credential", return_value=None), \
             mock.patch.object(cli, "exchange", new_callable=mock.AsyncMock,
                               return_value=payload) as exchange, \
             mock.patch.object(cli.os, "umask"), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = core.main(argv)
        return code, stdout.getvalue(), stderr.getvalue(), exchange

    def test_device_list_and_send_escape_only_display_copy(self):
        for command in ("list", "send"):
            original = {"ok": True, "status": EXTERNAL,
                        "sessions": [{"target": EXTERNAL, "agent": EXTERNAL,
                                      "id": EXTERNAL, "status": EXTERNAL},
                                     {"target": "second", "agent": "claude",
                                      "pid": EXTERNAL, "status": EXTERNAL}],
                        "guidance": {"nextAction": EXTERNAL}}
            expected_payload = {**original, "device": DEVICE, "host": "device:" + DEVICE,
                                "transport": "paired_device"}
            expected_json = json.dumps(core.json_result(command, expected_payload), ensure_ascii=False) + "\n"
            for json_mode in (False, True):
                with self.subTest(command=command, json=json_mode):
                    payload = copy.deepcopy(original)
                    code, stdout, stderr, exchange = self.invoke(command, payload, json_mode)
                    self.assertEqual(code, 0)
                    self.assertEqual(stderr, "")
                    self.assertEqual({key: payload[key] for key in original}, original)
                    if command == "send":
                        self.assertEqual(exchange.call_args.args[3], {"target": "fixture", "message": EXTERNAL})
                    if json_mode:
                        self.assertEqual(stdout.encode(), expected_json.encode())
                    else:
                        self.assertFalse(any(ord(char) < 0x20 and char != "\n"
                                             or 0x7f <= ord(char) <= 0x9f for char in stdout), repr(stdout))
                        self.assertIn(core.human_text(EXTERNAL), stdout)
                        self.assertEqual(len(stdout.splitlines()), 5 if command == "list" else 2)
                        if command == "list":
                            self.assertIn("\nTARGET  AGENT  ID  STATUS\n", stdout)

    def test_device_failure_reason_escaped_in_human_output(self):
        payload = {"ok": False, "reason": EXTERNAL}
        code, stdout, stderr, _ = self.invoke("list", payload)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, "Device result: " + core.human_text(EXTERNAL) + "\nTARGET  AGENT  ID  STATUS\n\n")
