"""Offline tests for read-only import lifecycle with both pinned user deletions."""
import hashlib
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(SOURCE))


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


export = load("export_import_lifecycle_15_26.py", "dual_lifecycle_export")
match = load("match_paperless_import_lifecycle_15_26.py", "dual_lifecycle_match")
schema15 = load("deleted_by_user_15_decision_journal.py", "dual_schema_15")
schema26 = load("deleted_by_user_decision_journal.py", "dual_schema_26")
SHA = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"
NORMAL_SHA = "a" * 64
NORMAL_RECEIVER = "Familie/scan--nas-" + NORMAL_SHA + ".pdf"
NORMAL_SENDER = hashlib.sha256(b"Familie\0scan.pdf").hexdigest() + ".json"
NORMAL_NAS = {
    "sender_receipt": NORMAL_SENDER, "scope": "Familie",
    "source": "scan.pdf", "receiver_source": NORMAL_RECEIVER,
    "sha256": NORMAL_SHA,
}
NORMAL_IMPORT = {
    "schema_version": 1, "status": "IMPORTED",
    "bridge_receipt": "c" * 24 + ".json",
    "receiver_source": NORMAL_RECEIVER, "sha256": NORMAL_SHA,
    "document_id": 23,
}


def evidence(docid):
    schema = {15: schema15, 26: schema26}[docid]
    receiver = "Privat/thomas/" + schema.SOURCE[:-4] + "--nas-" + SHA + ".pdf"
    nas = {
        "schema_version": 1, "sender_receipt": schema.SENDER,
        "scope": schema.SCOPE, "source": schema.SOURCE,
        "receiver_source": receiver, "sha256": SHA,
        "sender_status": "SENT", "nas_original_absent": True,
    }
    paperless = {
        "schema_version": 1, "bridge_receipt": schema.BRIDGE,
        "document_id": docid, "receiver_source": receiver, "sha256": SHA,
        "proposed_status": "DELETED_IN_PAPERLESS",
        "live_document_absent": True, "original_filename_absent": True,
    }
    return nas, paperless, schema.build(nas, paperless)


NAS15, PAPERLESS15, JOURNAL15 = evidence(15)
NAS26, PAPERLESS26, JOURNAL26 = evidence(26)


def line(value):
    return json.dumps(value, sort_keys=True)


def request():
    return {
        "journal": line(JOURNAL15) + "\n" + line(JOURNAL26) + "\nNO_FILES_CHANGED",
        "deleted_15": line(PAPERLESS15), "deleted_26": line(PAPERLESS26),
        "nas_deleted_15": line(NAS15) + "\nNO_FILES_CHANGED",
        "nas_deleted_26": line(NAS26) + "\nNO_FILES_CHANGED",
    }


def deleted_import(docid):
    schema = {15: schema15, 26: schema26}[docid]
    return {
        "schema_version": 1, "status": "DELETED_BY_USER",
        "bridge_receipt": schema.BRIDGE, "sender_receipt": schema.SENDER,
        "receiver_source": "Privat/thomas/" + schema.SOURCE[:-4] + "--nas-" + SHA + ".pdf",
        "sha256": SHA, "document_id": docid,
    }


def report(nas=None, imported=None, data=None):
    proofs = request() if data is None else data
    out = io.StringIO()
    with redirect_stdout(out):
        match.compare(
            "\n".join(map(line, [NORMAL_NAS] if nas is None else nas)),
            "\n".join(map(line, [NORMAL_IMPORT, deleted_import(15), deleted_import(26)]
                          if imported is None else imported)),
            proofs["journal"], proofs["nas_deleted_15"], proofs["nas_deleted_26"])
    return out.getvalue()


