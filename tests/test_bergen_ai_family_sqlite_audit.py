"""Regression tests for API-token-free, database read-only family inventory."""
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_sqlite_family_groups.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-family-sqlite-readonly.yml"
SPEC = importlib.util.spec_from_file_location("family_sqlite_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)

EXPECTED = {
    "family": "Synthetic Family Only",
    "adults": "Synthetic Adults Only",
    "children": "Synthetic Children Only",
}
DEFAULTS = {"features": {"web_search": True, "image_generation": True,
                          "code_interpreter": True, "api_keys": False,
                          "direct_tool_servers": False},
            "chat": {"file_upload": True},
            "workspace": {"tools": False}}
GROUP_PERMISSIONS = {"features": {"web_search": True, "image_generation": True,
                                  "code_interpreter": True, "api_keys": False,
                                  "direct_tool_servers": False},
                     "chat": {"file_upload": True},
                     "workspace": {"tools": False}}


class FamilySQLiteAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbfile = Path(self.tmp.name) / "webui.db"
        self.con = sqlite3.connect(self.dbfile)
        self.addCleanup(self.con.close)
        self.con.executescript("""
            CREATE TABLE "user" (id TEXT PRIMARY KEY, role TEXT);
            CREATE TABLE "group" (id TEXT PRIMARY KEY, name TEXT, user_id TEXT,
                                  data TEXT, permissions TEXT);
            CREATE TABLE "group_member" (group_id TEXT, user_id TEXT);
            CREATE TABLE "access_grant" (resource_type TEXT, principal_type TEXT,
                                         principal_id TEXT, permission TEXT);
            CREATE TABLE "api_key" (id TEXT);
            CREATE TABLE "config" (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.con.execute('INSERT INTO "user" VALUES (?, ?)', ("synthetic-admin", "admin"))
        self.con.execute('INSERT INTO "config" VALUES (?, ?)',
                         ("user.permissions", json.dumps(DEFAULTS)))
        for role, name in EXPECTED.items():
            self.con.execute('INSERT INTO "group" VALUES (?, ?, ?, ?, ?)',
                             ("id-" + role, name, "synthetic-admin",
                              json.dumps({"config": {"share": False}}),
                              json.dumps(GROUP_PERMISSIONS)))
        self.con.commit()

    def run_audit(self, **env):
        self.con.commit()
        return AUDIT.audit_db(self.dbfile, EXPECTED, env)

    def test_three_private_groups_and_stored_global_defaults(self):
        out = self.run_audit(ENABLE_PERSISTENT_CONFIG="true")
        self.assertEqual(out["STATUS"], "INVENTORY_PRESENT_ONLY")
        self.assertEqual(out["GROUP_COUNT"], 3)
        self.assertEqual(out["DEFAULT_SOURCE"], "DATABASE")
        self.assertEqual(out["DEFAULT_WEB_SEARCH"], "ON")
        self.assertEqual(out["DEFAULT_API_KEYS"], "OFF")
        for role in ("FAMILY", "ADULTS", "CHILDREN"):
            self.assertEqual(out[role], "PRESENT")
            self.assertEqual(out[role + "_SHARE"], "NO_ONE")
            self.assertEqual(out[role + "_MEMBERS"], 0)
            self.assertEqual(out[role + "_RESOURCE_GRANTS"], 0)
            self.assertEqual(out[role + "_OWNER_ADMIN"], "YES")
        self.assertEqual(out["MEMBERSHIP_SEPARATION_PROVEN"], "NO")
        self.assertEqual(out["RESOURCE_ACL_SEPARATION_PROVEN"], "NO")
        self.assertEqual(out["GROUPS_OR_PERMISSIONS_CHANGED"], "NO")

    def test_database_bytes_unchanged(self):
        self.con.commit()
        before = hashlib.sha256(self.dbfile.read_bytes()).digest()
        self.run_audit()
        self.run_audit()
        self.assertEqual(before, hashlib.sha256(self.dbfile.read_bytes()).digest())

    def test_no_names_user_ids_or_permission_json_leak(self):
        out = json.dumps(self.run_audit())
        for private in (*EXPECTED.values(), "synthetic-admin", "id-family",
                        "id-adults", "id-children", "Synthetic"):
            self.assertNotIn(private, out)

    def test_missing_duplicate_and_member_counters_do_not_overstate_access(self):
        self.con.execute("DELETE FROM 'group' WHERE name=?", (EXPECTED["children"],))
        result = self.run_audit()
        self.assertEqual(result["CHILDREN"], "MISSING")
        self.assertEqual(result["STATUS"], "MANUAL_REVIEW_REQUIRED")
        self.con.execute('INSERT INTO "group" VALUES (?, ?, ?, ?, ?)',
                         ("duplicate-family", EXPECTED["family"], "synthetic-admin",
                          '{"config":{"share":false}}', '{}'))
        result = self.run_audit()
        self.assertEqual(result["FAMILY"], "DUPLICATE")
        self.assertEqual(result["STATUS"], "MANUAL_REVIEW_REQUIRED")

    def test_existing_grants_and_members_are_only_counts(self):
        self.con.execute('INSERT INTO "group_member" VALUES (?, ?)', ("id-children", "private-user"))
        self.con.execute('INSERT INTO "access_grant" VALUES (?, ?, ?, ?)',
                         ("model", "group", "id-children", "read"))
        self.con.execute('INSERT INTO "access_grant" VALUES (?, ?, ?, ?)',
                         ("model", "user", "*", "read"))
        out = self.run_audit()
        self.assertEqual(out["CHILDREN_MEMBERS"], 1)
        self.assertEqual(out["CHILDREN_RESOURCE_GRANTS"], 1)
        self.assertEqual(out["PUBLIC_READ_GRANTS"], 1)
        self.assertEqual(out["RESOURCE_ACL_SEPARATION_PROVEN"], "NO")

    def test_persistence_off_does_not_treat_stored_values_as_effective(self):
        out = self.run_audit(ENABLE_PERSISTENT_CONFIG="false",
                             USER_PERMISSIONS_FEATURES_WEB_SEARCH="false")
        self.assertEqual(out["PERSISTENT_CONFIG"], "OFF")
        self.assertEqual(out["DEFAULT_SOURCE"], "ENV_DEFAULT")
        self.assertEqual(out["DEFAULT_WEB_SEARCH"], "OFF")

    def test_fails_closed_for_bad_input_and_schema(self):
        for invalid in ({}, {"family": "x", "adults": "x", "children": "y"},
                        {"family": "x", "adults": "y", "children": " z "}):
            with self.subTest(invalid=invalid), self.assertRaises(AUDIT.AuditError):
                AUDIT.audit_db(self.dbfile, invalid, {})
        self.con.execute('DROP TABLE "api_key"')
        self.con.commit()
        with self.assertRaises(AUDIT.AuditError):
            self.run_audit()

    def test_playbook_is_approved_single_host_and_always_read_only(self):
        data = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(data), 1)
        play = data[0]
        self.assertEqual(play["serial"], 1)
        self.assertFalse(play["gather_facts"])
        self.assertIn("__no_selected_family_host__", play["hosts"])
        tasks = play["tasks"]
        allowed = {"ansible.builtin.assert", "ansible.builtin.uri",
                   "ansible.builtin.command", "ansible.builtin.set_fact",
                   "ansible.builtin.debug"}
        for task in tasks:
            module = [k for k in task if k.startswith("ansible.builtin.")]
            self.assertEqual(len(module), 1)
            self.assertIn(module[0], allowed)
        for task in tasks:
            if "ansible.builtin.command" in task or "ansible.builtin.uri" in task:
                self.assertTrue(task["no_log"])
                self.assertFalse(task["changed_when"])
                self.assertFalse(task["check_mode"])
        command = next(t["ansible.builtin.command"] for t in tasks
                       if "ansible.builtin.command" in t)
        self.assertEqual(command["argv"][:2], ["python3", "-c"])
        self.assertIn("expected", command["stdin"])
        self.assertIn("lookup(", command["argv"][2])
        source = PLAY.read_text() + SCRIPT.read_text()
        for forbidden in ("vault_open_webui_admin_token", "ansible.builtin.copy",
                          "ansible.builtin.shell", "ansible.builtin.systemd_service",
                          "UPDATE \"group\"", "DELETE FROM \"group\""):
            self.assertNotIn(forbidden, source)
        self.assertIn("mode=ro", source)
        self.assertIn("PRAGMA query_only=ON", source)


if __name__ == "__main__":
    unittest.main()
