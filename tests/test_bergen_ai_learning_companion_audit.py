"""Synthetic, offline tests for the child learning-companion read-only audit.

No Open WebUI access, external API, identity data, groups or permissions
are modified. The pedagogical prompt checks are specification checks only.
"""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_learning_companion_v0102.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-learning-companion-readonly.yml"
PROMPT = ROOT / "ansible/files/bergen_ai/prompts/learning_companion_de_v1.md"

spec = importlib.util.spec_from_file_location("lc_audit", SCRIPT)
LC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LC)

NAMES = {"family": "Synthetic family", "adults": "Synthetic adults",
         "children": "Synthetic children"}


def base():
    return {
        "workspace": {},
        "sharing": {
            "public_calendars": False, "public_chats": False,
            "public_notes": False, "public_tools": False,
        },
        "access_grants": {},
        "chat": {"web_upload": False, "share": False, "file_upload": False},
        "features": {
            "memories": False, "calendar": False, "automations": False,
            "web_search": False, "image_generation": False,
            "code_interpreter": False, "api_keys": False,
            "direct_tool_servers": False, "webhooks": False,
        },
        "settings": {},
    }


class LearningCompanionContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbfile = Path(self.tmp.name) / "webui.db"
        self.db = sqlite3.connect(self.dbfile)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE "group" (
                id TEXT PRIMARY KEY, name TEXT, data TEXT, permissions TEXT
            );
            CREATE TABLE "group_member" (group_id TEXT, user_id TEXT);
            CREATE TABLE "config" (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE "access_grant" (
                principal_type TEXT, principal_id TEXT, permission TEXT
            );
        """)
        for role, name in NAMES.items():
            self.db.execute('INSERT INTO "group" VALUES (?, ?, ?, ?)', (
                role, name, '{"config":{"share":false}}', json.dumps({})
            ))
        self.insert("user.permissions", base())
        for key, value in {
            "memories.enable": True,
            "memories.system_context.enable": True,
            "memories.background_review.enable": False,
            "calendar.enable": True,
            "automations.enable": True,
            "ui.enable_user_webhooks": False,
        }.items():
            self.insert(key, value)
        self.db.commit()

    def insert(self, key, value):
        self.db.execute('REPLACE INTO "config" VALUES (?,?)', (key, json.dumps(value)))

    def group_rights(self, role, permissions):
        self.db.execute('UPDATE "group" SET permissions=? WHERE id=?',
                        (json.dumps(permissions), role))
        self.db.commit()

    def test_default_denied_then_explicit_family_learning_allowance(self):
        first = LC.audit_db(self.dbfile, NAMES)
        self.assertEqual(first["STATUS"], "POLICY_INVENTORY_ONLY")
        self.assertEqual(first["CHILD_IF_ASSIGNED_MEMORIES"], "OFF")
        self.assertEqual(first["CHILD_IF_ASSIGNED_CALENDAR"], "OFF")
        self.assertEqual(first["CHILD_IF_ASSIGNED_AUTOMATIONS"], "OFF")
        self.assertEqual(first["MEMORIES_BACKGROUND_REVIEW"], "OFF")
        self.group_rights("family", {"features": {
            "memories": True, "calendar": True, "automations": False,
        }})
        second = LC.audit_db(self.dbfile, NAMES)
        self.assertEqual(second["CHILD_IF_ASSIGNED_MEMORIES"], "ON")
        self.assertEqual(second["CHILD_IF_ASSIGNED_CALENDAR"], "ON")
        self.assertEqual(second["ADULT_IF_ASSIGNED_MEMORIES"], "ON")
        self.assertEqual(second["CHILD_IF_ASSIGNED_AUTOMATIONS"], "OFF")
        self.assertEqual(second["CHILD_IF_ASSIGNED_WEB_SEARCH"], "OFF")

    def test_additive_family_permission_cannot_be_denied_by_children(self):
        self.group_rights("family", {"features": {"web_search": True}})
        self.group_rights("children", {"features": {"web_search": False}})
        out = LC.audit_db(self.dbfile, NAMES)
        self.assertEqual(out["CHILD_IF_ASSIGNED_WEB_SEARCH"], "ON")

    def test_global_grant_cannot_be_revoked_in_group(self):
        data = base()
        data["features"]["automations"] = True
        self.insert("user.permissions", data)
        self.db.commit()
        self.group_rights("children", {"features": {"automations": False}})
        out = LC.audit_db(self.dbfile, NAMES)
        self.assertEqual(out["CHILD_IF_ASSIGNED_AUTOMATIONS"], "ON")

    def test_no_silent_change_during_inventory(self):
        self.db.commit()
        original = self.dbfile.read_bytes()
        LC.audit_db(self.dbfile, NAMES)
        self.assertEqual(original, self.dbfile.read_bytes())

    def test_controls_report_unset_without_invented_defaults(self):
        self.db.execute("DELETE FROM config WHERE key='calendar.enable'")
        self.db.commit()
        self.assertEqual(LC.audit_db(self.dbfile, NAMES)["CALENDAR_ENABLED"], "UNSET")

    def test_fail_closed_on_existing_membership(self):
        self.db.execute("INSERT INTO group_member VALUES (?,?)", ("children", "a-person"))
        self.db.commit()
        with self.assertRaises(LC.Refuse):
            LC.audit_db(self.dbfile, NAMES)

    def test_fail_closed_on_group_share_or_inventory_drift(self):
        self.db.execute(
            'UPDATE "group" SET data=? WHERE id=?',
            ('{"config":{"share":"members"}}', "family")
        )
        self.db.commit()
        with self.assertRaises(LC.Refuse):
            LC.audit_db(self.dbfile, NAMES)
        self.db.execute('DELETE FROM "group" WHERE id=?', ("family",))
        self.db.commit()
        with self.assertRaises(LC.Refuse):
            LC.audit_db(self.dbfile, NAMES)

    def test_fail_closed_on_invalid_config_type(self):
        self.insert("memories.enable", "not a boolean")
        self.db.commit()
        with self.assertRaises(LC.Refuse):
            LC.audit_db(self.dbfile, NAMES)

    def test_no_identity_leaks(self):
        out = LC.audit_db(self.dbfile, NAMES)
        rendered = json.dumps(out)
        for name in NAMES.values():
            self.assertNotIn(name, rendered)
        self.assertNotIn("a-person", rendered)
        for suffix in ("MEMORY_ISOLATION_E2E", "REMINDER_DELIVERY_E2E",
                       "HOMEWORK_BEHAVIOR_E2E", "RESOURCE_ACL_SEPARATION_E2E"):
            self.assertEqual(out[suffix], "NOT_PROVEN")

    def test_playbook_is_single_host_and_read_only(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["serial"], 1)
        accepted = {"ansible.builtin.assert", "ansible.builtin.uri",
                    "ansible.builtin.command", "ansible.builtin.set_fact",
                    "ansible.builtin.debug"}
        for task in plays[0]["tasks"]:
            entries = [name for name in task if name.startswith("ansible.builtin.")]
            self.assertEqual(len(entries), 1)
            self.assertIn(entries[0], accepted)
            if "ansible.builtin.command" in task:
                self.assertIs(task["changed_when"], False)
                self.assertIs(task["check_mode"], False)
                self.assertTrue(task["no_log"])
        source = SCRIPT.read_text() + PLAY.read_text()
        self.assertIn("mode=ro", source)
        self.assertIn("query_only=ON", source)
        self.assertNotIn("Config.upsert", source)
        self.assertNotIn("UPDATE config", source)
        self.assertNotIn("podman restart", source)

    def test_prompt_is_a_guardrail_not_false_service_or_security_claim(self):
        prompt = PROMPT.read_text()
        for term in ("Hausaufgabe", "selbstständiges", "Lernstand",
                     "gespeichert", "Eltern", "Erinnerung", "Zeitzone",
                     "kein technischer Berechtigungsmechanismus"):
            self.assertIn(term.lower(), prompt.lower())
        self.assertNotIn("jederzeit eine Push-Mitteilung", prompt)


if __name__ == "__main__":
    unittest.main()
