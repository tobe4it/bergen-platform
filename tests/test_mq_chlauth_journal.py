"""Offline crash-recovery and journal-integrity checks; no MQ access."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from module_utils.bergen_mq_chlauth_journal import (
    JournalError, LockedFixtureJournal, read_journal,
)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "audit"
        self.prefix = "BGT.A1B2C3D"

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
            with LockedFixtureJournal(self.root, "BGT.B2B2B2B"):
                pass

    def test_concurrent_session_refused(self):
        with LockedFixtureJournal(self.root, self.prefix):
            with self.assertRaisesRegex(JournalError, "active"):
                with LockedFixtureJournal(self.root, "BGT.C3C3C3C"):
                    pass

    def test_unknown_result_keeps_journal_unresolved(self):
        with LockedFixtureJournal(self.root, self.prefix) as audit:
            audit.intent("a", "add_deny")
            audit.result("a", "add_deny", "UNKNOWN")
            with self.assertRaisesRegex(JournalError, "Unresolved"):
                audit.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
        with self.assertRaises(JournalError):
            with LockedFixtureJournal(self.root, "BGT.B2B2B2B"):
                pass

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
        for prefix in ("BGT.CLIENT", "BGT.ABC123", "BGT.abc1234", "../pwn"):
            with self.subTest(prefix=prefix):
                with self.assertRaises(JournalError):
                    LockedFixtureJournal(self.root, prefix)


if __name__ == "__main__":
    unittest.main()
