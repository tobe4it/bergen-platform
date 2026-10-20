"""Synthetic readiness tests without private identities, secrets or API tokens."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_family_chat_ready_v0102.py"
STAGER = ROOT / "ansible/files/bergen_ai/manage_family_chat_profiles_v0102.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-family-chat-readiness-readonly.yml"
spec = importlib.util.spec_from_file_location("private_profile_readiness", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

NAMES = {
    "family": "Family@unit.invalid",
    "adults": "Parents@unit.invalid",
    "children": "Children@unit.invalid",
}
P = "Vorsagen untersagt. " + ("Üben und reflektieren. " * 65) + (
    "Gilt für beide Kinder-Chatprofile"
)


class ReadinessTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "webui.db"
        with sqlite3.connect(self.db) as db:
            db.executescript("""
            CREATE TABLE "group" (id TEXT, name TEXT);
            CREATE TABLE group_member (group_id TEXT, user_id TEXT);
            CREATE TABLE "model" (id TEXT);
            CREATE TABLE access_grant (
              resource_type TEXT, resource_id TEXT, principal_type TEXT,
              principal_id TEXT, permission TEXT);
            CREATE TABLE "user" (id TEXT, role TEXT);
            INSERT INTO "user" VALUES ('parent','user');
            INSERT INTO "group" VALUES ('f', 'Family@unit.invalid');
            INSERT INTO "group" VALUES ('a', 'Parents@unit.invalid');
            INSERT INTO "group" VALUES ('c', 'Children@unit.invalid');
            INSERT INTO group_member VALUES ('f','parent');
            INSERT INTO group_member VALUES ('a','parent');
            """)
        self.available = set(mod.REQUIRED)

    def evaluate(self):
        def fake_fetch(url):
            if url == mod.APP + "/api/version":
                return {"version": "0.10.2"}
            if url == mod.OLLAMA + "/api/tags":
                return {"models": [{"name": x} for x in sorted(self.available)]}
            raise AssertionError(url)

        with patch.object(mod, "fetch", side_effect=fake_fetch), \
             patch.object(mod, "check_env", return_value=self.db):
            return mod.audit(NAMES, P)

    def test_existing_parent_membership_is_not_a_blocker(self):
        report = self.evaluate()
        self.assertEqual(report["AUDIT"], "READ_ONLY")
        self.assertEqual(report["STATUS"], "READY_FOR_PRIVATE_PROFILES")
        self.assertEqual(report["ADULT_MEMBERS"], 1)
        self.assertEqual(report["FAMILY_MEMBERS"], 1)
        self.assertEqual(report["CHILD_MEMBERS"], 0)
        self.assertEqual(report["REGISTERED_MODELS"], 0)
        self.assertEqual(report["REQUIRED_BASE_MODELS_MISSING"], 0)
        self.assertEqual(report["PUBLIC_MODEL_GRANTS"], 0)
        self.assertFalse(report["CHANGED"])
        self.assertEqual(report["MODEL_API_AUTHENTICATION_REQUIRED_FOR_WRITES"],
                         "YES")
        self.assertEqual(len(report["CONFIG_SHA256"]), 64)
        self.assertNotIn("parent", json.dumps(report))
        self.assertNotIn("Parents@unit.invalid", json.dumps(report))

    def test_missing_ollama_basemodel_never_reports_ready(self):
        self.available.remove("mistral-nemo:12b")
        report = self.evaluate()
        self.assertEqual(report["STATUS"], "BASE_MODELS_MISSING")
        self.assertEqual(report["REQUIRED_BASE_MODELS_MISSING"], 1)

    def test_mixed_parent_child_roles_are_rejected(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO group_member VALUES ('c','parent')")
        with self.assertRaises(mod.Refuse):
            self.evaluate()

    def test_unknown_group_member_is_rejected(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO group_member VALUES ('c','unknown')")
        with self.assertRaises(mod.Refuse):
            self.evaluate()

    def test_model_inventory_must_be_known_and_reviewed(self):
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO "model" VALUES (?)', ("not-our-model",))
        self.assertEqual(self.evaluate()["STATUS"], "MODEL_OR_ACL_BASELINE_DRIFT")

    def test_public_grant_fails_fully_safe_ansible_audit(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO access_grant VALUES (?,?,?,?,?)",
                       ("model", "not-our-model", "user", "*", "read"))
        self.assertEqual(self.evaluate()["PUBLIC_MODEL_GRANTS"], 1)

    def test_prompt_must_be_learning_not_copy_paste(self):
        with self.assertRaises(mod.Refuse):
            self.evaluate_bad_prompt()

    def evaluate_bad_prompt(self):
        with patch.object(mod, "fetch", return_value={"version": "0.10.2"}):
            return mod.audit(NAMES, "unsafe")

    def test_playbook_never_requires_token_or_writes(self):
        s = PLAY.read_text()
        play = yaml.safe_load(s)[0]
        self.assertEqual(play["serial"], 1)
        self.assertIn("bergen_ai_family_audit_host", play["hosts"])
        self.assertNotIn("vault_open_webui_admin_token", s)
        self.assertNotIn("api_key", s.lower())
        self.assertNotIn("ansible.builtin.shell:", s)
        self.assertNotIn("ansible.builtin.copy:", s)
        self.assertNotIn("ansible.builtin.lineinfile:", s)
        self.assertIn("bp_family_chat_ready_raw", s)
        tasks = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0]["no_log"])
        self.assertEqual(tasks[0]["changed_when"], False)

    def test_oidc_active_legacy_stager_is_now_guarded(self):
        src = STAGER.read_text()
        self.assertIn("OIDC_GROUP_MANAGEMENT_NOT_ACTIVE", src)
        self.assertIn("OIDC_PRIVILEGE_BASELINE_DRIFT", src)
        self.assertIn("membership_fingerprint", src)
        self.assertIn('"ENABLE_OAUTH_GROUP_MANAGEMENT") is True', src)
        self.assertIn('SELECT gm.user_id, g.name FROM group_member', src)
        self.assertNotIn("demand(member_count == 0", src)
        self.assertIn("GROUP_MEMBERSHIP_REVIEW_REQUIRED", src)
        self.assertNotIn("INSERT INTO group_member", src)


if __name__ == "__main__":
    unittest.main()
