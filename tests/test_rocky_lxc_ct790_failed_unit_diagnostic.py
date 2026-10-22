#!/usr/bin/env python3
"""No-remediation CT790 degraded-systemd unit diagnosis and parser tests."""
import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "ansible/files/nextcloud/parse_ct790_failed_unit.py"
PLAY = ROOT / "ansible/playbooks/diagnose-rocky-9-8-ct790-failed-unit-readonly.yml"

spec = importlib.util.spec_from_file_location("ct790_failed_unit_parser", HELPER)
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


class FailedUnitDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PLAY.read_text()
        cls.plays = yaml.safe_load(cls.source)
        cls.play = cls.plays[1]
        cls.tasks = cls.play["tasks"]

    def test_known_systemd_formats_parsed_without_disclosing_description(self):
        cases = (
            b"dbus-broker.service loaded failed failed D-Bus Broker\n",
            "\u25cf systemd-networkd-wait-online.service loaded failed failed Wait for Network to be Configured\n".encode(),
            b"my@special-1.service loaded failed failed failed description\n",
        )
        for raw in cases:
            with self.subTest(raw=raw):
                result = parser.parse_failed_unit(raw)
                self.assertEqual(result["result"], "ROCKY_9_8_CT790_SINGLE_FAILED_UNIT_PARSED")
                self.assertEqual(result["failed_unit_count"], 1)
                self.assertEqual(result["writes"], 0)
                self.assertNotIn("description", str(result).lower())
                self.assertRegex(result["unit"], r"^[A-Za-z0-9_.@:-]+[.]service$")

    def test_ambiguous_malformed_or_oversized_output_fails_closed(self):
        cases = (
            b"",
            b"1 loaded units listed.\n",
            b"1 units listed.\n",
            b"unit.service loaded failed failed\nother.service loaded failed failed\n",
            b"../foo.service loaded failed failed\n",
            b";rm -rf /.service loaded failed failed\n",
            b"unit.service loaded active running Fine\n",
            b"unit.service loaded failed failed\n" * 500,
            b"\xff",
        )
        for raw in cases:
            with self.subTest(raw=raw[:90]):
                with self.assertRaises(ValueError):
                    parser.parse_failed_unit(raw)

    def test_play_imports_running_audit_and_does_not_replay_shutdown_preflight(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-running-readonly.yml",
        })
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertIn("rocky_running_systemd.stdout | trim == 'degraded'", self.source)
        self.assertIn("rocky_running_failed_units.stdout_lines | length == 1", self.source)
        self.assertIn("rocky_running_failed_units.stdout | length <= 8192", self.source)

    def test_command_whitelist_is_strict_and_non_mutating(self):
        actual = []
        for task in self.tasks:
            modules = [key for key in task if key.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, task["name"])
            self.assertIn(modules[0], (
                "ansible.builtin.assert",
                "ansible.builtin.command",
                "ansible.builtin.debug",
                "ansible.builtin.set_fact",
            ))
            command = task.get("ansible.builtin.command")
            if not command:
                continue
            argv = command["argv"]
            actual.append(argv)
            self.assertIs(task.get("changed_when"), False, task["name"])
            self.assertTrue(
                argv[:2] == ["python3", "-c"] or
                argv[:3] == ["pct", "exec", "790"] or
                argv == ["pct", "status", "790"], task["name"]
            )
            if argv[0:2] != ["pct", "status"]:
                self.assertIs(task.get("no_log"), True, task["name"])
        self.assertEqual(len(actual), 3)
        self.assertIn([
            "pct", "exec", "790", "--", "systemctl", "--no-pager", "show",
            "--property=Id,LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus,StateChangeTimestamp",
            "{{ rocky_failed_unit_name }}"
        ], actual)

    def test_no_external_side_effects(self):
        for forbidden in (
            "ansible.builtin.file:", "ansible.builtin.copy:",
            "ansible.builtin.shell:", "ansible.builtin.raw:",
            "ansible.builtin.service:", "ansible.builtin.systemd:",
            "pct, shutdown", "pct, stop", "pct, start",
            "pct, set", "pct, template", "pct, destroy",
            "systemctl, reset-failed", "systemctl, restart",
            "journalctl", "zfs, mount", "zfs, set",
        ):
            self.assertNotIn(forbidden, self.source)
        for bad in ("subprocess", "os.system(", "open(", "os.remove(",
                    "os.unlink(", "requests", "urllib"):
            self.assertNotIn(bad, HELPER.read_text())
        for required in (
            "ROCKY_9_8_CT790_FAILED_UNIT_DIAG_READ_ONLY_RECORDED",
            "file_writes_by_diagnostic: 0",
            "pct_shutdown_authorized: false",
            "pct_stop_authorized: false",
            "pct_template_authorized: false",
        ):
            self.assertIn(required, self.source)

if __name__ == "__main__":
    unittest.main()
