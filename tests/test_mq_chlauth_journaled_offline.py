"""Fake-only integration tests: lifecycle -> command allowlist -> fsynced journal."""
from pathlib import Path
import tempfile
import unittest

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_journal import JournalError, read_journal
from module_utils.bergen_mq_chlauth_journaled_offline import (
    run_offline_journaled_fixture,
)
from module_utils.bergen_mq_chlauth_write_contract import canonical_plan
from test_mq_chlauth_lifecycle import FakeAdapter


class InMemoryMQ(FakeAdapter):
    offline_chlauth_fake = True


class JournaledIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name) / "journal"
        self.plan = canonical_plan()

    def test_complete_fake_lifecycle_has_twelve_ordered_intents(self):
        fake = InMemoryMQ()
        states, path = run_offline_journaled_fixture(self.plan, fake, self.root)
        self.assertTrue(all(s.verified for s in states.values()))
        entries = read_journal(path)
        self.assertEqual(entries[-1]["kind"], "CLEAN")
        writes = [e["data"]["operation"] for e in entries
                  if e["kind"] == "INTENT"]
        self.assertEqual(len(writes), 12)
        self.assertEqual(writes[:3],
                         ["add_deny", "define_receiver", "add_allow"])
        self.assertEqual(writes[3:6],
                         ["add_deny", "define_receiver", "add_allow"])
        self.assertEqual(writes[6:9],
                         ["remove_allow", "delete_receiver", "remove_deny"])
        self.assertEqual(writes[9:],
                         ["remove_allow", "delete_receiver", "remove_deny"])
        for i, entry in enumerate(entries):
            if entry["kind"] == "INTENT":
                self.assertEqual(entries[i + 1]["kind"], "RESULT")
                self.assertEqual(entries[i + 1]["data"]["status"], "ACKED")

    def test_uncertain_fake_write_persists_unknown_and_blocks_new_run(self):
        fake = InMemoryMQ(fail=("a", "apply", "create_receiver"))
        with self.assertRaises(Exception):
            run_offline_journaled_fixture(self.plan, fake, self.root)
        entries = read_journal(self.root / "BGT.A1B2C3D.jsonl")
        self.assertTrue(any(
            e["kind"] == "RESULT" and e["data"]["status"] == "UNKNOWN"
            for e in entries))
        self.assertNotEqual(entries[-1]["kind"], "CLEAN")
        with self.assertRaisesRegex(JournalError, "Unresolved"):
            run_offline_journaled_fixture(
                self.plan, InMemoryMQ(), self.root)

    def test_negative_runcheck_causes_rollback_and_unfinished_journal(self):
        fake = InMemoryMQ(fail=("b", "check", "wrong_issuer"))
        with self.assertRaises(Exception):
            run_offline_journaled_fixture(self.plan, fake, self.root)
        entries = read_journal(self.root / "BGT.A1B2C3D.jsonl")
        self.assertFalse(any(e["kind"] == "CLEAN" for e in entries))
        self.assertEqual(
            len([e for e in entries if e["kind"] == "INTENT"]), 12)
        self.assertEqual(
            len([e for e in entries if e["kind"] == "RESULT"]), 12)

    def test_non_fake_mqsc_delegate_forbidden(self):
        with self.assertRaisesRegex(ChlauthPlanError, "No live"):
            run_offline_journaled_fixture(
                self.plan, FakeAdapter(), self.root)
        self.assertFalse(self.root.exists())

    def test_incorrect_plan_forbidden_before_journal_creation(self):
        broken = canonical_plan()
        broken["b"]["mcauser"] = "mqm"
        with self.assertRaises(ChlauthPlanError):
            run_offline_journaled_fixture(
                broken, InMemoryMQ(), self.root)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
