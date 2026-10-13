"""Read-only contract checks for authentik Proxmox preflight."""
from pathlib import Path
import unittest

PLAYBOOK = (
    Path(__file__).resolve().parents[1]
    / "ansible/playbooks/preflight-authentik-infrastructure.yml"
)

class AuthentikInfrastructurePreflightTests(unittest.TestCase):
    def test_read_only_proxmox_inventory_and_guards(self):
        text = PLAYBOOK.read_text(encoding="utf-8")
        for expected in (
            "hosts: venombox",
            "/cluster/nextid",
            '--vmid, "127"',
            "local-zfs",
            "bergen-synology-backup",
            "[pct, config, \"126\"]",
            "/nodes/venombox/network",
            "/cluster/backup",
            "AUTHENTIK_VMID_STORAGE_PREFLIGHT_PASS",
            "AUTHENTIK_PREFLIGHT_READONLY_PASS",
            "deployment: not_performed",
        ):
            self.assertIn(expected, text)
        self.assertEqual(6, text.count("changed_when: false"))
        for denied in (
            "argv: [pct, create",
            "qm create",
            "ansible.builtin.file:",
            "ansible.builtin.copy:",
            "ansible.builtin.template:",
            "ansible.builtin.apt:",
            "ansible.builtin.systemd:",
            "pvesh, create",
            "pvesh, set",
        ):
            self.assertNotIn(denied, text)


if __name__ == "__main__":
    unittest.main()
