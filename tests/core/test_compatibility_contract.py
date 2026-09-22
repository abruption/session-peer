"""Executable v1 compatibility fixtures; no network or real credentials."""
import json
from pathlib import Path
import tempfile
import unittest

import session_peer as core
import session_peer_mcp as mcp


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/fixtures/compatibility-v1.json").read_text())


def assert_result_contract(value):
    types = {"int": int, "bool": bool, "str": str}
    for field, kind in FIXTURE["jsonResult"]["required"].items():
        if field not in value or type(value[field]) is not types[kind]:
            raise AssertionError(f"invalid required result field: {field}")


class CompatibilityContract(unittest.TestCase):
    def test_cli_result_required_fields_types_additive_fields_and_exit_codes(self):
        value = core.json_result("list", {"sessions": [], "futureField": {"allowed": True}},
                                 host="fixture")
        assert_result_contract(value)
        self.assertEqual(value, {**FIXTURE["jsonResult"]["example"],
                                "futureField": {"allowed": True}})
        for changed in ({k: v for k, v in value.items() if k != "host"},
                        {**value, "ok": 1}):
            with self.assertRaises(AssertionError):
                assert_result_contract(changed)
        self.assertEqual(FIXTURE["exitCodes"], {
            "success": 0, "error": core.EXIT_ERROR,
            "noTargetOrUsage": core.EXIT_NO_TARGET,
        })

    def test_reply_uri_and_mcp_policy_round_trip_through_production_parsers(self):
        parsed = core.parse_reply_address(FIXTURE["replyUri"])
        self.assertEqual(parsed["agent"], "claude")
        self.assertEqual(parsed["target"], "worker")
        self.assertEqual(core.reply_address({
            "agent": parsed["agent"], "id": parsed["session"],
            "target": parsed["target"], "host": None,
        }, local=True), FIXTURE["replyUri"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(FIXTURE["mcpPolicy"]))
            self.assertEqual(mcp.load_policy(str(path)),
                             FIXTURE["mcpPolicy"]["destinations"])

    def test_relay_policy_and_backup_manifest_match_product_contracts(self):
        try:
            from session_peer_relay.identity import private_write
            from session_peer_relay.lifecycle import backup
            from session_peer_relay.native import Policy
            from session_peer_relay.store import Store
        except ModuleNotFoundError as error:
            if error.name not in {"cryptography", "fcntl"}:
                raise
            self.skipTest("optional relay dependencies are not installed")
        Policy(FIXTURE["relayPolicy"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "device")
            policy = root / "policy.json"
            private_write(policy, json.dumps(FIXTURE["relayPolicy"]))
            try:
                destination = root / "backup"
                backup(store, destination, policy)
                manifest = json.loads((destination / "manifest.json").read_text())
                self.assertEqual(manifest["schemaVersion"],
                                 FIXTURE["backupManifest"]["schemaVersion"])
                self.assertTrue(set(FIXTURE["backupManifest"]["required"])
                                <= set(manifest))
            finally:
                store.close()

    def test_protocol_and_operation_receipt_golden_values(self):
        protocol = FIXTURE["relayProtocol"]
        self.assertEqual(protocol, {
            "alpn": "session-peer-device-v1",
            "publicStateSchemaVersion": 1,
            "replayStateSchemaVersion": 1,
        })
        receipt = FIXTURE["operationReceipt"]
        self.assertEqual(set(receipt), {"operationId", "committed", "principal",
                                       "keyFingerprint", "keyGeneration"})
        self.assertIs(receipt["committed"], True)
        self.assertIs(type(receipt["keyGeneration"]), int)


if __name__ == "__main__":
    unittest.main()
