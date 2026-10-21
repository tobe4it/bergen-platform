"""Offline safeguards for Bergen-AI v2 all-owner Inbox from imported cutoff."""
import ast
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
import yaml

ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/"ansible/files/paperless/bergen_ai_catalog_runner.py"
POLICY=ROOT/"ansible/files/paperless/bergen_ai_catalog_policy.py"
UPGRADE=ROOT/"ansible/playbooks/upgrade-paperless-ai-all-inbox-since-20261001.yml"


def module():
    # Runner performs Django imports and calls run() at module bottom; select
    # *only* the isolated eligibility function into an offline namespace.
    syntax=ast.parse(RUNNER.read_text())
    fn=next(n for n in syntax.body if isinstance(n, ast.FunctionDef) and n.name=="eligible")
    pure=ast.Module(body=[fn],type_ignores=[])
    code=compile(ast.fix_missing_locations(pure),str(RUNNER),"exec")
    namespace={"IMPORT_CUTOFF":datetime(2026,10,1,0,0,tzinfo=ZoneInfo("Europe/Berlin"))}
    exec(code,namespace)
    return namespace["eligible"]


def doc(imported, owner=None, *, inbox=True, content="x"*50, root_id=None, revisions=False):
    tags=SimpleNamespace(filter=lambda **kw: SimpleNamespace(exists=lambda: inbox))
    return SimpleNamespace(
      pk=9999, added=imported,owner_id=getattr(owner,"pk",None),owner=owner,
      tags=tags,content=content,root_document_id=root_id,
      versions=SimpleNamespace(exists=lambda:revisions),
    )


