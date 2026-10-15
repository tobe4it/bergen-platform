"""Read-only and site-neutral contract for the proposed reverse-proxy preflight."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/preflight-reverse-proxy.yml"
EXAMPLE = ROOT / "ansible/group_vars/all/bergen-proxy.yml.example"


class ReverseProxyPreflightContract(unittest.TestCase):
    def setUp(self):
        self.plays = yaml.safe_load(PLAYBOOK.read_text())
        self.sample = yaml.safe_load(EXAMPLE.read_text())

    def test_only_preflight_plays_and_no_modifying_modules(self):
        self.assertEqual(len(self.plays), 2)
        permitted = {"ansible.builtin.assert", "ansible.builtin.command",
                     "ansible.builtin.set_fact", "ansible.builtin.debug"}
        for play in self.plays:
            self.assertFalse(play.get("gather_facts", True))
            for task in play["tasks"]:
                modules = [key for key in task if key.startswith("ansible.builtin.")]
                self.assertEqual(len(modules), 1, task["name"])
                self.assertIn(modules[0], permitted, task["name"])
                if modules[0] == "ansible.builtin.command":
                    self.assertIs(task.get("changed_when"), False, task["name"])
                    self.assertIs(task.get("check_mode"), False, task["name"])
                    self.assertIn(task[modules[0]]["argv"][0],
                                  {"pvesh", "pct", "pvesm", "ip"})

    def test_generic_example_and_separate_secrets(self):
        self.assertTrue(self.sample["lxc_unprivileged"])
        self.assertEqual(self.sample["lxc_firewall"], 1)
        self.assertTrue(self.sample["reverse_proxy_internal_only"])
        self.assertEqual(len({s["hostname"] for s in self.sample["reverse_proxy_sites"]}),
                         len(self.sample["reverse_proxy_sites"]))
        text = EXAMPLE.read_text()
        self.assertNotIn("thebergens.net", text)
        self.assertNotIn("192.168.", text)
        self.assertNotIn("BEGIN PRIVATE KEY", text)


if __name__ == "__main__":
    unittest.main()
