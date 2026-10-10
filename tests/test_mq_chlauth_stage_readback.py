"""Readback verification using simulated independent MQSC responses only."""
import unittest

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_stage_readback import verify_stage_evidence
from module_utils.bergen_mq_chlauth_write_contract import canonical_plan

TAIL = ("One MQSC command read.\n"
        "No commands have a syntax error.\n"
        "All valid MQSC commands were processed.\n")
MISSING = ("AMQ8147E: IBM MQ object not found.\n"
           "One MQSC command read.\n"
           "No commands have a syntax error.\n"
           "One valid MQSC command could not be processed.\n")


def record(fields):
    return ("AMQ8878I: Display channel authentication record details.\n"
            + "   " + " ".join("%s(%s)" % (k, v) for k, v in fields.items())
            + "\n")


def evidence(spec, *, present, deny, allow):
    if present:
        channel = (
            "AMQ8414I: Display Channel details.\n"
            " CHANNEL(%s) CHLTYPE(RCVR) SSLCIPH(TLS_AES_256_GCM_SHA384)\n"
            " SSLCAUTH(REQUIRED) CERTLABL(bergentransport) MCAUSER(%s)\n"
            % (spec["receiver"], spec["mcauser"])
        ) + TAIL
        rc = 0
    else:
        channel, rc = MISSING, 10
    records = record({"CHLAUTH": "BGT.CLIENT", "TYPE": "ADDRESSMAP",
                      "ADDRESS": "*", "USERSRC": "NOACCESS"})
    if deny:
        records += record({"CHLAUTH": spec["receiver"], "TYPE": "ADDRESSMAP",
                           "ADDRESS": "*", "USERSRC": "NOACCESS", "WARN": "NO"})
    if allow:
        records += record({"CHLAUTH": spec["receiver"], "TYPE": "SSLPEERMAP",
                           "SSLPEER": spec["peer_subject"],
                           "SSLCERTI": spec["peer_issuer"],
                           "ADDRESS": spec["peer_ip"], "USERSRC": "MAP",
                           "MCAUSER": spec["mcauser"], "WARN": "NO"})
    return {"channel": {"rc": rc, "stdout": channel},
            "rules": {"rc": 0, "stdout": records + TAIL}}


class StageReadbackTests(unittest.TestCase):
    def setUp(self):
        self.plan = canonical_plan()

    def test_each_supported_stage_requires_matching_observations(self):
        stages = {
            "deny": (False, True, False),
            "receiver": (True, True, False),
            "allow": (True, True, True),
            "no_allow": (True, True, False),
            "no_receiver": (False, True, False),
            "clean": (False, False, False),
        }
        for side in ("a", "b"):
            for stage, (present, deny, allow) in stages.items():
                with self.subTest(side=side, stage=stage):
                    result = verify_stage_evidence(
                        self.plan, side, stage,
                        evidence(self.plan[side], present=present,
                                 deny=deny, allow=allow))
                    self.assertEqual(result["readback_contract"], "PASS")
                    self.assertFalse(result["can_authorize_live_apply"])

    def test_receiver_appearing_before_define_is_rejected(self):
        spec = self.plan["a"]
        with self.assertRaises(ChlauthPlanError):
            verify_stage_evidence(self.plan, "a", "deny",
                                  evidence(spec, present=True, deny=True, allow=False))

    def test_missing_allow_or_modified_receiver_is_rejected(self):
        spec = self.plan["b"]
        snapshot = evidence(spec, present=True, deny=True, allow=False)
        with self.assertRaises(ChlauthPlanError):
            verify_stage_evidence(self.plan, "b", "allow", snapshot)
        snapshot = evidence(spec, present=True, deny=True, allow=True)
        snapshot["channel"]["stdout"] = snapshot["channel"]["stdout"].replace(
            "SSLCAUTH(REQUIRED)", "SSLCAUTH(OPTIONAL)")
        with self.assertRaises(ChlauthPlanError):
            verify_stage_evidence(self.plan, "b", "allow", snapshot)

    def test_cleanup_requires_both_absent(self):
        spec = self.plan["a"]
        with self.assertRaises(ChlauthPlanError):
            verify_stage_evidence(self.plan, "a", "clean",
                                  evidence(spec, present=False, deny=True, allow=False))
        with self.assertRaises(ChlauthPlanError):
            verify_stage_evidence(self.plan, "a", "clean",
                                  evidence(spec, present=True, deny=False, allow=False))

    def test_truncated_rules_refused(self):
        spec = self.plan["a"]
        snapshot = evidence(spec, present=False, deny=True, allow=False)
        snapshot["rules"]["stdout"] = snapshot["rules"]["stdout"].replace(
            "All valid MQSC commands were processed.", "Result truncated.")
        with self.assertRaises(ChlauthPlanError):
            verify_stage_evidence(self.plan, "a", "deny", snapshot)

    def test_receiver_inactivity_unproven_and_never_accepted(self):
        spec = self.plan["a"]
        with self.assertRaisesRegex(ChlauthPlanError, "inactivity"):
            verify_stage_evidence(self.plan, "a", "receiver_inactive",
                                  evidence(spec, present=True, deny=True, allow=False))


if __name__ == "__main__":
    unittest.main()
