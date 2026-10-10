"""Simulated MQSC CURRENT status responses, never contacts IBM MQ."""
import unittest

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_current_status import (
    current_status_command, require_no_current_receiver_status,
)
from module_utils.bergen_mq_chlauth_write_contract import canonical_plan


def sample(plan, side):
    command = current_status_command(plan, side)
    return (
        "5724-H72 (C) Copyright IBM Corp. 1994, 2026.\n"
        "Starting MQSC for queue manager %s.\n\n"
        "     1 : %s\n"
        "AMQ8420I: Channel Status not found.\n"
        "One MQSC command read.\n"
        "No commands have a syntax error.\n"
        "One valid MQSC command could not be processed.\n"
    ) % (plan[side]["qmgr"], command)


class CurrentStatusTests(unittest.TestCase):
    def setUp(self):
        self.plan = canonical_plan()

    def check(self, side, output, rc=10, command=None):
        return require_no_current_receiver_status(
            self.plan, side,
            command if command is not None
            else current_status_command(self.plan, side),
            rc, output,
        )

    def test_both_sides_report_no_current_instance(self):
        for side in ("a", "b"):
            with self.subTest(side=side):
                evidence = self.check(side, sample(self.plan, side))
                self.assertFalse(evidence["current_instances_reported"])
                self.assertFalse(evidence["can_authorize_delete"])
                self.assertFalse(evidence["can_authorize_live_apply"])
                self.assertTrue(evidence["read_only"])

    def test_valid_informational_message_can_return_zero(self):
        result = self.check("a", sample(self.plan, "a"), rc=0)
        self.assertFalse(result["current_instances_reported"])

    def test_current_running_stopped_and_retrying_are_not_absent(self):
        base = sample(self.plan, "a")
        for state in ("RUNNING", "STOPPED", "RETRYING", "STOPPING"):
            with self.subTest(state=state):
                invalid = base.replace(
                    "AMQ8420I: Channel Status not found.",
                    "AMQ8417I: Display Channel Status details.\n"
                    " CHANNEL(%s) CHLTYPE(RCVR) CURRENT STATUS(%s)"
                    % (self.plan["a"]["receiver"], state)
                ).replace(
                    "One valid MQSC command could not be processed.",
                    "All valid MQSC commands were processed."
                )
                with self.assertRaises(ChlauthPlanError):
                    self.check("a", invalid, rc=0)

    def test_wrong_qmgr_side_command_and_saved_are_refused(self):
        base = sample(self.plan, "a")
        bad_qmgr = base.replace("BERGENLAB.", "BERGENLABB.")
        with self.assertRaises(ChlauthPlanError):
            self.check("a", bad_qmgr)
        with self.assertRaises(ChlauthPlanError):
            self.check("b", base)
        with self.assertRaises(ChlauthPlanError):
            self.check("a", base, command=current_status_command(self.plan, "a").replace(
                " CURRENT", " SAVED"))
        with self.assertRaises(ChlauthPlanError):
            self.check("a", base.replace(" CURRENT", " SAVED"))

    def test_missing_duplicate_or_extra_messages_are_refused(self):
        base = sample(self.plan, "a")
        variants = (
            base.replace("AMQ8420I: Channel Status not found.\n", ""),
            base.replace("One MQSC command read.\n", ""),
            base + "AMQ8420I: Channel Status not found.\n",
            base + "AMQ8135E: Not authorized.\n",
            base + "CHANNEL(AUDIT.A1B2C3D.B2A) STATUS(RUNNING)\n",
            base.replace("AMQ8420I: Channel Status not found.\n",
                         "AMQ8420I: Channel Status not found.\n"
                         "AMQ8417I: Display Channel Status details.\n"),
            base + "  2 : DISPLAY CHSTATUS('*') CURRENT\n",
            base.replace("     1 : ", ""),
        )
        for changed in variants:
            with self.subTest(changed=changed[-95:]):
                with self.assertRaises(ChlauthPlanError):
                    self.check("a", changed)

    def test_unusable_rc_and_output_are_refused(self):
        base = sample(self.plan, "a")
        for rc in (10.0, True, 20, -1):
            with self.subTest(rc=rc):
                with self.assertRaises(ChlauthPlanError):
                    self.check("a", base, rc=rc)
        with self.assertRaises(ChlauthPlanError):
            self.check("a", None)

    def test_replayed_other_receiver_echo_is_refused(self):
        base = sample(self.plan, "b")
        with self.assertRaises(ChlauthPlanError):
            self.check("b", base.replace("AUDIT.A1B2C3D.A2B",
                                        "AUDIT.A1B2C3D.B2A"))


if __name__ == "__main__":
    unittest.main()
