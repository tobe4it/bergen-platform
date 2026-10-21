"""Offline review tests for post-watermark protected Paperless journal audit."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_ai_catalog_timer_journal_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-ai-timer-journal-readonly.yml"


def load():
    spec = importlib.util.spec_from_file_location("timer_journal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TimerJournalTests(unittest.TestCase):
    def test_exact_positive_watermark_only(self):
        mod = load()
        self.assertEqual(
            mod.validate({"protocol": "timer-journal-readonly-v1", "watermark": 29}),
            29,
        )
        for incorrect in (0, -1, True, "29", None, 2147483647):
            with self.subTest(incorrect=incorrect):
                self.assertIsNone(mod.validate({
                    "protocol": "timer-journal-readonly-v1",
                    "watermark": incorrect,
                }))
        self.assertIsNone(mod.validate({
            "protocol": "timer-journal-readonly-v1",
            "watermark": 29, "unreviewed": True,
        }))

    def test_counters_accept_no_change_and_refuse_other_states(self):
        mod = load()
        got = mod.state_counts([
            ("APPLIED", 2), ("NO_CHANGE", 1), ("REQUIRES_REVIEW", 3),
        ])
        self.assertEqual(got["APPLIED"], 2)
        self.assertEqual(got["NO_CHANGE"], 1)
        self.assertEqual(got["REQUIRES_REVIEW"], 3)
        self.assertEqual(got["PROCESSING"], 0)
        self.assertEqual(set(got), set(mod.VALID_STATES))
        for rows in ([("NOT_RECORDED", 1)], [("APPLIED", 0)],
                     [("UNKNOWN", 10)], [("APPLIED", "5")]):
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    mod.state_counts(rows)

    def test_malformed_payload_does_not_touch_django(self):
        proc = subprocess.run(
            [sys.executable, "-c", SCRIPT.read_text() + "\nmain()"],
            input='{"protocol":"timer-journal-readonly-v1","watermark":-1}',
            capture_output=True, text=True, check=True, timeout=5,
        )
        self.assertIn('"STATUS": "INPUT_REJECTED"', proc.stdout)
        self.assertIn('"CHANGED": false', proc.stdout)
        self.assertEqual(proc.stderr, "")

    def test_no_write_or_inference_and_host_gate(self):
        src = SCRIPT.read_text()
        ast.parse(src)
        for required in ("mode=ro", "PRAGMA query_only=ON",
                         "document_id > ?", "is_inbox_tag=True",
                         "NEW_PARENT_AI_NOTES", "NO_CHANGE"):
            self.assertIn(required, src)
        for forbidden in ("get_ai_document_classification(",
                          "Note.objects.create(", "Document.objects.create(",
                          "db.execute(\"UPDATE ", "db.execute(\"DELETE ",
                          "db.execute(\"INSERT ", "open(path, 'w'"):
            self.assertNotIn(forbidden, src)
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(plays), 1)
        play = plays[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        self.assertIn("paperless_ai_catalog_timer_activate", PLAY.read_text())
        self.assertIn("paperless_ai_catalog_approved", PLAY.read_text())
        self.assertIn("catalog-policy.json", PLAY.read_text())
        self.assertIn("no_log: true", PLAY.read_text())
        for task in play["tasks"]:
            self.assertNotIn("ansible.builtin.systemd", task)
            self.assertNotIn("ansible.builtin.copy", task)
            self.assertNotIn("ansible.builtin.file", task)
            if "ansible.builtin.command" in task:
                self.assertFalse(task["changed_when"])
                self.assertTrue(task["no_log"])


if __name__ == "__main__":
    unittest.main()
