"""Code-only atomic staging guard for unattended group metadata reconciliation."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "ansible/playbooks/stage-paperless-group-auto-metadata-reconciliation.yml"
WORKER = ROOT / "ansible/playbooks/stage-paperless-synology-archive-worker.yml"
SENDER = ROOT / "ansible/playbooks/stage-paperless-synology-group-collision-sender.yml"


class AutoGroupMetadataStagingTests(unittest.TestCase):
    def test_opt_in_before_any_imports_and_timer_not_active(self):
        plays = yaml.safe_load(STAGE.read_text())
        self.assertEqual(len(plays), 3)
        tasks = plays[0]["tasks"]
        assert_task = tasks[0]["ansible.builtin.assert"]
        self.assertIn("(paperless_group_metadata_stage | default(false)) is sameas true",
                      assert_task["that"])
        self.assertIn("not ansible_check_mode", assert_task["that"])
        self.assertIn("DISABLE_GROUP_AUTO_TIMER_BEFORE_METADATA_UPDATE",
                      tasks[-1]["ansible.builtin.assert"]["fail_msg"])
        self.assertIn("systemctl", str(tasks[1]))
        self.assertEqual(plays[1]["import_playbook"], WORKER.name)
        self.assertEqual(plays[2]["import_playbook"], SENDER.name)
        self.assertIs(plays[2]["vars"]["paperless_group_collision_stage"], True)

    def test_existing_integrity_checks_and_no_group_automation_enable(self):
        worker = WORKER.read_text()
        sender = SENDER.read_text()
        for marker in ("sha256sum", "archive-move.enabled"):
            self.assertIn(marker, worker + sender)
        self.assertIn("synology_same_volume_archive_move.py", worker)
        self.assertIn("audit_synology_completed_archive_moves.py", sender)
        self.assertIn("synology_scan_sync.py", sender)
        self.assertIn("synology_group_collision_alias.py", sender)
        self.assertNotIn("systemctl enable", STAGE.read_text())
        self.assertNotIn("archive-next-verified-paperless-group-v1", STAGE.read_text())
        self.assertNotIn("commit-paperless-one-group-v1-archive", STAGE.read_text())


if __name__ == "__main__":
    unittest.main()
