"""Journaled in-memory lifecycle exercising the read-only cleanup evidence gate."""
import copy
import tempfile
import unittest
from pathlib import Path

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_cleanup_lifecycle_offline import (
    OfflineReadbackGatedLifecycleAdapter,
)
from module_utils.bergen_mq_chlauth_journal import LockedFixtureJournal, read_journal
from module_utils.bergen_mq_chlauth_journaled_offline import JournaledOfflineAdapter
from module_utils.bergen_mq_chlauth_lifecycle import (
    ChlauthFixtureLifecycle, FixtureLifecycleError,
)
from module_utils.bergen_mq_chlauth_write_contract import (
    ApprovedCommandContract, canonical_plan,
)
from test_mq_chlauth_cleanup_readback import allow_rule, fixture_evidence, TAIL
from test_mq_chlauth_journaled_offline import InMemoryMQ


class CleanupLifecycleOfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "journal"
        self.plan = canonical_plan()
        self.prefix = "AUDIT.A1B2C3D"

    def bridge(self, journal, fake, readbacks=None):
        delegate = JournaledOfflineAdapter(
            fake, journal, ApprovedCommandContract(self.plan)
        )
        provider = readbacks if readbacks is not None else (
            lambda side: fixture_evidence(self.plan, side)
        )
        return OfflineReadbackGatedLifecycleAdapter(
            self.plan, delegate, provider
        )

    def test_complete_two_sided_lifecycle_and_journal(self):
        fake = InMemoryMQ()
        with LockedFixtureJournal(self.root, self.prefix) as journal:
            bridge = self.bridge(journal, fake)
            states = ChlauthFixtureLifecycle(self.plan, bridge).run()
            self.assertTrue(all(s.verified for s in states.values()))
            for side in ("a", "b"):
                self.assertIn((side, "apply", "delete_receiver"), fake.events)
                self.assertIn((side, "apply", "remove_deny"), fake.events)
            journal.mark_clean({
                "a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"
            })
            self.assertEqual(read_journal(journal.path)[-1]["kind"], "CLEAN")

    def test_delete_without_inactivity_readback_never_reaches_fake(self):
        fake = InMemoryMQ()
        with LockedFixtureJournal(self.root, self.prefix) as journal:
            bridge = self.bridge(journal, fake)
            with self.assertRaisesRegex(ChlauthPlanError, "evidence missing"):
                bridge.apply("a", self.plan["a"]["cleanup"][1])
            self.assertFalse(any(event[1] == "apply" for event in fake.events))

    def test_deny_removal_without_absence_proof_refused(self):
        fake = InMemoryMQ()
        with LockedFixtureJournal(self.root, self.prefix) as journal:
            bridge = self.bridge(journal, fake)
            with self.assertRaisesRegex(ChlauthPlanError, "receiver absence"):
                bridge.apply("a", self.plan["a"]["cleanup"][2])
            self.assertFalse(any(event[1] == "apply" for event in fake.events))

    def test_wrong_readback_prevents_receiver_delete_and_retains_deny(self):
        fake = InMemoryMQ()
        def readbacks(side):
            result = fixture_evidence(self.plan, side)
            if side == "b":
                result["rules"]["stdout"] = result["rules"]["stdout"].replace(
                    TAIL, allow_rule(self.plan["b"]) + TAIL
                )
            return result

        with LockedFixtureJournal(self.root, self.prefix) as journal:
            bridge = self.bridge(journal, fake, readbacks)
            with self.assertRaises(FixtureLifecycleError):
                ChlauthFixtureLifecycle(self.plan, bridge).run()
            self.assertNotIn(("b", "apply", "delete_receiver"), fake.events)
            self.assertNotIn(("b", "apply", "remove_deny"), fake.events)
            self.assertNotEqual(read_journal(journal.path)[-1]["kind"], "CLEAN")

    def test_current_instance_prevents_receiver_delete(self):
        fake = InMemoryMQ()
        def readbacks(side):
            result = fixture_evidence(self.plan, side)
            if side == "b":
                result["current"]["rc"] = 0
                result["current"]["stdout"] = result["current"]["stdout"].replace(
                    "AMQ8420I: Channel Status not found.",
                    "AMQ8417I: Display Channel Status details.\n"
                    "STATUS(RUNNING)"
                )
            return result

        with LockedFixtureJournal(self.root, self.prefix) as journal:
            bridge = self.bridge(journal, fake, readbacks)
            with self.assertRaises(FixtureLifecycleError):
                ChlauthFixtureLifecycle(self.plan, bridge).run()
            self.assertNotIn(("b", "apply", "delete_receiver"), fake.events)
            self.assertNotIn(("b", "apply", "remove_deny"), fake.events)

    def test_inactivity_readback_without_no_allow_stage_refused(self):
        fake = InMemoryMQ()
        with LockedFixtureJournal(self.root, self.prefix) as journal:
            bridge = self.bridge(journal, fake)
            with self.assertRaisesRegex(ChlauthPlanError, "no_allow"):
                bridge.verify("a", self.plan["a"], "receiver_inactive")
            self.assertFalse(any(event[1] == "apply" for event in fake.events))

    def test_wrong_side_readbacks_refused_in_cleanup(self):
        fake = InMemoryMQ()
        def readbacks(side):
            if side == "b":
                return fixture_evidence(self.plan, "a")
            return fixture_evidence(self.plan, side)
        with LockedFixtureJournal(self.root, self.prefix) as journal:
            bridge = self.bridge(journal, fake, readbacks)
            with self.assertRaises(FixtureLifecycleError):
                ChlauthFixtureLifecycle(self.plan, bridge).run()
            self.assertNotIn(("b", "apply", "delete_receiver"), fake.events)

    def test_requires_exact_journaled_offline_adapter(self):
        with self.assertRaisesRegex(ChlauthPlanError, "in-memory fake"):
            OfflineReadbackGatedLifecycleAdapter(
                self.plan, object(), lambda side: fixture_evidence(self.plan, side)
            )


if __name__ == "__main__":
    unittest.main()
