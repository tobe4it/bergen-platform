"""Offline safety checks for the optional controller timer (not deployment)."""
import configparser
import subprocess
import unittest
from pathlib import Path

BASE = (Path(__file__).resolve().parents[1] /
        "ansible/files/paperless")
SCRIPT = BASE / "run-paperless-group-auto-v1.sh"
SERVICE = BASE / "bergen-paperless-group-auto-v1.service"
TIMER = BASE / "bergen-paperless-group-auto-v1.timer"


def unit_file(path):
    ini = configparser.RawConfigParser(interpolation=None)
    ini.read(path)
    return ini


class GroupTimerPackageTests(unittest.TestCase):
    def test_bash_syntax_and_no_vault_password_in_argv(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        content = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('readonly VAULT_FILE=', content)
        self.assertIn('--vault-id "paperless@$VAULT_FILE"', content)
        self.assertNotIn("paperless@prompt", content)
        self.assertNotIn("vault_password=", content)
        self.assertIn("-e '{\"paperless_group_auto_archive\":true,\"paperless_archive_commit\":true}'",
                      content)

    def test_expected_two_encrypted_local_vars_and_approved_entrypoint(self):
        content = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("archive-next-verified-paperless-group-v1.yml", content)
        self.assertIn("paperless.vault.yml", content)
        self.assertIn("paperless-synology.local.yml", content)
        self.assertIn("/home/ansible/bergen-platform-pr81", content)
        self.assertIn("/home/ansible/bergen-platform", content)
        self.assertNotIn("commit-paperless-reviewed-groups-v1-once", content)
        self.assertNotIn("purge", content.lower().split('exec "$VENV_ANSIBLE"')[-1])

    def test_service_requires_explicit_root_provisioned_vault_credential(self):
        svc = unit_file(SERVICE)
        self.assertEqual(svc["Service"]["Type"], "oneshot")
        self.assertEqual(svc["Service"]["User"], "ansible")
        self.assertEqual(svc["Service"]["NoNewPrivileges"], "true")
        self.assertEqual(svc["Service"]["UMask"], "0077")
        self.assertEqual(
            svc["Service"]["LoadCredential"],
            "paperless-vault:/etc/bergen-paperless/group-auto-vault")
        self.assertIn(
            "ConditionPathExists=/etc/bergen-paperless/group-auto-vault",
            SERVICE.read_text(encoding="utf-8"))
        self.assertIn("%d/paperless-vault", svc["Service"]["ExecStart"])

    def test_timer_is_not_enabled_by_install(self):
        timer = unit_file(TIMER)
        self.assertEqual(timer["Timer"]["OnUnitInactiveSec"], "5min")
        self.assertEqual(timer["Timer"]["OnBootSec"], "5min")
        self.assertEqual(
            timer["Timer"]["Unit"], "bergen-paperless-group-auto-v1.service")
        self.assertEqual(timer["Install"]["WantedBy"], "timers.target")
        self.assertNotIn("systemctl enable", SCRIPT.read_text(encoding="utf-8"))
        self.assertNotIn("systemctl start", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
