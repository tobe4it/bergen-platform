"""Offline regression tests for non-identifying failed-apply diagnostics."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/diagnose_default_permissions_v0102.py"
PLAY = ROOT / "ansible/playbooks/diagnose-bergen-ai-default-permissions-readonly.yml"
spec = importlib.util.spec_from_file_location("ber_ai_read_diagnostic", SCRIPT)
AUDIT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AUDIT)


class FailedApplyDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dbfile = Path(self.temp.name) / "webui.db"
        self.value = {"features": {"web_search": True}, "chat": {"file_upload": True}}
        with sqlite3.connect(self.dbfile) as db:
            db.execute("CREATE TABLE config (key TEXT, value TEXT)")
            db.execute("INSERT INTO config VALUES (?,?)",
                       ("user.permissions", json.dumps(self.value)))
        self.sha = AUDIT.sha256(self.value)

    def test_missing_backup(self):
        root = Path(self.temp.name)
        with mock.patch.object(AUDIT, "Path", return_value=root):
            self.assertEqual(AUDIT.check_backup("0" * 64), "NOT_FOUND")

    def test_safe_classifier_does_not_print_raw_subprocess_output(self):
        class Result:
            returncode = 0
            stdout = "CONFIDENTIAL_KEY=do_not_print\nPROBE=READ_CONFIRMED\n"
        with mock.patch.object(AUDIT.subprocess, "run", return_value=Result()):
            self.assertEqual(AUDIT.probe_app(self.sha), "READ_CONFIRMED")
            Result.stdout = "Traceback: confidential\n"
            self.assertEqual(AUDIT.probe_app(self.sha), "UNCLASSIFIED_FAILURE")
            Result.stdout = "PROBE=READ_CONFIRMED\n"
            Result.returncode = 1
            self.assertEqual(AUDIT.probe_app(self.sha), "UNCLASSIFIED_FAILURE")

    def test_digest_is_stable_and_version_gate_rejects_unknown(self):
        self.assertEqual(self.sha, AUDIT.sha256(json.loads(json.dumps(self.value))))
        with self.assertRaises(AUDIT.AuditError):
            AUDIT.audit({"version": "0.12.3", "previous_sha256": self.sha})
        with self.assertRaises(AUDIT.AuditError):
            AUDIT.audit({"version": "0.10.2", "previous_sha256": "../webui.db"})

    def test_playbook_contract_is_read_only_and_sanitized(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["serial"], 1)
        allowed = {"ansible.builtin.assert", "ansible.builtin.uri",
                   "ansible.builtin.command", "ansible.builtin.set_fact",
                   "ansible.builtin.debug"}
        for task in plays[0]["tasks"]:
            keys = [key for key in task if key.startswith("ansible.builtin.")]
            self.assertEqual(len(keys), 1)
            self.assertIn(keys[0], allowed)
            if keys[0] == "ansible.builtin.command":
                self.assertFalse(task["changed_when"])
                self.assertTrue(task["no_log"])
                self.assertFalse(task["check_mode"])
        source = SCRIPT.read_text()
        self.assertIn("mode=ro", source)
        self.assertIn("query_only=ON", source)
        self.assertNotIn("Config.upsert", source)
        self.assertNotIn("DELETE FROM", source)
        self.assertNotIn("UPDATE config", source)
        self.assertIn("Config.get", source)
        self.assertNotIn("vault_open_webui_admin_token", PLAY.read_text())


if __name__ == "__main__":
    unittest.main()
