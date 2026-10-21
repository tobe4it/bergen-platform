"""Offline regression for bounded, read-only AI catalogue journal status inventory."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless/audit_ai_catalog_journal_inventory_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-ai-catalog-journal-inventory-readonly.yml"


def load():
    spec = importlib.util.spec_from_file_location("catalog_journal_inventory_readonly", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class JournalInventoryTests(unittest.TestCase):
    def test_exact_and_bounded_id_inputs(self):
        m = load()
        self.assertEqual(m.validate({"protocol": "catalog-journal-inventory-v1",
                                      "document_ids": [2, 5]}), [2, 5])
        for items in ([], [0], [True], [1, 1], [1] * 9, ["3"], None):
            self.assertIsNone(m.validate({"protocol": "catalog-journal-inventory-v1",
                                           "document_ids": items}))
        self.assertIsNone(m.validate({"protocol": "wrong", "document_ids": [2]}))
        self.assertIsNone(m.validate({"protocol": "catalog-journal-inventory-v1",
                                       "document_ids": [2], "extra": 4}))

    def test_no_write_journal_scoped_query_and_input_order(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            dbpath = Path(tmp) / "catalog.sqlite3"
            with sqlite3.connect(dbpath) as db:
                db.execute("CREATE TABLE catalogue (document_id INTEGER PRIMARY KEY,"
                           "state TEXT NOT NULL)")
                db.executemany("INSERT INTO catalogue VALUES (?,?)",
                               [(2, "APPLIED"), (11, "REQUIRES_REVIEW"),
                                (16, "REQUIRES_REVIEW"), (99, "APPLIED")])
            m.JOURNAL = dbpath
            initial_bytes = dbpath.read_bytes()
            expected = [{"document_id": 16, "state": "REQUIRES_REVIEW"},
                        {"document_id": 21, "state": "NOT_RECORDED"},
                        {"document_id": 2, "state": "APPLIED"}]
            self.assertEqual(m.query_states([16, 21, 2]), expected)
            self.assertEqual(dbpath.read_bytes(), initial_bytes)

    def test_unknown_journal_state_fails_closed(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            dbpath = Path(tmp) / "catalog.sqlite3"
            with sqlite3.connect(dbpath) as db:
                db.execute("CREATE TABLE catalogue (document_id INTEGER PRIMARY KEY,"
                           "state TEXT NOT NULL)")
                db.execute("INSERT INTO catalogue VALUES (2,'SUSPICIOUS')")
            m.JOURNAL = dbpath
            with self.assertRaises(ValueError):
                m.query_states([2])

    def test_invalid_input_does_not_import_django(self):
        code = SRC.read_text() + "\nmain()"
        process = subprocess.run([sys.executable, "-c", code],
            input=json.dumps({"protocol": "catalog-journal-inventory-v1",
                              "document_ids": [0]}),
            text=True, capture_output=True, check=True, timeout=5)
        self.assertIn('"STATUS": "INPUT_REJECTED"', process.stdout)
        self.assertIn('"DOCUMENTS_CHANGED": "NO"', process.stdout)

    def test_no_unsafe_operations_or_unscoped_output(self):
        src = SRC.read_text()
        play = PLAY.read_text()
        for needle in ("mode=ro", "PRAGMA query_only=ON", "WHERE document_id IN",
                       "MODEL_INFERENCE", "MAX_IDS = 8"):
            self.assertIn(needle, src)
        for forbidden in (".save(", ".delete(", "objects.create(", "get_ai_document_classification(",
                          "journal.unlink(", "execute(\"UPDATE ", "os.system(", "subprocess."):
            self.assertNotIn(forbidden, src)
        p = yaml.safe_load(play)[0]
        self.assertEqual(p["hosts"], "venombox")
        self.assertTrue(p["become"])
        self.assertFalse(p["gather_facts"])
        commands = [x for x in p["tasks"] if "ansible.builtin.command" in x]
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(x.get("no_log") and x.get("changed_when") is False
                            for x in commands))
        self.assertIn("paperless_ai_catalog_journal_document_ids", play)
        self.assertIn("JOURNAL_INVENTORY_SCOPE_OR_STATUS_INVALID", play)


if __name__ == "__main__":
    unittest.main()
