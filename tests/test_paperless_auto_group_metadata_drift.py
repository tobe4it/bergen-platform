"""Automatic group-only metadata reconciliation remains SHA- and inode-bound.

No real NAS/Paperless access, no manual archival and no release gates.
"""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "ansible/files/paperless"
SENDER = CODE / "synology_scan_sync.py"
AUDIT = CODE / "audit_synology_completed_archive_moves.py"
WORKER = CODE / "synology_same_volume_archive_move.py"
AUTO = ROOT / "ansible/playbooks/archive-next-verified-paperless-group-v1.yml"


def sender_module():
    fake = types.ModuleType("synology_config")
    fake.SETTINGS = {
        "sources": (), "root": Path("/root"), "parent": Path("/root/sender"),
        "state": Path("/root/sender/paperless-sync"),
        "gate": Path("/root/sender/synology-sync.enabled"),
        "identity": Path("/tmp/unused-key"),
        "destination": "dummy@not-used.invalid", "quiet": 60, "max_size": 1024 * 1024,
        "max_files": 10, "sync_user": "paperless-sync",
    }
    spec = importlib.util.spec_from_file_location(
        "paperless_metadata_sender_under_test", SENDER)
    mod = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"synology_config": fake}):
        spec.loader.exec_module(mod)
    return mod


spec = importlib.util.spec_from_file_location("paperless_metadata_audit", AUDIT)
auditor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditor)
sender = sender_module()


class GroupSenderMetadataTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.pdf = Path(t.name) / "scan.pdf"
        self.content = b"%PDF-1.4\nstable metadata drift\n%%EOF\n"
        self.pdf.write_bytes(self.content)
        self.saved_sig = sender.signature(self.pdf.stat())
        self.record = {
            "status": "SENT",
            "signature": self.saved_sig,
            "sha256": hashlib.sha256(self.content).hexdigest(),
        }

    def test_same_inode_and_same_sha_with_mtime_change_is_tracked(self):
        os.utime(self.pdf, ns=(self.saved_sig[3] + 2_000_000_000,
                               self.saved_sig[3] + 2_000_000_000))
        now = sender.signature(self.pdf.stat())
        self.assertEqual(now[:3], self.saved_sig[:3])
        self.assertNotEqual(now, self.saved_sig)
        self.assertTrue(sender.verified_metadata_only_sender_drift(
            self.pdf, self.record, now))

    def test_same_inode_modified_pdf_bytes_must_fail(self):
        self.pdf.write_bytes(self.content.replace(b"stable", b"STABLE"))
        self.assertFalse(sender.verified_metadata_only_sender_drift(
            self.pdf, self.record, sender.signature(self.pdf.stat())))

    def test_new_inode_cannot_masquerade_as_metadata_drift(self):
        self.pdf.rename(self.pdf.with_suffix(".prior"))
        self.pdf.write_bytes(self.content)
        self.assertNotEqual(sender.signature(self.pdf.stat())[1], self.saved_sig[1])
        self.assertFalse(sender.verified_metadata_only_sender_drift(
            self.pdf, self.record, sender.signature(self.pdf.stat())))

    def test_invalid_or_unconfirmed_receipt_not_reconciled(self):
        now = sender.signature(self.pdf.stat())
        self.assertFalse(sender.verified_metadata_only_sender_drift(
            self.pdf, dict(self.record, status="PREPARED"), now))
        self.assertFalse(sender.verified_metadata_only_sender_drift(
            self.pdf, dict(self.record, sha256="x" * 64), now))
        self.assertFalse(sender.verified_metadata_only_sender_drift(
            self.pdf, dict(self.record, signature=[1]), now))

    def test_sender_does_not_rewrite_historical_sent(self):
        code = SENDER.read_text()
        self.assertIn("verified_metadata_only_sender_drift", code)
        self.assertIn('print("TRACKED_METADATA_DRIFT", scope)', code)
        self.assertIn("scope in (\"Familie\", \"Eltern\")", code)
        self.assertNotIn("write_receipt(receipt_file, old)", code)

    def test_automation_still_requires_full_lifecycle_pre_and_post(self):
        source = AUTO.read_text()
        self.assertIn("list-paperless-v1-archive-candidates.yml", source)
        self.assertIn("commit-paperless-one-group-v1-archive.yml", source)
        self.assertNotIn("paperless_archive_purge", source)
        self.assertNotIn("paperless_private_archive_commit", source)


class DriftJournalContractTests(unittest.TestCase):
    def base(self):
        name = "f" * 64
        signature = [101, 202, 33, 44, 55]
        source = "scan.pdf"
        core = {
            "schema_version": 1,
            "archive_type": "same_subvolume_rename",
            "scope": "Familie", "source": source,
            "sender_receipt": name + ".json",
            "bridge_receipt": "a" * 24 + ".json",
            "document_id": 10, "sha256": "b" * 64,
            "signature": signature, "archive_site": "paperless-scan",
            "archive_scope_dir": "/protected/Familie",
            "archive_month": "2026-10",
            "archive_name": name + ".pdf",
        }
        return name, core

    def verify(self, core):
        name = core["sender_receipt"][:-5]
        import datetime
        prepared = dict(core, stage="ARCHIVE_PREPARED")
        archived = dict(core, stage="ARCHIVED",
                        archived_at=datetime.datetime.now(
                            datetime.timezone.utc).isoformat())
        return auditor.inspect_events(
            [name + ".prepared.json", name + ".archived.json"],
            lambda path: prepared if ".prepared." in path else archived)

    def test_valid_group_dual_signature_is_auditable(self):
        _, event = self.base()
        event["sender_signature"] = [101, 202, 33, 30, 31]
        self.assertEqual(len(self.verify(event)), 1)

    def test_private_scope_cannot_reconcile_sender_signature(self):
        _, event = self.base()
        event["scope"] = "Privat/thomas"
        event["sender_signature"] = [101, 202, 33, 30, 31]
        with self.assertRaisesRegex(RuntimeError, "INVALID_ARCHIVE_METADATA_RECONCILIATION"):
            self.verify(event)

    def test_different_inode_size_or_equal_signatures_rejected(self):
        _, event = self.base()
        for sig in ([101, 204, 33, 30, 31],
                    [101, 202, 34, 30, 31],
                    [101, 202, 33, 44, 55]):
            with self.subTest(sig=sig):
                with self.assertRaisesRegex(RuntimeError, "INVALID_ARCHIVE_METADATA_RECONCILIATION"):
                    self.verify(dict(event, sender_signature=sig))

    def test_unknown_journal_schema_and_missing_pair_rejected(self):
        key, event = self.base()
        with self.assertRaisesRegex(RuntimeError, "CONFLICTING_ARCHIVE_JOURNAL"):
            self.verify(dict(event, extra_field="not-reviewed"))
        with self.assertRaisesRegex(RuntimeError, "INCOMPLETE_ARCHIVE_JOURNAL"):
            auditor.inspect_events(
                [key + ".prepared.json"],
                lambda _: dict(event, stage="ARCHIVE_PREPARED"))


if __name__ == "__main__":
    unittest.main()
