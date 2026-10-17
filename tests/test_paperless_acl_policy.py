#!/usr/bin/env python3
"""Offline guardrails for the Bergen Paperless ACL migration and reconciler.

These tests require only Python standard library and never connect to Django,
Synology or the production LXC. Run with:
python3 -m unittest discover -s tests -p 'test_paperless_acl_policy.py' -v
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "ansible/files/paperless/migrate_permissions.py"
RECONCILER = ROOT / "ansible/files/paperless/reconcile_ingest.py"


def top_level_literal(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("missing top-level constant: " + name)


class PaperlessACLContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = MIGRATION.read_text(encoding="utf-8")
        cls.reconciler = RECONCILER.read_text(encoding="utf-8")
        cls.migration_tree = ast.parse(cls.migration)
        cls.reconciler_tree = ast.parse(cls.reconciler)

    def test_both_scripts_compile(self):
        compile(self.migration, str(MIGRATION), "exec")
        compile(self.reconciler, str(RECONCILER), "exec")
        inner = top_level_literal(self.reconciler_tree, "DJANGO_VERIFY")
        compile(inner, "<embedded-django-verify>", "exec")

    def test_only_parents_receive_adult_rights(self):
        self.assertEqual(top_level_literal(self.migration_tree, "PARENTS"),
                         ("nadja", "thomas"))
        granted = top_level_literal(self.migration_tree, "ADULT_GLOBAL")
        self.assertIn("change_document", granted)
        self.assertIn("view_document", granted)
        self.assertNotIn("delete_document", granted)
        self.assertNotIn("delete_tag", granted)
        self.assertNotIn("delete_correspondent", granted)
        self.assertNotIn("delete_documenttype", granted)

    def test_workflow_routes_and_owners_are_unchanged(self):
        expected = top_level_literal(self.migration_tree, "WORKFLOWS")
        self.assertEqual(set(expected), set(range(1, 6)))
        self.assertEqual(expected[4][3], "admin")
        self.assertEqual(expected[5][3], "admin")
        self.assertTrue(expected[4][2].endswith("/Eltern/*"))
        self.assertTrue(expected[5][2].endswith("/Familie/*"))

    def test_strict_shared_document_delete_prohibition(self):
        self.assertIn('("delete_document", expected_delete)', self.migration)
        self.assertIn("permitted_document_ids(user, perm=perm)", self.migration)
        self.assertIn("UNOWNED_DOCUMENTS_BLOCK_MODEL_DELETE_PERMISSION", self.migration)
        self.assertIn("if not COMMIT:", self.migration)
        self.assertIn("with transaction.atomic():", self.migration)
        self.assertIn("PAPERLESS_ACL_MIGRATION_COMMITTED_AND_VERIFIED", self.migration)
        self.assertNotIn('assign_perm("delete_document"', self.migration)
        self.assertNotIn('assign_perm("delete_document"', self.reconciler)

    def test_parent_edit_rights_on_eltern_group_and_effective_user_grants(self):
        # Regression: group change rights appear for each parent when
        # get_users_with_perms combines group and user grants. The previous
        # postcondition rejected those legitimate effective permissions.
        self.assertIn(
            'expected_users = {name: {"view_document", "change_document"} for name in PARENTS}',
            self.migration,
        )
        self.assertIn(
            'actions[4].assign_change_users.add(*(users[name] for name in PARENTS))',
            self.migration,
        )
        self.assertIn(
            'assign_perm("change_document", users[name], doc)',
            self.migration,
        )
        self.assertIn(
            'allowed = ({"view_document"}, {"view_document", "change_document"})',
            self.migration,
        )

    def test_private_document_edit_and_visibility_are_checked(self):
        self.assertIn("def audit_private_documents(users, after=False):", self.migration)
        self.assertIn("audit_private_documents(users, after=False)", self.migration)
        self.assertIn("audit_private_documents(users, after=True)", self.migration)
        self.assertIn("UNEXPECTED_PRIVATE_GRANT", self.migration)
        self.assertIn("PRIVATE_ACCESS_DIFFERENCE", self.migration)
        self.assertIn("PRIVATE_GLOBAL_PERMISSION_MISSING", self.migration)

    def test_family_parent_edit_is_individual_not_family_group(self):
        inner = top_level_literal(self.reconciler_tree, "DJANGO_VERIFY")
        self.assertIn("scope == 'Familie@bergen.intern'", inner)
        self.assertIn("'change_document'", inner)
        self.assertIn("expected_delete = user.is_superuser or user.pk == doc.owner_id", inner)
        self.assertIn("expected_groups = {scope: {'view_document'}}", inner)
        self.assertIn("elif scope == 'Familie@bergen.intern'", inner)

    def test_reconciler_can_audit_imported_receipts_without_commit(self):
        self.assertIn("--audit-imported", self.reconciler)
        self.assertIn("AUDITED_IMPORTED", self.reconciler)
        self.assertIn("if args.commit and args.audit_imported:", self.reconciler)


if __name__ == "__main__":
    unittest.main()
