"""Offline contract tests for staged daily Synology Paperless provisioning."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "systemd/user/bergen-paperless-autoprovision.service.example"
AUDIT = ROOT / "ansible/playbooks/audit-synology-paperless-groups.yml"


class PaperlessDailyGroupAuditTests(unittest.TestCase):
    def test_oneshot_orders_personal_provision_before_read_only_group_audit(self):
        unit = SERVICE.read_text(encoding="utf-8")
        self.assertIn("Type=oneshot", unit)
        commands = [
            line for line in unit.splitlines()
            if line.startswith("ExecStart=")
        ]
        self.assertEqual(2, len(commands))
        self.assertIn("provision-synology-paperless.yml", commands[0])
        self.assertIn("-e synology_paperless_apply=true", commands[0])
        self.assertIn("audit-synology-paperless-groups.yml", commands[1])
        self.assertNotIn("-e ", commands[1])
        for command in commands:
            self.assertIn("-i ldap.thebergens.net,", command)
            self.assertIn("-u supervisor --become", command)
        self.assertIn(
            "WorkingDirectory=%h/bergen-platform-paperless-runtime",
            unit,
        )

    def test_group_audit_requires_hardened_acl_and_both_directories(self):
        content = AUDIT.read_text(encoding="utf-8")
        self.assertIn("inventory_hostname == 'ldap.thebergens.net'", content)
        self.assertIn("tasks_from: preflight", content)
        self.assertIn("GROUP_PREFLIGHT_PASS root=hardened", content)
        self.assertIn("PRESENT: Eltern", content)
        self.assertIn("PRESENT: Familie", content)
        self.assertNotIn("tasks_from: provision", content)
        self.assertNotIn("tasks_from: harden_root", content)


if __name__ == "__main__":
    unittest.main()