class AllInboxTests(unittest.TestCase):
    def test_berlin_midnight_and_ownerless_selection(self):
        check=module()
        berlin=ZoneInfo("Europe/Berlin")
        cutoff=datetime(2026,10,1,0,0,tzinfo=berlin)
        self.assertTrue(check(doc(cutoff),None,10000,False,all_inbox=True))
        self.assertTrue(check(doc(cutoff,SimpleNamespace(pk=4)),None,10000,False,all_inbox=True))
        self.assertFalse(check(doc(cutoff-timedelta(microseconds=1)),None,0,False,all_inbox=True))
        self.assertTrue(check(doc(cutoff.astimezone(timezone.utc)),None,0,False,all_inbox=True))
        self.assertFalse(check(doc(cutoff, inbox=False),None,0,False,all_inbox=True))
        self.assertFalse(check(doc(cutoff, content="tiny"),None,0,False,all_inbox=True))
        self.assertFalse(check(doc(cutoff, root_id=10),None,0,False,all_inbox=True))
        self.assertFalse(check(doc(cutoff, revisions=True),None,0,False,all_inbox=True))

    def test_v1_still_requires_parent_group_and_id_watermark(self):
        check=module()
        d=doc(datetime(2026,10,2,tzinfo=timezone.utc))
        self.assertFalse(check(d,None,0,False))
        user=SimpleNamespace(pk=3,is_active=True,is_staff=False,is_superuser=False,
          groups=SimpleNamespace(filter=lambda **kw:SimpleNamespace(exists=lambda:True)))
        d=doc(datetime(2026,10,2,tzinfo=timezone.utc),owner=user)
        self.assertTrue(check(d,SimpleNamespace(pk=12),0,False))
        self.assertFalse(check(d,SimpleNamespace(pk=12),10000,False))

    def test_ownerless_snapshot_allowed_but_not_ambiguous(self):
        spec=importlib.util.spec_from_file_location("policy_v2",POLICY)
        m=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        d=dict(id=30,owner_id=None,title="x",original_filename="x.pdf",
          correspondent_id=None,document_type_id=None,storage_path_id=None,
          created="c",modified="m",checksum="x",content_sha256="y",
          tag_ids=[1],inbox=True)
        self.assertIn('"owner_id":null',m.stable_snapshot(d))
        with self.assertRaises(m.PolicyError):
            m.stable_snapshot(dict(d, owner_id=-1))

    def test_deployment_requires_separate_upgrade_approval(self):
        play=yaml.safe_load(UPGRADE.read_text())[0]
        self.assertEqual(play["hosts"],"venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        txt=UPGRADE.read_text()
        for expected in ("paperless_ai_catalog_v2_upgrade_approved",
                         "paperless_ai_catalog_v2_history_from_october_approved",
                         "paperless_ai_catalog_verified_backup",
                         "ALL_INBOX_V2_ORIGINAL_TIMER_POLICY_NOT_RECOGNIZED",
                         "ALL_INBOX_V2_SELECTION_PREFLIGHT_FAILED",
                         "ALL_INBOX_V2_SERVICE_BUSY",
                         "state: stopped","start_added_date","catalog-v2",
                         "TIMER=STOPPED_FAIL_CLOSED"):
            self.assertIn(expected,txt)

    def test_regular_pipeline_is_not_group_or_pilot_scoped(self):
        runner = RUNNER.read_text()
        upgrade = UPGRADE.read_text()
        audit = (ROOT / "ansible/files/paperless/audit_ai_catalog_v2_scope_readonly.py").read_text()
        audit_playbook = (ROOT / "ansible/playbooks/audit-paperless-ai-v2-scope-readonly.yml").read_text()
        self.assertIn("tags__is_inbox_tag=True", runner)
        self.assertIn("added__gte=IMPORT_CUTOFF", runner)
        self.assertIn("all_inbox = request[\"protocol\"] == \"catalog-v2\"", runner)
        self.assertIn("paperless_ai_catalog_v2_regular_pipeline_approved", upgrade)
        self.assertNotIn("paperless_ai_catalog_v2_pilot_document_id", upgrade)
        self.assertNotIn("audit_ai_catalog_v2_pilot_success.py", upgrade)
        self.assertIn("ALL_INBOX_ADDED_FROM_OCT1", audit)
        self.assertIn("READY_UNJOURNALIZED", audit)
        self.assertNotIn("Eltern@bergen.intern", audit)
        self.assertNotIn("owner__groups", audit)
        self.assertNotIn("GroupObjectPermission", audit)
        self.assertNotIn("OWNERLESS_PARENT_", audit_playbook)
        self.assertNotIn("Eltern", audit_playbook)
        self.assertIn("all_tag_ids.update(tag.get_ancestors_pks())", runner)

    def test_alternative_cutover_is_blocked(self):
        legacy = (ROOT / "ansible/playbooks/upgrade-paperless-ai-inbox-catalog-all-inbox-oct2026.yml").read_text()
        self.assertIn("DEPRECATED_ALL_INBOX_V2_UPGRADE_USE_GUARDED_REGULAR_PIPELINE", legacy)
        self.assertIn("- false  # DEPRECATED:", legacy)

    def test_runner_keeps_failed_entry_and_system_note(self):
        src=RUNNER.read_text()
        ast.parse(src)
        self.assertIn('added__gte=IMPORT_CUTOFF',src)
        self.assertIn('document_id=?',src)
        self.assertIn('user=None if all_inbox else doc.owner',src)
        self.assertIn('doc.added < IMPORT_CUTOFF',src)
        self.assertIn('REQUIRES_REVIEW',src)
        self.assertIn('classify_v2_no_rag(doc, before_groups)',src)
        self.assertIn('build_prompt_without_rag(doc, AIConfig()',src)
        self.assertIn('direct_document_group_ids(doc)',src)
        self.assertIn('GroupObjectPermission.objects.filter(',src)
        self.assertIn('permission__codename=perm',src)
        self.assertIn('Cast("object_pk", IntegerField())',src)
        self.assertIn('verify_choices_v2(current_doc, current_groups',src)
        self.assertIn('user=None if all_inbox else doc.owner',src)
        self.assertNotIn('demand(False, "GROUP_ACL_CONTEXT_UNVERIFIED")',src)
        self.assertNotIn('get_taxonomy_context(',src.split("def classify_v2_no_rag",1)[1].split("def resolve_choices_v2",1)[0])
        self.assertIn('INBOX_TAG_REMOVAL="NEVER"',src)
        self.assertIn('count = request.get("batch_size", 1)',src)


if __name__=="__main__":
    unittest.main()
