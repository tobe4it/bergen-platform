"""Staging must never silently install or enable a destructive document worker."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/stage-paperless-synology-group-collision-sender.yml"
CODE = ROOT / "ansible/files/paperless"


class CollisionStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PLAY.read_text(encoding="utf-8")
        cls.play = yaml.safe_load(cls.raw)[0]
        cls.tasks = cls.play["tasks"]

    def test_opt_in_and_no_archive_timer_while_staging(self):
        first = self.tasks[0]["ansible.builtin.assert"]["that"]
        self.assertIn("(paperless_group_collision_stage | default(false)) is sameas true", first)
        self.assertIn("not ansible_check_mode", first)
        self.assertIn("synology_config.sync_user == 'paperless-sync'", first)
        self.assertIn("systemctl", self.raw)
        self.assertIn("is-active", self.raw)
        self.assertIn("STOP_CONTROLLER_ARCHIVE_TIMER_BEFORE_SENDER_UPDATE", self.raw)
        self.assertNotIn("systemctl enable", self.raw)
        self.assertNotIn("systemctl start", self.raw)

    def test_helpers_installed_before_sender_and_only_fixed_names(self):
        sources = self.play["vars"]["collision_sender_code"]
        self.assertEqual(sources, [
            "audit_synology_completed_archive_moves.py",
            "synology_group_collision_alias.py",
            "synology_scan_sync.py",
        ])
        for name in sources:
            self.assertTrue((CODE / name).is_file(), name)
        self.assertIn("item | quote", self.raw)

    def test_hashed_atomic_root_owned_code_no_receipt_mutation(self):
        self.assertIn("base64 -d", self.raw)
        self.assertIn("hash('sha256')", self.raw)
        self.assertIn("sha256sum", self.raw)
        self.assertIn("chown root:root", self.raw)
        self.assertIn("chmod 0644", self.raw)
        self.assertIn("mktemp", self.raw)
        self.assertIn("mv -f", self.raw)
        self.assertIn("archive-move.paperless-scan.enabled", self.raw)
        self.assertNotIn("synology-sync.enabled", self.raw.split("Atomically install")[1])
        self.assertNotIn("purge --commit", self.raw)

    def test_no_sync_or_archive_gate_is_created(self):
        for dangerous in ("touch archive-move", "archive-move.enabled: true",
                          "paperless_archive_commit", "paperless_group_auto_archive",
                          "synology_scan_sync.py --scheduled",
                          "synology_scan_sync.py --commit"):
            self.assertNotIn(dangerous, self.raw)
        self.assertEqual(self.play["hosts"], "localhost")
        self.assertTrue(self.play.get("connection") == "local")


if __name__ == "__main__":
    unittest.main()
