"""Offline-only tests for two-sided confidential CURRENT CHSTATUS audits."""
import unittest

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_chstatus_audit import audit_current_status
from module_utils.bergen_mq_chlauth_current_status import current_status_command
from module_utils.bergen_mq_chlauth_write_contract import canonical_plan


class TwoSidedChstatusAuditTests(unittest.TestCase):
    def setUp(self):
        self.plan = canonical_plan()
        self.responses = {
            side: {"rc": 10, "stdout": self.example(side), "stderr": ""}
            for side in ("a", "b")
        }

    def example(self, side):
        command = current_status_command(self.plan, side)
        return (
            "5724-H72 (C) Copyright IBM Corp. 1994, 2026.\n"
            "Starting MQSC for queue manager %s.\n"
            "     1 : %s\n"
            "AMQ8420I: Channel Status not found.\n"
            "One MQSC command read.\n"
            "No commands have a syntax error.\n"
            "One valid MQSC command could not be processed.\n"
        ) % (self.plan[side]["qmgr"], command)

    def test_both_complete_responses_accepted_without_authorization(self):
        report = audit_current_status(self.responses)
        self.assertEqual(report["verification"], "PASS")
        self.assertEqual(set(report["observations"]), {"a", "b"})
        self.assertTrue(report["read_only"])
        self.assertFalse(report["changed"])
        self.assertFalse(report["can_authorize_delete"])
        self.assertFalse(report["can_authorize_live_apply"])

    def test_missing_or_extra_side_refused(self):
        for changed in (
            {"a": self.responses["a"]},
            dict(self.responses, c=self.responses["a"]),
            [],
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ChlauthPlanError):
                    audit_current_status(changed)

    def test_missing_or_extra_result_field_refused(self):
        for changed in (
            {"rc": 10, "stdout": self.example("a")},
            {"rc": 10, "stdout": self.example("a"), "stderr": "", "x": 1},
            None,
        ):
            responses = dict(self.responses)
            responses["a"] = changed
            with self.subTest(changed=changed):
                with self.assertRaises(ChlauthPlanError):
                    audit_current_status(responses)

    def test_stderr_never_ignored(self):
        responses = dict(self.responses)
        responses["b"] = dict(self.responses["b"], stderr="unexpected diagnostic")
        with self.assertRaisesRegex(ChlauthPlanError, "stderr"):
            audit_current_status(responses)

    def test_boolean_or_invalid_rc_refused(self):
        for bad_rc in (True, "10", 10.0, 20):
            responses = dict(self.responses)
            responses["a"] = dict(self.responses["a"], rc=bad_rc)
            with self.subTest(rc=bad_rc):
                with self.assertRaises(ChlauthPlanError):
                    audit_current_status(responses)

    def test_wrong_qmgr_and_replayed_other_side_refused(self):
        for output in (
            self.example("b"),
            self.example("a").replace(
                "Starting MQSC for queue manager BERGENLAB.",
                "Starting MQSC for queue manager BERGENLABB."
            ),
        ):
            responses = dict(self.responses)
            responses["a"] = dict(self.responses["a"], stdout=output)
            with self.assertRaises(ChlauthPlanError):
                audit_current_status(responses)

    def test_active_receiver_refused_even_when_other_side_absent(self):
        responses = dict(self.responses)
        output = self.example("b").replace(
            "AMQ8420I: Channel Status not found.",
            "AMQ8417I: Display Channel Status details.\n"
            "CHANNEL(AUDIT.A1B2C3D.A2B) STATUS(STOPPED)"
        )
        responses["b"] = dict(self.responses["b"], rc=0, stdout=output)
        with self.assertRaises(ChlauthPlanError):
            audit_current_status(responses)

    def test_missing_tail_or_unexpected_extra_line_refused(self):
        for output in (
            self.example("a").replace("One MQSC command read.\n", ""),
            self.example("a") + "Unexpected output.\n",
        ):
            responses = dict(self.responses)
            responses["a"] = dict(self.responses["a"], stdout=output)
            with self.assertRaises(ChlauthPlanError):
                audit_current_status(responses)


if __name__ == "__main__":
    unittest.main()
