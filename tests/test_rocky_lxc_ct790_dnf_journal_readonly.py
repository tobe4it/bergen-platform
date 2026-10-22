#!/usr/bin/env python3
"""No-URL DNF journal classification and no-mutation first-party audit tests."""
import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "ansible/files/nextcloud/classify_ct790_dnf_makecache_journal.py"
PLAY = ROOT / "ansible/playbooks/diagnose-rocky-9-8-ct790-dnf-journal-readonly.yml"
spec = importlib.util.spec_from_file_location("ct790_dnf_journal_classify", HELPER)
classifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classifier)


class DnfJournalDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PLAY.read_text()
        cls.plays = yaml.safe_load(cls.source)
        cls.tasks = cls.plays[1]["tasks"]

    def test_classifier_discloses_no_raw_journal_urls_or_hostnames(self):
        cases = {
            b"Curl error (6): Couldn't resolve host name for https://secret.internal/path?token=sensitive":
                "DNS_RESOLUTION_ERROR_OBSERVED",
            b"curl error (7): Failed to connect to https://secret.internal":
                "NETWORK_CONNECTION_ERROR_OBSERVED",
            b"Failed to download metadata for repo 'baseos': Cannot download repomd.xml":
                "REPOSITORY_METADATA_ERROR_OBSERVED_CAUSE_UNDETERMINED",
            b"No enabled repositories":
                "REPOSITORY_CONFIG_ERROR_OBSERVED",
            b"An unexpected plugin exception":
                "NO_RECOGNIZED_CAUSE_IN_BOUNDED_JOURNAL",
            b"": "NO_RECOGNIZED_CAUSE_IN_BOUNDED_JOURNAL",
        }
        for raw, expected in cases.items():
            with self.subTest(expected=expected):
                result = classifier.classify(raw)
                self.assertEqual(result["category"], expected)
                self.assertFalse(result["raw_content_disclosed"])
                self.assertEqual(result["files_written"], 0)
                self.assertEqual(result["services_changed"], 0)
                self.assertFalse(result["guest_started_or_stopped"])
                self.assertNotIn("secret.internal", str(result))
                self.assertNotIn("sensitive", str(result))

    def test_parser_fails_closed_on_unbounded_or_invalid_data(self):
        for raw in (b"x"*32769, b"\xff", b"line\n"*81):
            with self.subTest(length=len(raw)):
                with self.assertRaises(ValueError):
                    classifier.classify(raw)

    def test_same_run_precise_degraded_unit_preflight_and_scope(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "diagnose-rocky-9-8-ct790-failed-unit-readonly.yml",
        })
        play = self.plays[1]
        self.assertEqual(play["hosts"], "venombox")
        self.assertIs(play["become"], True)
        self.assertIs(play["gather_facts"], False)
        self.assertIs(play["any_errors_fatal"], True)
        for snippet in (
            "rocky_failed_unit_name == 'dnf-makecache.service'",
            "rocky_failed_unit_fields.ActiveState == 'failed'",
            "rocky_failed_unit_fields.Result == 'exit-code'",
            "rocky_failed_unit_fields.ExecMainStatus == '1'",
            "rocky_running_systemd.stdout | trim == 'degraded'",
            "NON_LOOPBACK_DEVICES=0",
            "GUEST_IDMAP_NONIDENTITY=YES",
            "2026-10-22 05:00:00",
            "2026-10-22 05:40:00",
            "ROCKY_9_8_CT790_DNF_JOURNAL_CLASSIFIED_READ_ONLY",
        ):
            self.assertIn(snippet, self.source)

    def test_all_commands_read_only_and_logs_protected(self):
        expected = [
            ["pct", "exec", "790", "--", "journalctl", "--utc",
             "--no-pager", "--output=cat", "--unit=dnf-makecache.service",
             "--since", "2026-10-22 05:00:00",
             "--until", "2026-10-22 05:40:00", "-n", "80"],
            ["python3", "-c",
             "{{ lookup('ansible.builtin.file', playbook_dir ~ '/../files/nextcloud/classify_ct790_dnf_makecache_journal.py') }}"],
            ["pct", "status", "790"],
        ]
        commands = []
        for task in self.tasks:
            modules = [key for key in task if key.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, msg=task["name"])
            self.assertIn(modules[0], (
                "ansible.builtin.assert", "ansible.builtin.command",
                "ansible.builtin.debug",
            ))
            c = task.get("ansible.builtin.command")
            if c:
                self.assertIs(task["changed_when"], False)
                commands.append(c["argv"])
                if c["argv"] != ["pct", "status", "790"]:
                    self.assertIs(task.get("no_log"), True)
        self.assertEqual(commands, expected)
        for forbidden in (
            "ansible.builtin.copy:", "ansible.builtin.shell:",
            "ansible.builtin.raw:", "ansible.builtin.file:",
            "ansible.builtin.systemd:", "ansible.builtin.service:",
            "pct, shutdown", "pct, stop", "pct, start", "pct, reboot",
            "pct, template", "pct, set", "dnf, makecache",
            "systemctl, restart", "systemctl, reset-failed",
            "journalctl, --follow",
        ):
            self.assertNotIn(forbidden, self.source)

if __name__ == "__main__":
    unittest.main()
