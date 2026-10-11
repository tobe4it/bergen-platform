"""Contract tests for isolated LXC bootstrap over PCT-mediated SSH."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/bootstrap-isolated-lxc.yml"
SOURCE = PLAY.read_text()


class IsolatedBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.play = yaml.safe_load(SOURCE)[0]

    def test_explicit_guest_target_and_no_bulk_linux_group(self):
        self.assertIn("lxc_inventory_group", self.play["hosts"])
        self.assertNotIn("linux_lxcs", self.play["hosts"])
        self.assertEqual(self.play["serial"], 1)
        self.assertFalse(self.play["gather_facts"])

    def test_check_mode_or_explicit_live_approval(self):
        checks = self.play["pre_tasks"][0]["ansible.builtin.assert"]["that"]
        self.assertIn("inventory_hostname == lxc_hostname", checks)
        self.assertIn(
            "ansible_check_mode or (isolated_lxc_bootstrap_approved | default(false) | bool)",
            checks)
        joined = " ".join(checks)
        for expected in ["pct_ssh_proxy.py", "StrictHostKeyChecking=yes",
                         "HostKeyAlias=lxc-", "--vmid "]:
            self.assertIn(expected, joined)

    def test_no_direct_port_probe_or_hostkey_reset(self):
        self.assertNotIn("ansible.builtin.wait_for:", SOURCE)
        self.assertNotIn("ssh-keyscan", SOURCE.split("  tasks:", 1)[-1])
        self.assertNotIn("ssh-keygen -R", SOURCE)
        wait = self.play["pre_tasks"][1]
        self.assertIn("ansible.builtin.wait_for_connection", wait)
        self.assertEqual(wait["changed_when"], False)

    def test_reuse_existing_baseline_and_validate_live_only(self):
        tasks = self.play["tasks"]
        self.assertEqual(tasks[0]["ansible.builtin.import_role"]["name"], "lxc_base")
        tmux_check = next(t for t in tasks if "Confirm tmux" in t["name"])
        self.assertEqual(tmux_check["when"], "not ansible_check_mode")

    def test_use_ansible_facts_mapping_not_deprecated_injected_vars(self):
        checks = self.play["pre_tasks"][3]["ansible.builtin.assert"]["that"]
        self.assertIn("ansible_facts['system'] == 'Linux'", checks)
        self.assertIn("ansible_facts['os_family'] == 'Debian'", checks)
        self.assertIn("ansible_facts['hostname'] == lxc_hostname", checks)
        for old_name in ["ansible_system", "ansible_os_family", "ansible_hostname"]:
            self.assertNotIn(old_name, SOURCE)

    def test_no_site_specific_values(self):
        self.assertNotIn("192.168.", SOURCE)
        self.assertNotIn("thebergens.net", SOURCE)
        self.assertNotIn("BEGIN PRIVATE KEY", SOURCE)


if __name__ == "__main__":
    unittest.main()
