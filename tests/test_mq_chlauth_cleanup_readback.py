"""Offline-only cleanup gate tests: no MQ writes and no delete authority."""
import copy
import unittest

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_cleanup_readback import (
    verify_receiver_cleanup_readbacks,
)
from module_utils.bergen_mq_chlauth_current_status import current_status_command
from module_utils.bergen_mq_chlauth_write_contract import canonical_plan

TAIL = (
    "One MQSC command read.\n"
    "No commands have a syntax error.\n"
    "All valid MQSC commands were processed.\n"
)
MISSING_TAIL = (
    "One MQSC command read.\n"
    "No commands have a syntax error.\n"
    "One valid MQSC command could not be processed.\n"
)


def record(**fields):
    return (
        "AMQ8878I: Display channel authentication record details.\n"
        "  " + " ".join("%s(%s)" % (key, value) for key, value in fields.items())
        + "\n"
    )


def fixture_evidence(plan, side):
    spec = plan[side]
    channel_cmd = "DISPLAY CHANNEL('%s') ALL" % spec["receiver"]
    channel = (
        "AMQ8414I: Display Channel details.\n"
        " CHANNEL(%s) CHLTYPE(RCVR)\n"
        " SSLCIPH(TLS_AES_256_GCM_SHA384) SSLCAUTH(REQUIRED)\n"
        " CERTLABL(bergentransport) MCAUSER(%s)\n"
        % (spec["receiver"], spec["mcauser"])
    ) + TAIL
    deny = record(
        CHLAUTH=spec["receiver"], TYPE="ADDRESSMAP", ADDRESS="*",
        USERSRC="NOACCESS", WARN="NO",
    )
    baseline = record(
        CHLAUTH="BGT.CLIENT", TYPE="ADDRESSMAP", ADDRESS="*",
        USERSRC="NOACCESS",
    )
    current_cmd = current_status_command(plan, side)
    current = (
        "5724-H72 (C) Copyright IBM Corp. 1994, 2026.\n"
        "Starting MQSC for queue manager %s.\n"
        "    1 : %s\n"
        "AMQ8420I: Channel Status not found.\n"
        ":\n"
        % (spec["qmgr"], current_cmd)
    ) + MISSING_TAIL
    return {
        "channel": {"command": channel_cmd, "rc": 0, "stdout": channel, "stderr": ""},
        "rules": {"command": "DISPLAY CHLAUTH(*) ALL", "rc": 0,
                  "stdout": baseline + deny + TAIL, "stderr": ""},
        "current": {"command": current_cmd, "rc": 10,
                    "stdout": current, "stderr": ""},
    }


def allow_rule(spec):
    return record(
        CHLAUTH=spec["receiver"], TYPE="SSLPEERMAP",
        SSLPEER=spec["peer_subject"], SSLCERTI=spec["peer_issuer"],
        ADDRESS=spec["peer_ip"], USERSRC="MAP",
        MCAUSER=spec["mcauser"], WARN="NO",
    )


