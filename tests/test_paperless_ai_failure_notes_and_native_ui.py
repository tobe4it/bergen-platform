"""Offline fail-closed tests of Bergen-AI phase-3 + native UI phase-4.

No production Paperless, SQLite journal, LLM inference or document writes.
"""
import ast
import importlib.util
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "ansible/files/paperless/bergen_ai_catalog_policy.py"
WORKER = ROOT / "ansible/files/paperless/bergen_ai_catalog_runner.py"
UI = ROOT / "ansible/files/paperless/bergen_ai_catalog_native_ui.py"
NOTE_RIGHTS = ROOT / "ansible/files/paperless/bergen_ai_catalog_note_permissions.py"
WORKER_PLAY = ROOT / "ansible/playbooks/manage-paperless-ai-inbox-catalog.yml"
UI_PLAY = ROOT / "ansible/playbooks/manage-paperless-native-ai-suggestions-ui.yml"
NOTES_PLAY = ROOT / "ansible/playbooks/manage-paperless-ai-native-notes.yml"
TIMER_PLAY = ROOT / "ansible/playbooks/deploy-paperless-ai-inbox-catalog-timer.yml"
TIMER_READY = ROOT / "ansible/files/paperless/bergen_ai_catalog_timer_readiness.py"


def policy():
    spec = importlib.util.spec_from_file_location("catalog_policy_phase34", POLICY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TwoPhaseAiTests(unittest.TestCase):
    def test_valid_no_change_is_not_failure(self):
        mod = policy()
        unchanged = dict(title=None, correspondent_id=None,
                         document_type_id=None, add_tag_ids=[])
        self.assertFalse(mod.has_metadata_changes(unchanged))
        for key, value in (("title", "new"), ("correspondent_id", 5),
                           ("document_type_id", 6), ("add_tag_ids", [12])):
            with self.subTest(key=key):
                changes = dict(unchanged, **{key: value})
                self.assertTrue(mod.has_metadata_changes(changes))
        with self.assertRaises(mod.PolicyError):
            mod.has_metadata_changes({"title": "x"})

    def test_proposal_note_is_bounded_and_human_review_only(self):
        mod = policy()
        suggestions = {
            "document_types": {"new_names": ["Zertifikat"]},
            "tags": {"new_names": ["Qualifikation", " Weiterbildung "]},
        }
        note = mod.review_note_text(
            suggestions, resolved_type_name="Zertifikat",
            resolved_tag_names=["Weiterbildung"],
        )
        self.assertIn("Zertifikat", note)
        self.assertIn("Qualifikation", note)
        self.assertIn("manuellen Pruefung", note)
        self.assertIn("Posteingangs-Tag", note)
        self.assertLessEqual(len(note), 2048)
        with self.assertRaises(mod.PolicyError):
            mod.bounded_ai_labels(["x"] * 13)
        with self.assertRaises(mod.PolicyError):
            mod.bounded_ai_labels(["x" * 129])

    def test_worker_journals_failure_stages_and_atomic_notes(self):
        src = WORKER.read_text()
        ast.parse(src)
        self.assertIn('"NO_CHANGE"', src)
        self.assertIn('stage = "INFERENCE"', src)
        self.assertIn('stage = "RESOLUTION"', src)
        self.assertIn('stage = "DB_WRITE"', src)
        self.assertIn('stage = "JOURNAL"', src)
        self.assertIn('db.execute("UPDATE catalogue SET state=?,applied_json=? WHERE document_id=?"', src)
        self.assertIn('with transaction.atomic():', src)
        self.assertIn('Note.objects.create(document=current_doc, user=doc.owner,', src)
        self.assertIn('notes_enabled=request.get("notes_enabled", False)', src)
        self.assertIn('if db.execute("SELECT 1 FROM catalogue WHERE document_id=?"', src)
        self.assertNotIn('raise PolicyError("NO_APPLICABLE_SUGGESTIONS")', src)

    def test_ui_guarded_and_embedding_disabled(self):
        src = UI.read_text()
        ast.parse(src)
        self.assertIn('__full_version_str__ != "3.3.0"', src)
        self.assertIn('cfg.llm_backend != "ollama"', src)
        self.assertIn('cfg.llm_embedding_backend', src)
        self.assertIn('obj.save(update_fields=["ai_enabled"])', src)
        self.assertIn('not req["approved"] or not req["backup_verified"]', src)
        self.assertNotIn('objects.create(', src)
        self.assertNotIn('llm_embedding_backend = "', src)
        play = yaml.safe_load(UI_PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        self.assertIn("paperless_native_ai_ui_approved", UI_PLAY.read_text())

    def test_note_rights_adult_only_and_separate_approval(self):
        src = NOTE_RIGHTS.read_text()
        ast.parse(src)
        self.assertIn('req["group"] == "Eltern@bergen.intern"', src)
        self.assertIn('("add_note", "view_note")', src)
        self.assertIn('not user.is_staff and not user.is_superuser', src)
        self.assertIn('with transaction.atomic():', src)
        play = yaml.safe_load(NOTES_PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertIn("paperless_ai_notes_permission_approved", NOTES_PLAY.read_text())

    def test_timer_requires_note_approval_and_post_watermark(self):
        src = TIMER_PLAY.read_text()
        self.assertIn('paperless_ai_catalog_notes_enabled', src)
        self.assertIn('paperless_ai_catalog_notes_approved', src)
        self.assertIn('paperless_ai_catalog_pilot_passed', src)
        self.assertIn('paperless_native_ai_ui_approved', src)
        self.assertIn("'notes_enabled': true", src)
        self.assertIn('WATERMARK_MUST_EQUAL_LIVE_MAX_DOCUMENT_ID', src)
        self.assertIn('paperless_ai_catalog_timer_activate', src)
        self.assertIn('paperless_ai_catalog_notes_enabled', WORKER_PLAY.read_text())
        readiness = TIMER_READY.read_text()
        ast.parse(readiness)
        self.assertIn("cfg.ai_enabled", readiness)
        self.assertIn("not cfg.llm_embedding_backend", readiness)
        self.assertIn("documents.add_note", readiness)
        self.assertIn("Eltern@bergen.intern", readiness)
        self.assertIn("bergen_ai_catalog_timer_readiness.py", src)


if __name__ == "__main__":
    unittest.main()