class DualLifecycleTests(unittest.TestCase):
    def test_two_distinct_journal_events_with_identical_content_digest(self):
        self.assertNotEqual(JOURNAL15["event_id"], JOURNAL26["event_id"])
        self.assertEqual(JOURNAL15["sha256"], JOURNAL26["sha256"])
        self.assertEqual(hashlib.sha256(schema15.canonical(JOURNAL15)).hexdigest(),
                         schema15.EXPECTED_PAYLOAD_HASH)
        self.assertEqual(hashlib.sha256(schema26.canonical(JOURNAL26)).hexdigest(),
                         export.DELETIONS[26]["journal_sha"])

    def test_reconciles_both_deleted_and_live_import(self):
        output = report()
        self.assertIn("IMPORT_LIFECYCLE_RECONCILED", output)
        self.assertIn("DELETED_BY_USER_CONFIRMED 15", output)
        self.assertIn("DELETED_BY_USER_CONFIRMED 26", output)
        self.assertIn("DELETED_BY_USER 2", output)
        self.assertIn("PAPERLESS_LIVE_IMPORTED 1", output)
        self.assertIn("NAS_SENT_VERIFIED 1", output)
        self.assertIn("ARCHIVE_NOT_AUTHORIZED", output)
        self.assertNotIn("ARCHIVE_MATCH_READY", output)

    def test_exporter_validates_both_current_evidence_sets(self):
        self.assertEqual(export.validate_proofs(request()),
                         {15: JOURNAL15, 26: JOURNAL26})

    def test_missing_second_journal_blocks(self):
        data = request()
        data["journal"] = line(JOURNAL26) + "\nNO_FILES_CHANGED"
        with self.assertRaisesRegex(RuntimeError, "REQUIRE_EXACTLY_TWO_VERIFIED_JOURNALS"):
            export.validate_proofs(data)
        with self.assertRaisesRegex(RuntimeError, "REQUIRE_TWO_PRIVATE_JOURNALS"):
            report(data=data)

    def test_duplicate_journal_blocks(self):
        data = request()
        data["journal"] = line(JOURNAL26) + "\n" + line(JOURNAL26) + "\nNO_FILES_CHANGED"
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_OR_UNKNOWN_JOURNAL"):
            export.validate_proofs(data)

    def test_changed_journal_hash_blocks(self):
        data = request()
        data["journal"] = line(dict(JOURNAL15, decision_reason="different")) + "\n" + line(JOURNAL26) + "\nNO_FILES_CHANGED"
        with self.assertRaisesRegex(RuntimeError, "UNAPPROVED_DELETED_BY_USER_PROOF 15"):
            export.validate_proofs(data)
        with self.assertRaisesRegex(RuntimeError, "UNVERIFIED_JOURNAL_OR_NAS_DELETION 15"):
            report(data=data)

    def test_wrong_nas_sender_blocks(self):
        data = request()
        data["nas_deleted_15"] = line(dict(NAS15, sender_receipt=schema26.SENDER)) + "\nNO_FILES_CHANGED"
        with self.assertRaisesRegex(RuntimeError, "UNAPPROVED_DELETED_BY_USER_PROOF 15"):
            export.validate_proofs(data)

    def test_source_reappears_blocks(self):
        data = request()
        data["nas_deleted_26"] = line(dict(NAS26, nas_original_absent=False)) + "\nNO_FILES_CHANGED"
        with self.assertRaisesRegex(RuntimeError, "UNAPPROVED_DELETED_BY_USER_PROOF 26"):
            export.validate_proofs(data)

    def test_paperless_reappears_blocks(self):
        data = request()
        data["deleted_15"] = line(dict(PAPERLESS15, live_document_absent=False))
        with self.assertRaisesRegex(RuntimeError, "UNAPPROVED_DELETED_BY_USER_PROOF 15"):
            export.validate_proofs(data)

    def test_unknown_deleted_receipt_blocks(self):
        unexpected = dict(NORMAL_IMPORT, status="DELETED_BY_USER", sender_receipt=NORMAL_SENDER)
        with self.assertRaisesRegex(RuntimeError, "DELETED_IMPORT_NOT_JOURNALED"):
            report(imported=[unexpected, deleted_import(15), deleted_import(26)])

    def test_missing_deleted_receipt_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "REQUIRE_EXACTLY_TWO_JOURNALED_DELETIONS"):
            report(imported=[NORMAL_IMPORT, deleted_import(26)])

    def test_deleted_source_cannot_be_current_nas_original(self):
        conflicting = dict(NORMAL_NAS, receiver_source=NAS15["receiver_source"])
        with self.assertRaisesRegex(RuntimeError, "INVALID_OR_DUPLICATE_NAS_SOURCE"):
            report(nas=[conflicting])

    def test_live_import_absent_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "MISSING_OR_MISMATCHED_LIVE_IMPORT"):
            report(imported=[deleted_import(15), deleted_import(26)])

    def test_unmatched_extra_import_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "UNMATCHED_OR_MISSING_LIFECYCLE_RECEIPT"):
            report(nas=[])

    def test_exporter_rechecks_both_absences_and_live_import(self):
        paths = {15: Path(schema15.BRIDGE), 26: Path(schema26.BRIDGE)}
        normal = Path(NORMAL_IMPORT["bridge_receipt"])
        def load_receipt(path):
            if path == normal:
                return ({"status": "IMPORTED", "source": NORMAL_RECEIVER,
                         "sha256": NORMAL_SHA, "document_id": 23},
                        "normal.pdf", ("admin", "Familie@bergen.intern"))
            docid = 15 if path == paths[15] else 26
            return ({"status": "IMPORTED",
                     "source": {15: NAS15, 26: NAS26}[docid]["receiver_source"],
                     "sha256": SHA, "document_id": docid},
                    "original-" + str(docid) + ".pdf", ("thomas", ""))
        def verify(filename, sha, owner, group):
            return None if owner == "thomas" else 23
        mod = SimpleNamespace(
            RECEIPTS=SimpleNamespace(glob=lambda pattern: [normal, paths[15], paths[26]]),
            load_receipt=load_receipt, verify=Mock(side_effect=verify))
        with patch.object(export.subprocess, "run", return_value=SimpleNamespace(
                returncode=0,
                stdout='BP_DELETION_LOOKUP:{"id_exists":false,"filename_exists":false}\n')) as runner:
            rows = export.collect(request(), mod)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["document_id"] for r in rows if r["status"] == "DELETED_BY_USER"}, {15, 26})
        self.assertEqual(mod.verify.call_count, 3)
        self.assertEqual(runner.call_count, 2)

    def test_deleted_doc_reappearing_in_django_blocks(self):
        mod = SimpleNamespace(
            RECEIPTS=SimpleNamespace(glob=lambda pattern: [Path(schema15.BRIDGE)]),
            load_receipt=lambda path: (
                {"status": "IMPORTED", "source": NAS15["receiver_source"],
                 "sha256": SHA, "document_id": 15},
                "original.pdf", ("thomas", "")),
            verify=lambda *args: None)
        with patch.object(export.subprocess, "run", return_value=SimpleNamespace(
                returncode=0,
                stdout='BP_DELETION_LOOKUP:{"id_exists":true,"filename_exists":false}\n')):
            with self.assertRaisesRegex(RuntimeError, "DELETED_DOCUMENT_OR_FILENAME_PRESENT 15"):
                export.collect(request(), mod)

    def test_no_write_primitives_or_archive_apply(self):
        for filename in (
                "export_verified_user_deletion_journals_15_26.py",
                "export_import_lifecycle_15_26.py",
                "match_paperless_import_lifecycle_15_26.py"):
            src = (SOURCE / filename).read_text()
            for forbidden in ("os.unlink(", "os.replace(", "os.mkdir(", "os.chmod(",
                              "os.chown(", "publish_once(", ".write_bytes(",
                              ".write_text(", "shutil.move("):
                self.assertNotIn(forbidden, src)
        play = (ROOT / "ansible/playbooks/audit-paperless-import-lifecycle-15-26.yml").read_text()
        self.assertIn("changed_when: false", play)
        self.assertIn("export_verified_user_deletion_journals_15_26.py", play)
        self.assertIn("export_import_lifecycle_15_26.py", play)
        self.assertIn("match_paperless_import_lifecycle_15_26.py", play)
        self.assertIn("diagnose_deleted_import_15_nas.py", play)
        self.assertIn("export_deleted_by_user_nas_evidence.py", play)
        self.assertIn("DELETED_BY_USER 2", play)
        self.assertNotIn("publish_deleted_by_user", play)
        self.assertNotIn("ARCHIVE_MATCH_READY' in", play)


if __name__ == "__main__":
    unittest.main()
