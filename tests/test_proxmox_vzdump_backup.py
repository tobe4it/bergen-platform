"""Offline safety checks for scoped Paperless host-side backup timer."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/proxmox_vzdump_backup"


class ProxmoxVzdumpBackupSafety(unittest.TestCase):
    def test_gated_and_scoped(self):
        tasks = (ROLE / "tasks/main.yml").read_text()
        playbook = (ROOT / "ansible/playbooks/configure-paperless-backup.yml").read_text()
        self.assertIn("paperless_backup_schedule_approved | bool", tasks)
        self.assertIn("inventory_hostname == paperless_backup_pve_host", tasks)
        self.assertIn("backup_mount_source.stdout == paperless_backup_expected_export", tasks)
        self.assertIn("backup_tmpdir_stat.stat.mode == '1777'", tasks)
        self.assertIn("paperless_backup_pve_host | default", playbook)
        self.assertNotIn("hosts: all", playbook)

    def test_service_backup_safety(self):
        service = (ROLE / "templates/bergen-paperless-vzdump.service.j2").read_text()
        self.assertIn("--mode stop", service)
        self.assertIn("--compress zstd", service)
        self.assertIn("--tmpdir", service)
        self.assertIn("--prune-backups", service)
        self.assertIn("ExecStartPre=/usr/bin/mountpoint -q", service)
        self.assertNotIn("--all", service)

    def test_timer_review(self):
        timer = (ROLE / "templates/bergen-paperless-vzdump.timer.j2").read_text()
        defaults = (ROLE / "defaults/main.yml").read_text()
        self.assertIn("Persistent=false", timer)
        self.assertIn("*-*-* 03:00:00 Europe/Berlin", defaults)
        self.assertIn("paperless_backup_timer_enabled: false", defaults)
        self.assertIn("paperless_backup_schedule_approved: false", defaults)

    def test_existing_scheduled_backup_is_protected(self):
        tasks=(ROLE / "tasks/main.yml").read_text()
        self.assertIn("BACKUP_UNIT_DRIFT", tasks)
        self.assertIn("BACKUP_UNIT_PARTIAL_OR_UNTRUSTED", tasks)
        self.assertIn("BACKUP_EXISTING_SCHEDULE_CHANGE_REQUIRES_SEPARATE_APPROVAL", tasks)
        self.assertIn("ansible.builtin.slurp", tasks)
        self.assertIn("backup_existing_units.results[0].stat.exists", tasks)
        self.assertIn("backup_existing_timer_state_change_approved: false",
                      (ROLE / "defaults/main.yml").read_text())
        self.assertIn("backup=1(,|$)", tasks)

    def test_site_values_not_versioned(self):
        ignored = (ROOT / ".gitignore").read_text()
        self.assertIn("ansible/vars/paperless-backup.local.yml", ignored)
        sample = (ROOT / "docs/examples/paperless-backup.local.yml.example").read_text()
        self.assertIn("REPLACE_WITH_NFS_SERVER", sample)


if __name__ == "__main__":
    unittest.main()