class CleanupReadbackTests(unittest.TestCase):
    def setUp(self):
        self.plan = canonical_plan()
        self.data = fixture_evidence(self.plan, "a")

    def check(self, data=None, side="a"):
        return verify_receiver_cleanup_readbacks(
            self.plan, side, self.data if data is None else data,
        )

    def test_both_sides_complete_and_never_authorize_delete(self):
        for side in ("a", "b"):
            with self.subTest(side=side):
                result = self.check(fixture_evidence(self.plan, side), side)
                self.assertEqual(result["readback_contract"], "PASS")
                self.assertTrue(result["no_current_status_observed"])
                self.assertTrue(result["allow_rule_absent_observed"])
                self.assertTrue(result["deny_rule_present_observed"])
                self.assertTrue(result["receiver_definition_present_observed"])
                self.assertFalse(result["can_authorize_delete"])
                self.assertFalse(result["can_authorize_live_apply"])

    def test_missing_extra_or_malformed_results_refused(self):
        for variant in (
            {k: v for k, v in self.data.items() if k != "current"},
            dict(self.data, unexpected={}),
            dict(self.data, current=None),
        ):
            with self.subTest(variant=str(variant.keys())):
                with self.assertRaises(ChlauthPlanError):
                    self.check(variant)

    def test_exact_display_command_required_for_each_result(self):
        for key in ("channel", "rules", "current"):
            variant = copy.deepcopy(self.data)
            variant[key]["command"] = "DISPLAY QMGR ALL"
            with self.subTest(key=key):
                with self.assertRaises(ChlauthPlanError):
                    self.check(variant)

    def test_chstatus_from_other_qmgr_or_wrong_receiver_refused(self):
        for output in (
            fixture_evidence(self.plan, "b")["current"]["stdout"],
            self.data["current"]["stdout"].replace(
                "AUDIT.A1B2C3D.B2A", "AUDIT.A1B2C3D.A2B",
            ),
        ):
            variant = copy.deepcopy(self.data)
            variant["current"]["stdout"] = output
            with self.assertRaises(ChlauthPlanError):
                self.check(variant)

    def test_current_running_stopped_or_ambiguous_refused(self):
        for state in ("RUNNING", "STOPPED", "RETRYING"):
            variant = copy.deepcopy(self.data)
            variant["current"]["stdout"] = variant["current"]["stdout"].replace(
                "AMQ8420I: Channel Status not found.",
                "AMQ8417I: Display Channel Status details.\nSTATUS(%s)" % state,
            )
            variant["current"]["rc"] = 0
            with self.subTest(state=state):
                with self.assertRaises(ChlauthPlanError):
                    self.check(variant)

    def test_allow_rule_must_already_be_absent(self):
        variant = copy.deepcopy(self.data)
        variant["rules"]["stdout"] = variant["rules"]["stdout"].replace(
            TAIL, allow_rule(self.plan["a"]) + TAIL,
        )
        with self.assertRaises(ChlauthPlanError):
            self.check(variant)

    def test_default_deny_must_still_exist(self):
        variant = copy.deepcopy(self.data)
        spec = self.plan["a"]
        deny = record(
            CHLAUTH=spec["receiver"], TYPE="ADDRESSMAP", ADDRESS="*",
            USERSRC="NOACCESS", WARN="NO",
        )
        variant["rules"]["stdout"] = variant["rules"]["stdout"].replace(deny, "")
        with self.assertRaises(ChlauthPlanError):
            self.check(variant)

    def test_receiver_must_exist_with_exact_reviewed_tls_identity(self):
        for changed in ("SSLCAUTH(OPTIONAL)", "SSLCAUTH(REQUIRED)"):
            variant = copy.deepcopy(self.data)
            if changed == "SSLCAUTH(OPTIONAL)":
                variant["channel"]["stdout"] = variant["channel"]["stdout"].replace(
                    "SSLCAUTH(REQUIRED)", changed,
                )
            else:
                variant["channel"]["stdout"] = (
                    "AMQ8147E: IBM MQ object not found.\n" + MISSING_TAIL
                )
                variant["channel"]["rc"] = 10
            with self.subTest(scenario=changed):
                with self.assertRaises(ChlauthPlanError):
                    self.check(variant)

    def test_stderr_or_invalid_return_codes_refused(self):
        for kind in ("channel", "rules", "current"):
            variant = copy.deepcopy(self.data)
            variant[kind]["stderr"] = "not-empty"
            with self.subTest(kind=kind):
                with self.assertRaises(ChlauthPlanError):
                    self.check(variant)
        for bad_rc in (True, "10", 20):
            variant = copy.deepcopy(self.data)
            variant["current"]["rc"] = bad_rc
            with self.subTest(rc=bad_rc):
                with self.assertRaises(ChlauthPlanError):
                    self.check(variant)

    def test_truncated_or_duplicate_status_refused(self):
        for change in (
            lambda x: x.replace("One MQSC command read.\n", ""),
            lambda x: x.replace("AMQ8420I: Channel Status not found.\n",
                                "AMQ8420I: Channel Status not found.\n:\n:\n"),
            lambda x: x + "AMQ8420I: Channel Status not found.\n",
        ):
            variant = copy.deepcopy(self.data)
            variant["current"]["stdout"] = change(variant["current"]["stdout"])
            with self.assertRaises(ChlauthPlanError):
                self.check(variant)


if __name__ == "__main__":
    unittest.main()
