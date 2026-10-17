#!/usr/bin/env python3
"""Offline policy tests for Paperless user-rights audit and tag deletion."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "ansible/files/paperless/provision_user_rights.py"
PLAYBOOK = ROOT / "ansible/playbooks/prepare-paperless-user-rights.yml"


class UserRightsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")

    def test_compiles(self):
        compile(self.source, str(SCRIPT), "exec")
        self.assertIsInstance(ast.parse(self.source), ast.Module)

    def test_only_model_tag_delete_is_added(self):
        self.assertIn('codename="delete_tag"', self.source)
        self.assertIn("user.user_permissions.add(perm)", self.source)
        self.assertIn('ADULT_TAG_EDITORS = ("nadja", "thomas")', self.source)
        self.assertIn("for user in editors:", self.source)
        self.assertIn("MISSING_TAG_EDITOR_BASELINE", self.source)
        self.assertNotIn('assign_perm("delete_tag"', self.source)
        self.assertNotIn('assign_perm("delete_document"', self.source)
        self.assertNotIn('user.is_staff = True', self.source)

    def test_unowned_and_foreign_object_delete_blockers(self):
        self.assertIn("Tag.objects.filter(owner__isnull=True)", self.source)
        self.assertIn('"delete_tag" in rights', self.source)
        self.assertIn("user.pk != tag.owner_id", self.source)
        self.assertIn("if blockers:", self.source)
        self.assertIn("TAG_DELETE_UNSAFE", self.source)

    def test_dry_run_first_and_opt_in_commit(self):
        self.assertIn('os.environ.get("BP_USER_RIGHTS_APPLY", "0")', self.source)
        self.assertIn('print("DRY_RUN_NO_CHANGES")', self.source)
        self.assertIn("with transaction.atomic():", self.source)
        self.assertIn("paperless_user_rights_apply | default(false) | bool", self.playbook)
        self.assertIn("BP_USER_RIGHTS_APPLY=0", self.playbook)
        self.assertIn("BP_USER_RIGHTS_APPLY=1", self.playbook)
        self.assertIn("OWN_TAG_DELETE_COMMITTED_AND_VERIFIED", self.playbook)

    def test_other_permissions_only_audited(self):
        self.assertIn("REVIEW_ONLY_MISSING", self.source)
        self.assertIn("documents.add_savedview", self.source)
        self.assertIn("documents.view_customfield", self.source)
        self.assertIn("FUTURE_USERS_REQUIRE_BASELINE_PROVISIONING", self.source)


if __name__ == "__main__":
    unittest.main()
