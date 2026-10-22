"""Offline fail-closed checks for controlled native child chat acceptance.

No real user session, index changes, model calls or site-local secrets.
"""
import ast
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/verify_native_chat_child_e2e.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-native-chat-child-e2e.yml"
DOCS = ROOT / "docs/PAPERLESS-CHAT-CHILD-E2E-ACCEPTANCE.md"


class TestChildChatE2E(unittest.TestCase):
    def test_python_is_parseable_and_bounds_sensitive_output(self):
        source = SCRIPT.read_text()
        ast.parse(source)
        self.assertIn("MAX_STREAM_BYTES = 131072", source)
        self.assertIn("MAX_CHILDREN = 4", source)
        self.assertIn("MAX_INPUT = 120000", source)
        self.assertIn("MODE", source)
        self.assertIn("FRAME + json.dumps", source)
        self.assertNotIn("print(content)", source)
        self.assertNotIn("print(answer)", source)
        self.assertNotIn("print(parents)", source)
        self.assertNotIn("print(family)", source)
        self.assertNotIn("print(user)", source)
        self.assertIn('except Exception:\n        emit("BLOCKED", "UNCLASSIFIED"', source)

    def test_exact_version_document_scope_and_index_read_only(self):
        src = SCRIPT.read_text()
        for token in (
            '__full_version_str__ == "3.3.0"',
            "native-chat-import-proof-v1",
            "imported[name] <= grants[name]",
            "not (parents & family)",
            'user.has_perm("documents.view_document")',
            "not (visible & parents) and family <= visible",
            'has_perms_owner_aware(',
            'uri=True, timeout=10',
            'PRAGMA query_only=ON',
            "modified == docs",
            "chunk_count == vector_count",
            "get_configured_model_name(AIConfig())",
        ):
            self.assertIn(token, src)
        self.assertNotIn("get_vector_store(", src)
        self.assertNotIn("Document.objects.update(", src)
        self.assertNotIn("Group.objects.create(", src)
        self.assertNotIn("user_permissions.add(", src)
        self.assertNotIn("document_llmindex rebuild", src)

    def test_each_real_child_session_routes_through_native_chat_endpoint(self):
        src = SCRIPT.read_text()
        for token in (
            'ENDPOINT = "/api/documents/chat/"',
            "Client(enforce_csrf_checks=False",
            "client.force_login(",
            "client.logout()",
            'denied.status_code == 403',
            'and not seen_routes',
            'positive = client.post(',
            'archive = client.post(',
            'len(seen_routes) == 2',
            'seen_routes[1] == allowed',
            'kwargs.get("unrestricted") is False',
            'not (ids & parents)',
            'consume_response(',
            'metadata.get("references")',
            'not (set(ids) & parents)',
            'get_llm_output_language(AIConfig(), user) == "de"',
            'SESSION_CREATED="EPHEMERAL_CLEANED"',
            'EXTERNAL_OIDC_AUTHENTICATION="NOT_TESTED"',
            'GERMAN_ANSWER_LANGUAGE="MANUAL_REVIEW_REQUIRED"',
        ):
            self.assertIn(token, src)

    def test_playbook_audit_default_and_live_gates_are_separate(self):
        parsed = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(parsed), 1)
        play = parsed[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        tasks = play["tasks"]
        raw = PLAY.read_text()
        for token in (
            "paperless_native_chat_e2e_mode | default('audit')",
            "paperless_native_chat_e2e_approved",
            "paperless_native_chat_model_inference_approved",
            "paperless_ai_catalog_verified_backup",
            "paperless_native_chat_acl_modify_approved",
            "paperless_native_chat_index_build_approved",
            "NATIVE_CHAT_E2E_NO_RECENT_BACKUP",
            "AUDIT=READ_ONLY",
            "LIVE_CHAT=NOT_STARTED",
            "EXTERNAL_OIDC_SMOKE_TEST_REQUIRED",
        ):
            self.assertIn(token, raw)
        for task in tasks:
            if "ansible.builtin.command" in task and (
                "bp_e2e_" in str(task) or "bp_child_e2e_" in str(task)
            ):
                self.assertTrue(task.get("no_log", False), task["name"])
        live = next(task for task in tasks if task["name"].startswith(
            "Perform separately approved temporary child sessions"
        ))
        self.assertIn("bp_child_e2e_live", live["when"])
        self.assertTrue(live["no_log"])
        self.assertFalse(live["failed_when"])
        command = live["ansible.builtin.command"]
        self.assertIn("stdin", command)
        self.assertTrue(command["stdin_add_newline"])
        self.assertIn("'mode':'live'", command["stdin"])
        self.assertIn("'approved':true", command["stdin"])

    def test_live_gate_diagnostic_is_allowlisted_and_gate_stays_fail_closed(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        tasks = play["tasks"]
        diagnostic = next(task for task in tasks if task["name"].startswith(
            "Report sanitized live authorization gate state"
        ))
        report = "\\n".join(diagnostic["ansible.builtin.debug"]["msg"])
        self.assertEqual(diagnostic["when"], "bp_child_e2e_live")
        for field in (
            "SESSION_APPROVED=", "MODEL_INFERENCE_APPROVED=",
            "BACKUP_VERIFIED_DECLARED=", "UNRELATED_ACL_APPLY_APPROVED=",
            "UNRELATED_INDEX_BUILD_APPROVED=",
            "UNRELATED_NATIVE_CONFIG_APPLY_APPROVED=",
        ):
            self.assertIn(field, report)
        self.assertNotIn("password", report.lower())
        self.assertNotIn("stdout", report)
        assertion = next(task for task in tasks if task["name"].startswith(
            "Require exact target and refuse unrelated production approvals"
        ))
        self.assertTrue(assertion["no_log"])
        checks = " ".join(assertion["ansible.builtin.assert"]["that"])
        self.assertIn("paperless_ai_catalog_verified_backup", checks)
        self.assertIn("paperless_native_chat_e2e_approved", checks)
        self.assertIn("paperless_native_chat_model_inference_approved", checks)

    def test_docs_disclose_session_mutation_and_oidc_limit(self):
        docs = DOCS.read_text()
        self.assertIn("force_login", docs)
        self.assertIn("OIDC", docs)
        self.assertIn("temporary", docs)
        self.assertIn("EXTERNAL_OIDC_SMOKE_TEST_REQUIRED", docs)
        self.assertIn("48 hours", docs)
        self.assertIn("59/59", docs)
        self.assertIn("988", docs)


if __name__ == "__main__":
    unittest.main()
