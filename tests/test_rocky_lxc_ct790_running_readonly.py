#!/usr/bin/env python3
"""Independent CT790 runtime audit is observational; no stopped preflight replay."""
from pathlib import Path
import unittest
import yaml

PLAYBOOK = (
    Path(__file__).resolve().parents[1] /
    "ansible/playbooks/audit-rocky-9-8-ct790-running-readonly.yml"
)


class Ct790RunningReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PLAYBOOK.read_text()
        cls.plays = yaml.safe_load(cls.source)
        cls.play = cls.plays[0]
        cls.tasks = cls.play["tasks"]

    def test_exact_running_guest_only_and_no_stopped_preflight(self):
        self.assertEqual(len(self.plays), 1)
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertNotIn("import_playbook", self.source)
        self.assertIn("'status: running' in rocky_running_status.stdout_lines",
                      self.source)
        self.assertIn("'status: running' in rocky_running_final_status.stdout_lines",
                      self.source)
        self.assertNotIn("'status: stopped'", self.source)

    def test_exact_readonly_command_allowlist(self):
        allowed_commands = [
            ["hostname", "-s"],
            ["pct", "status", "790"],
            ["pct", "config", "790"],
            ["pct", "exec", "790", "--", "/bin/sh", "-ec",
             "{{ lookup('ansible.builtin.file', playbook_dir ~ '/../files/nextcloud/inspect_rocky_ct790_firstboot_runtime.sh') }}"],
            ["pct", "exec", "790", "--", "systemctl", "--no-pager", "is-system-running"],
            ["pct", "exec", "790", "--", "systemctl", "--no-pager", "--plain", "--no-legend", "list-units", "--state=failed"],
            ["pct", "config", "701"],
        ]
        actual = []
        for task in self.tasks:
            modules = [key for key in task if key.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, task["name"])
            self.assertIn(modules[0], (
                "ansible.builtin.command",
                "ansible.builtin.assert",
                "ansible.builtin.debug",
            ))
            cmd = task.get("ansible.builtin.command")
            if cmd:
                argv = cmd["argv"]
                self.assertIn(argv, allowed_commands, task["name"])
                self.assertIs(task.get("changed_when"), False, task["name"])
                actual.append(argv)
                if argv[0:2] == ["pct", "exec"] or argv[0:2] == ["pct", "config"]:
                    self.assertIs(task.get("no_log"), True)
        self.assertEqual(len(actual), 8)
        self.assertEqual(actual.count(["pct", "status", "790"]), 2)
        self.assertEqual(actual.count(["pct", "config", "701"]), 1)
        self.assertEqual(actual.count(["pct", "config", "790"]), 1)

    def test_enforced_guest_network_and_privilege_checks(self):
        for expected in (
            "ROCKY_9_8_CT790_RUNTIME_IDENTITY=VERIFIED",
            "NON_LOOPBACK_DEVICES=0",
            "GUEST_IDMAP_NONIDENTITY=YES",
            "rocky_running_guest.rc == 0",
            "'unprivileged: 1' in rocky_running_config.stdout_lines",
            "'protection: 1' in rocky_running_config.stdout_lines",
            "'onboot: 0' in rocky_running_config.stdout_lines",
            "rocky_running_ct701.stdout_lines",
            "status: RUNNING",
        ):
            self.assertIn(expected, self.source)

    def test_systemd_health_is_diagnostic_not_declared_healthy(self):
        for expected in (
            "is-system-running",
            "--state=failed",
            "'degraded'",
            "'starting'",
            "failed_unit_output_lines",
            "REQUIRES_SEPARATE_REVIEW",
            "RUNNING_WITH_ZERO_FAILED_UNIT_LINES",
            "pct_stop_authorized: false",
            "pct_template_authorized: false",
        ):
            self.assertIn(expected, self.source)
        self.assertNotIn("systemctl, restart", self.source)
        self.assertNotIn("systemctl, stop", self.source)

    def test_no_effectful_actions_and_no_unsafe_modules(self):
        for forbidden in (
            "pct, start", "pct, stop", "pct, restart",
            "pct, reboot", "pct, create", "pct, destroy", "pct, template",
            "pct, mount", "pct, set", "zfs, mount", "zfs, set",
            "ansible.builtin.shell:", "ansible.builtin.raw:",
            "ansible.builtin.copy:", "ansible.builtin.file:",
            "ansible.builtin.template:", "ansible.builtin.systemd:",
        ):
            self.assertNotIn(forbidden, self.source)
        self.assertIn("ROCKY_9_8_CT790_RUNNING_READ_ONLY_INVENTORY_RECORDED",
                      self.source)


if __name__ == "__main__":
    unittest.main()
