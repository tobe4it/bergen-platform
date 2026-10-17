"""Unit and safety contract tests for the generic pct SSH ProxyCommand."""
import importlib.util
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/scripts/pct_ssh_proxy.py"
PLAY = ROOT / "ansible/playbooks/preflight-pct-ssh.yml"

spec = importlib.util.spec_from_file_location("pct_ssh_proxy", SCRIPT)
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class PctSshTransport(unittest.TestCase):
    def test_command_has_explicit_vmid_and_non_interactive_host_connection(self):
        command = transport.build_command("pve.example.net", 999)
        self.assertEqual(command[:2], ["ssh", "-T"])
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("BatchMode=yes", command)
        self.assertIn("root@pve.example.net", command)
        self.assertIn("pct exec 999 -- /usr/bin/python3 -c ", command[-1])
        self.assertIn("127.0.0.1", command[-1])
        self.assertIn("socket.SHUT_WR", command[-1])
        self.assertNotIn("socat", command[-1])

    def test_untrusted_host_and_id_rejected(self):
        bad = ["-V", "bad;hostname", "a b", "foo$(date)", "bad/path", ""]
        for host in bad:
            with self.subTest(host=host), self.assertRaises(ValueError):
                transport.build_command(host, 125)
        for vmid in [0, -1, 99, 1000000000]:
            with self.subTest(vmid=vmid), self.assertRaises(ValueError):
                transport.build_command("pve.example.net", vmid)
        with self.assertRaises(ValueError):
            transport.build_command("pve.example.net", 125, "root;id")

    def test_read_only_preflight(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(plays), 1)
        self.assertFalse(plays[0]["gather_facts"])
        allowed = {"ansible.builtin.assert", "ansible.builtin.command", "ansible.builtin.debug"}
        for task in plays[0]["tasks"]:
            modules = [name for name in task if name.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, task["name"])
            self.assertIn(modules[0], allowed)
            if modules[0] == "ansible.builtin.command":
                self.assertEqual(task["ansible.builtin.command"]["argv"][0], "pct")
                self.assertIs(task.get("changed_when"), False)
                self.assertIs(task.get("check_mode"), False)

    def test_no_real_site_data(self):
        for path in [SCRIPT, PLAY, ROOT / "docs/PROXMOX-PCT-SSH.md"]:
            contents = path.read_text()
            self.assertNotIn("192.168.", contents)
            self.assertNotIn("thebergens.net", contents)
            self.assertNotIn("BEGIN PRIVATE KEY", contents)


if __name__ == "__main__":
    unittest.main()
