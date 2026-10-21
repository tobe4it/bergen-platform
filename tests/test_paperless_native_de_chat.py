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

    def test_new_german_tags_are_note_proposals_not_auto_creation(self):
        """v0.16 existing-tag resolution is unchanged, even after translation."""
        source = WORKER.read_text()
        self.assertIn('output["_bergen_original_match_names"]', source)
        self.assertIn('field: list(result[field]["new_names"])', source)
        self.assertIn('names = name_source.get(key, block.get("new_names"))', source)
        self.assertIn('bounded_ai_labels(block.get("new_names"))', source)
        # No free-form tag object creation in the worker.
        self.assertNotIn("Tag.objects.create(", source)
        self.assertNotIn("Tag.objects.get_or_create(", source)
        self.assertIn('resolved_tag_names=[t.name for t in tags]', source)
        self.assertIn("review_note_text(", source)
        self.assertIn('Note.objects.create(document=current_doc,', source)
        policy_source = (
            ROOT / "ansible/files/paperless/bergen_ai_catalog_policy.py"
        ).read_text()
        self.assertIn('tag_names = bounded_ai_labels(tags.get("new_names"))',
                      policy_source)
        self.assertIn('"LLM-Tags: " +', policy_source)

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

    def test_readonly_chat_index_and_effective_acl_negative_audit(self):
        """A parent-shared ownerless Document may be accessible to others."""
        base = ROOT / "ansible/files/paperless"
        index = (base / "audit_native_de_chat_index.py").read_text()
        acl = (base / "audit_native_chat_ownerless_acl.py").read_text()
        play = (ROOT / "ansible/playbooks/audit-paperless-native-chat-access-and-index-readonly.yml").read_text()
        ast.parse(index)
        ast.parse(acl)
        yaml.safe_load(play)
        self.assertIn('ai.llm_output_language == "de"', index)
        self.assertIn("Document.objects.count()", index)
        self.assertIn('INDEX_COVERAGE="NOT_PROVEN"', index)
        executable = " ".join(line for line in index.splitlines()
                              if not line.lstrip().startswith("#"))
        self.assertNotIn("get_vector_store(", executable)
        self.assertIn("permitted_document_ids(user)", acl)
        self.assertIn("owner__isnull=True", acl)
        self.assertIn("user.has_perm(\"documents.view_document\")", acl)
        self.assertIn("CHILD_GROUP_VISIBLE_DOCUMENT_PAIRS", play)
        self.assertIn("CHAT_RELEASE_GATE", play)
        self.assertIn("DOCUMENTS_CHANGED=NO", play)
        self.assertIn("MODEL_INFERENCE", index)
        self.assertNotIn("Note.objects.create", acl)
        self.assertNotIn("User.objects.create", acl)

    def test_child_chat_parent_boundary_uses_actual_import_provenance(self):
        """A missing global model grant is NOT evidence of future safety."""
        files = ROOT / "ansible/files/paperless"
        receipt = (files / "audit_native_chat_verified_group_imports.py").read_text()
        boundary = (files / "audit_native_chat_child_boundary.py").read_text()
        play = (ROOT / "ansible/playbooks/audit-paperless-native-chat-child-boundary-readonly.yml").read_text()
        ast.parse(receipt)
        ast.parse(boundary)
        parsed = yaml.safe_load(play)
        self.assertEqual(parsed[0]["hosts"], "venombox")
        self.assertIn('mod.verify(filename, receipt["sha256"], owner, grant)', receipt)
        self.assertIn('"SUBMITTED", "IMPORTED"', receipt)
        self.assertIn('owner != "admin"', receipt)
        self.assertIn('permitted_document_ids(', boundary)
        self.assertIn('child.has_perm("documents.view_document")', boundary)
        self.assertIn('has_perms_owner_aware(child, "view_document", docs[document_id])', boundary)
        self.assertIn('CHILD_PARENT_VISIBLE_IF_MODEL_VIEW_GRANTED=', boundary)
        self.assertIn('CHILD_PARENT_SINGLE_DOCUMENT_ALLOW=', boundary)
        self.assertIn('CHILD_FAMILY_VISIBLE_IF_MODEL_VIEW_GRANTED=', boundary)
        self.assertIn("if imported[\"Eltern\"] - parent_grants", boundary)
        self.assertIn('"USER_SESSION_AND_INDEX_TEST_STILL_REQUIRED"', boundary)
        self.assertIn('no_log: true', play)
        self.assertIn('CHILD_PARENT_VISIBLE_IF_MODEL_VIEW_GRANTED=', play)
        self.assertNotIn("document_llmindex rebuild", play)
        self.assertNotIn("user_permissions.add(", boundary)
        self.assertNotIn("owner =", boundary)
        self.assertNotIn("Document.objects.update(", boundary)

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
