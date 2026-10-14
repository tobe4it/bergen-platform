"""Read-only deleted Paperless import exception policy regression tests."""
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "ansible/files/paperless/preview_deleted_import_policy.py"
EXPORT = ROOT / "ansible/files/paperless/export_deleted_import_candidate.py"
PLAY = ROOT / "ansible/playbooks/preview-paperless-deleted-import.yml"
spec = importlib.util.spec_from_file_location("deleted_policy", POLICY)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

DIGEST = "a" * 64
DEST = "Privat/thomas/sample--nas-" + DIGEST + ".pdf"
BRIDGE = "b" * 24 + ".json"
NAS = {
    "sender_receipt": "c" * 64 + ".json",
    "scope": "Privat/thomas",
    "source": "sample.pdf",
    "receiver_source": DEST,
    "sha256": DIGEST,
}
DELETED = {
    "schema_version": 1,
    "bridge_receipt": BRIDGE,
    "document_id": 26,
    "receiver_source": DEST,
    "sha256": DIGEST,
    "proposed_status": "DELETED_IN_PAPERLESS",
    "live_document_absent": True,
    "original_filename_absent": True,
}


def run(nas=None, deleted=None, document_id=26, bridge=BRIDGE):
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        policy.preview(json.dumps(NAS if nas is None else nas),
                       json.dumps(DELETED if deleted is None else deleted),
                       document_id, bridge)
    return stdout.getvalue()


class DeletedImportPolicyTests(unittest.TestCase):
    def test_approved_missing_document_preview_only(self):
        out = run()
        for token in ("PREVIEW_DELETED_IN_PAPERLESS 26",
                      "NAS_ORIGINAL_VERIFIED_AND_PRESERVED",
                      "REIMPORT_NOT_REQUESTED",
                      "EXCLUDED_FROM_ARCHIVE_MATCH_READY",
                      "NO_RECEIPT_STATUS_CHANGED",
                      "NO_FILES_CHANGED"):
            self.assertIn(token, out)
        self.assertNotIn("ARCHIVE_MATCH_READY\n", out)

    def test_document_still_exists_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_DELETION_EVIDENCE"):
            run(deleted=dict(DELETED, live_document_absent=False))

    def test_original_filename_still_exists_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_DELETION_EVIDENCE"):
            run(deleted=dict(DELETED, original_filename_absent=False))

    def test_wrong_document_id_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_DELETION_EVIDENCE"):
            run(document_id=27)

    def test_wrong_approval_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_DELETION_EVIDENCE"):
            run(bridge="d" * 24 + ".json")

    def test_wrong_digest_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "DELETED_IMPORT_NAS_MISMATCH"):
            run(nas=dict(NAS, sha256="d" * 64))

    def test_missing_nas_source_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "DELETED_IMPORT_NOT_IN_VERIFIED_NAS_SOURCES"):
            run(nas=dict(NAS, receiver_source="Privat/thomas/other.pdf"))

    def test_duplicate_nas_source_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_OR_DUPLICATE_NAS_EVIDENCE"):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                policy.preview(json.dumps(NAS) + "\n" + json.dumps(NAS),
                               json.dumps(DELETED), 26, BRIDGE)

    def test_invalid_status_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_DELETION_EVIDENCE"):
            run(deleted=dict(DELETED, proposed_status="IMPORTED"))

    def test_unexpected_field_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_DELETION_EVIDENCE"):
            run(deleted=dict(DELETED, extra=True))

    def test_read_only_scripts_and_playbook(self):
        for path in (POLICY, EXPORT):
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
            for forbidden in (".unlink(", ".rename(", "os.replace(", ".mkdir(", "os.chmod(", "os.chown("):
                self.assertNotIn(forbidden, source)
        play = PLAY.read_text(encoding="utf-8")
        self.assertIn("changed_when: false", play)
        self.assertIn("export_deleted_import_candidate.py", play)
        self.assertIn("audit_synology_archive_candidates.py", play)
        self.assertNotIn("paperless_archive_apply", play)


if __name__ == "__main__":
    unittest.main()
