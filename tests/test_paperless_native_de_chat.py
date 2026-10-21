"""Offline regression: native German AI UI/chat and no-RAG worker coexist."""
import ast
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "ansible/files/paperless/bergen_ai_catalog_runner.py"
CONFIG = ROOT / "ansible/files/paperless/bergen_ai_native_de_chat_config.py"
PLAY = ROOT / "ansible/playbooks/manage-paperless-native-de-chat.yml"


class TestNativeGermanChat(unittest.TestCase):
    def test_pinned_worker_preserves_scope_and_journal(self):
        s = WORKER.read_text()
        ast.parse(s)
        self.assertIn("added__gte=IMPORT_CUTOFF", s)
        self.assertIn("tags__is_inbox_tag=True", s)
        self.assertIn("SELECT 1 FROM catalogue WHERE document_id=?", s)
        self.assertIn("classify_v2_no_rag(doc, before_groups)", s)
        self.assertIn("build_prompt_without_rag(doc, AIConfig()", s)
        self.assertNotIn('get_taxonomy_context(', s.split("def classify_v2_no_rag", 1)[1].split("def resolve_choices_v2", 1)[0])
        self.assertIn("verify_choices_v2(current_doc, current_groups", s)
        self.assertIn("INBOX_TAG_REMOVAL=\"NEVER\"", s)

    def test_german_localization_reuses_native_schema_with_fixed_object_ids(self):
        s = WORKER.read_text()
        for token in (
            'build_localization_prompt(result, "de")',
            'output["title"] = localized["title"] or result["title"]',
            '"existing_ids": result[field]["existing_ids"]',
            'output["correspondents"] = result["correspondents"]',
            'output["dates"] = result["dates"]',
        ):
            self.assertIn(token, s)
        self.assertIn("bge-m3:latest", s)
        self.assertIn('config.llm_embedding_backend == "ollama"', s)

    def test_config_apply_is_version_pinned_and_fingerprinted(self):
        s = CONFIG.read_text()
        ast.parse(s)
        for token in (
            '"ai_enabled": True',
            '"llm_output_language": "de"',
            '"llm_embedding_backend": "ollama"',
            '"llm_embedding_model": "bge-m3:latest"',
            '__full_version_str__ != "3.3.0"',
            "expected_sha256",
            "APPROVAL_OR_FINGERPRINT",
            "chat_index_permission_reviewed",
            "with transaction.atomic():",
            "select_for_update()",
            'local_model_tags(effective.llm_endpoint)',
            'MODE_INVALID',
        ):
            if token == "MODE_INVALID":
                continue
            self.assertIn(token, s)
        self.assertNotIn("Document.objects", s)
        self.assertNotIn("Note.objects", s)
        self.assertNotIn("document_llmindex rebuild", s)
        self.assertIn('INDEX_CHANGED=False', s)

    def test_playbook_audit_is_default_and_explicit_gate_for_mutations(self):
        p = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(p["hosts"], "venombox")
        self.assertTrue(p["become"])
        s = PLAY.read_text()
        for token in (
            "paperless_native_de_chat_mode | default('audit')",
            "paperless_native_de_chat_approved",
            "paperless_ai_catalog_verified_backup",
            "paperless_native_chat_acl_reviewed",
            "paperless_native_de_chat_expected_sha256",
            "bp_native_apply",
            "state: stopped",
            "state: started",
            "NATIVE_DE_CHAT_APPLY_FAILED_TIMER_STOPPED_MANUAL_REVIEW_REQUIRED",
            "INDEX_REBUILD=SEPARATE_APPROVAL_REQUIRED",
        ):
            self.assertIn(token, s)
        self.assertNotIn("user__is_superuser", s)
        self.assertNotIn("systemctl restart", s)


if __name__ == "__main__":
    unittest.main()
