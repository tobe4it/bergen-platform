"""Offline regression for archive candidate listing after two pinned user deletions."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(BASE))
import match_paperless_import_lifecycle_15_26 as lifecycle

spec = importlib.util.spec_from_file_location(
    "v1_lifecycle_candidates",
    BASE / "list_verified_lifecycle_archive_candidates.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SHA = "b" * 64
S = {
    "sender_receipt": "a" * 64 + ".json",
    "scope": "Familie", "source": "Scan.pdf",
    "receiver_source": "Familie/Scan--nas-" + SHA + ".pdf", "sha256": SHA,
}
P = {
    "schema_version": 1, "status": "IMPORTED",
    "bridge_receipt": "c" * 24 + ".json",
    "receiver_source": S["receiver_source"], "sha256": SHA, "document_id": 12,
}


def deletions():
    result = []
    for docid, data in sorted(lifecycle.DELETIONS.items()):
        _, _, bridge, sender, original = data
        result.append({
            "schema_version": 1,
            "status": "DELETED_BY_USER",
            "bridge_receipt": bridge, "sender_receipt": sender,
            "receiver_source": "Privat/thomas/" + original[:-4] +
                               "--nas-" + lifecycle.SHA + ".pdf",
            "sha256": lifecycle.SHA,
            "document_id": docid,
        })
    return result


def jsonl(*records):
    return "\n".join(json.dumps(item, sort_keys=True) for item in records)


def bundle(nas=None, live=None, markers=None):
    sender = [S] if nas is None else nas
    imported = [P] if live is None else live
    report = [
        "PAPERLESS_LIVE_IMPORTED " + str(len(imported)),
        "NAS_SENT_VERIFIED " + str(len(sender)),
        "DELETED_BY_USER 2",
        "IMPORT_LIFECYCLE_RECONCILED", "ARCHIVE_NOT_AUTHORIZED",
        "NO_RECEIPTS_CHANGED", "NO_FILES_CHANGED",
    ] if markers is None else markers
    return {
        "nas": jsonl(*sender),
        "paperless_lifecycle": jsonl(*imported, *deletions()),
        "lifecycle_report": "\n".join(report),
    }


class V1LifecycleCandidatesTests(unittest.TestCase):
    def test_live_original_listed_and_two_deleted_excluded(self):
        lines = m.report(bundle())
        self.assertEqual(lines, [
            "V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 1",
            "DELETED_BY_USER_EXCLUDED 2",
            'CANDIDATE "Familie/Scan.pdf"',
            "CANDIDATE_AUDIT_COMPLETE",
            "NO_FILES_CHANGED",
            "ARCHIVE_NOT_AUTHORIZED",
            "PURGE_NOT_AUTHORIZED",
        ])
        self.assertNotIn(lifecycle.SHA, str(lines))
        self.assertNotIn("Gebuehren", str(lines))
        self.assertNotIn("document_id", str(lines))

    def test_real_live_counts_must_match_sender(self):
        with self.assertRaisesRegex(ValueError, "LIFECYCLE_COUNTS_DO_NOT_MATCH"):
            m.report(bundle(nas=[]))
        with self.assertRaisesRegex(ValueError, "LIFECYCLE_COUNTS_DO_NOT_MATCH"):
            m.report(bundle(live=[]))

    def test_mismatched_sha_or_receiver_cannot_be_candidate(self):
        for key, value in [("sha256", "d"*64),
                           ("receiver_source", "Eltern/wrong.pdf")]:
            with self.subTest(key=key), self.assertRaisesRegex(
                    ValueError, "SOURCE_NOT_LIVE_IMPORTED"):
                m.report(bundle(live=[dict(P, **{key: value})]))

    def test_missing_deleted_proof_fails_closed(self):
        data = bundle()
        data["paperless_lifecycle"] = jsonl(P, deletions()[0])
        with self.assertRaisesRegex(ValueError, "MISSING_VERIFIED_DELETED_LIFECYCLE"):
            m.report(data)

    def test_unapproved_deleted_identity_blocks(self):
        for key, value in [
            ("bridge_receipt", "e"*24 + ".json"),
            ("sender_receipt", "d"*64 + ".json"),
            ("sha256", "0"*64),
            ("receiver_source", "Privat/thomas/other.pdf"),
            ("document_id", 99),
        ]:
            with self.subTest(key=key):
                data = bundle()
                records = deletions()
                records[0] = dict(records[0], **{key: value})
                data["paperless_lifecycle"] = jsonl(P, *records)
                with self.assertRaises(ValueError):
                    m.report(data)

    def test_duplicate_lifecycle_source_refused(self):
        data = bundle()
        data["paperless_lifecycle"] = jsonl(P, P, *deletions())
        with self.assertRaisesRegex(ValueError, "DUPLICATE_LIFECYCLE_IDENTITY"):
            m.report(data)

    def test_duplicate_field_rejected(self):
        raw = '{"schema_version":1,"schema_version":2}'
        with self.assertRaisesRegex(ValueError, "DUPLICATE_LIFECYCLE_FIELD"):
            json.loads(raw, object_pairs_hook=m.strict_object)

    def test_deleted_status_not_accepted_for_another_doc(self):
        data = bundle()
        new = dict(P, status="DELETED_BY_USER",
                   sender_receipt="e"*64 + ".json")
        data["paperless_lifecycle"] = jsonl(new, *deletions())
        with self.assertRaisesRegex(ValueError, "UNAPPROVED_DELETED_LIFECYCLE"):
            m.report(data)

    def test_deletion_receiver_reappears_as_nas_source_rejected(self):
        data = bundle()
        deleted = deletions()[0]
        extra = dict(S, source="Gebuehren.pdf",
                     scope="Privat/thomas",
                     sender_receipt=deleted["sender_receipt"],
                     receiver_source=deleted["receiver_source"],
                     sha256=deleted["sha256"])
        data["nas"] = jsonl(S, extra)
        # Cannot list stale deletion as a live source even if it reappears.
        with self.assertRaises(ValueError):
            m.report(data)

    def test_lifecycle_report_marker_missing(self):
        data = bundle()
        data["lifecycle_report"] = "\n".join(
            line for line in data["lifecycle_report"].splitlines()
            if line != "IMPORT_LIFECYCLE_RECONCILED")
        with self.assertRaisesRegex(ValueError, "LIFECYCLE_AUDIT_INCOMPLETE"):
            m.report(data)

    def test_lifecycle_report_bad_count(self):
        data = bundle()
        data["lifecycle_report"] = data["lifecycle_report"].replace(
            "NAS_SENT_VERIFIED 1", "NAS_SENT_VERIFIED 24")
        with self.assertRaisesRegex(ValueError, "LIFECYCLE_AUDIT_INCOMPLETE"):
            m.report(data)

    def test_boolean_document_id_refused(self):
        data = bundle(live=[dict(P, document_id=True)])
        with self.assertRaises(RuntimeError):
            m.report(data)

    def test_unknown_status_blocks(self):
        data = bundle(live=[dict(P, status="RECEIVED")])
        with self.assertRaisesRegex(ValueError, "UNKNOWN_LIFECYCLE_STATUS"):
            m.report(data)

    def test_no_writes_or_remote_operations(self):
        src = (BASE / "list_verified_lifecycle_archive_candidates.py").read_text()
        for fragment in ("subprocess.run(", "os.unlink(", "os.remove(",
                         "os.rename(", "os.replace(", "archive_one(",
                         "open(", "os.mkdir("):
            self.assertNotIn(fragment, src)


if __name__ == "__main__":
    unittest.main()
