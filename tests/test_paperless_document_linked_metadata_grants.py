"""Static and pure-function regression tests for bounded metadata read grants.

Never import the live Django script (it intentionally executes in shell -c).
Execute only the extracted pure plan_user_grants function with synthetic IDs.
"""
import ast
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/reconcile_document_linked_metadata_view.py"
PLAY = ROOT / "ansible/playbooks/manage-paperless-document-linked-metadata-view.yml"


class LinkedMetadataGrantPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = SCRIPT.read_text()
        cls.tree = ast.parse(cls.code)
        funcs = [x for x in cls.tree.body if isinstance(x, ast.FunctionDef)
                 and x.name == "plan_user_grants"]
        assert len(funcs) == 1
        # Load only pure function into isolated test namespace.
        isolated = ast.Module(body=funcs, type_ignores=[])
        scope = {}
        exec(compile(isolated, "<policy-pure-helper>", "exec"), scope)
        cls.plan = staticmethod(scope["plan_user_grants"])

    def test_existing_visible_items_do_not_gain_duplicate_grants(self):
        self.assertEqual(
            self.plan(2, 80, {1, 2, 3}, {1, 2, 3}), set())

    def test_grant_only_linked_metadata_and_never_unrelated_private_objects(self):
        self.assertEqual(
            self.plan(2, 80, {1, 3}, {1, 2, 5}),
            {(2, 80, "3")},
        )
        self.assertNotIn((2, 80, "9"), self.plan(
            2, 80, {1, 3}, {1, 2, 9}))

    def test_different_users_receive_different_metadata_views(self):
        first = self.plan(1, 80, {1, 2, 9}, {1})
        second = self.plan(2, 80, {1}, set())
        self.assertEqual(first, {(1, 80, "2"), (1, 80, "9")})
        self.assertEqual(second, {(2, 80, "1")})

    def test_document_type_and_correspondent_perms_are_distinct(self):
        self.assertEqual(
            self.plan(3, 80, {1}, set()), {(3, 80, "1")})
        self.assertEqual(
            self.plan(3, 90, {1}, set()), {(3, 90, "1")})

    def test_django_shell_always_executes_entrypoint(self):
        last = self.tree.body[-1]
        self.assertIsInstance(last, ast.Expr)
        self.assertIsInstance(last.value, ast.Call)
        self.assertIsInstance(last.value.func, ast.Name)
        self.assertEqual(last.value.func.id, "main")

    def test_database_mutations_are_limited_and_transactional(self):
        code = self.code
        for permitted in (
            'assign_perm(codename, User.objects.get(pk=user_id), obj)',
            '"view_documenttype"',
            '"view_correspondent"',
            'with transaction.atomic():',
            'metadata_user_acl() == existing_meta_acl | planned',
            'safe_snapshot() == before',
            '"METADATA_PERMISSION_DELTA_UNEXPECTED"',
            '"THOMAS_PRIVATE_SCOPE_NOT_PROVEN"',
            '"CHILD_PARENT_DOC_VISIBLE"',
            '"CHILD_THOMAS_PRIVATE_VISIBLE"',
            'FUTURE_RECONCILIATION="NOT_ENABLED"',
            'REVOCATION_POLICY="NOT_ENABLED"',
        ):
            self.assertIn(permitted, code)
        for forbidden in (
            'assign_perm("view_document"',
            'assign_perm("change_document"',
            'assign_perm("delete_document"',
            'assign_perm("change_documenttype"',
            'assign_perm("change_correspondent"',
            'remove_perm(',
            'Document.objects.update(',
            'Document.objects.create(',
            '.tags.add(',
            '.tags.remove(',
            '.permissions.add(',
        ):
            self.assertNotIn(forbidden, code)

    def test_default_no_write_and_sensitive_tasks_hidden(self):
        tasks = yaml.safe_load(PLAY.read_text())[0]["tasks"]
        src = PLAY.read_text()
        for fragment in (
            "default('audit')",
            "paperless_linked_metadata_apply_approved",
            "paperless_ai_catalog_verified_backup",
            "paperless_linked_metadata_expected_docs",
            "paperless_linked_metadata_expected_type_gaps",
            "paperless_linked_metadata_expected_correspondent_gaps",
            "'unprivileged: 1'",
            "'125'",  # not present, wrong host should remain excluded
        )[:-1]:
            self.assertIn(fragment, src)
        self.assertNotIn("pct, exec, '125'", src)
        self.assertNotIn("ansible.builtin.template", src)
        self.assertNotIn("ansible.builtin.systemd_service", src)
        self.assertEqual(len([
            task for task in tasks
            if task.get("ansible.builtin.command") and
            "manage.py" in str(task["ansible.builtin.command"])
        ]), 2)
        apply_task = next(task for task in tasks if
                          task["name"].startswith("Apply only direct metadata"))
        self.assertEqual(apply_task["when"], "bp_linked_meta_apply")
        self.assertTrue(apply_task["no_log"])


if __name__ == "__main__":
    unittest.main()
