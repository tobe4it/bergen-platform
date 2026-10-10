"""Offline crash-recovery and journal-integrity checks; no MQ access."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from module_utils.bergen_mq_chlauth_journal import (
    JournalError, LockedFixtureJournal, read_journal, recovery_report,
)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "audit"
        self.prefix = "AUDIT.A1B2C3D"

    def test_clean_journal_and_digest_chain(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("a", "add_deny")
            audit.result("a", "add_deny", "ACKED")
            audit.intent("b", "add_deny")
            audit.result("b", "add_deny", "ACKED")
            audit.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
            path = audit.path
        events = read_journal(path)
        self.assertEqual([x["kind"] for x in events],
                         ["BEGIN", "INTENT", "RESULT", "INTENT", "RESULT", "CLEAN"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_interrupted_run_blocks_future_runs(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("a", "add_deny")
        with self.assertRaisesRegex(JournalError, "Unresolved"):
            with LockedFixtureJournal(self.root, "AUDIT.B2B2B2B"):
                pass

    def test_concurrent_session_refused(self):
        with LockedFixtureJournal(self.root, self.prefix):
            with self.assertRaisesRegex(JournalError, "active"):
                with LockedFixtureJournal(self.root, "AUDIT.C3C3C3C"):
                    pass

    def test_unknown_result_keeps_journal_unresolved(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("a", "add_deny")
            audit.result("a", "add_deny", "UNKNOWN")
            with self.assertRaisesRegex(JournalError, "Unresolved"):
                audit.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
        with self.assertRaises(JournalError):
            with LockedFixtureJournal(self.root, "AUDIT.B2B2B2B"):
                pass

    def test_unsuccessful_result_blocks_followup_intents_in_same_session(self):
        for status in ("UNKNOWN", "FAILED"):
            with self.subTest(status=status):
                root = self.root / status.lower()
                with LockedFixtureJournal(root, self.prefix) as journal:
                    journal.intent("a", "add_deny")
                    journal.result("a", "add_deny", status)
                    with self.assertRaisesRegex(JournalError, "manual recovery"):
                        journal.intent("b", "define_receiver")
                    with self.assertRaises(JournalError):
                        journal.mark_clean({
                            "a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"
                        })
                    path = journal.path
                self.assertEqual(
                    [event["kind"] for event in read_journal(path)],
                    ["BEGIN", "INTENT", "RESULT"],
                )

    def test_rehashed_intent_after_unknown_result_is_invalid(self):
        with LockedFixtureJournal(self.root, self.prefix) as journal:
            journal.intent("a", "add_deny")
            journal.result("a", "add_deny", "UNKNOWN")
            path = journal.path

        def forge(rows):
            rows.append({
                "seq": 0, "prev": "", "kind": "INTENT",
                "data": {"side": "b", "operation": "define_receiver"},
                "digest": "",
            })
            rows.append({
                "seq": 0, "prev": "", "kind": "RESULT",
                "data": {"side": "b", "operation": "define_receiver",
                         "status": "ACKED"},
                "digest": "",
            })

        self._forge_valid_digests(path, forge)
        with self.assertRaisesRegex(JournalError, "Intent after failed"):
            read_journal(path)

    def test_no_completion_without_both_verified_sides(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            with self.assertRaises(JournalError):
                audit.mark_clean({"a": "VERIFIED_CLEAN"})
        self.assertEqual(read_journal(audit.path)[-1]["kind"], "BEGIN")

    def test_invalid_operation_and_unmatched_result_refused(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            with self.assertRaises(JournalError):
                audit.intent("a", "ALTER_QMGR")
            with self.assertRaises(JournalError):
                audit.result("a", "add_deny", "ACKED")
            audit.intent("a", "add_deny")
            with self.assertRaises(JournalError):
                audit.intent("b", "add_deny")

    def test_truncation_or_tampering_detected(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
        path = audit.path
        saved = path.read_bytes()
        path.write_bytes(saved[:-1])
        with self.assertRaises(JournalError):
            read_journal(path)
        path.write_bytes(saved.replace(b"BEGIN", b"OTHER"))
        with self.assertRaises(JournalError):
            read_journal(path)

    def test_symlink_and_insecure_directory_refused(self):
        self.root.mkdir(mode=0o700)
        (Path(self.temp.name) / "alias").symlink_to(self.root)
        with self.assertRaises(JournalError):
            with LockedFixtureJournal(Path(self.temp.name) / "alias",
                                      self.prefix):
                pass
        os.chmod(self.root, 0o755)
        with self.assertRaises(JournalError):
            with LockedFixtureJournal(self.root, self.prefix):
                pass

    def test_prefix_validation(self):
        for prefix in ("BGT.CLIENT", "AUDIT.ABC123", "BGT.abc1234", "../pwn"):
            with self.subTest(prefix=prefix):
                with self.assertRaises(JournalError):
                    LockedFixtureJournal(self.root, prefix)


    @staticmethod
    def _forge_valid_digests(path, mutate):
        """Adversarial event semantics with valid SHA-256 chain."""
        records = [json.loads(row) for row in path.read_text().splitlines()]
        mutate(records)
        previous = "0" * 64
        for seq, record in enumerate(records, 1):
            record["seq"] = seq
            record["prev"] = previous
            core = {key: record[key] for key in ("seq", "prev", "kind", "data")}
            encoded = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
            previous = hashlib.sha256(encoded).hexdigest()
            record["digest"] = previous
        path.write_text("".join(json.dumps(r) + "\n" for r in records))

    def test_recovery_report_unanswered_intent_is_not_cleanup_authority(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("a", "add_deny")
        report = recovery_report(audit.path)
        self.assertEqual(report["state"], "MANUAL_REVIEW_REQUIRED")
        self.assertTrue(report["has_unanswered_intent"])
        self.assertEqual(report["possible_residual_sides"], ["a"])
        self.assertEqual(report["attempts"][0]["status"], "NO_RESULT")
        self.assertFalse(report["can_auto_cleanup"])
        self.assertFalse(report["can_authorize_live_apply"])

    def test_recovery_report_after_uncertain_write(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("b", "add_allow")
            audit.result("b", "add_allow", "UNKNOWN")
        report = recovery_report(audit.path)
        self.assertFalse(report["has_unanswered_intent"])
        self.assertEqual(report["attempts"][0]["status"], "UNKNOWN")
        self.assertEqual(report["possible_residual_sides"], ["b"])
        self.assertTrue(report["requires_independent_mq_readback"])

    def test_recovery_report_clean_still_not_live_authorization(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
        report = recovery_report(audit.path)
        self.assertEqual(report["state"], "CLEAN_RECORDED")
        self.assertEqual(report["possible_residual_sides"], [])
        self.assertFalse(report["can_auto_cleanup"])
        self.assertFalse(report["can_authorize_live_apply"])

    def test_reject_rehashed_unmatched_result(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("a", "add_deny")
            audit.result("a", "add_deny", "ACKED")
        self._forge_valid_digests(
            audit.path, lambda rows: rows[2]["data"].update({"side": "b"}))
        with self.assertRaisesRegex(JournalError, "Unmatched"):
            read_journal(audit.path)

    def test_reject_rehashed_forged_clean_after_failure(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("a", "add_deny")
            audit.result("a", "add_deny", "UNKNOWN")
        self._forge_valid_digests(
            audit.path,
            lambda rows: rows.append({
                "seq": 0, "prev": "", "kind": "CLEAN",
                "data": {"verified_sides": {
                    "a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"}},
                "digest": ""
            }))
        with self.assertRaisesRegex(JournalError, "Invalid clean"):
            read_journal(audit.path)

    def test_reject_rehashed_second_begin(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("a", "add_deny")
        self._forge_valid_digests(
            audit.path, lambda rows: rows[1].update({"kind": "BEGIN"}))
        with self.assertRaisesRegex(JournalError, "Unknown"):
            read_journal(audit.path)

    def test_reject_journal_prefix_mismatch(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            pass
        self._forge_valid_digests(
            audit.path,
            lambda rows: rows[0]["data"].update({"prefix": "AUDIT.B2B2B2B"}))
        with self.assertRaisesRegex(JournalError, "BEGIN must bind"):
            read_journal(audit.path)


    def test_recovery_cli_clean_is_read_only(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
        original = audit.path.read_bytes()
        cli = Path(__file__).resolve().parents[1] / "scripts" / "mq_chlauth_journal_inspect.py"
        run = subprocess.run(
            [sys.executable, str(cli), str(audit.path)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["state"], "CLEAN_RECORDED")
        self.assertEqual(audit.path.read_bytes(), original)

    def test_recovery_cli_unfinished_returns_nonzero(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("b", "add_deny")
        cli = Path(__file__).resolve().parents[1] / "scripts" / "mq_chlauth_journal_inspect.py"
        run = subprocess.run(
            [sys.executable, str(cli), str(audit.path)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(
            json.loads(run.stdout)["state"], "MANUAL_REVIEW_REQUIRED"
        )

    def test_recovery_cli_corrupted_returns_error(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            pass
        audit.path.write_text("corrupted\n")
        cli = Path(__file__).resolve().parents[1] / "scripts" / "mq_chlauth_journal_inspect.py"
        run = subprocess.run(
            [sys.executable, str(cli), str(audit.path)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(run.returncode, 3)
        self.assertEqual(json.loads(run.stdout)["state"], "INVALID_JOURNAL")


if __name__ == "__main__":
    unittest.main()
