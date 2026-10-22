"""Static fail-closed checks for shared Tag visibility, without live mutation."""
import ast
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/reconcile_family_shared_tag_visibility.py"
PLAY = ROOT / "ansible/playbooks/manage-paperless-family-shared-tags.yml"
DOCS = ROOT / "docs/PAPERLESS-FAMILY-SHARED-TAGS.md"


class TestFamilyVisibleTags(unittest.TestCase):
    def test_script_compiles_and_has_bounded_request(self):
        code = SCRIPT.read_text()
        ast.parse(code)
        for token in (
            'GROUP = "Familie@bergen.intern"',
            'PARENTS = ("thomas", "nadja")',
            'CHILD = "Kinder@bergen.intern"',
            'MAX_TAGS = 500',
            'MAX_DOCUMENTS = 5000',
            'sys.stdin.read(2049)',
            'mode = "AUDIT"',
            'req["mode"] in ("audit", "apply")',
            '__full_version_str__ == "3.3.0"',
            'THOMAS_PRIVATE_DENIED_TO_NADJA',
            'except Exception:',
            '"UNCLASSIFIED"',
        ):
            self.assertIn(token, code)

    def test_writes_are_limited_to_native_tag_read_grants(self):
        code = SCRIPT.read_text()
        self.assertIn('family.permissions.add(model_permission)', code)
        self.assertIn('assign_perm("view_tag", family, Tag.objects.get(pk=pk))', code)
        self.assertIn('permission=permission, content_type=ct', code)
        self.assertIn('with transaction.atomic():', code)
        self.assertIn('TAG_GROUP_GRANTS_INCOMPLETE', code)
        self.assertIn('DOCUMENT_SECURITY_DRIFT', code)
        self.assertIn('THOMAS_PRIVACY_CHANGED', code)
        self.assertIn('TAG_OWNERS_CHANGED', code)
        self.assertIn('Document.tags.through.objects.values_list', code)
        for forbidden in (
            'assign_perm("view_document"',
            'assign_perm("change_document"',
            'assign_perm("delete_document"',
            'assign_perm("change_tag"',
            'Document.objects.update(',
            'Document.objects.create(',
            '.tags.add(',
            '.tags.remove(',
            'UiSettings.objects.update(',
        ):
            self.assertNotIn(forbidden, code)

    def test_audit_is_default_apply_requires_exact_count_and_backup(self):
        data = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(data), 1)
        play = data[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        variables = play["vars"]
        self.assertIn("default('audit')", variables["bp_family_tag_mode"])
        self.assertIn("default(0)", variables["bp_family_tag_expected_count"])
        tasks = play["tasks"]
        initial = tasks[0]["ansible.builtin.assert"]["that"]
        joined = " ".join(initial)
        self.assertIn("paperless_family_tags_apply_approved", joined)
        self.assertIn("paperless_ai_catalog_verified_backup", joined)
        self.assertIn("bp_family_tag_expected_count > 0", joined)
        task = next(t for t in tasks if t["name"].startswith(
            "Apply only granted tag"
        ))
        self.assertEqual(task["when"], "bp_family_tag_apply")
        self.assertTrue(task["no_log"])
        self.assertIn("'mode':'apply'", task["ansible.builtin.command"]["stdin"])
        self.assertIn("'approved':true", task["ansible.builtin.command"]["stdin"])
        assert_task = next(t for t in tasks if t["name"].startswith(
            "Reject incomplete or errorful private"
        ))
        self.assertTrue(assert_task["no_log"])

    def test_documentation_discloses_future_tag_and_privacy_constraints(self):
        doc = DOCS.read_text()
        for token in (
            "Tag-only", "newly created", "new Tags",
            "Thomas", "Nadja", "children",
            "view_tag", "change_document", "default view groups",
        ):
            self.assertIn(token.lower(), doc.lower())


if __name__ == "__main__":
    unittest.main()
