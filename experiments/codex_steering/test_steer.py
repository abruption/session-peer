import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace
import os
import stat
from steer import Rpc, Refused, Unknown, Rejected, pages, steer

THREAD = "00000000-0000-4000-8000-000000000001"
HOME = "/test-home"


class Fake:
    info = {"codexHome": HOME}

    def __init__(self, active=True, loaded=True, flag=True, error=None, direct=True, flags=None):
        self.active, self.loaded, self.flag, self.error, self.direct = active, loaded, flag, error, direct
        self.flags = flags or []
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": [THREAD] if self.loaded else [], "nextCursor": None}
        if method == "thread/read":
            return {"thread": {"id": THREAD, "status": {"type": "active" if self.active else "idle", "activeFlags": self.flags}, "canAcceptDirectInput": self.direct}}
        if method == "experimentalFeature/list":
            return {"data": [{"name": "instant_interrupt", "enabled": self.flag}], "nextCursor": None}
        if self.error:
            raise self.error
        return {"turnId": "turn-test"}


def send(rpc, **kwargs):
    return steer(rpc, THREAD, kwargs.pop("turn", "turn-test"), kwargs.pop("text", "test input"),
                 expected_home=kwargs.pop("home", HOME), opt_in=kwargs.pop("opt_in", True), **kwargs)


class Contract(unittest.TestCase):
    def test_opt_in(self):
        rpc = Fake()
        with self.assertRaises(Refused):
            send(rpc, opt_in=False)
        self.assertEqual(rpc.calls, [])

    def test_exact_one_shot(self):
        rpc = Fake()
        result = send(rpc)
        self.assertTrue(result["submitted"])
        self.assertFalse(result["consumptionConfirmed"])
        self.assertEqual(sum(m == "turn/steer" for m, _ in rpc.calls), 1)
        self.assertEqual(set(rpc.calls[-1][1]), {"threadId", "expectedTurnId", "input", "clientUserMessageId"})
        self.assertNotIn("turn/start", [m for m, _ in rpc.calls])
        self.assertFalse(rpc.calls[1][1]["includeTurns"])

    def test_dry_run_not_proof_of_turn(self):
        rpc = Fake()
        result = send(rpc, dry_run=True)
        self.assertFalse(result["submitted"])
        self.assertFalse(result["expectedTurnValidated"])
        self.assertNotIn("turn/steer", [m for m, _ in rpc.calls])

    def test_idle(self):
        with self.assertRaisesRegex(Refused, "not_active"):
            send(Fake(active=False))

    def test_unloaded(self):
        with self.assertRaisesRegex(Refused, "not_loaded"):
            send(Fake(loaded=False))

    def test_home(self):
        with self.assertRaisesRegex(Refused, "home_mismatch"):
            send(Fake(), home="/wrong-home")

    def test_capability(self):
        with self.assertRaisesRegex(Refused, "unverified"):
            send(Fake(direct=None))

    def test_approval(self):
        with self.assertRaisesRegex(Refused, "interaction_pending"):
            send(Fake(flags=["waitingOnApproval"]))

    def test_disabled_requires_instant(self):
        with self.assertRaisesRegex(Refused, "not_enabled"):
            send(Fake(flag=False), require_instant=True)

    def test_unknown_requires_instant(self):
        with self.assertRaises(Refused):
            send(Fake(flag=None), require_instant=True)

    def test_noninstant_steer_is_distinct(self):
        self.assertFalse(send(Fake(flag=False))["instantInterruptEnabledSnapshot"])

    def test_turn_required(self):
        with self.assertRaises(Refused):
            send(Fake(), turn="")

    def test_invalid_message(self):
        for text in ("", "\x00", "가" * 22000):
            with self.assertRaises(Refused):
                send(Fake(), text=text)

    def test_wrong_turn_no_fallback(self):
        rpc = Fake(error=Rejected("turn/steer", -32600))
        with self.assertRaises(Refused):
            send(rpc)
        self.assertEqual(sum(m == "turn/steer" for m, _ in rpc.calls), 1)

    def test_timeout_unknown(self):
        rpc = Fake(error=TimeoutError())
        with self.assertRaises(Unknown):
            send(rpc)
        self.assertEqual(sum(m == "turn/steer" for m, _ in rpc.calls), 1)

    def test_invalid_response_unknown(self):
        with self.assertRaises(Unknown):
            send(Fake(error=Refused("invalid_rpc_response")))

    def test_internal_error_unknown(self):
        with self.assertRaises(Unknown):
            send(Fake(error=Rejected("turn/steer", -32603)))

    def test_returned_turn_mismatch_unknown(self):
        with self.assertRaises(Unknown):
            send(Fake(), turn="different-turn")

    def test_relative_socket_refused(self):
        with self.assertRaisesRegex(Refused, "absolute"):
            Rpc("relative.sock").__enter__()

    def test_missing_socket_no_connection(self):
        with mock.patch.object(Path, "lstat", side_effect=FileNotFoundError()):
            with self.assertRaises(FileNotFoundError):
                Rpc("/dummy/missing.sock").__enter__()

    def test_socket_owner_refused(self):
        value = SimpleNamespace(st_uid=os.getuid() + 1, st_mode=stat.S_IFSOCK | 0o600)
        with mock.patch.object(Path, "lstat", return_value=value), \
             mock.patch.object(Path, "resolve", return_value=Path("/dummy/app.sock")):
            with self.assertRaisesRegex(Refused, "owned_socket"):
                Rpc("/dummy/app.sock").__enter__()

    def test_socket_mode_refused(self):
        value = SimpleNamespace(st_uid=os.getuid(), st_mode=stat.S_IFSOCK | 0o666)
        with mock.patch.object(Path, "lstat", return_value=value), \
             mock.patch.object(Path, "resolve", return_value=Path("/dummy/app.sock")):
            with self.assertRaisesRegex(Refused, "private_socket"):
                Rpc("/dummy/app.sock").__enter__()

    def test_repeated_cursor_refused(self):
        rpc = SimpleNamespace(call=lambda *args: {"data": [], "nextCursor": "repeat"})
        with self.assertRaisesRegex(Refused, "cursor"):
            list(pages(rpc, "thread/loaded/list", {}))

    def test_invalid_inventory_refused(self):
        rpc = SimpleNamespace(call=lambda *args: {"data": None})
        with self.assertRaisesRegex(Refused, "inventory"):
            list(pages(rpc, "thread/loaded/list", {}))


if __name__ == "__main__":
    unittest.main()
