"""Offline checks for the staged, read-only family permission plan."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "ansible/files/bergen_ai/plan_family_rights_v0102.py"
PLAY = ROOT / "ansible/playbooks/plan-bergen-ai-family-rights-readonly.yml"
spec = importlib.util.spec_from_file_location("family_rights_preflight", HELPER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ROLE_MAP = {"family": "Example family", "adults": "Example adults",
            "children": "Example children"}


def defaults():
    return {
        "workspace": {},
        "sharing": {
            "public_calendars": False, "public_chats": False,
            "public_notes": False, "public_tools": False,
            "public_models": False, "public_knowledge": False,
            "public_prompts": False, "public_skills": False,
        },
        "access_grants": {},
        "chat": {
            "file_upload": False, "web_upload": True, "share": True,
            "delete": True,
        },
        "features": {
            "web_search": False, "image_generation": False,
            "code_interpreter": False, "memories": True, "calendar": True,
            "automations": False, "api_keys": False,
            "direct_tool_servers": False, "webhooks": False,
        },
        "settings": {"interface": True},
    }


def group_defaults():
    return {
        "features": {
            "web_search": True, "image_generation": True,
            "code_interpreter": True, "memories": True, "calendar": True,
            "automations": False,
        },
        "chat": {"file_upload": True, "web_upload": True, "share": True},
    }


class FamilyRightsPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "webui.db"
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE "user" (id TEXT, role TEXT);
            CREATE TABLE "group" (
                id TEXT PRIMARY KEY, name TEXT, user_id TEXT,
                data TEXT, permissions TEXT
            );
            CREATE TABLE "group_member" (group_id TEXT, user_id TEXT);
            CREATE TABLE "access_grant" (principal_type TEXT, principal_id TEXT);
            CREATE TABLE "config" (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.execute("INSERT INTO user VALUES ('root-id','admin')")
        for role, name in ROLE_MAP.items():
            perms = group_defaults() if role != "adults" else {}
            self.db.execute('INSERT INTO "group" VALUES (?,?,?,?,?)', (
                role, name, "root-id", '{"config":{"share":false}}',
                json.dumps(perms)
            ))
        self.db.execute("INSERT INTO config VALUES (?,?)", (
            "user.permissions", json.dumps(defaults())
        ))
        self.db.commit()

    def group(self, role, data):
        self.db.execute('UPDATE "group" SET permissions=? WHERE id=?',
                        (json.dumps(data), role))
        self.db.commit()

    def default(self, data):
        self.db.execute("UPDATE config SET value=? WHERE key='user.permissions'",
                        (json.dumps(data),))
        self.db.commit()

    def test_plan_keeps_memories_calendar_and_denies_tools(self):
        original = self.path.read_bytes()
        result = mod.audit(self.path, ROLE_MAP)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(result["AUDIT"], "READ_ONLY")
        self.assertFalse(result["CHANGED"])
        self.assertEqual(result["TARGET_CHILD_MEMORIES"], "ON")
        self.assertEqual(result["TARGET_CHILD_CALENDAR"], "ON")
        for perm in ("AUTOMATIONS", "WEB_SEARCH", "IMAGE_GENERATION",
                     "CODE_INTERPRETER", "FILE_UPLOAD", "WEB_UPLOAD", "CHAT_SHARING"):
            self.assertEqual(result["TARGET_CHILD_" + perm], "OFF")
        self.assertEqual(result["CURRENT_GLOBAL_MEMORIES"], "ON")
        self.assertEqual(result["CURRENT_GLOBAL_CHAT_SHARING"], "ON")
        self.assertNotEqual(result["CURRENT_BUNDLE_SHA256"],
                            result["TARGET_BUNDLE_SHA256"])
        self.assertEqual(result["REMAINING_UNREVIEWED_GROUP_TRUE"], 0)
        self.assertEqual(result["STATUS"], "READY_FOR_SEPARATE_APPROVAL")

    def test_unknown_group_grant_is_manual_review(self):
        group = group_defaults()
        group["workspace"] = {"tools": True}
        self.group("children", group)
        result = mod.audit(self.path, ROLE_MAP)
        self.assertEqual(result["STATUS"], "NEEDS_POLICY_REVIEW")
        self.assertEqual(result["REMAINING_UNREVIEWED_WORKSPACE_TRUE"], 1)
        self.assertEqual(result["REMAINING_UNREVIEWED_GROUP_TRUE"], 1)

    def test_global_baseline_is_required(self):
        data = defaults()
        data["features"]["web_search"] = True
        self.default(data)
        with self.assertRaises(mod.GateError):
            mod.audit(self.path, ROLE_MAP)

    def test_positive_group_membership_is_blocking(self):
        self.db.execute("INSERT INTO group_member VALUES('children', 'person-x')")
        self.db.commit()
        with self.assertRaises(mod.GateError):
            mod.audit(self.path, ROLE_MAP)

    def test_nonprivate_sharing_or_resource_grants_block(self):
        self.db.execute(
            "UPDATE \"group\" SET data=? WHERE id='family'",
            ('{"config":{"share":true}}',)
        )
        self.db.commit()
        with self.assertRaises(mod.GateError):
            mod.audit(self.path, ROLE_MAP)

    def test_other_groups_block(self):
        self.db.execute('INSERT INTO "group" VALUES (?,?,?,?,?)', (
            "other-id", "unexpected", "root-id", '{"config":{"share":false}}', '{}'
        ))
        self.db.commit()
        with self.assertRaises(mod.GateError):
            mod.audit(self.path, ROLE_MAP)

    def test_no_secret_names_or_contents_in_results(self):
        result = json.dumps(mod.audit(self.path, ROLE_MAP))
        for name in ROLE_MAP.values():
            self.assertNotIn(name, result)
        self.assertNotIn("root-id", result)
        self.assertIn("NOT_TESTED", result)

    def test_playbook_is_approved_readonly_and_single_host(self):
        p = yaml.safe_load(PLAY.read_text())
        self.assertEqual(p[0]["serial"], 1)
        assert p[0]["tasks"]
        allowed = {
            "ansible.builtin.assert", "ansible.builtin.uri",
            "ansible.builtin.command", "ansible.builtin.set_fact",
            "ansible.builtin.debug"
        }
        for task in p[0]["tasks"]:
            kinds = [name for name in task if name.startswith("ansible.builtin.")]
            self.assertEqual(len(kinds), 1)
            self.assertIn(kinds[0], allowed)
            if kinds[0] == "ansible.builtin.command":
                self.assertFalse(task["changed_when"])
                self.assertFalse(task["check_mode"])
                self.assertTrue(task["no_log"])
        source = PLAY.read_text() + HELPER.read_text()
        self.assertIn("mode=ro", source)
        self.assertIn("query_only=ON", source)
        for forbidden in ("Config.upsert", "GROUP_ID=", "sqlite3 connect",
                          "DELETE FROM", "UPDATE config", "WEBUI_SECRET_KEY"):
            self.assertNotIn(forbidden, source)

if __name__ == "__main__":
    unittest.main()
