"""NAS SENT and live Paperless IMPORTED evidence matching regression tests."""
import importlib.util
import io
import json
import unittest
from datetime import datetime, timezone
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/match_paperless_archive_evidence.py"
NAS = ROOT / "ansible/files/paperless/audit_synology_archive_candidates.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-archive-imports.yml"
spec = importlib.util.spec_from_file_location("archive_matcher", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
D = "a" * 64
DEST = "Familie/scan--nas-" + D + ".pdf"
N = {"sender_receipt": "b" * 64 + ".json", "scope": "Familie", "source": "scan.pdf", "receiver_source": DEST, "sha256": D, "sent_at": 1791972000.0}
P = {"schema_version": 1, "bridge_receipt": "c" * 24 + ".json", "receiver_source": DEST, "sha256": D, "document_id": 23}


def output(nas, paperless):
    stream = io.StringIO()
    with redirect_stdout(stream):
        m.compare(nas, paperless)
    return stream.getvalue()


class ArchiveEvidenceTests(unittest.TestCase):
    def test_matching_live_proof(self):
        result = output(json.dumps(N), json.dumps(P))
        self.assertIn("ARCHIVE_MATCH_READY", result)
        self.assertIn("MATCHED 1", result)
        self.assertIn("PREVIEW_ARCHIVE_COPY Familie source scan.pdf target Familie/2026-10/" + "b" * 64 + ".pdf", result)
        self.assertIn("ARCHIVE_COPY_NOT_IMPLEMENTED", result)
        self.assertIn("NO_FILES_CHANGED", result)

    def test_missing_timestamp_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_OR_DUPLICATE_NAS_RECORD"):
            output(json.dumps(dict(N, sent_at=None)), json.dumps(P))

    def test_nonfinite_timestamp_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_OR_DUPLICATE_NAS_RECORD"):
            output(json.dumps(dict(N, sent_at=float("nan"))), json.dumps(P))

    def test_unknown_schema_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_OR_DUPLICATE_PAPERLESS_PROOF"):
            output(json.dumps(N), json.dumps(dict(P, schema_version=2)))

    def test_missing_proof_blocks(self):
        self.assertIn("ARCHIVE_MATCH_BLOCKED", output(json.dumps(N), ""))

    def test_empty_source_blocks(self):
        self.assertIn("ARCHIVE_MATCH_BLOCKED", output("", json.dumps(P)))

    def test_wrong_digest_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "DIGEST_MISMATCH"):
            output(json.dumps(N), json.dumps(dict(P, sha256="d" * 64)))

    def test_duplicate_proof_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE"):
            output(json.dumps(N), json.dumps(P) + "\n" + json.dumps(P))

    def test_invalid_record_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_NAS_RECORD"):
            output(json.dumps(dict(N, unexpected=True)), json.dumps(P))

    def test_inventory_is_read_only(self):
        src = NAS.read_text(encoding="utf-8")
        compile(src, str(NAS), "exec")
        for forbidden in (".unlink(", ".rename(", "os.replace(", "os.mkdir(", ".mkdir(", "os.chmod(", "os.chown("):
            self.assertNotIn(forbidden, src)
        self.assertIn("SOURCE_CHANGED_OR_HASH_MISMATCH", src)
        self.assertIn("LOCK_EX | LOCK_NB", src)

    def test_playbook_read_only(self):
        play = PLAY.read_text(encoding="utf-8")
        self.assertIn("changed_when: false", play)
        self.assertIn('failed_when: "archive_guest_status.rc', play)
        self.assertIn("pct", play)
        self.assertIn("audit_synology_archive_candidates.py", play)
        self.assertNotIn("paperless_archive_apply", play)


if __name__ == "__main__":
    unittest.main()
