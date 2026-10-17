"""Synthetic verification of 0 archived -> 1 archived lifecycle transition.

All PDF/journal fixtures are temporary; no Synology, LXC or real PDFs.
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

CODE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(CODE))
import audit_synology_completed_archive_moves as nas_audit
import match_paperless_import_lifecycle_15_26 as match
import list_verified_lifecycle_archive_candidates as candidates
import select_one_verified_lifecycle_archive_preview as preview
from test_paperless_import_lifecycle_15_26 import (
    NORMAL_NAS, NORMAL_IMPORT, deleted_import, request, line)
from test_paperless_list_verified_lifecycle_archive_candidates import (
    S, P, deletions, jsonl)


def archived_doc():
    return {
        "schema_version": 1,
        "sender_receipt": NORMAL_NAS["sender_receipt"],
        "scope": NORMAL_NAS["scope"],
        "source": NORMAL_NAS["source"],
        "receiver_source": NORMAL_NAS["receiver_source"],
        "sha256": NORMAL_NAS["sha256"],
        "bridge_receipt": NORMAL_IMPORT["bridge_receipt"],
        "document_id": NORMAL_IMPORT["document_id"],
        "archive_site": "paperless-scan",
        "archive_month": "2026-10",
        "archive_name": NORMAL_NAS["sender_receipt"][:-5] + ".pdf",
        "signature": [123, 1234, 56, 789, 777],
    }


def compare(sources, archives, imports=None):
    req = request()
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        match.compare(
            jsonl(*sources),
            jsonl(*(imports if imports is not None else [
                NORMAL_IMPORT, deleted_import(15), deleted_import(26)])),
            req["journal"], req["nas_deleted_15"], req["nas_deleted_26"],
            jsonl(*archives) + ("\n" if archives else "") + "NO_FILES_CHANGED")
    return buffer.getvalue()


def archived_fixture(key="f"*64, *, stage="ARCHIVED"):
    return {
        "schema_version": 1,
        "archive_type": "same_subvolume_rename",
        "scope": "Familie",
        "source": "Scan.pdf",
        "sender_receipt": key + ".json",
        "bridge_receipt": "a"*24 + ".json",
        "document_id": 12,
        "sha256": "a"*64,
        "signature": [1, 2, 3, 4, 5],
        "archive_site": "paperless-scan",
        "archive_scope_dir": "/volume1/paperless-scan/.bergen-paperless-archive/Familie",
        "archive_month": "2026-10",
        "archive_name": key + ".pdf",
        "stage": stage,
        **({"archived_at": "2026-10-16T16:20:00+00:00"}
           if stage == "ARCHIVED" else {}),
    }


class ArchiveAwareLifecycleTests(unittest.TestCase):
    def test_zero_archives_keeps_existing_22_source_contract(self):
        text = compare([NORMAL_NAS], [])
        self.assertIn("NAS_SENT_VERIFIED 1", text)
        self.assertIn("NAS_ARCHIVED_VERIFIED 0", text)
        self.assertIn("NAS_CURRENT_ORIGINALS_VERIFIED 1", text)
        self.assertIn("IMPORT_LIFECYCLE_RECONCILED", text)

    def test_one_archived_no_longer_in_source_is_valid(self):
        text = compare([], [archived_doc()])
        self.assertIn("NAS_SENT_VERIFIED 0", text)
        self.assertIn("NAS_ARCHIVED_VERIFIED 1", text)
        self.assertIn("NAS_CURRENT_ORIGINALS_VERIFIED 1", text)
        self.assertIn("ARCHIVED_LIVE_IMPORTED Familie document 23", text)

    def test_source_and_archive_both_present_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ARCHIVED_IDENTITY"):
            compare([NORMAL_NAS], [archived_doc()])

    def test_missing_source_and_archive_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "UNMATCHED_OR_MISSING_LIFECYCLE_RECEIPT"):
            compare([], [])

    def test_archive_not_live_imported_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_IMPORT_PROOF_MISMATCH"):
            compare([], [dict(archived_doc(), document_id=998)])

    def test_archive_checksum_wrong_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_IMPORT_PROOF_MISMATCH"):
            compare([], [dict(archived_doc(), sha256="e"*64)])

    def test_archive_bridge_wrong_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_IMPORT_PROOF_MISMATCH"):
            compare([], [dict(archived_doc(), bridge_receipt="e"*24 + ".json")])

    def test_archive_wrong_scope_or_site_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ARCHIVED_IDENTITY"):
            compare([], [dict(archived_doc(), archive_site="homes")])

    def test_archive_sender_receipt_changed_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ARCHIVED_IDENTITY"):
            compare([], [dict(archived_doc(), sender_receipt="e"*64 + ".json")])

    def test_archive_incomplete_marker_blocks(self):
        req = request()
        with self.assertRaisesRegex(RuntimeError, "INCOMPLETE_ARCHIVE_AUDIT"):
            match.compare("", jsonl(NORMAL_IMPORT, deleted_import(15),
                                    deleted_import(26)), req["journal"],
                          req["nas_deleted_15"], req["nas_deleted_26"],
                          jsonl(archived_doc()))

    def test_prepared_only_journal_blocks(self):
        key = "f"*64
        with self.assertRaisesRegex(RuntimeError, "INCOMPLETE_ARCHIVE_JOURNAL"):
            nas_audit.inspect_events(
                [key + ".prepared.json"],
                lambda _name: archived_fixture(key, stage="ARCHIVE_PREPARED"))

    def test_complete_prepared_archived_journals(self):
        key = "f"*64
        rows = {
            key + ".prepared.json": archived_fixture(key, stage="ARCHIVE_PREPARED"),
            key + ".archived.json": archived_fixture(key, stage="ARCHIVED"),
        }
        self.assertEqual(set(nas_audit.inspect_events(list(rows), rows.get)), {key})

    def test_conflicting_archive_journal_identity_blocks(self):
        key = "f"*64
        rows = {
            key + ".prepared.json": archived_fixture(key, stage="ARCHIVE_PREPARED"),
            key + ".archived.json": dict(
                archived_fixture(key, stage="ARCHIVED"), sha256="1"*64),
        }
        with self.assertRaisesRegex(RuntimeError, "CONFLICTING_ARCHIVE_JOURNAL"):
            nas_audit.inspect_events(list(rows), rows.get)

    def test_unknown_archive_journal_entry_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "UNEXPECTED_ARCHIVE_JOURNAL_ENTRY"):
            nas_audit.inspect_events(["other.json"], lambda name: None)

    def test_invalid_archive_timestamp_blocks(self):
        key = "f"*64
        rows = {
            key + ".prepared.json": archived_fixture(key, stage="ARCHIVE_PREPARED"),
            key + ".archived.json": dict(
                archived_fixture(key, stage="ARCHIVED"),
                archived_at="2026-10-16"),
        }
        with self.assertRaisesRegex(RuntimeError, "INVALID_ARCHIVE_TIMESTAMP"):
            nas_audit.inspect_events(list(rows), rows.get)

    def test_archived_pdf_same_inode_and_checksum(self):
        pdf = b"%PDF-1.4\narchive test\n%%EOF\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "original.pdf"
            path.write_bytes(pdf)
            st = path.stat()
            sig = [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
            target = Path(temporary) / "archived.pdf"
            path.rename(target)
            folder_fd = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY)
            try:
                nas_audit.inspect_pdf(folder_fd, target.name, sig,
                                      hashlib.sha256(pdf).hexdigest(), 100000)
                with self.assertRaisesRegex(
                        RuntimeError, "ARCHIVED_PDF_INVALID_OR_SHA_MISMATCH"):
                    nas_audit.inspect_pdf(folder_fd, target.name, sig, "e"*64, 100000)
            finally:
                os.close(folder_fd)

    def test_candidate_list_after_single_archive_does_not_offer_original(self):
        sender = dict(S)
        arch = {
            "schema_version": 1, "sender_receipt": S["sender_receipt"],
            "scope": S["scope"], "source": S["source"],
            "receiver_source": S["receiver_source"], "sha256": S["sha256"],
            "bridge_receipt": P["bridge_receipt"],
            "document_id": P["document_id"], "archive_site": "paperless-scan",
            "archive_month": "2026-10",
            "archive_name": S["sender_receipt"][:-5] + ".pdf",
            "signature": [1, 2, 3, 4, 5],
        }
        live = [P, *deletions()]
        markers = "\n".join([
            "PAPERLESS_LIVE_IMPORTED 1", "NAS_SENT_VERIFIED 0",
            "NAS_ARCHIVED_VERIFIED 1", "NAS_CURRENT_ORIGINALS_VERIFIED 1",
            "DELETED_BY_USER 2", "IMPORT_LIFECYCLE_RECONCILED",
            "ARCHIVE_NOT_AUTHORIZED", "NO_RECEIPTS_CHANGED", "NO_FILES_CHANGED",
        ])
        data = {"nas": "", "paperless_lifecycle": jsonl(*live),
                "archived": jsonl(arch) + "\nNO_FILES_CHANGED",
                "lifecycle_report": markers}
        result = candidates.report(data)
        self.assertEqual(result[0], "V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 0")
        self.assertFalse(any(x.startswith("CANDIDATE ") for x in result))
        data["only"] = "Familie/Scan.pdf"
        with self.assertRaisesRegex(RuntimeError, "REQUEST_NOT_A_VERIFIED_LIVE_CANDIDATE"):
            preview.select(data)

    def test_audit_has_no_mutating_api(self):
        src = (CODE / "audit_synology_completed_archive_moves.py").read_text()
        for forbidden in ("os.mkdir(", "os.unlink(", "os.rename(", "os.replace(",
                          "os.chmod(", "os.chown(", ".write_text(", ".write_bytes(",
                          "renameat2(", "os.link("):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
