#!/usr/bin/env python3
"""Offline safety contract for per-user UI settings provisioning."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "ansible/files/paperless/enable_personal_settings.py"
PLAYBOOK = ROOT / "ansible/playbooks/prepare-paperless-personal-settings.yml"


class PersonalSettingsPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.script)

    def test_syntax_and_exact_permissions(self):
        compile(self.script, str(SCRIPT), "exec")
        variable = next(
            node for node in self.tree.body
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "RIGHTS" for t in node.targets
            )
        )
        self.assertEqual(
            set(ast.literal_eval(variable.value.args[0])),
            {"view_uisettings", "add_uisettings", "change_uisettings"},
        )

    def test_no_administration_document_or_delete_rights(self):
        self.assertNotIn("delete_uisettings", self.script)
        self.assertNotIn("applicationconfiguration", self.script)
        self.assertNotIn("assign_perm(", self.script)
        self.assertIn("candidate.user_permissions.add(", self.script)
        self.assertIn(".exclude(username__iexact=\"AnonymousUser\")", self.script)
        self.assertIn("is_superuser=False", self.script)

    def test_dry_run_default_and_transactional_commit(self):
        self.assertIn('os.environ.get("BP_UI_SETTINGS_APPLY", "0")', self.script)
        self.assertIn('print("DRY_RUN_NO_CHANGES")', self.script)
        self.assertIn("with transaction.atomic():", self.script)
        self.assertIn("PERSONAL_UI_SETTINGS_COMMITTED_AND_VERIFIED", self.script)
        self.assertIn("BP_UI_SETTINGS_APPLY=0", self.playbook)
        self.assertIn("BP_UI_SETTINGS_APPLY=1", self.playbook)
        self.assertIn("paperless_ui_settings_apply | default(false)", self.playbook)

    def test_future_account_provisioning_not_misrepresented(self):
        self.assertIn("FUTURE_USERS_REQUIRE_BASELINE_PROVISIONING", self.script)


if __name__ == "__main__":
    unittest.main()
