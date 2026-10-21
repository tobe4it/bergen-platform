#!/usr/bin/env python3
"""Validate one-time CT790 offline boot permissions and post-start verification."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "ansible/playbooks/start-rocky-9-8-ct790-offline.yml"
GUEST_PROBE = ROOT / "ansible/files/nextcloud/inspect_rocky_ct790_firstboot_runtime.sh"


class FirstBootPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PLAN.read_text()
        cls.plays = yaml.safe_load(cls.source)
        cls.play = cls.plays[1]
        cls.tasks = cls.play["tasks"]

    def test_mandatory_independent_firstboot_preflight(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-firstboot-readonly.yml",
        })
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertIn("rocky_ct790_first_start_apply | default(false) | bool",
                      self.source)

    def test_single_mutation_only_explicitly_authorized_pct_start(self):
        starts = []
        for task in self.tasks:
            modules = {k for k in task if k.startswith("ansible.builtin.")}
            self.assertEqual(len(modules), 1, task["name"])
            self.assertTrue(modules <= {
                "ansible.builtin.command",
                "ansible.builtin.assert",
                "ansible.builtin.debug",
            }, task["name"])
            cmd = task.get("ansible.builtin.command")
            if not cmd:
                continue
            argv = cmd["argv"]
            if argv == ["pct", "start", "790"]:
                starts.append(task)
                self.assertEqual(task["when"], "rocky_start_apply | bool")
                self.assertIs(task["changed_when"], True)
                self.assertIs(task["no_log"], True)
            else:
                self.assertIs(task["changed_when"], False, task["name"])
                self.assertTrue(
                    argv in (["pct", "config", "790"],
                             ["pct", "config", "701"],
                             ["pct", "status", "790"])
                    or argv[:3] == ["pct", "exec", "790"],
                    task["name"],
                )
        self.assertEqual(len(starts), 1)
        for forbidden in (
            "pct, stop", "pct, destroy", "pct, restart", "pct, reboot",
            "pct, mount", "pct, template", "pct, set", "pct, create",
            "zfs, destroy", "zfs, rollback",
            "ansible.builtin.shell", "ansible.builtin.copy",
            "ansible.builtin.file", "ansible.builtin.template",
            "ansible.builtin.systemd", "ansible.builtin.apt",
        ):
            self.assertNotIn(forbidden, self.source)

    def test_exact_separate_two_variable_authorization(self):
        for expression in (
            "rocky_ct790_first_start_apply is defined",
            "rocky_ct790_first_start_apply | bool",
            "rocky_ct790_first_start_confirm is defined",
            "rocky_ct790_first_start_confirm == rocky_exact_first_start_confirm",
            "START_ONLY_NETWORKLESS_ROCKY_9_8_CT790",
        ):
            self.assertIn(expression, self.source)
        self.assertIn("ROCKY_9_8_CT790_FIRSTBOOT_PLAN_READ_ONLY_READY",
                      self.source)
        self.assertIn("ROCKY_9_8_CT790_FIRSTBOOT_STARTED_NETWORKLESS_VERIFIED",
                      self.source)
        plan = [t for t in self.tasks if "ROCKY_9_8_CT790_FIRSTBOOT_PLAN_READ_ONLY_READY"
                in str(t)]
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["when"], "not rocky_start_apply | bool")
        for task in self.tasks:
            if task["name"].startswith(("Require a separate exact",
                                        "Read CT790 configuration again",
                                        "Refuse a changed container",
                                        "Read CT790 state one",
                                        "Refuse a second boot",
                                        "Start ONLY separately",
                                        "Read CT790 status after",
                                        "Require CT790 is running",
                                        "Confirm running CT790",
                                        "Fail closed if the running",
                                        "Inspect Rocky guest identity",
                                        "Require actual running Rocky",
                                        "Review CT701 still-isolated",
                                        "Require protected CT701",
                                        "Report only the bounded first-boot")):
                self.assertEqual(task.get("when"), "rocky_start_apply | bool")

    def test_no_auto_cleanup_and_runtime_zero_nic_proof(self):
        for required in (
            "rocky_start_final_config.stdout == rocky_firstboot_config.stdout",
            "'status: stopped' in rocky_start_final_stopped.stdout_lines",
            "rocky_start_after_config.stdout == rocky_firstboot_config.stdout",
            "rocky_start_ct701_after.stdout == rocky_post_ct701.stdout",
            "NON_LOOPBACK_DEVICES=0",
            "GUEST_IDMAP_NONIDENTITY=YES",
            "ROCKY_9_8_CT790_RUNTIME_IDENTITY=VERIFIED",
            "pct_template_authorized: false",
            "automatic_cleanup_or_stop: false",
        ):
            self.assertIn(required, self.source)

    def test_guest_runtime_probe_contains_only_bounded_shell_reads(self):
        s = GUEST_PROBE.read_text()
        for required in (
            "set -eu", "/usr/lib/os-release", "/proc/1/comm",
            "/proc/1/uid_map", "/proc/sys/kernel/hostname",
            "/sys/class/net/lo", "NON_LOOPBACK_DEVICES=0",
            "GUEST_IDMAP_NONIDENTITY=YES", "ROCKY_9_8_CT790_RUNTIME_IDENTITY=VERIFIED",
        ):
            self.assertIn(required, s)
        for forbidden in (
            "touch ", "rm ", "printf > ", "systemctl ",
            "ip link ", "ip route ", "mount ", "umount ", "reboot ",
            "shutdown ", "journalctl ", "curl ", "wget ",
        ):
            self.assertNotIn(forbidden, s)


if __name__ == "__main__":
    unittest.main()
