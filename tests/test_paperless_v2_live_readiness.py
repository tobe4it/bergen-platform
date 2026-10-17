"""Synthetic only: no remote connections and no file system modifications."""
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] / "ansible/files/paperless" /
          "summarize_paperless_v2_live_readiness.py")
spec = importlib.util.spec_from_file_location("v2_live_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

SCOPE_ROWS = ("Familie", "Eltern", "Privat/thomas", "Privat/nadja")
V2 = "v2-" + "a" * 32 + "-" + "b" * 64


def nas(*, v2=0, v1=21):
    rows = []
    for i, scope in enumerate(SCOPE_ROWS):
        current_v1 = v1 if i == 0 else 0
        current_v2 = v2 if i == 0 else 0
        rows.append(f"SCOPE {scope} V1_SENT {current_v1} V1_PREPARED 0 "
                    f"V2_PREPARED {current_v2} V2_ATTEMPTED {current_v2} "
                    f"V2_SENT {current_v2}")
    return "\n".join(rows + [
        f"TOTAL_JOURNAL_EVENTS {v1 + 3 * v2}",
        f"TOTAL_V1_SENT {v1}", "UNRESOLVED_JOURNAL_EVENTS 0",
        "HISTORY_AUDIT_COMPLETE", "ARCHIVE_NOT_AUTHORIZED", "NO_FILES_CHANGED",
    ]) + "\n"


def imported(**changes):
    record = {
        "schema_version": 2, "status": "IMPORTED",
        "bridge_receipt": "c" * 24 + ".json", "sha256": "d" * 64,
        "receipt_id": V2, "receiver_source": "Familie/nas-" + V2 + ".pdf",
        "document_id": 3,
    }
    record.update(changes)
    return record


def paperless(items=()):
    return "\n".join([json.dumps(x, sort_keys=True) for x in items] + [
        "V2_LIVE_IMPORT_AUDIT_COMPLETE", "ARCHIVE_NOT_AUTHORIZED",
        "SOURCE_DELETE_NOT_AUTHORIZED", "NO_FILES_CHANGED",
    ]) + "\n"


class V2ReadinessTests(unittest.TestCase):
    def bundle(self, *, n=None, p=None):
        return {"nas": nas() if n is None else n,
                "paperless": paperless() if p is None else p}

    def test_no_v2_receipt_is_no_permission(self):
        lines = audit.summarize(self.bundle())
        self.assertIn("V1_SENT_COUNT 21", lines)
        self.assertIn("V2_SENT_COUNT 0", lines)
        self.assertIn("V2_LIVE_IMPORTED_COUNT 0", lines)
        self.assertIn("ARCHIVE_NOT_AUTHORIZED", lines)
        self.assertIn("SOURCE_DELETE_NOT_AUTHORIZED", lines)
        self.assertIn("PURGE_NOT_AUTHORIZED", lines)

    def test_positive_counts_still_never_authorize_move(self):
        lines = audit.summarize(self.bundle(n=nas(v2=1), p=paperless([imported()])))
        self.assertIn("V2_SENT_COUNT 1", lines)
        self.assertIn("V2_LIVE_IMPORTED_COUNT 1", lines)
        self.assertIn("V2_EXACT_RECEIPT_JOIN_NOT_YET_VERIFIED", lines)
        self.assertIn("ARCHIVE_NOT_AUTHORIZED", lines)
        self.assertNotIn(V2, "\n".join(lines))

    def test_incomplete_nas_markers_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "INCOMPLETE_NAS_AUDIT"):
            audit.summarize(self.bundle(n=nas().replace("NO_FILES_CHANGED\n", "")))

    def test_inconsistent_sender_totals_fail(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_TOTAL_MISMATCH"):
            audit.summarize(self.bundle(n=nas().replace("TOTAL_V1_SENT 21", "TOTAL_V1_SENT 20")))

    def test_duplicate_sender_scope_fail(self):
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_NAS_SCOPE"):
            audit.summarize(self.bundle(n=nas().replace("SCOPE Eltern", "SCOPE Familie")))

    def test_unknown_nas_output_cannot_be_logged(self):
        with self.assertRaisesRegex(RuntimeError, "UNEXPECTED_NAS_OUTPUT"):
            audit.summarize(self.bundle(n=nas() + "PRIVATE_SOURCE secret.pdf\n"))

    def test_v2_stage_counts_must_not_be_out_of_order(self):
        altered = nas(v2=1).replace("V2_ATTEMPTED 1 V2_SENT 1", "V2_ATTEMPTED 0 V2_SENT 1")
        with self.assertRaisesRegex(RuntimeError, "INCONSISTENT_V2_EVENT_STAGES"):
            audit.summarize(self.bundle(n=altered))

    def test_missing_paperless_marker(self):
        with self.assertRaisesRegex(RuntimeError, "INCOMPLETE_PAPERLESS_AUDIT"):
            audit.summarize(self.bundle(p=paperless().replace("NO_FILES_CHANGED", "")))

    def test_paperless_invalid_status(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PAPERLESS_RECORD_IDENTITY"):
            audit.summarize(self.bundle(p=paperless([imported(status="SENT")])))

    def test_paperless_forged_destination(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PAPERLESS_DESTINATION"):
            audit.summarize(self.bundle(p=paperless([imported(receiver_source="../../file.pdf")])))

    def test_paperless_boolean_id_is_invalid(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PAPERLESS_RECORD_IDENTITY"):
            audit.summarize(self.bundle(p=paperless([imported(document_id=True)])))

    def test_paperless_duplicate_receipt(self):
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_PAPERLESS_IMPORT"):
            audit.summarize(self.bundle(p=paperless([
                imported(), imported(bridge_receipt="e" * 24 + ".json")])))

    def test_paperless_duplicate_json_keys(self):
        bad = '{"schema_version":2,"schema_version":2}' + "\n" + paperless()
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_JSON_KEY"):
            audit.summarize(self.bundle(p=bad))

    def test_unexpected_field(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PAPERLESS_RECORD_SCHEMA"):
            audit.summarize(self.bundle(p=paperless([imported(archive_authorized=True)])))

    def test_missing_scope(self):
        with self.assertRaisesRegex(RuntimeError, "INCOMPLETE_NAS_AUDIT"):
            audit.summarize(self.bundle(n="\n".join(nas().splitlines()[1:])))

    def test_no_writable_host_operations_in_script(self):
        source = SCRIPT.read_text()
        for forbidden in ("subprocess.run(", "os.unlink(", "os.remove(", "os.rename(",
                          "os.mkdir(", "os.chmod(", "os.chown(", 'open("wb"'):
            self.assertNotIn(forbidden, source)

    def test_control_characters_fail(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_STREAM_CONTROL"):
            audit.summarize(self.bundle(n=nas() + "\r"))


if __name__ == "__main__":
    unittest.main()
