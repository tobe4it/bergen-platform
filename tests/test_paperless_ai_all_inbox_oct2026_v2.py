"""Strict offline review of the all-owner October Inbox v2 cutover.

No external services, journal writes, production changes or model invocation.
"""
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless"
RUNNER = SRC / "bergen_ai_catalog_runner_v2.py"
POLICY = SRC / "bergen_ai_catalog_policy_v2.py"
READ_AUDIT = SRC / "audit_ai_catalog_all_inbox_oct2026_readonly.py"
UPGRADE = ROOT / "ansible/playbooks/upgrade-paperless-ai-inbox-catalog-all-inbox-oct2026.yml"
AUDIT_PLAY = ROOT / "ansible/playbooks/audit-paperless-ai-all-inbox-oct2026-readonly.yml"
LAUNCH = SRC / "bergen-ai-catalog-run-v2.sh"
SERVICE = SRC / "bergen-ai-catalog-v2.service"


def load_function(file, name, globs):
    tree = ast.parse(file.read_text())
    function = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = dict(globs)
    exec(compile(ast.Module(body=[function], type_ignores=[]),
                 str(file), "exec"), ns)
    return ns[name]


class Probe:
    def __init__(self, added, content="A" * 40, inbox=True,
                 owner=None, versions=False):
        self.added = added
        self.content = content
        self.owner = owner
        self.owner_id = None if owner is None else getattr(owner, "pk", 15)
        self.pk = 5
        self.root_document_id = None
        self.tags = SimpleNamespace(filter=lambda **kw:
            SimpleNamespace(exists=lambda: inbox))
        self.versions = SimpleNamespace(exists=lambda: versions)


class TestAllInboxV2(unittest.TestCase):
    def test_document_added_date_inclusive_not_owner_id(self):
        cutoff = datetime.fromisoformat("2026-10-01T00:00:00+02:00")
        eligible = load_function(RUNNER, "eligible", {"CUTOFF": cutoff})
        before = datetime.fromisoformat("2026-09-30T23:59:59+02:00")
        on = datetime.fromisoformat("2026-10-01T00:00:00+02:00")
        later = datetime.fromisoformat("2026-10-10T12:30:00+02:00")
        self.assertFalse(eligible(Probe(before), None, 0, False))
        self.assertTrue(eligible(Probe(on), None, 10000, False))
        self.assertTrue(eligible(Probe(later), None, 10000, False))
        self.assertTrue(eligible(Probe(on, owner=SimpleNamespace(
            pk=44, is_staff=True, is_superuser=True)), None, 200, False))
        self.assertFalse(eligible(Probe(later, inbox=False), None, 0, False))
        self.assertFalse(eligible(Probe(later, content="short"), None, 0, False))
        self.assertFalse(eligible(Probe(later, versions=True), None, 0, False))

    def test_nullable_owner_snapshot_is_valid(self):
        tree = ast.parse(POLICY.read_text())
        fns = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
               and n.name in ("stable_snapshot", "demand", "PolicyError")]
        globs = {"json": __import__("json")}
        exec(compile(ast.Module(body=fns, type_ignores=[]),
                     str(POLICY), "exec"), globs)
        data = dict(
            id=10, owner_id=None, title="Import", original_filename="file.pdf",
            correspondent_id=None, document_type_id=None, storage_path_id=None,
            created="2026-10-01", added="2026-10-20T12:00:00+00:00",
            modified="2026-10-20T12:00:00+00:00", checksum="checksum",
            content_sha256="hex", tag_ids=[1], inbox=True,
        )
        self.assertIn('"owner_id":null', globs["stable_snapshot"](data))

    def test_versioned_worker_never_downgrades_to_legacy_scope(self):
        src = RUNNER.read_text()
        ast.parse(src)
        self.assertIn('added__gte=CUTOFF', src)
        self.assertIn('doc.added < CUTOFF', src)
        self.assertIn('"2026-10-01T00:00:00+02:00"', src)
        self.assertIn('request.get("protocol") == "catalog-v2"', src)
        self.assertIn('"allowed_group" not in request', src)
        self.assertIn('"min_document_id" not in request', src)
        self.assertNotIn("owner__groups=group", src)
        self.assertNotIn("owner__is_active=True", src)
        self.assertNotIn("doc.owner.groups.filter", src)
        self.assertIn("get_ai_document_classification(doc, doc.owner, None)", src)
        self.assertIn("Note.objects.create(document=current_doc, user=None,", src)
        self.assertIn('db.execute("SELECT 1 FROM catalogue WHERE document_id=?"', src)
        self.assertIn('"REQUIRES_REVIEW"', src)
        self.assertIn('"NO_CHANGE"', src)
        self.assertIn('JOURNAL_BASE = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1")', src)
        self.assertIn('current_doc.tags.filter(is_inbox_tag=True).exists()', src)

    def test_no_write_audit_has_exact_import_date_without_private_output(self):
        a = READ_AUDIT.read_text()
        ast.parse(a)
        self.assertIn('added__gte=CUTOFF', a)
        self.assertIn('tags__is_inbox_tag=True', a)
        self.assertIn("mode=ro", a)
        self.assertIn("PRAGMA query_only=ON", a)
        self.assertIn("OWNERLESS_INBOX", a)
        self.assertIn("PENDING_NOT_JOURNALED", a)
        self.assertNotIn('get_ai_document_classification(', a)
        self.assertNotIn('Note.objects.create(', a)
        p = yaml.safe_load(AUDIT_PLAY.read_text())[0]
        self.assertEqual(p["hosts"], "venombox")
        self.assertTrue(p["become"])
        for t in p["tasks"]:
            self.assertNotIn("ansible.builtin.copy", t)
            self.assertNotIn("ansible.builtin.systemd", t)

    def test_upgrade_is_explicit_and_retains_old_journal(self):
        src = UPGRADE.read_text()
        p = yaml.safe_load(src)[0]
        self.assertEqual(p["hosts"], "venombox")
        self.assertTrue(p["become"])
        for token in ("paperless_ai_catalog_all_inbox_upgrade_approved",
                      "paperless_ai_catalog_all_inbox_date_scope_approved",
                      "paperless_ai_catalog_timer_upgrade_approved",
                      "paperless_ai_catalog_verified_backup",
                      "paperless_ai_catalog_notes_approved",
                      "not ansible_check_mode",
                      "catalog-policy-v2.json", "bergen_ai_catalog_runner_v2.py",
                      "bergen-ai-catalog-run-v2",
                      "state: stopped", "enabled: true"):
            self.assertIn(token, src)
        self.assertNotIn("catalog.sqlite3", src)
        self.assertNotIn("remove:", src)
        self.assertIn('added_since: "{{ bp_v2_date }}"', src)
        self.assertIn("ExecStart=/usr/local/libexec/bergen-ai-catalog-run-v2",
                      SERVICE.read_text())
        self.assertIn("catalog-policy-v2.json", LAUNCH.read_text())


if __name__ == "__main__":
    unittest.main()
