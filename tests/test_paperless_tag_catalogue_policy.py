#!/usr/bin/env python3
"""Offline contract for Bergen Paperless managed tag catalogue."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "ansible/files/paperless/prepare_inbox_tag.py"
PLAYBOOK = ROOT / "ansible/playbooks/prepare-paperless-inbox-tag.yml"

EXPECTED = {
    "Steuer", "Haus", "Finanzen", "Versicherung", "Mobilität",
    "Gesundheit", "Bildung", "Beruf", "Reise", "IT", "Ehrenamt",
    "Behörden", "Haustiere", "Energie", "Gewährleistung",
    "Posteingang", "Aktion offen", "Frist prüfen",
}


class ManagedTagCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.catalogue = next(
            ast.literal_eval(node.value)
            for node in cls.tree.body
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "CATALOGUE"
                for target in node.targets
            )
        )

    def test_syntax_and_all_eighteen_names(self):
        compile(self.source, str(SCRIPT), "exec")
        self.assertEqual(len(self.catalogue), 18)
        self.assertEqual({name for name, *_ in self.catalogue}, EXPECTED)

    def test_only_topic_tags_use_auto_training(self):
        for name, _color, learn, inbox in self.catalogue:
            if name in {"Posteingang", "Aktion offen", "Frist prüfen"}:
                self.assertFalse(learn)
            else:
                self.assertTrue(learn)
            self.assertEqual(inbox, name == "Posteingang")

    def test_safe_no_history_or_document_acl_changes(self):
        self.assertIn("DOCUMENTS_AND_ACLS_UNCHANGED", self.source)
        self.assertNotIn("Document.objects.update(", self.source)
        self.assertNotIn("delete_document", self.source)
        self.assertNotIn("change_document", self.source)
        self.assertNotIn("assign_perm(\"change_tag\"", self.source)
        self.assertIn('assign_perm("view_tag", user, tag)', self.source)
        self.assertIn("with transaction.atomic():", self.source)
        self.assertIn("TAG_NOT_ADMIN_OWNED", self.source)
        self.assertIn("OTHER_INBOX_TAGS_NEED_REVIEW", self.source)

    def test_dry_run_and_explicit_apply(self):
        self.assertIn('os.environ.get("BP_INBOX_APPLY", "0")', self.source)
        self.assertIn('print("DRY_RUN_NO_CHANGES")', self.source)
        self.assertIn("paperless_inbox_apply | default(false) | bool", self.playbook)
        self.assertIn("BP_INBOX_APPLY=0", self.playbook)
        self.assertIn("BP_INBOX_APPLY=1", self.playbook)
        self.assertIn("BERGEN_TAG_CATALOGUE_COMMITTED_AND_VERIFIED", self.playbook)

    def test_existing_ui_preferences_retained(self):
        self.assertIn("if current is not None:", self.source)
        self.assertIn("copy.deepcopy(data)", self.source)
        self.assertIn("FUTURE_USERS_REQUIRE_BASELINE_PROVISIONING", self.source)


if __name__ == "__main__":
    unittest.main()
