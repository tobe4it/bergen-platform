"""Offline tests for Open WebUI 0.10.2 family model ACL audit (no network)."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "ansible/files/bergen_ai/audit_family_model_access_v0102.py"
PLAYBOOK = ROOT / "ansible/playbooks/audit-bergen-ai-family-model-access-readonly.yml"

spec = importlib.util.spec_from_file_location("family_acl", HELPER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
GROUPS = {"family": "family@site.example", "adults": "adults@site.example",
          "children": "children@site.example"}


def fixture(db):
    with sqlite3.connect(db) as c:
        c.executescript("""
        CREATE TABLE "group"(id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE "group_member"(group_id TEXT, user_id TEXT);
        CREATE TABLE "user"(id TEXT PRIMARY KEY, role TEXT);
        CREATE TABLE "model"(id TEXT PRIMARY KEY, base_model_id TEXT, is_active INTEGER);
        CREATE TABLE "access_grant"(resource_type TEXT, resource_id TEXT,
                                    principal_type TEXT, principal_id TEXT,
                                    permission TEXT);
        CREATE TABLE "config"(key TEXT, value TEXT);
        """)
        for role in ("family", "adults", "children"):
            c.execute('INSERT INTO "group" VALUES (?,?)', (role, GROUPS[role]))
        c.executemany('INSERT INTO "user" VALUES (?,?)',
                      [("adult1", "user"), ("kid1", "user")])
        c.executemany('INSERT INTO "group_member" VALUES (?,?)',
                      [("family", "adult1"), ("family", "kid1"),
                       ("adults", "adult1"), ("children", "kid1")])
        c.executemany('INSERT INTO "model" VALUES (?,?,1)', [
            ("parent-qwen", "qwen2.5:14b-instruct-q4_K_M"),
            ("child-qwen", "qwen2.5:14b-instruct-q4_K_M"),
            ("parent-mistral", "mistral-nemo:12b"),
            ("child-mistral", "mistral-nemo:12b"),
        ])
        c.executemany('INSERT INTO "access_grant" VALUES (?,?,?,?,?)', [
            ("model", "parent-qwen", "group", "adults", "read"),
            ("model", "child-qwen", "group", "children", "read"),
            ("model", "parent-mistral", "group", "adults", "read"),
            ("model", "child-mistral", "group", "children", "read"),
        ])


class FamilyModelACLTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "webui.db"
        fixture(self.db)

    def read(self):
        return mod.read_db(self.db, GROUPS)

    def test_expected_scoped_child_and_parent_aliases(self):
        r = self.read()
        self.assertEqual(r["AUDIT"], "READ_ONLY")
        self.assertEqual(r["CHANGED"], False)
        self.assertEqual(r["STATUS"], "INVENTORY_ONLY")
        self.assertEqual(r["ADULT_MEMBERS"], 1)
        self.assertEqual(r["CHILD_MEMBERS"], 1)
        self.assertEqual(r["PUBLIC_READ_GRANTS"], 0)
        self.assertEqual(r["CHILD_RAW_MODEL_READ_GRANTS"], 0)
        self.assertEqual(r["CATALOG_MODEL"]["CHILD_READ_ALIASES"], 1)
        self.assertEqual(r["CATALOG_MODEL"]["ADULT_READ_ALIASES"], 1)
        self.assertEqual(r["MULTILINGUAL_MODEL"]["CHILD_READ_ALIASES"], 1)
        self.assertEqual(r["EMBEDDING_MODEL"]["CHILD_READ_ALIASES"], 0)
        self.assertEqual(r["CATALOG_MODEL"]["RAW_REGISTERED"], False)
        self.assertEqual(r["GROUP_REVOCATION_E2E"], "NOT_PROVEN")
        self.assertNotIn("kid1", json.dumps(r))
        self.assertNotIn("family@site.example", json.dumps(r))

    def test_public_read_requires_review(self):
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO access_grant VALUES (?,?,?,?,?)",
                      ("model", "parent-qwen", "user", "*", "read"))
        self.assertEqual(self.read()["STATUS"], "REVIEW_REQUIRED")

    def test_direct_child_access_to_raw_requires_review(self):
        with sqlite3.connect(self.db) as c:
            c.execute('INSERT INTO "model" VALUES (?,?,1)',
                      ("qwen2.5:14b-instruct-q4_K_M", None))
            c.execute("INSERT INTO access_grant VALUES (?,?,?,?,?)",
                      ("model", "qwen2.5:14b-instruct-q4_K_M",
                       "group", "children", "read"))
        r = self.read()
        self.assertEqual(r["CHILD_RAW_MODEL_READ_GRANTS"], 1)
        self.assertEqual(r["STATUS"], "REVIEW_REQUIRED")

    def test_child_in_adult_group_requires_review(self):
        with sqlite3.connect(self.db) as c:
            c.execute('INSERT INTO "group_member" VALUES (?,?)',
                      ("adults", "kid1"))
        self.assertEqual(self.read()["ADULT_CHILD_MEMBER_OVERLAP"], "YES")
        self.assertEqual(self.read()["STATUS"], "REVIEW_REQUIRED")

    def test_unmapped_foreign_grant_requires_review(self):
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO access_grant VALUES (?,?,?,?,?)",
                      ("model", "child-qwen", "group", "other-group", "read"))
        self.assertEqual(self.read()["UNKNOWN_OR_FOREIGN_MODEL_GRANTS"], 1)
        self.assertEqual(self.read()["STATUS"], "REVIEW_REQUIRED")

    def test_missing_group_and_unreviewed_name_fail(self):
        with self.assertRaises(mod.Refuse):
            mod.read_db(self.db, dict(GROUPS, extra="other"))
        with sqlite3.connect(self.db) as c:
            c.execute('DELETE FROM "group" WHERE id=?', ("children",))
        with self.assertRaises(mod.Refuse):
            self.read()

    def test_playbook_read_only_and_bound_to_single_host(self):
        src = PLAYBOOK.read_text()
        self.assertIn("ansible_play_hosts_all | length == 1", src)
        self.assertIn("MODEL_VERSION_UNREVIEWED", src)
        self.assertIn("READ_ONLY", src)
        self.assertIn("CHANGED=False", src)
        self.assertIn("no_log: true", src)
        self.assertIn("changed_when: false", src)
        self.assertIn("audit_family_model_access_v0102.py", src)
        for forbidden in ("ansible.builtin.copy:", "ansible.builtin.systemd:",
                          "ansible.builtin.user:", "ansible.builtin.shell:"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
