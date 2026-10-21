#!/usr/bin/env python3
"""CT790 shutdown proposal: fail closed, default read-only, no hard stop."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "ansible/playbooks/shutdown-rocky-9-8-ct790-offline.yml"


class RockyShutdownPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PATH.read_text()
        cls.plays = yaml.safe_load(cls.raw)
        cls.play = cls.plays[1]
        cls.tasks = cls.play["tasks"]

    def test_same_run_independent_running_preflight(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-running-readonly.yml",
        })
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertEqual(self.play["vars"]["rocky_shutdown_timeout_seconds"], 90)
        self.assertIn("rocky_ct790_shutdown_apply | default(false) | bool", self.raw)
        self.assertIn("rocky_running_systemd.stdout | trim == 'running'", self.raw)
        self.assertIn("rocky_running_failed_units.stdout_lines | length == 0", self.raw)
        self.assertIn("NON_LOOPBACK_DEVICES=0", self.raw)
        self.assertIn("GUEST_IDMAP_NONIDENTITY=YES", self.raw)

    def test_only_single_exact_graceful_pct_shutdown_can_mutate(self):
        actual = []
        for task in self.tasks:
            modules = {k for k in task if k.startswith("ansible.builtin.")}
            self.assertEqual(len(modules), 1, msg=task["name"])
            self.assertTrue(modules <= {
                "ansible.builtin.assert",
                "ansible.builtin.command",
                "ansible.builtin.debug",
            }, msg=task["name"])
            argv = task.get("ansible.builtin.command", {}).get("argv")
            if argv:
                actual.append(argv)
                if argv[0:2] == ["pct", "shutdown"]:
                    self.assertEqual(argv, [
                        "pct", "shutdown", "790",
                        "--timeout", "90", "--forceStop", "0",
                    ])
                    self.assertIs(task.get("changed_when"), True)
                    self.assertIs(task.get("no_log"), True)
                    self.assertEqual(task.get("when"), "rocky_shutdown_apply | bool")
                else:
                    self.assertIn(argv, [
                        ["pct", "help", "shutdown"],
                        ["pct", "config", "790"],
                        ["pct", "config", "701"],
                        ["pct", "status", "790"],
                    ])
                    self.assertIs(task.get("changed_when"), False)
        self.assertEqual(
            actual.count(["pct", "shutdown", "790", "--timeout", "90",
                          "--forceStop", "0"]), 1
        )
        self.assertEqual(len(actual), 7)

    def test_default_noop_and_double_approval(self):
        for expected in (
            "ROCKY_9_8_CT790_SHUTDOWN_PLAN_READ_ONLY_READY",
            "when: not rocky_shutdown_apply | bool",
            "rocky_ct790_shutdown_apply is defined",
            "rocky_ct790_shutdown_apply | bool",
            "rocky_ct790_shutdown_confirm is defined",
            "rocky_ct790_shutdown_confirm == rocky_shutdown_confirm_exact",
            "SHUTDOWN_ONLY_RUNNING_NETWORKLESS_CT790",
            "rocky_shutdown_last_config.stdout == rocky_running_config.stdout",
            "'status: running' in rocky_shutdown_before_state.stdout_lines",
            "ROCKY_9_8_CT790_GRACEFUL_SHUTDOWN_STOPPED_VERIFIED",
            "'status: stopped' in rocky_shutdown_after_state.stdout_lines",
            "rocky_shutdown_ct701_after.stdout == rocky_running_ct701.stdout",
            "pct_template_authorized: false",
            "force_stopped: false",
        ):
            self.assertIn(expected, self.raw)
        gated = [task for task in self.tasks if
                 task["name"].startswith((
                     "Require separately approved exact",
                     "Read exact CT790 config immediately",
                     "Reject PVE CT790 configuration",
                     "Independently confirm CT790",
                     "Refuse re-run when CT790",
                     "Request only one explicitly",
                     "Read CT790 status after single",
                     "Require CT790 stopped",
                     "Confirm original CT790",
                     "Refuse any unexpected CT790",
                     "Confirm protected CT701",
                     "Demand exact protected offline CT701",
                     "Report only verified graceful"
                 ))]
        self.assertEqual(len(gated), 13)
        self.assertTrue(all(t.get("when") == "rocky_shutdown_apply | bool"
                            for t in gated))

    def test_no_force_stop_retry_reboot_template_or_config_write(self):
        for forbidden in (
            "argv: [pct, stop", "argv: [pct, restart",
            "argv: [pct, reboot", "argv: [pct, start",
            "argv: [pct, create", "argv: [pct, destroy",
            "argv: [pct, template", "argv: [pct, set",
            "argv: [zfs, rollback", "argv: [zfs, destroy",
            "ansible.builtin.shell:", "ansible.builtin.raw:",
            "ansible.builtin.copy:", "ansible.builtin.file:",
            "ansible.builtin.template:", "ansible.builtin.service:",
            "ansible.builtin.systemd:",
        ):
            self.assertNotIn(forbidden, self.raw)
        self.assertIn("--forceStop, '0'", self.raw)


if __name__ == "__main__":
    unittest.main()
