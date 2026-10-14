"""Offline tests for read-only IMPORTED + DELETED_BY_USER reconciliation."""
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(SOURCE))
import deleted_by_user_decision_journal as schema


def module(filename, name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


match = module("match_paperless_import_lifecycle.py", "lifecycle_match")
export = module("export_import_lifecycle.py", "lifecycle_export")
DIGEST = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"
RECEIVER = "Privat/thomas/Gebuehren 2--nas-" + DIGEST + ".pdf"
NORMAL_SHA = "a" * 64
NORMAL_RECEIVER = "Familie/scan--nas-" + NORMAL_SHA + ".pdf"
NORMAL_SENDER = hashlib.sha256(b"Familie\0scan.pdf").hexdigest() + ".json"
NORMAL_NAS = {
    "sender_receipt": NORMAL_SENDER, "scope": "Familie",
    "source": "scan.pdf", "receiver_source": NORMAL_RECEIVER,
    "sha256": NORMAL_SHA,
}
NORMAL_IMPORTED = {
    "schema_version": 1, "status": "IMPORTED",
    "bridge_receipt": "c" * 24 + ".json",
    "receiver_source": NORMAL_RECEIVER, "sha256": NORMAL_SHA,
    "document_id": 23,
}
DELETED_IMPORTED = {
    "schema_version": 1, "status": "DELETED_BY_USER",
    "bridge_receipt": schema.BRIDGE, "sender_receipt": schema.SENDER,
    "receiver_source": RECEIVER, "sha256": DIGEST, "document_id": 26,
}
NAS_DELETED = {
    "schema_version": 1, "sender_receipt": schema.SENDER,
    "scope": schema.SCOPE, "source": schema.SOURCE,
    "receiver_source": RECEIVER, "sha256": DIGEST,
    "sender_status": "SENT", "nas_original_absent": True,
}
PAPERLESS_DELETED = {
    "schema_version": 1, "bridge_receipt": schema.BRIDGE,
    "document_id": 26, "receiver_source": RECEIVER,
    "sha256": DIGEST, "proposed_status": "DELETED_IN_PAPERLESS",
    "live_document_absent": True, "original_filename_absent": True,
}
JOURNAL = schema.build(NAS_DELETED, PAPERLESS_DELETED)


def lines(*records):
    return "\n".join(json.dumps(x, sort_keys=True) for x in records)


def request():
    return {
        "journal": lines(JOURNAL) + "\nNO_FILES_CHANGED",
        "deleted": lines(PAPERLESS_DELETED),
        "nas_deleted": lines(NAS_DELETED) + "\nNO_FILES_CHANGED",
    }


def report(nas=None, paperless=None, journal=None, nas_deleted=None):
    buf = io.StringIO()
    with redirect_stdout(buf):
        match.compare(
            lines(*(nas if nas is not None else [NORMAL_NAS])),
            lines(*(paperless if paperless is not None else [NORMAL_IMPORTED, DELETED_IMPORTED])),
            journal if journal is not None else request()["journal"],
            nas_deleted if nas_deleted is not None else request()["nas_deleted"])
    return buf.getvalue()


class ImportLifecycleTests(unittest.TestCase):
    def test_expected_fixed_record_matches_published_sha(self):
        self.assertEqual(JOURNAL["event_id"], export.EVENT)
        self.assertEqual(hashlib.sha256(schema.canonical(JOURNAL)).hexdigest(),
                         export.JOURNAL_SHA)

    def test_reconciles_import_and_one_deleted_document(self):
        out = report()
        self.assertIn("IMPORT_LIFECYCLE_RECONCILED", out)
        self.assertIn("DELETED_BY_USER_CONFIRMED 26", out)
        self.assertIn("PAPERLESS_LIVE_IMPORTED 1", out)
        self.assertIn("NAS_SENT_VERIFIED 1", out)
        self.assertIn("ARCHIVE_NOT_AUTHORIZED", out)
        self.assertIn("NO_FILES_CHANGED", out)
        self.assertNotIn("ARCHIVE_MATCH_READY", out)

    def test_missing_deletion_proof_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "REQUIRE_EXACTLY_ONE"):
            report(paperless=[NORMAL_IMPORTED])

    def test_wrong_journal_hash_blocks(self):
        altered = dict(JOURNAL, decision_reason="other")
        with self.assertRaisesRegex(RuntimeError, "INVALID_PUBLISHED_USER_DELETION"):
            report(journal=lines(altered) + "\nNO_FILES_CHANGED")

    def test_missing_journal_marker_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_JOURNAL_READ_ONLY_PROOF"):
            report(journal=lines(JOURNAL))

    def test_wrong_nas_deleted_proof_blocks(self):
        altered = dict(NAS_DELETED, nas_original_absent=False)
        with self.assertRaisesRegex(RuntimeError, "DELETED_NAS_EVIDENCE_MISMATCH"):
            report(nas_deleted=lines(altered) + "\nNO_FILES_CHANGED")

    def test_deleted_record_cannot_match_live_nas(self):
        conflict = dict(NORMAL_NAS, receiver_source=RECEIVER)
        with self.assertRaisesRegex(RuntimeError, "INVALID_OR_DUPLICATE_NAS_SOURCE"):
            report(nas=[conflict])

    def test_duplicate_live_receipt_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_OR_DUPLICATE_LIVE_IMPORT"):
            report(paperless=[NORMAL_IMPORTED, NORMAL_IMPORTED, DELETED_IMPORTED])

    def test_unknown_deletion_cannot_be_whitelisted(self):
        extra = dict(NORMAL_IMPORTED, status="DELETED_BY_USER",
                     sender_receipt=NORMAL_SENDER)
        with self.assertRaisesRegex(RuntimeError, "DELETED_IMPORT_NOT_JOURNALED"):
            report(paperless=[extra, DELETED_IMPORTED])

    def test_other_missing_live_import_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "MISSING_OR_MISMATCHED_LIVE_IMPORT"):
            report(paperless=[DELETED_IMPORTED])

    def test_unmatched_import_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "UNMATCHED_OR_MISSING_LIFECYCLE_RECEIPT"):
            report(nas=[])

    def test_changed_sha_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "MISSING_OR_MISMATCHED_LIVE_IMPORT"):
            report(paperless=[dict(NORMAL_IMPORTED, sha256="b" * 64), DELETED_IMPORTED])

    def test_exporter_accepts_only_pinned_journal(self):
        self.assertEqual(export.validate_proofs(request()), JOURNAL)
        changed = request()
        changed["journal"] = lines(dict(JOURNAL, event_id="0" * 64)) + "\nNO_FILES_CHANGED"
        with self.assertRaisesRegex(RuntimeError, "UNAPPROVED_DELETED_BY_USER_PROOF"):
            export.validate_proofs(changed)

    def test_exporter_rechecks_all_imports_and_deleted_absence(self):
        normal = Path("cccccccccccccccccccccccc.json")
        deleted = Path(schema.BRIDGE)
        def load(path):
            if path == normal:
                return ({
                    "status": "IMPORTED", "source": NORMAL_RECEIVER,
                    "sha256": NORMAL_SHA, "document_id": 23,
                }, "scan--bp-cccccccccccccccccccccccc.pdf", ("admin", "Familie@bergen.intern"))
            return ({
                "status": "IMPORTED", "source": RECEIVER,
                "sha256": DIGEST, "document_id": 26,
            }, "Gebuehren 2--bp-1ebb2c1d26d7b1494d28d9cd.pdf", ("thomas", "")
            )
        def verify(name, sha, owner, group):
            return None if owner == "thomas" else 23
        mod = SimpleNamespace(
            RECEIPTS=SimpleNamespace(glob=lambda pattern: [normal, deleted]),
            load_receipt=load, verify=Mock(side_effect=verify),
        )
        with patch.object(export.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout='BP_DELETION_LOOKUP:{"id_exists":false,"filename_exists":false}\n')):
            records = export.collect(request(), mod)
        self.assertEqual(len(records), 2)
        self.assertEqual([x["status"] for x in records], ["IMPORTED", "DELETED_BY_USER"])
        self.assertEqual(mod.verify.call_count, 2)

    def test_exporter_rejects_document_reappearing(self):
        receipt = Path(schema.BRIDGE)
        mod = SimpleNamespace(
            RECEIPTS=SimpleNamespace(glob=lambda pattern: [receipt]),
            load_receipt=lambda path: ({
                "status": "IMPORTED", "source": RECEIVER,
                "sha256": DIGEST, "document_id": 26,
            }, "original.pdf", ("thomas", "")),
            verify=lambda *args: 26,
        )
        with self.assertRaisesRegex(RuntimeError, "DELETED_DOCUMENT_STILL_LIVE"):
            export.collect(request(), mod)

    def test_exporter_rejects_wrong_live_document(self):
        receipt = Path(schema.BRIDGE)
        mod = SimpleNamespace(
            RECEIPTS=SimpleNamespace(glob=lambda pattern: [receipt]),
            load_receipt=lambda path: ({
                "status": "IMPORTED", "source": RECEIVER,
                "sha256": DIGEST, "document_id": 26,
            }, "original.pdf", ("thomas", "")),
            verify=lambda *args: None,
        )
        with patch.object(export.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout='BP_DELETION_LOOKUP:{"id_exists":true,"filename_exists":false}\n')):
            with self.assertRaisesRegex(RuntimeError, "DELETED_DOCUMENT_OR_FILENAME_PRESENT"):
                export.collect(request(), mod)

    def test_no_write_primitives_in_new_readers(self):
        for filename in (
                "export_verified_user_deletion_journal.py",
                "export_import_lifecycle.py",
                "match_paperless_import_lifecycle.py"):
            src = (SOURCE / filename).read_text()
            for forbidden in ("os.unlink(", "os.replace(", "os.mkdir(",
                              "os.chmod(", "os.chown(", ".write_bytes(",
                              ".write_text(", "publish_once(", "shutil.move("):
                self.assertNotIn(forbidden, src)

    def test_new_audit_is_read_only_and_keeps_archive_audit_unchanged(self):
        play = (ROOT / "ansible/playbooks/audit-paperless-import-lifecycle.yml").read_text()
        self.assertIn("changed_when: false", play)
        self.assertIn("export_verified_user_deletion_journal.py", play)
        self.assertIn("export_import_lifecycle.py", play)
        self.assertIn("export_deleted_import_candidate.py", play)
        self.assertIn("export_deleted_by_user_nas_evidence.py", play)
        self.assertIn("audit_synology_archive_candidates.py", play)
        self.assertIn("match_paperless_import_lifecycle.py", play)
        self.assertNotIn("publish_deleted_by_user_journal.py", play)
        self.assertNotIn("ARCHIVE_MATCH_READY' in", play)
        archive = (ROOT / "ansible/playbooks/audit-paperless-archive-imports.yml").read_text()
        self.assertIn("export_imported_scans.py", archive)
        self.assertNotIn("export_import_lifecycle.py", archive)


if __name__ == "__main__":
    unittest.main()
