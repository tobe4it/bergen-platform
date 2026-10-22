"""Offline policy regressions for view-only metadata auto-reconciliation.

Never import the Django script itself: it intentionally runs main() inside
manage.py shell -c. Only ast-extracted pure delta() receives synthetic sets.
"""
import ast
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "ansible/files/paperless/reconcile_metadata_with_provenance.py"
RUNNER = ROOT / "ansible/files/paperless/bergen_metadata_auto_runner.py"
PLAY = ROOT / "ansible/playbooks/manage-paperless-metadata-provenance.yml"
ACTIVATE = ROOT / "ansible/playbooks/activate-paperless-metadata-timer.yml"
SERVICE = ROOT / "ansible/files/paperless/bergen-paperless-metadata.service"
TIMER = ROOT / "ansible/files/paperless/bergen-paperless-metadata.timer"


class ProvenanceMetadataReconciliationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = POLICY.read_text()
        cls.script = ast.parse(cls.code)
        cls.runner = RUNNER.read_text()
        ast.parse(cls.runner)
        funcs = [fn for fn in cls.script.body
                 if isinstance(fn, ast.FunctionDef) and fn.name == "delta"]
        assert len(funcs) == 1
        scope = {}
        exec(compile(ast.Module(body=funcs, type_ignores=[]),
                     "<pure-provenance-policy>", "exec"), scope)
        cls.delta = staticmethod(scope["delta"])

    def test_preexisting_grants_are_never_adopted(self):
        manual_tag = ("group", 14, 80, "4")
        manual_type = ("user", 3, 90, "2")
        required = {manual_tag, manual_type}
        add, revoke = self.delta(required, required, set())
        self.assertEqual(add, set())
        self.assertEqual(revoke, set())

    def test_only_new_missing_user_rights_are_added(self):
        old = {("user", 2, 90, "1"), ("group", 14, 80, "4")}
        new = ("user", 3, 91, "9")
        add, revoke = self.delta(old | {new}, old, set())
        self.assertEqual(add, {new})
        self.assertEqual(revoke, set())

    def test_revocation_never_touches_historical_manual_permissions(self):
        manual = ("user", 3, 90, "9")
        managed = ("user", 2, 90, "7")
        add, revoke = self.delta(set(), {manual, managed}, {managed})
        self.assertEqual(add, set())
        self.assertEqual(revoke, {managed})
        self.assertNotIn(manual, revoke)

    def test_lost_managed_grant_is_recreated_without_duplicate_provenance(self):
        grant = ("user", 3, 91, "9")
        add, revoke = self.delta({grant}, set(), {grant})
        self.assertEqual(add, {grant})
        self.assertEqual(revoke, set())
        self.assertIn("not in managed:", self.code)

    def test_privacy_boundary_and_transactional_postchecks(self):
        for token in (
            'permitted_document_ids(',
            'permitted_object_ids(',
            'CHILD_SEES_ELTERN_DOCUMENT',
            'CHILD_SEES_THOMAS_PRIVATE_DOCUMENT',
            'THOMAS_PRIVATE_NOT_PROVEN',
            'with transaction.atomic():',
            'SET TRANSACTION ISOLATION LEVEL SERIALIZABLE',
            'pg_advisory_xact_lock',
            'DOCUMENT_PRIVACY_POSTCHECK_FAILED',
            'PROTECTED_DATA_CHANGED',
            'VIEW_GRANT_POSTCHECK_FAILED',
            'LEDGER_POSTCHECK_FAILED',
            'EXPECTED_COUNTERS_DRIFT',
            'DATABASE_SCHEMA_UNREVIEWED',
            'LEDGER_OWNER_UNVERIFIED',
            'CREATE TABLE',
            'COMMENT ON TABLE',
        ):
            self.assertIn(token, self.code)

    def test_only_allowed_native_view_permission_writes(self):
        for token in (
            '"view_tag"', '"view_documenttype"', '"view_correspondent"',
            'GroupObjectPermission.objects.create(',
            'UserObjectPermission.objects.create(',
            'GroupObjectPermission.objects.filter(',
            'UserObjectPermission.objects.filter(',
            '"INSERT INTO " + LEDGER',
            '"DELETE FROM " + LEDGER',
        ):
            self.assertIn(token, self.code)
        for forbidden in (
            'Document.objects.create(', 'Document.objects.update(',
            '.tags.add(', '.tags.remove(',
            'User.user_permissions.add(', 'Group.permissions.add(',
            'assign_perm(', 'remove_perm(',
            'set_permissions',
            'change_documenttype', 'change_correspondent',
        ):
            self.assertNotIn(forbidden, self.code)

    def test_script_runs_in_django_shell_c_and_is_default_no_write(self):
        last = self.script.body[-1]
        self.assertIsInstance(last, ast.Expr)
        self.assertIsInstance(last.value, ast.Call)
        self.assertEqual(last.value.func.id, "main")
        p = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(p["hosts"], "venombox")
        self.assertIn("default('audit')", PLAY.read_text())
        tasks = p["tasks"]
        apply_task = next(x for x in tasks if
                          x["name"].startswith("Apply only reviewed"))
        self.assertEqual(apply_task["when"], "bp_tax_apply")
        self.assertTrue(apply_task["no_log"])
        for t in tasks:
            self.assertNotIn("ansible.builtin.systemd_service", t)
            self.assertNotIn("ansible.builtin.copy", t)

    def test_production_write_requires_backup_ledger_and_exact_count_pin(self):
        play = PLAY.read_text()
        for token in (
            'paperless_taxonomy_apply_approved',
            'paperless_taxonomy_database_ledger_approved',
            'paperless_ai_catalog_verified_backup',
            'vzdump-lxc-126-*.tar.zst',
            "bp_tax_audit.DOCUMENTS | int == bp_tax_expected.documents | int",
            "bp_tax_audit.TAG_GAPS | int == bp_tax_expected.tag_gaps | int",
            "bp_tax_audit.MANAGED_REVOCATIONS | int == bp_tax_expected.managed_revocations | int",
            'bp_tax_apply_frames | length == 1',
        ):
            self.assertIn(token, play)

    def test_timer_never_starts_without_separate_activation_approval(self):
        activate = yaml.safe_load(ACTIVATE.read_text())[0]
        self.assertEqual(activate["hosts"], "venombox")
        source = ACTIVATE.read_text()
        for term in (
            'paperless_metadata_timer_activate',
            'paperless_metadata_timer_approved',
            'paperless_metadata_provenance_bootstrap_verified',
            "LEDGER == 'VALID'",
            'PAPERLESS_METADATA_TIMER_UPGRADE_REQUIRES_SEPARATE_APPROVAL',
            'AUTO_ADD_LIMIT=25_PER_RUN',
            'AUTO_REVOKE_LIMIT=25_PER_RUN',
        ):
            self.assertIn(term, source)
        self.assertIn('OnCalendar=hourly', TIMER.read_text())
        self.assertIn('RandomizedDelaySec=10m', TIMER.read_text())
        self.assertIn('Type=oneshot', SERVICE.read_text())

    def test_runner_checks_sha_nfs_privacy_and_bounded_changes(self):
        for token in (
            'POLICY_FINGERPRINT_DRIFT',
            'BACKUP_NOT_RECENT',
            'LEDGER_BOOTSTRAP_REQUIRED',
            'AUTOMATIC_CHANGE_BUDGET_EXCEEDED',
            'MAX_ADDS = 25',
            'MAX_REVOKES = 25',
            'CHILD_SEES_THOMAS_PRIVATE_DOCUMENTS',
            'DOCUMENT_ACLS_CHANGED',
            'APPLY_POSTCHECK_REFUSED',
        ):
            self.assertIn(token, self.runner)
        for forbidden in (
            'shell=True', 'requests.', 'httpx.', 'openai.',
            'send_email', 'Authorization:', 'password',
        ):
            self.assertNotIn(forbidden, self.runner)


if __name__ == "__main__":
    unittest.main()
