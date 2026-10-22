"""Fail-closed static scope tests for document-derived taxonomy audit."""
import ast
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "ansible/files/paperless/audit_visible_document_taxonomy_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-visible-document-taxonomy.yml"


class VisibleDocumentTaxonomyAuditContracts(unittest.TestCase):
    def test_django_shell_c_exec_invokes_main_unconditionally(self):
        # Django shell -c executes the supplied code in its management command
        # namespace, not as a __main__ Python file. A guarded entrypoint does
        # not run and cannot emit the required bounded audit frame.
        module = ast.parse(AUDIT.read_text())
        self.assertIsInstance(module.body[-1], ast.Expr)
        call = module.body[-1].value
        self.assertIsInstance(call, ast.Call)
        self.assertIsInstance(call.func, ast.Name)
        self.assertEqual(call.func.id, "main")
        self.assertEqual(call.args, [])
        self.assertEqual(call.keywords, [])

    def test_script_read_only_and_version_pinned(self):
        src = AUDIT.read_text()
        ast.parse(src)
        for token in (
            '__full_version_str__ == "3.3.0"',
            '"document_type_id", "correspondent_id"',
            'permitted_document_ids(user)',
            'permitted_object_ids(',
            '"view_documenttype"',
            '"view_correspondent"',
            "parent_doc_pks & visible_docs",
            "THOMAS_PRIVATE_BOUNDARY_NOT_PROVEN",
            "CHILD_SEES_ELTERN_DOCUMENT",
            'TYPE_VIEW_GAPS',
            'CORRESPONDENT_VIEW_GAPS',
            'THOMAS_PRIVATE_DENIED_TO_NADJA',
            'DOCUMENT_ACLS_CHANGED="NO"',
            'METADATA_ACLS_CHANGED="NO"',
        ):
            self.assertIn(token, src)
        for forbidden in (
            'assign_perm(', 'remove_perm(', '.permissions.add(',
            '.permissions.remove(', '.objects.update(',
            '.objects.create(', '.save(',
        ):
            self.assertNotIn(forbidden, src)

    def test_playbook_only_audits_ct126(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(plays), 1)
        play = plays[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        src = PLAY.read_text()
        for token in (
            "'hostname: bergen-paperless'",
            "'unprivileged: 1'",
            "paperless_visible_taxonomy_apply_approved",
            "bp_visible_taxonomy_raw",
            "CHILD_SEES_ELTERN_DOCUMENTS",
            "DOCUMENT_ACLS_CHANGED=NO",
            "METADATA_ACLS_CHANGED=NO",
        ):
            self.assertIn(token, src)
        for task in play["tasks"]:
            self.assertNotIn("ansible.builtin.template", task)
            self.assertNotIn("ansible.builtin.systemd_service", task)
            self.assertNotIn("ansible.builtin.file", task)
        self.assertTrue(all(
            task.get("no_log", False)
            for task in play["tasks"] if "ansible.builtin.command" in task
            and "bp_visible_taxonomy_raw" in str(task)
        ))


if __name__ == "__main__":
    unittest.main()
