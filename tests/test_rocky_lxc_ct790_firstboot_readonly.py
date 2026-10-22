#!/usr/bin/env python3
"""Static and synthetic guard tests for the CT790 no-write firstboot preflight."""
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "ansible/playbooks/audit-rocky-9-8-ct790-firstboot-readonly.yml"
CONFIG = """arch: amd64
cores: 2
features: nesting=0
hostname: rocky9-base-790
memory: 2048
onboot: 0
ostype: centos
protection: 1
rootfs: local-zfs:subvol-790-disk-0,size=16G
swap: 0
unprivileged: 1
"""


class FirstBootReadonlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATH.read_text()
        cls.plays = yaml.safe_load(cls.source)
        cls.play = cls.plays[1]
        cls.tasks = cls.play["tasks"]

    def test_release_proof_is_required_in_same_run(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-rootfs-release-readonly.yml",
        })
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertEqual(self.play["vars"]["rocky_firstboot_vmid"], 790)
        self.assertIn("ROCKY_9_8_CT790_ROOTFS_RELEASE_READ_ONLY_VERIFIED",
                      self.source)
        self.assertIn("rocky_release_zfs_mounted.stdout | trim == 'yes'",
                      self.source)

    def test_only_approved_readonly_commands_and_modules(self):
        allowed = {
            "ansible.builtin.command",
            "ansible.builtin.assert",
            "ansible.builtin.debug",
        }
        calls = [
            ["pct", "config", "790"],
            ["pct", "help", "start"],
            ["pct", "status", "790"],
        ]
        actual_calls = []
        for task in self.tasks:
            modules = {key for key in task if key.startswith("ansible.builtin.")}
            self.assertEqual(len(modules), 1, task["name"])
            self.assertTrue(modules <= allowed, task["name"])
            cmd = task.get("ansible.builtin.command")
            if cmd:
                self.assertIs(task.get("changed_when"), False)
                actual_calls.append(cmd["argv"])
                if cmd["argv"] == ["pct", "config", "790"]:
                    self.assertIs(task.get("no_log"), True)
        self.assertEqual(actual_calls, calls)

    def test_strict_key_allowlist_rejects_unexpected_guest_features(self):
        allowed = set(self.play["vars"]["rocky_firstboot_allowed_config_keys"])
        pattern = r"(?m)^([^\s:\n][^:\n]*):"
        def unknown(cfg):
            return set(re.findall(pattern, cfg)) - allowed
        self.assertFalse(unknown(CONFIG))
        for appended in (
            "net0: name=eth0,bridge=vmbr0\n",
            "mp0: /some/host/path,mp=/mnt/host\n",
            "hookscript: local:snippets/evil.pl\n",
            "lxc.mount.entry: / /host none bind 0 0\n",
            "lxc.net.0.type: veth\n",
            "lxc.idmap: u 0 100000 65536\n",
            "startup: order=1\n",
            "nameserver: 8.8.8.8\n",
            "template: 1\n",
            "dev0: /dev/kvm\n",
        ):
            with self.subTest(appended=appended):
                self.assertTrue(unknown(CONFIG + appended))
        for disallowed_value in ("nesting=1", "keyctl=1", "nesting=0,keyctl=1"):
            with self.subTest(features=disallowed_value):
                self.assertRegex(
                    CONFIG.replace("nesting=0", disallowed_value),
                    r"(?m)^features: (?!nesting=0$)"
                )

    def test_no_start_approval_or_other_mutations(self):
        for required in (
            "ROCKY_9_8_CT790_FIRSTBOOT_PREFLIGHT_READ_ONLY_READY",
            "pct_start_authorized: false",
            "pct_template_authorized: false",
            "guest_started: false",
            "runtime_behavior_tested: false",
            "ct701_unchanged: true",
            "network_interfaces_configured: 0",
            "additional_mounts: 0",
            "hooks_detected: false",
        ):
            self.assertIn(required, self.source)
        for forbidden in (
            "ansible.builtin.copy", "ansible.builtin.file",
            "ansible.builtin.shell", "ansible.builtin.template",
            "pct, start, '790'", "pct, set", "pct, mount",
            "zfs, mount", "pct, template", "pct, stop",
        ):
            self.assertNotIn(forbidden, self.source)


if __name__ == "__main__":
    unittest.main()
