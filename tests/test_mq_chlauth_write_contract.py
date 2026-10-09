"""Offline negative tests for CHLAUTH command contract. No MQ access."""
import copy
import unittest

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_write_contract import (
    ApprovedCommandContract, OfflineOnlyMutationAdapter, canonical_plan,
)


class WriteContractTests(unittest.TestCase):
    def setUp(self):
        self.plan = canonical_plan()
        self.contract = ApprovedCommandContract(self.plan)

    def test_six_exact_operations_on_both_sides(self):
        expected = ("add_deny", "define_receiver", "add_allow",
                    "remove_allow", "delete_receiver", "remove_deny")
        for side in ("a", "b"):
            commands = self.plan[side]["apply_order"] + self.plan[side]["cleanup"]
            self.assertEqual(tuple(
                self.contract.classify(side, item) for item in commands
            ), expected)

    def test_reject_changes_to_identity_or_command(self):
        for side in ("a", "b"):
            for field, value in (
                ("mcauser", "mqm"),
                ("receiver", "BGT.CLIENT"),
                ("peer_ip", "192.168.20.1"),
                ("peer_subject", "CN=Unknown"),
            ):
                invalid = copy.deepcopy(self.plan)
                invalid[side][field] = value
                with self.subTest(side=side, field=field):
                    with self.assertRaises(ChlauthPlanError):
                        ApprovedCommandContract(invalid)
        changed = copy.deepcopy(self.plan)
        changed["a"]["apply_order"][0] += " WARN(YES)"
        with self.assertRaises(ChlauthPlanError):
            ApprovedCommandContract(changed)

    def test_reject_unapproved_commands_and_cross_side(self):
        for command in (
            "ALTER QMGR CHLAUTH(DISABLED)",
            "SET CHLAUTH(BGT.CLIENT) TYPE(ADDRESSMAP) ACTION(REMOVE)",
            "DELETE CHANNEL('SYSTEM.ADMIN.SVRCONN')",
            self.plan["b"]["apply_order"][2],
        ):
            with self.subTest(command=command):
                with self.assertRaises(ChlauthPlanError):
                    self.contract.classify("a", command)

    def test_write_adapter_always_refuses_even_valid_command(self):
        adapter = OfflineOnlyMutationAdapter(self.contract)
        with self.assertRaisesRegex(ChlauthPlanError, "not implemented"):
            adapter.apply("a", self.plan["a"]["apply_order"][0])
        with self.assertRaises(ChlauthPlanError):
            adapter.apply("a", "ALTER QMGR CHLAUTH(DISABLED)")

    def test_write_result_is_not_ownership_proof(self):
        response = ("One MQSC command read.\n"
                    "No commands have a syntax error.\n"
                    "All valid MQSC commands were processed.\n")
        self.assertEqual(
            self.contract.require_write_result(
                "a", self.plan["a"]["apply_order"][0], 0, response
            ), "add_deny",
        )
        with self.assertRaises(ChlauthPlanError):
            self.contract.require_write_result(
                "a", self.plan["a"]["apply_order"][0], 10, response
            )


if __name__ == "__main__":
    unittest.main()
