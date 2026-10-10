"""Fake-only integration tests: lifecycle -> command allowlist -> fsynced journal."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_journal import JournalError, LockedFixtureJournal, read_journal
from module_utils.bergen_mq_chlauth_journaled_offline import (
    JournaledOfflineAdapter, run_offline_journaled_fixture,
)
from module_utils.bergen_mq_chlauth_write_contract import (
    ApprovedCommandContract, canonical_plan,
)
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
        entries = read_journal(self.root / "AUDIT.A1B2C3D.jsonl")
        self.assertTrue(any(
            e["kind"] == "RESULT" and e["data"]["status"] == "UNKNOWN"
            for e in entries))
        self.assertNotEqual(entries[-1]["kind"], "CLEAN")
        with self.assertRaisesRegex(JournalError, "Unresolved"):
            run_offline_journaled_fixture(
                self.plan, InMemoryMQ(), self.root)

    def test_journal_intent_failure_prevents_fake_write(self):
        fake = InMemoryMQ()

        with patch.object(
            LockedFixtureJournal, "intent",
            side_effect=OSError("simulated journal intent failure")
        ):
            with self.assertRaises(Exception):
                run_offline_journaled_fixture(
                    self.plan, fake, self.root
                )

        writes = [e for e in fake.events if e[1] == "apply"]
        self.assertEqual(writes, [])

        entries = read_journal(
            self.root / "AUDIT.A1B2C3D.jsonl"
        )
        self.assertEqual(
            [e["kind"] for e in entries], ["BEGIN"]
        )

    def test_journal_result_failure_blocks_followup_writes(self):
        fake = InMemoryMQ()

        with patch.object(
            LockedFixtureJournal, "result",
            side_effect=OSError("simulated journal result failure")
        ):
            with self.assertRaises(Exception):
                run_offline_journaled_fixture(
                    self.plan, fake, self.root
                )

        writes = [e for e in fake.events if e[1] == "apply"]
        self.assertEqual(
            writes, [("a", "apply", "add_deny")]
        )

        entries = read_journal(
            self.root / "AUDIT.A1B2C3D.jsonl"
        )
        self.assertEqual(
            [e["kind"] for e in entries],
            ["BEGIN", "INTENT"]
        )

    def test_unknown_write_blocks_followup_mutations(self):
        fake = InMemoryMQ(fail=("a", "apply", "create_receiver"))

        with self.assertRaises(Exception):
            run_offline_journaled_fixture(self.plan, fake, self.root)

        writes = [
            event for event in fake.events
            if event[1] == "apply"
        ]
        self.assertEqual(writes, [
            ("a", "apply", "add_deny"),
            ("a", "apply", "create_receiver"),
        ])

        entries = read_journal(
            self.root / "AUDIT.A1B2C3D.jsonl"
        )
        intents = [
            row["data"]["operation"]
            for row in entries if row["kind"] == "INTENT"
        ]
        self.assertEqual(
            intents, ["add_deny", "define_receiver"]
        )
        self.assertNotEqual(entries[-1]["kind"], "CLEAN")

    def test_second_adapter_cannot_write_after_first_reports_unknown(self):
        command = self.plan["a"]["apply_order"][0]
        failing = InMemoryMQ(fail=("a", "apply", "add_deny"))
        independent = InMemoryMQ()
        contract = ApprovedCommandContract(self.plan)

        with LockedFixtureJournal(self.root, "AUDIT.A1B2C3D") as journal:
            first = JournaledOfflineAdapter(failing, journal, contract)
            second = JournaledOfflineAdapter(independent, journal, contract)

            with self.assertRaises(RuntimeError):
                first.apply("a", command)
            with self.assertRaisesRegex(JournalError, "manual recovery"):
                second.apply("a", command)

            self.assertEqual(
                [event for event in independent.events if event[1] == "apply"],
                [],
            )
            self.assertEqual(
                [event["data"]["status"] for event in read_journal(journal.path)
                 if event["kind"] == "RESULT"],
                ["UNKNOWN"],
            )
            self.assertTrue(second._write_uncertain)

    def test_negative_runcheck_causes_rollback_and_unfinished_journal(self):
        fake = InMemoryMQ(fail=("b", "check", "wrong_issuer"))
        with self.assertRaises(Exception):
            run_offline_journaled_fixture(self.plan, fake, self.root)
        entries = read_journal(self.root / "AUDIT.A1B2C3D.jsonl")
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
