"""Synthetic no-network tests for an exact-one archived PDF recovery exercise.

This test never opens NAS, SSH, vaults or Paperless; real verification is
explicitly gated by the read-only pre/post lifecycle Ansible playbook.
"""
import hashlib
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

BASE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"


def load_module(module, name):
    path = BASE / module
    spec = importlib.util.spec_from_file_location(name, path)
    item = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(item)
    return item


nas = load_module("readonly_archive_recovery_stream.py", "readonly_recovery_nas")
ctl = load_module("verify_isolated_archive_recovery.py", "isolated_recovery_controller")


class IsolatedArchiveRecoveryTests(unittest.TestCase):
    def sample_pdf(self):
        return b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"

    def header(self, content):
        return {"schema_version": 1, "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content)}

    def test_correct_copy_roundtrip_is_private_and_rehashed(self):
        payload = self.sample_pdf()
        head = self.header(payload)
        raw = (json.dumps(head) + "\n").encode("ascii")
        self.assertEqual(ctl.parse_header(raw), head)
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "restored.pdf"
            ctl.copy_stream(io.BytesIO(payload), destination, head)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_header_rejects_noncanonical_shape_and_overlimits(self):
        pdf = self.sample_pdf()
        good = self.header(pdf)
        candidates = [
            b"", b"not json\n", b"{}\n", b"{}\r\n",
            json.dumps({**good, "other": "injected"}).encode() + b"\n",
            json.dumps({**good, "bytes": True}).encode() + b"\n",
            json.dumps({**good, "bytes": 0}).encode() + b"\n",
            json.dumps({**good, "bytes": 512 * 1024 * 1024 + 1}).encode() + b"\n",
            json.dumps({**good, "sha256": "bad"}).encode() + b"\n",
            json.dumps({**good, "schema_version": True}).encode() + b"\n",
            (b'{"schema_version":1,"sha256":"' +
             good["sha256"].encode() + b'","bytes":5,"bytes":6}\n'),
            b'{"schema_version":1}\n' + b"x" * 256,
        ]
        for wrong in candidates:
            with self.subTest(wrong=wrong[:30]), self.assertRaises(Exception):
                ctl.parse_header(wrong)

    def test_copy_rejects_truncation_suffix_mismatch_and_invalid_pdf(self):
        pdf = self.sample_pdf()
        valid_header = self.header(pdf)
        with tempfile.TemporaryDirectory() as tmp:
            cases = [
                (pdf[:-1], valid_header),  # truncated byte stream
                (pdf + b"extra", valid_header),
                (pdf.replace(b"%%EOF", b"%%ZZZ"), valid_header),
                (b"ZZZZ" + pdf[4:], valid_header),
                (pdf, {**valid_header, "sha256": "a" * 64}),
            ]
            for index, (payload, head) in enumerate(cases):
                with self.subTest(index=index), self.assertRaises(RuntimeError):
                    ctl.copy_stream(io.BytesIO(payload),
                                    Path(tmp) / ("fail%d.pdf" % index), head)

    def sample_event(self):
        source = "Bergen-Platform-fuer-Dummies.pdf"
        digest = hashlib.sha256(("Familie\0" + source).encode()).hexdigest()
        prepare = {
            "schema_version": 1, "archive_type": "same_subvolume_rename",
            "scope": "Familie", "source": source,
            "sender_receipt": digest + ".json",
            "bridge_receipt": "f" * 24 + ".json",
            "document_id": 8, "sha256": "a" * 64,
            "signature": [100, 250, 30, 400, 500],
            "archive_site": "paperless-scan",
            "archive_scope_dir": "/tmp/.bergen-paperless-archive/Familie",
            "archive_month": "2026-10",
            "archive_name": digest + ".pdf",
            "stage": "ARCHIVE_PREPARED",
        }
        done = dict(prepare, stage="ARCHIVED",
                    archived_at="2026-10-16T20:50:00+00:00")
        return prepare, done, digest

    def test_complete_exact_canary_archive_journal_verified(self):
        first, last, sender = self.sample_event()
        self.assertEqual(
            nas.verify_pair(
                first, last, scope="Familie",
                filename="Bergen-Platform-fuer-Dummies.pdf",
                sender_id=sender,
                archive_dir=Path("/tmp/.bergen-paperless-archive/Familie")),
            first)

    def test_missing_changed_or_different_archive_journal_fails_closed(self):
        first, last, sender = self.sample_event()
        invalid = [
            (first, dict(last, document_id=7)),
            (first, dict(last, stage="ARCHIVE_PREPARED")),
            (first, dict(last, sha256="b" * 64)),
            (dict(first, archive_site="homes"), last),
            (dict(first, document_id=9), last),
            (dict(first, archive_month="../../etc"), last),
            (dict(first, extra="x"), last),
            (first, dict(last, extra="x")),
        ]
        for index, (before, after) in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                nas.verify_pair(
                    before, after, scope="Familie",
                    filename="Bergen-Platform-fuer-Dummies.pdf",
                    sender_id=sender,
                    archive_dir=Path("/tmp/.bergen-paperless-archive/Familie"))

    def test_pdf_inode_signature_changed_rejected(self):
        st = SimpleNamespace(st_mode=0o100600, st_nlink=1, st_dev=100,
                             st_ino=250, st_size=30, st_mtime_ns=400,
                             st_ctime_ns=501)
        self.assertIsNone(nas.verify_pdf_stat(st, [100, 250, 30, 400, 500], 500))
        for changes in ({"st_ino": 1}, {"st_dev": 10}, {"st_size": 31},
                        {"st_mode": 0o040700}, {"st_ctime_ns": 499},
                        {"st_nlink": 2}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                nas.verify_pdf_stat(
                    SimpleNamespace(**dict(vars(st), **changes)),
                    [100, 250, 30, 400, 500], 500)

    def test_playbook_has_two_full_independent_lifecycle_audits(self):
        import yaml
        path = BASE.parents[1] / "playbooks/verify-paperless-one-group-isolated-recovery.yml"
        data = yaml.safe_load(path.read_text())
        self.assertEqual(len(data), 4)
        self.assertEqual(data[0]["import_playbook"],
                         "audit-paperless-import-lifecycle-15-26.yml")
        self.assertEqual(data[2]["import_playbook"],
                         "audit-paperless-import-lifecycle-15-26.yml")
        self.assertTrue(data[1]["tasks"][1]["ansible.builtin.command"]["no_log"]
                        if "no_log" in data[1]["tasks"][1]["ansible.builtin.command"]
                        else data[1]["tasks"][1]["no_log"])
        self.assertFalse(data[1]["tasks"][1]["changed_when"])
        self.assertIn("ARCHIVE_PURGE_NOT_AUTHORIZED", str(data[3]))

    def test_neither_script_contains_mutating_nas_operations(self):
        src = (BASE / "readonly_archive_recovery_stream.py").read_text()
        controller = (BASE / "verify_isolated_archive_recovery.py").read_text()
        for token in ("os.unlink(", "os.rename(", "os.replace(", "os.chmod(",
                      "os.chown(", "os.mkdir(", "os.rmdir(", "renameat2("):
            with self.subTest(token=token):
                self.assertNotIn(token, src)
        self.assertIn('Path("/dev/shm")', controller)
        self.assertIn("TemporaryDirectory", controller)
        self.assertNotIn('dir="/tmp"', controller)


if __name__ == "__main__":
    unittest.main()
