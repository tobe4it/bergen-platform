"""Post systemd unattended group move readiness never replays or releases a PDF."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/verify-paperless-group-auto-v1-readiness.yml"


class PostAutomaticArchiveReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = PLAY.read_text()
        cls.plays = yaml.safe_load(cls.code)

    def test_reruns_full_independent_audit_readonly_and_does_not_select_source(self):
        self.assertEqual(self.plays[0]["import_playbook"],
                         "audit-paperless-import-lifecycle-15-26.yml")
        self.assertIs(self.plays[0]["vars"]["paperless_lifecycle_quiet"], True)
        self.assertEqual(self.plays[1]["hosts"], "venombox")
        self.assertNotIn("archive-next-verified", self.code)
        self.assertNotIn("commit-paperless-one-group", self.code)
        self.assertNotIn("paperless_archive_only", self.code)
        self.assertNotIn("systemctl start", self.code)
        self.assertNotIn("systemctl enable", self.code)
        self.assertNotIn("--commit", self.code)

    def test_must_prove_at_least_one_extra_archived_after_sixteen_baseline(self):
        tests = [
            t for task in self.plays[1]["tasks"]
            for t in task.get("ansible.builtin.assert", {}).get("that", [])
        ]
        self.assertIn("group_accept_archived | int >= 17", tests)
        self.assertIn("group_accept_imported | int >= 30", tests)
        self.assertIn(
            "group_accept_remaining | int + group_accept_archived | int == group_accept_imported | int",
            tests)
        self.assertIn("group_accept_group_archived | int >= 1", tests)
        self.assertIn("'DELETED_BY_USER 2' in lifecycle_report.stdout_lines", tests)

    def test_no_raw_private_evidence_published_and_gates_rechecked(self):
        raw = [
            x for x in self.plays[1]["tasks"]
            if "ansible.builtin.set_fact" in x or "ansible.builtin.command" in x
        ]
        self.assertEqual(len(raw), 2)
        for task in raw:
            self.assertIs(task["no_log"], True)
        self.assertIn("ALL_ARCHIVE_RELEASE_GATES_ABSENT", self.code)
        self.assertIn("archive-move.paperless-scan.enabled", self.code)
        self.assertIn("AUTO_ARCHIVE_NEW_MOVE_VERIFIED=true", self.code)
        self.assertIn("NO_PURGE_AUTHORIZED=true", self.code)
        self.assertNotIn("lifecycle_report.stdout_lines\n", self.code.split("Print only reconciled independent counts")[1])


if __name__ == "__main__":
    unittest.main()
