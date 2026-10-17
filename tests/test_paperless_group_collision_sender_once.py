"""Privacy-preserving opt-in real sender probe after archival-proof validation."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "ansible/playbooks/run-paperless-synology-group-collision-sender-once.yml"


class GroupCollisionSenderOnceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATH.read_text()
        cls.play = yaml.safe_load(cls.text)[0]
        cls.tasks = cls.play["tasks"]

    def test_exact_explicit_opt_in_and_no_archive_timer(self):
        asserts = self.tasks[0]["ansible.builtin.assert"]["that"]
        self.assertIn("(paperless_group_collision_sender_once | default(false)) is sameas true", asserts)
        self.assertIn("not ansible_check_mode", asserts)
        self.assertIn("STOP_AUTOMATED_GROUP_ARCHIVER_FIRST", self.text)
        self.assertNotIn("systemctl start ", self.text)
        self.assertNotIn("systemctl enable", self.text)

    def test_readonly_code_hash_and_absent_archive_gates(self):
        self.assertIn("VERIFIED_STAGED_SENDER_NO_ARCHIVE_GATE", self.text)
        self.assertIn("sha256sum", self.text)
        for code in ("synology_scan_sync.py", "synology_group_collision_alias.py",
                     "audit_synology_completed_archive_moves.py"):
            self.assertIn(code, self.text)
        for gate in ("archive-move.enabled", "archive-move.homes.enabled",
                     "archive-move.paperless-scan.enabled"):
            self.assertIn(gate, self.text)
        self.assertNotIn("archive-move.enabled; touch", self.text)

    def test_remote_sender_uses_existing_restricted_user_and_gate(self):
        execute = next(t for t in self.tasks
                       if t.get("register") == "sender_once_result")
        args = execute["ansible.builtin.command"]["argv"]
        self.assertEqual(args[0], "ssh")
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("sudo -n -u", args[-1])
        self.assertIn("--scheduled --commit", args[-1])
        self.assertIn("/bin/synology_scan_sync.py", args[-1])
        self.assertIs(execute["no_log"], True)
        self.assertIs(execute["failed_when"], False)

    def test_only_aggregate_output_never_private_paths_or_remote_stderr(self):
        print_task = next(t for t in self.tasks if
                          t.get("name", "").startswith("Reveal only aggregate"))
        joined = "\n".join(print_task["ansible.builtin.debug"]["msg"])
        self.assertIn("GROUP_NEW_INSTANCES_RENAMED=", joined)
        self.assertIn("GROUP_DOCUMENTS_SENT=", joined)
        self.assertIn("GROUP_DOCUMENTS_WAITING=", joined)
        self.assertIn("SENDER_REPORTED_BLOCKERS=", joined)
        self.assertIn("select('match', '^SENT (Familie|Eltern)/')", joined)
        self.assertNotIn("sender_once_result.stderr", joined)
        self.assertNotIn("Privat", joined)
        self.assertNotIn("sender_once_result.stdout }}", joined)
        self.assertIn("SENDER_PARTIAL_OR_BLOCKED", self.text)

    def test_no_archive_code_or_direct_receipt_writes(self):
        for bad in ("archive-next-verified", "commit-paperless-one-group",
                    "archive-move --commit", "unlink(", "write_receipt(",
                    "paperless_group_auto_archive", "paperless_archive_commit"):
            self.assertNotIn(bad, self.text)


if __name__ == "__main__":
    unittest.main()
