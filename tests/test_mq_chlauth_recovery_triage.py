"""Recovery triage must never turn name/attribute matches into ownership."""
from pathlib import Path
import tempfile
import unittest

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_journal import LockedFixtureJournal
from module_utils.bergen_mq_chlauth_recovery_triage import triage_recovery
from module_utils.bergen_mq_chlauth_write_contract import canonical_plan


class RecoveryTriageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.plan = canonical_plan()
        with LockedFixtureJournal(
                Path(self.temp.name) / "log", "BGT.A1B2C3D") as journal:
            journal.intent("a", "add_deny")
            journal.result("a", "add_deny", "ACKED")
            self.path = journal.path

    def snapshot(self):
        return {
            side: {
                "qmgr": spec["qmgr"],
                "channel": {"status": "ABSENT", "attributes": None},
                "rules": [],
            }
            for side, spec in self.plan.items()
        }

    def receiver(self, side):
        spec = self.plan[side]
        return {
            "CHANNEL": spec["receiver"], "CHLTYPE": "RCVR",
            "SSLCIPH": "TLS_AES_256_GCM_SHA384",
            "SSLCAUTH": "REQUIRED", "CERTLABL": "bergentransport",
            "MCAUSER": spec["mcauser"],
        }

    def deny(self, side):
        return {
            "CHLAUTH": self.plan[side]["receiver"],
            "TYPE": "ADDRESSMAP", "ADDRESS": "*",
            "USERSRC": "NOACCESS", "WARN": "NO",
        }

    def allow(self, side):
        spec = self.plan[side]
        return {
            "CHLAUTH": spec["receiver"],
            "TYPE": "SSLPEERMAP", "SSLPEER": spec["peer_subject"],
            "SSLCERTI": spec["peer_issuer"], "ADDRESS": spec["peer_ip"],
            "USERSRC": "MAP", "MCAUSER": spec["mcauser"], "WARN": "NO",
        }

    def test_both_absent_still_requires_manual_review(self):
        output = triage_recovery(self.path, self.snapshot())
        self.assertEqual(output["assessment"], "NO_EXACT_FIXTURE_OBJECTS_REPORTED")
        self.assertFalse(output["can_auto_cleanup"])
        self.assertFalse(output["can_authorize_live_apply"])
        self.assertTrue(output["requires_independent_mq_readback_and_manual_review"])

    def test_identical_name_attributes_never_prove_ownership(self):
        snapshots = self.snapshot()
        snapshots["a"]["channel"] = {
            "status": "PRESENT", "attributes": self.receiver("a")}
        snapshots["a"]["rules"] = [self.deny("a"), self.allow("a")]
        output = triage_recovery(self.path, snapshots)
        self.assertEqual(output["assessment"], "RESIDUAL_OBJECT_OWNERSHIP_UNPROVEN")
        self.assertEqual(
            output["sides"]["a"]["classification"],
            "MATCHING_ATTRIBUTES_OWNERSHIP_UNPROVEN",
        )
        self.assertFalse(output["can_delete_matching_objects"])

    def test_same_name_changed_mcauser_is_foreign_or_modified(self):
        snapshots = self.snapshot()
        attrs = self.receiver("a")
        attrs["MCAUSER"] = "mqm"
        snapshots["a"]["channel"] = {"status": "PRESENT", "attributes": attrs}
        output = triage_recovery(self.path, snapshots)
        self.assertEqual(output["assessment"], "COLLISION_OR_POST_CLEAN_DRIFT_POSSIBLE")
        self.assertEqual(
            output["sides"]["a"]["classification"],
            "FOREIGN_OR_MODIFIED_OBJECT_POSSIBLE",
        )
        self.assertFalse(output["can_auto_cleanup"])

    def test_foreign_rule_on_same_profile_stops_cleanup(self):
        snapshots = self.snapshot()
        snapshots["b"]["rules"] = [{
            "CHLAUTH": self.plan["b"]["receiver"],
            "TYPE": "USERMAP", "CLNTUSER": "mqm", "USERSRC": "MAP",
        }]
        output = triage_recovery(self.path, snapshots)
        self.assertEqual(output["assessment"], "COLLISION_OR_POST_CLEAN_DRIFT_POSSIBLE")
        self.assertFalse(output["can_delete_matching_objects"])

    def test_duplicate_matching_rule_type_is_not_owned(self):
        snapshots = self.snapshot()
        snapshots["a"]["rules"] = [self.deny("a"), self.deny("a")]
        output = triage_recovery(self.path, snapshots)
        self.assertEqual(
            output["sides"]["a"]["classification"],
            "FOREIGN_OR_MODIFIED_OBJECT_POSSIBLE",
        )

    def test_incomplete_or_contradictory_evidence_is_fail_closed(self):
        snapshots = self.snapshot()
        snapshots["a"]["channel"] = {"status": "ABSENT",
                                      "attributes": self.receiver("a")}
        output = triage_recovery(self.path, snapshots)
        self.assertEqual(output["assessment"], "EVIDENCE_INCOMPLETE")
        self.assertFalse(output["can_auto_cleanup"])

    def test_wrong_queue_manager_is_not_a_safe_absence_proof(self):
        snapshots = self.snapshot()
        snapshots["b"]["qmgr"] = "OTHER"
        output = triage_recovery(self.path, snapshots)
        self.assertEqual(output["assessment"], "EVIDENCE_INCOMPLETE")
        self.assertFalse(output["can_authorize_live_apply"])

    def test_clean_marker_does_not_permit_object_reappearance(self):
        # A second, completed journal simulates a past fully cleaned fixture.
        with LockedFixtureJournal(
                Path(self.temp.name) / "clean", "BGT.A1B2C3D") as journal:
            journal.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
            clean_path = journal.path
        snapshots = self.snapshot()
        snapshots["a"]["rules"] = [self.deny("a")]
        output = triage_recovery(clean_path, snapshots)
        self.assertEqual(output["assessment"], "COLLISION_OR_POST_CLEAN_DRIFT_POSSIBLE")
        self.assertFalse(output["can_delete_matching_objects"])

    def test_missing_peer_snapshot_is_not_accepted(self):
        with self.assertRaisesRegex(ChlauthPlanError, "Two separate"):
            triage_recovery(self.path, {"a": self.snapshot()["a"]})


if __name__ == "__main__":
    unittest.main()
