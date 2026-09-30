import unittest
from side_session import Refused, RpcRejected, Unknown, loaded_ids, send


TARGET = "00000000-0000-4000-8000-000000000001"


class Fake:
    def __init__(self, ephemeral=True, status="idle", direct=True, loaded=True, fail=None):
        self.calls = []
        self.ephemeral, self.status, self.direct, self.loaded, self.fail = ephemeral, status, direct, loaded, fail

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": [TARGET] if self.loaded else [], "nextCursor": None}
        if method == "thread/read":
            return {"thread": {"id": TARGET, "ephemeral": self.ephemeral,
                               "status": {"type": self.status}, "canAcceptDirectInput": self.direct}}
        if self.fail:
            raise self.fail
        return {"turn": {"id": "test-turn"}}


class Contract(unittest.TestCase):
    def test_opt_in(self):
        rpc = Fake()
        with self.assertRaisesRegex(Refused, "exclusive"):
            send(rpc, TARGET, "hello")
        self.assertEqual(rpc.calls, [])

    def test_dry_run(self):
        rpc = Fake()
        self.assertFalse(send(rpc, TARGET, "hello", exclusive=True, dry_run=True)["submitted"])
        self.assertNotIn("turn/start", [m for m, _ in rpc.calls])

    def test_accept_not_ack(self):
        rpc = Fake()
        result = send(rpc, "codex:" + TARGET, "hello", exclusive=True)
        self.assertTrue(result["submitted"])
        self.assertFalse(result["consumptionConfirmed"])
        self.assertEqual([m for m, _ in rpc.calls], ["thread/loaded/list", "thread/read", "turn/start"])
        params = rpc.calls[-1][1]
        self.assertEqual(set(params), {"threadId", "input", "clientUserMessageId"})
        self.assertFalse(rpc.calls[1][1]["includeTurns"])

    def test_persistent_refused(self):
        with self.assertRaisesRegex(Refused, "ephemeral"):
            send(Fake(ephemeral=False), TARGET, "hello", exclusive=True)

    def test_busy_refused(self):
        with self.assertRaisesRegex(Refused, "idle"):
            send(Fake(status="active"), TARGET, "hello", exclusive=True)

    def test_unloaded_refused(self):
        with self.assertRaisesRegex(Refused, "not_loaded"):
            send(Fake(loaded=False), TARGET, "hello", exclusive=True)

    def test_loaded_idle_has_no_ui_lifetime_proof(self):
        # Models the live closure finding. This is a documented limitation,
        # not a test claiming that UI-closed destinations are safely refused.
        rpc = Fake(loaded=True, ephemeral=True, status="idle")
        result = send(rpc, TARGET, "hello", exclusive=True, dry_run=True)
        self.assertEqual(result["status"], "validated")
        self.assertNotIn("turn/start", [m for m, _ in rpc.calls])

    def test_capability_refused(self):
        with self.assertRaisesRegex(Refused, "unverified"):
            send(Fake(direct=None), TARGET, "hello", exclusive=True)

    def test_timeout_unknown_no_retry(self):
        rpc = Fake(fail=TimeoutError())
        with self.assertRaises(Unknown):
            send(rpc, TARGET, "hello", exclusive=True)
        self.assertEqual(sum(m == "turn/start" for m, _ in rpc.calls), 1)

    def test_rejection_no_retry(self):
        rpc = Fake(fail=RpcRejected("turn/start", -32600))
        with self.assertRaises(Refused):
            send(rpc, TARGET, "hello", exclusive=True)
        self.assertEqual(sum(m == "turn/start" for m, _ in rpc.calls), 1)

    def test_internal_error_unknown(self):
        with self.assertRaises(Unknown):
            send(Fake(fail=RpcRejected("turn/start", -32603)), TARGET, "hello", exclusive=True)

    def test_invalid_response_unknown(self):
        with self.assertRaises(Unknown):
            send(Fake(fail=Refused("invalid_rpc_response")), TARGET, "hello", exclusive=True)

    def test_invalid_inputs(self):
        for text in ("", "\x00", "가" * 22000):
            with self.subTest(text_length=len(text)), self.assertRaises(Refused):
                send(Fake(), TARGET, text, exclusive=True)
        with self.assertRaises(Refused):
            send(Fake(), "not-uuid", "hello", exclusive=True)


if __name__ == "__main__":
    unittest.main()
