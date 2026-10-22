#!/usr/bin/env python3
"""Static policy tests: exact degraded sole-DNF exception, no automatic hard stop."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/shutdown-rocky-9-8-ct790-dnf-exception-offline.yml"


class DnfShutdownExceptionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PLAY.read_text()
        cls.plays = yaml.safe_load(cls.raw)
        cls.tasks = cls.plays[1]["tasks"]

    def test_independent_running_audit_and_locked_default(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-running-readonly.yml"
        })
        play = self.plays[1]
        self.assertEqual(play["hosts"], "venombox")
        self.assertIs(play["become"], True)
        self.assertIs(play["gather_facts"], False)
        self.assertIs(play["any_errors_fatal"], True)
        self.assertEqual(play["vars"]["rocky_dnf_shutdown_timeout_seconds"], 90)
        self.assertIn("rocky_ct790_dnf_shutdown_apply | default(false) | bool", self.raw)
        self.assertIn("SHUTDOWN_ONLY_CT790_HEALTHY_OR_SOLE_FAILED_DNF_MAKECACHE", self.raw)
        self.assertIn("not ansible_check_mode", self.raw)

    def test_only_exact_one_graceful_command_mutates_and_only_on_approval(self):
        expected = ["pct", "shutdown", "790", "--timeout", "90", "--forceStop", "0"]
        commands = []
        for task in self.tasks:
            modules = [k for k in task if k.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, msg=task["name"])
            self.assertIn(modules[0], [
                "ansible.builtin.assert", "ansible.builtin.command",
                "ansible.builtin.debug", "ansible.builtin.set_fact",
            ], msg=task["name"])
            c = task.get("ansible.builtin.command")
            if not c:
                continue
            cmd = c["argv"]
            commands.append(cmd)
            if cmd[0:2] == ["pct", "shutdown"]:
                self.assertEqual(cmd, expected)
                self.assertIs(task.get("changed_when"), True)
                self.assertIs(task.get("no_log"), True)
                self.assertEqual(task.get("when"), "rocky_dnf_shutdown_apply | bool")
            else:
                self.assertIs(task.get("changed_when"), False)
                self.assertTrue(
                    cmd[:2] == ["python3", "-c"] or
                    cmd in [
                        ["pct", "help", "shutdown"],
                        ["pct", "config", "790"], ["pct", "config", "701"],
                        ["pct", "status", "790"],
                        ["pct", "exec", "790", "--", "systemctl", "--no-pager",
                         "is-system-running"],
                        ["pct", "exec", "790", "--", "systemctl", "--no-pager",
                         "--plain", "--no-legend", "list-units",
                         "--state=failed"],
                        ["pct", "exec", "790", "--", "systemctl", "--no-pager",
                         "show",
                         "--property=Id,LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus,StateChangeTimestamp",
                         "dnf-makecache.service"],
                    ], msg=task["name"])
                if cmd[:3] == ["pct", "exec", "790"] or cmd[:2] == ["python3", "-c"] or cmd[:2] == ["pct", "config"]:
                    self.assertIs(task.get("no_log"), True)
        self.assertEqual(commands.count(expected), 1)
        self.assertEqual(len(commands), 13)

    def test_default_preview_and_new_exact_scope_approval(self):
        for snippet in (
            "when: not rocky_dnf_shutdown_apply | bool",
            "ROCKY_9_8_CT790_DNF_EXCEPTION_SHUTDOWN_PLAN_READ_ONLY_READY",
            "rocky_ct790_dnf_shutdown_apply is defined",
            "rocky_ct790_dnf_shutdown_apply | bool",
            "rocky_ct790_dnf_shutdown_confirm is defined",
            "rocky_ct790_dnf_shutdown_confirm == rocky_dnf_shutdown_exact_confirm",
            "Previous healthy-only approval does not cover failed-DNF shutdown exception",
            "ROCKY_9_8_CT790_DNF_EXCEPTION_GRACEFUL_SHUTDOWN_STOPPED_VERIFIED",
            "pct_template_authorized: false",
        ):
            self.assertIn(snippet, self.raw)

    def test_exception_only_exact_failed_dnf_exit_one(self):
        required = [
            "rocky_running_systemd.stdout | trim == 'running'",
            "rocky_running_systemd.stdout | trim == 'degraded'",
            "rocky_running_failed_units.stdout_lines | length == 0",
            "rocky_running_failed_units.stdout_lines | length == 1",
            "parse_ct790_failed_unit.py",
            "rocky_dnf_shutdown_unit_parse.rc == 0",
            "rocky_dnf_shutdown_unit_fields.Id == 'dnf-makecache.service'",
            "rocky_dnf_shutdown_unit_fields.LoadState == 'loaded'",
            "rocky_dnf_shutdown_unit_fields.ActiveState == 'failed'",
            "rocky_dnf_shutdown_unit_fields.Result == 'exit-code'",
            "rocky_dnf_shutdown_unit_fields.ExecMainStatus == '1'",
            "rocky_dnf_shutdown_unit_fields.ExecMainCode == '1'",
            "rocky_dnf_shutdown_last_systemd.stdout == rocky_running_systemd.stdout",
            "rocky_dnf_shutdown_last_failed.stdout == rocky_running_failed_units.stdout",
            "rocky_dnf_shutdown_last_unit_show.stdout == rocky_dnf_shutdown_unit_show.stdout",
            "NON_LOOPBACK_DEVICES=0", "GUEST_IDMAP_NONIDENTITY=YES",
            "rocky_dnf_shutdown_after_config.stdout == rocky_running_config.stdout",
            "rocky_dnf_shutdown_ct701_after.stdout == rocky_running_ct701.stdout",
        ]
        for snippet in required:
            self.assertIn(snippet, self.raw)

    def test_no_forced_stop_service_reset_restart_or_template(self):
        for forbidden in (
            "argv: [pct, stop", "argv: [pct, start", "argv: [pct, restart",
            "argv: [pct, destroy", "argv: [pct, set",
            "argv: [pct, template", "argv: [pct, mount",
            "ansible.builtin.shell:", "ansible.builtin.raw:",
            "ansible.builtin.file:", "ansible.builtin.copy:",
            "ansible.builtin.systemd:", "ansible.builtin.service:",
            "systemctl, reset-failed", "systemctl, restart",
            "dnf, makecache", "dnf, update", "dnf, install",
        ):
            self.assertNotIn(forbidden, self.raw)
        self.assertIn("--forceStop, '0'", self.raw)


if __name__ == "__main__":
    unittest.main()
