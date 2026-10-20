"""Offline safety regression for a voluntary Paperless pilot ID diagnosis."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_ai_catalog_pilot_candidates_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-ai-pilot-selection-readonly.yml"


def load():
    spec = importlib.util.spec_from_file_location("pilot_diag", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeMatch:
    def __init__(self, allowed):
        self.allowed = allowed

    def exists(self):
        return self.allowed


class FakeFilter:
    def __init__(self, allowed):
        self.allowed = allowed

    def filter(self, **kw):
        return FakeMatch(self.allowed)

    def exists(self):
        return self.allowed


class FakeDocument:
    def __init__(self, *, owner=True, active=True, privileged=False,
                 group=True, inbox=True, ocr=50, version=False):
        self.owner_id = 1 if owner else None
        self.owner = type("Owner", (), {
            "is_active": active,
            "is_staff": privileged,
            "is_superuser": False,
            "groups": FakeFilter(group)
        })() if owner else None
        self.tags = FakeFilter(inbox)
        self.content = "x" * ocr
        self.root_document_id = 42 if version else None
        self.versions = FakeFilter(False)

class TestPilotReadonly(unittest.TestCase):
    def test_selected_id_envelope(self):
        p = load()
        self.assertTrue(p.valid_ids([]))
        self.assertTrue(p.valid_ids([42]))
        for value in ([0], [-1], [1, 1], [1, 2, 3], ["42"], [True], {}, None):
            self.assertFalse(p.valid_ids(value))

    def test_reason_categories_match_runner_policy(self):
        p = load()
        group = type("Group", (), {"pk": 1})()
        cases = [
            (None, "DOCUMENT_ABSENT"),
            (FakeDocument(owner=False), "OWNER_MISSING"),
            (FakeDocument(active=False), "OWNER_INACTIVE"),
            (FakeDocument(privileged=True), "OWNER_PRIVILEGED"),
            (FakeDocument(group=False), "OWNER_OUTSIDE_PARENT_GROUP"),
            (FakeDocument(inbox=False), "INBOX_TAG_MISSING"),
            (FakeDocument(ocr=10), "OCR_INSUFFICIENT"),
            (FakeDocument(version=True), "VERSIONED_DOCUMENT"),
            (FakeDocument(), "ELIGIBLE"),
        ]
        for doc, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(p.classify(doc, group), expected)

    def test_invalid_envelope_fails_without_django(self):
        x = subprocess.run(
            [sys.executable, "-c", SCRIPT.read_text() + "\\nmain()"],
            input=json.dumps({"protocol": "unexpected", "pilot_ids": [42],
                              "show_candidate_ids": True}),
            text=True, capture_output=True, check=True, timeout=5,
        )
        self.assertIn("STATUS", x.stdout)
        self.assertIn('"STATUS": "INPUT_REJECTED"', x.stdout)
        self.assertNotIn("42", x.stdout)

    def test_anonymity_and_readonly_source(self):
        src = SCRIPT.read_text()
        for marker in ('MAX_CANDIDATE_SCAN = 30', 'MAX_CANDIDATE_IDS = 8',
                       'request["show_candidate_ids"]', 'doc.owner.groups.filter',
                       'doc.tags.filter', 'doc.versions.exists()'):
            self.assertIn(marker, src)
        for forbidden in ('get_ai_document_classification(', 'ollama_model_available(',
                          '.save(', '.delete(', '.create(', 'objects.create(',
                          'subprocess.', 'requests.', 'urllib.', 'print(doc.content',
                          'print(doc.title', 'document.owner ='):
            self.assertNotIn(forbidden, src)
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        actions = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(t["no_log"] for t in actions))
        self.assertTrue(all(t["changed_when"] is False for t in actions))
        self.assertIn("paperless_ai_catalog_show_candidate_ids", PLAY.read_text())
        self.assertIn("paperless_ai_catalog_approved", PLAY.read_text())
        self.assertIn("PILOT_ELIGIBILITY", PLAY.read_text())


if __name__ == "__main__":
    unittest.main()
