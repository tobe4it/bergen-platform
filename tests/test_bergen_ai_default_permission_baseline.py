"""Synthetic tests for version-gated Bergen-AI application default-rights change."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "ansible/files/bergen_ai/manage_default_permissions_v0102.py"
PLAYBOOK = ROOT / "ansible/playbooks/manage-bergen-ai-default-permissions.yml"
SPEC = importlib.util.spec_from_file_location("default_rights_helper", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

EXPECTED = {
    "family": "Synthetic Family",
    "adults": "Synthetic Adults",
    "children": "Synthetic Children",
}
PERMISSIONS = {
    "workspace": {"tools": False},
    "sharing": {"tools": False},
    "access_grants": {"allow_users": True},
    "chat": {"file_upload": True, "delete": True},
    "features": {
        "web_search": True, "image_generation": True,
        "code_interpreter": True, "api_keys": False,
    },
    "settings": {"interface": True},
}


class BaselineContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "webui.db"
        self.backups = Path(self.temp.name) / "backups"
        self.con = sqlite3.connect(self.path)
        self.addCleanup(self.con.close)
        self.con.executescript("""
            CREATE TABLE "group" (name TEXT, data TEXT);
            CREATE TABLE "group_member" (group_id TEXT, user_id TEXT);
            CREATE TABLE "access_grant" (principal_type TEXT, principal_id TEXT);
            CREATE TABLE "config" (key TEXT, value TEXT);
        """)
        for name in EXPECTED.values():
            self.con.execute('INSERT INTO "group" VALUES (?,?)',
                             (name, '{"config":{"share":false}}'))
        self.store(PERMISSIONS)
        self.runtime = mock.patch.object(MODULE, "read_runtime", return_value=self.path)
        self.runtime.start()
        self.addCleanup(self.runtime.stop)
        self.backup_override = mock.patch.object(MODULE, "BACKUP_DIR", self.backups)
        self.backup_override.start()
        self.addCleanup(self.backup_override.stop)
        self.root_override = mock.patch.object(MODULE, "ensure_root", return_value=None)
        self.root_override.start()
        self.addCleanup(self.root_override.stop)

    def store(self, permissions):
        self.con.execute("DELETE FROM config")
        self.con.execute("INSERT INTO config VALUES (?,?)",
                         ("user.permissions", json.dumps(permissions)))
        self.con.commit()

    def current(self):
        return MODULE.read_db(self.path, EXPECTED)

    def req(self, action, sha=None, approved=False, rollback_selector=None):
        return {
            "version": "0.10.2", "action": action,
            "expected": EXPECTED, "approved": approved,
            "expected_sha256": sha, "rollback_selector": rollback_selector,
        }

    def test_read_only_preflight_and_target(self):
        before = hashlib.sha256(self.path.read_bytes()).digest()
        result = MODULE.execute(self.req("audit"))
        self.assertEqual(result["STATUS"], "BASELINE_READY")
        self.assertEqual(result["DEFAULT_WEB_SEARCH"], "ON")
        self.assertEqual(result["DEFAULT_FILE_UPLOAD"], "ON")
        self.assertEqual(result["TARGET_SHA256"],
                         MODULE.digest(MODULE.target_permissions(PERMISSIONS)))
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).digest())
        self.assertFalse(self.backups.exists())

    def test_only_four_flags_change(self):
        result = MODULE.target_permissions(PERMISSIONS)
        self.assertFalse(result["features"]["web_search"])
        self.assertFalse(result["features"]["image_generation"])
        self.assertFalse(result["features"]["code_interpreter"])
        self.assertFalse(result["chat"]["file_upload"])
        self.assertEqual(result["chat"]["delete"], True)
        self.assertEqual(result["features"]["api_keys"], False)
        self.assertEqual(result["settings"]["interface"], True)
        self.assertEqual(PERMISSIONS["features"]["web_search"], True)

    def test_exact_sha_and_approval_required(self):
        before = MODULE.digest(self.current())
        for sha, approval in [("", True), ("0"*64, True), (before, False)]:
            with self.subTest(sha=sha, approved=approval), self.assertRaises(MODULE.GateError):
                MODULE.execute(self.req("apply", sha, approval))
        self.assertFalse(self.backups.exists())
        self.assertEqual(self.current(), PERMISSIONS)

    def test_apply_backup_repeat_and_guarded_rollback(self):
        before = self.current()
        before_sha = MODULE.digest(before)
        after = MODULE.target_permissions(before)
        calls = []
        def fake_app_upsert(old, new):
            self.assertEqual(self.current(), old)
            calls.append((copy.deepcopy(old), copy.deepcopy(new)))
            self.store(new)
        with mock.patch.object(MODULE, "app_upsert", side_effect=fake_app_upsert):
            res = MODULE.execute(self.req("apply", before_sha, True))
            self.assertEqual(res["STATUS"], "BASELINE_APPLIED")
            self.assertTrue(res["CHANGED"])
            self.assertEqual(res["ROLLBACK_SELECTOR"], before_sha)
            backup = self.backups / ("default-user-permissions-" + before_sha + ".json")
            self.assertTrue(backup.exists())
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.current(), after)
            self.assertEqual(len(calls), 1)
            repeat = MODULE.execute(self.req("apply", MODULE.digest(after), True))
            self.assertEqual(repeat["STATUS"], "ALREADY_COMPLIANT")
            self.assertFalse(repeat["CHANGED"])
            self.assertEqual(len(calls), 1)
            rb = MODULE.execute(self.req("rollback", MODULE.digest(after), True, before_sha))
            self.assertEqual(rb["STATUS"], "BASELINE_ROLLED_BACK")
            self.assertEqual(self.current(), before)
            self.assertEqual(len(calls), 2)

    def test_rollback_rejects_intervening_edits(self):
        original = self.current()
        after = MODULE.target_permissions(original)
        with mock.patch.object(MODULE, "app_upsert", side_effect=lambda old, new: self.store(new)):
            self.assertEqual(
                MODULE.execute(self.req("apply", MODULE.digest(original), True))["STATUS"],
                "BASELINE_APPLIED")
        # Operator changed an unrelated default permission after our apply.
        drift = copy.deepcopy(after)
        drift["chat"]["delete"] = False
        self.store(drift)
        with self.assertRaises(MODULE.GateError):
            MODULE.execute(self.req("rollback", MODULE.digest(drift), True,
                                    MODULE.digest(original)))
        self.assertEqual(self.current(), drift)

    def test_group_and_membership_changes_stop_every_operation(self):
        self.con.execute('INSERT INTO "group_member" VALUES (?, ?)',
                         ("synthetic-group", "synthetic-user"))
        self.con.commit()
        for action in ("audit", "apply", "rollback"):
            with self.subTest(action=action), self.assertRaises(MODULE.GateError):
                MODULE.execute(self.req(action, "0"*64, True, "0"*64))

    def test_share_policy_drift_fails_closed(self):
        self.con.execute('UPDATE "group" SET data=? WHERE name=?',
                         ('{"config":{"share":"members"}}', EXPECTED["family"]))
        self.con.commit()
        with self.assertRaises(MODULE.GateError):
            MODULE.execute(self.req("audit"))

    def test_unreviewed_version_refused(self):
        req = self.req("audit")
        req["version"] = "0.12.3"
        with self.assertRaises(MODULE.GateError):
            MODULE.execute(req)

    def test_playbook_only_invokes_pinned_python_application_helper(self):
        data = yaml.safe_load(PLAYBOOK.read_text())
        self.assertEqual(len(data), 1)
        tasks = data[0]["tasks"]
        valid = {"ansible.builtin.assert", "ansible.builtin.uri",
                 "ansible.builtin.command", "ansible.builtin.set_fact",
                 "ansible.builtin.debug"}
        for task in tasks:
            parts = [k for k in task if k.startswith("ansible.builtin.")]
            self.assertEqual(len(parts), 1)
            self.assertIn(parts[0], valid)
        command = next(x for x in tasks if "ansible.builtin.command" in x)
        self.assertTrue(command["no_log"])
        self.assertFalse(command["check_mode"])
        self.assertEqual(command["ansible.builtin.command"]["argv"][:2],
                         ["python3", "-c"])
        source = PLAYBOOK.read_text() + HELPER.read_text()
        self.assertIn("Config.upsert", source)
        self.assertIn("mode=ro", source)
        self.assertIn("query_only=ON", source)
        for forbidden in ("vault_open_webui_admin_token", "ansible.builtin.shell",
                          "ansible.builtin.copy", "sqlite3.connect(", "ENABLE_OAUTH_GROUP_MANAGEMENT=true"):
            # sqlite3 is only used for host-side SELECT, never .execute DML.
            if forbidden != "sqlite3.connect(":
                self.assertNotIn(forbidden, source)
        self.assertIn("SELECT value FROM config", source)
        self.assertNotIn("UPDATE config", source)
        self.assertNotIn("DELETE FROM config", source)


if __name__ == "__main__":
    unittest.main()
