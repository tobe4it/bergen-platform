"""Offline regressions for the no-write Paperless failure journal review."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless/audit_ai_catalog_review_state_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-ai-catalog-review-readonly.yml"


def load():
    spec = importlib.util.spec_from_file_location("catalog_review_readonly", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def snapshot():
    return {
        "id": 11, "owner_id": 2,
        "title": "redacted-test",
        "original_filename": "redacted-test.pdf",
        "correspondent_id": None, "document_type_id": None,
        "storage_path_id": None,
        "created": "2026-10-20T10:00:00+00:00",
        "modified": "2026-10-20T10:00:00+00:00",
        "checksum": "abc", "content_sha256": "def",
        "tag_ids": [1], "inbox": True
    }


class ReviewAuditTests(unittest.TestCase):
    def test_snapshot_comparison_categories(self):
        m = load()
        base = snapshot()
        self.assertEqual(m.compare(base, dict(base), 11),
                         ("MATCH", "NONE", "PRESENT"))
        changed = dict(base, modified="2026-10-20T10:01:00+00:00")
        self.assertEqual(m.compare(base, changed, 11),
                         ("DIFF", "MODIFIED_ONLY", "PRESENT"))
        changed = dict(base, title="different", inbox=False)
        self.assertEqual(m.compare(base, changed, 11),
                         ("DIFF", "OTHER_FIELDS", "ABSENT"))
        self.assertEqual(m.compare(base, dict(base), 12),
                         ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED"))
        self.assertEqual(m.compare({"title": "x"}, dict(base), 11),
                         ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED"))

    def test_invalid_input_never_reads_django_or_journal(self):
        code = SRC.read_text() + "\nmain()"
        x = subprocess.run(
            [sys.executable, "-c", code],
            input=json.dumps({"protocol": "catalog-review-v1", "document_id": 0}),
            text=True, capture_output=True, timeout=5, check=True,
        )
        self.assertIn('"STATUS": "INPUT_REJECTED"', x.stdout)
        self.assertIn('"MODEL_INFERENCE": "NO"', x.stdout)
        self.assertNotIn("redacted-test", x.stdout)

    def test_no_write_policy(self):
        s = SRC.read_text()
        for substring in (
            "mode=ro", "PRAGMA query_only=ON",
            "where document_id", "def compare(", "MODEL_INFERENCE",
        ):
            self.assertIn(substring.lower(), s.lower())
        for forbidden in (
            ".save(", ".delete(", "objects.create(", "get_ai_document_classification(",
            "requests.", "urllib.", "subprocess.", "CREATE TABLE ",
            "UPDATE catalogue SET", "INSERT INTO catalogue", "print(doc.",
        ):
            self.assertNotIn(forbidden, s)

    def test_approved_guest_single_doc_and_suppressed_output(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        tasks = play["tasks"]
        commands = [t for t in tasks if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(t["no_log"] and t["changed_when"] is False
                            for t in commands))
        self.assertIn("paperless_ai_catalog_review_document_id", PLAY.read_text())
        self.assertIn("PAPERLESS_REVIEW_EVIDENCE_UNVERIFIED", PLAY.read_text())
        self.assertIn("MODEL_INFERENCE=NO", PLAY.read_text())


if __name__ == "__main__":
    unittest.main()
