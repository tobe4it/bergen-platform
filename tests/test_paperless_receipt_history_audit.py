"""Offline-only regression tests for complete, locked v1/v2 inventory."""
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'ansible/files/paperless/audit_synology_receipt_history.py'
spec = importlib.util.spec_from_file_location('audit_synology_receipt_history', MODULE)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
SCOPE = 'Familie'
SCOPE2 = 'Privat/thomas'
SHA = hashlib.sha256(b'%PDF-1.4 sample %%EOF').hexdigest()
SIG = [47, 123, 200, 400, 500]
SCOPES = (SCOPE, SCOPE2)


def write_record(directory, name, content):
    path = directory / name
    if isinstance(content, dict):
        content = (json.dumps(content, sort_keys=True, separators=(',', ':'),
                              ensure_ascii=True) + '\n').encode('ascii')
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def legacy(directory, name='Scan.pdf', scope=SCOPE, status='SENT', number=0):
    key = hashlib.sha256((scope + '\0' + name).encode()).hexdigest()
    stem = Path(name).stem
    record = dict(scope=scope, source=name, status=status, sha256=SHA,
                  signature=[47, number + 10, 100, 1000 + number, 2000 + number],
                  destination=scope + '/' + stem + '--nas-' + SHA + '.pdf',
                  sent_at=1791968400.0)
    path = write_record(directory, key + '.json', record)
    return path, record


def v2(directory, stage='PREPARED', nonce='a' * 32):
    name = 'Repeated.pdf'
    event = a.v2_id(SCOPE, name, SHA, SIG, nonce)
    record = dict(schema_version=2, receipt_id=event, status=stage, scope=SCOPE,
                  source=name, sha256=SHA, signature=SIG,
                  destination=SCOPE + '/nas-' + event + '.pdf', incarnation_nonce=nonce)
    if stage == 'SENT':
        record['transfer_evidence'] = dict(receiver_source=record['destination'],
                                           receiver_sha256=SHA, new_file_confirmed=True)
    path = write_record(directory, event + '.' + stage.lower() + '.json', record)
    return path, record


class HistoryAuditTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.root.chmod(0o700)
        self.lock = write_record(self.root, 'sync.lock', b'')

    def result(self):
        return a.audit_directory(self.root, SCOPES)

    def test_full_seventeen_v1_sent(self):
        for i in range(17):
            legacy(self.root, name='Scan-%02d.pdf' % i, number=i)
        result = self.result()
        self.assertEqual(result['total_receipts'], 17)
        self.assertEqual(result['total_v1_sent'], 17)
        self.assertEqual(result['counts'][SCOPE]['v1_sent'], 17)
        self.assertEqual(result['unresolved'], 0)
        self.assertIs(result['can_archive'], False)

    def test_legacy_manual_reconciliation_receipt(self):
        path, rec = legacy(self.root)
        rec.pop('sent_at')
        rec.update(manually_confirmed_imported=True, bridge_receipt='a' * 24 + '.json',
                   reconciled_at=1791970000.0)
        write_record(self.root, path.name, rec)
        self.assertEqual(self.result()['total_receipts'], 1)

    def test_verified_recovery_receipt_matches_real_repair_writer(self):
        # repair_synology_prepared_receipt.py adds these two fields after
        # a fresh verified Paperless import, preserving original v1 key.
        path, obj = legacy(self.root)
        obj.update(
            status='SENT',
            manually_confirmed_imported=True,
            bridge_receipt='a' * 24 + '.json',
            document_id=23,
            recovery_reason='verified_paperless_import',
            sent_at=1791972000.0,
            reconciled_at=1791972001.0,
        )
        write_record(self.root, path.name, obj)
        result = self.result()
        self.assertEqual(result['total_v1_sent'], 1)
        self.assertEqual(result['unresolved'], 0)

    def test_repair_receipt_incomplete_metadata_fails_closed(self):
        path, obj = legacy(self.root)
        obj.update(
            manually_confirmed_imported=True,
            bridge_receipt='a' * 24 + '.json',
            document_id=23,
            recovery_reason='verified_paperless_import',
            reconciled_at=1791972001.0,
        )
        for bad in (
            dict(obj, recovery_reason='other_reason'),
            dict(obj, document_id=True),
            dict(obj, bridge_receipt='not-a-bridge'),
            dict(obj, manually_confirmed_imported=False),
            dict(obj, status='PREPARED'),
        ):
            with self.subTest(bad=bad):
                write_record(self.root, path.name, bad)
                with self.assertRaisesRegex(RuntimeError, 'INVALID_LEGACY_REPAIR_METADATA'):
                    self.result()

    def test_unrecognized_repair_extra_field_still_rejected(self):
        path, obj = legacy(self.root)
        obj['some_unreviewed_key'] = True
        write_record(self.root, path.name, obj)
        with self.assertRaisesRegex(RuntimeError, 'INVALID_LEGACY_RECEIPT_SCHEMA'):
            self.result()

    def test_both_v2_events_and_v1_coexist(self):
        legacy(self.root)
        v2(self.root, 'PREPARED')
        v2(self.root, 'SENT')
        result = self.result()
        self.assertEqual(result['total_receipts'], 3)
        self.assertEqual(result['counts'][SCOPE]['v2_prepared'], 1)
        self.assertEqual(result['counts'][SCOPE]['v2_sent'], 1)
        self.assertEqual(result['unresolved'], 0)
        self.assertFalse(result['can_archive'])

    def test_unresolved_prepared_counts(self):
        legacy(self.root, status='PREPARED')
        v2(self.root, 'PREPARED')
        self.assertEqual(self.result()['unresolved'], 2)

    def test_sent_without_prepared_rejected(self):
        v2(self.root, 'SENT')
        with self.assertRaisesRegex(RuntimeError, 'SENT_WITHOUT_PREPARED'):
            self.result()

    def test_tampered_sent_and_nonce_rejected(self):
        v2(self.root, 'PREPARED')
        path, record = v2(self.root, 'SENT', nonce='b' * 32)
        with self.assertRaisesRegex(RuntimeError, 'SENT_WITHOUT_PREPARED'):
            self.result()
        path.unlink()
        path, record = v2(self.root, 'SENT', nonce='a' * 32)
        record['transfer_evidence']['new_file_confirmed'] = False
        write_record(self.root, path.name, record)
        with self.assertRaisesRegex(RuntimeError, 'INVALID_V2_TRANSFER_EVIDENCE'):
            self.result()

    def test_unknown_json_and_orphan_temp_are_blocked(self):
        for name in ('unknown.json', '.receipt-old.tmp', '.v2-receipt-old.tmp'):
            with self.subTest(name=name):
                path = write_record(self.root, name, b'ignored?')
                with self.assertRaisesRegex(RuntimeError, 'UNKNOWN_OR_ORPHANED'):
                    self.result()
                path.unlink()

    def test_legacy_wrong_filename_and_destination_rejected(self):
        path, obj = legacy(self.root)
        bad = self.root / ('f' * 64 + '.json')
        path.rename(bad)
        with self.assertRaisesRegex(RuntimeError, 'LEGACY_FILENAME_MISMATCH'):
            self.result()
        bad.rename(path)
        obj['destination'] = 'Familie/wrong.pdf'
        write_record(self.root, path.name, obj)
        with self.assertRaisesRegex(RuntimeError, 'LEGACY_DESTINATION_MISMATCH'):
            self.result()

    def test_symlink_hardlink_and_permissions_rejected(self):
        path, _ = legacy(self.root)
        other = self.root / 'original'
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, 'UNSAFE_RECEIPT_FILE'):
            self.result()
        path.unlink()
        os.link(other, path)
        with self.assertRaisesRegex(RuntimeError, 'UNSAFE_RECEIPT_FILE'):
            self.result()
        path.unlink()
        other.rename(path)
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'UNSAFE_RECEIPT_FILE'):
            self.result()

    def test_sync_lock_contention_and_unsafe_mode(self):
        fd = os.open(self.lock, os.O_RDONLY)
        try:
            flock(fd, LOCK_EX | LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.result()
        finally:
            flock(fd, LOCK_UN)
            os.close(fd)
        self.lock.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'UNSAFE_SYNC_LOCK'):
            self.result()

    def test_duplicate_json_properties_rejected(self):
        path, _ = legacy(self.root)
        write_record(self.root, path.name, b'{"status":"SENT","status":"SENT"}')
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_JSON_FIELDS'):
            self.result()

    def test_no_new_files_on_success(self):
        legacy(self.root)
        before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.iterdir()}
        self.result()
        after = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.iterdir()}
        self.assertEqual(before, after)

    def test_static_no_mutations(self):
        source = MODULE.read_text()
        for prohibited in ('os.unlink(', '.unlink(', 'os.replace(', 'os.rename(',
                           '.mkdir(', 'os.mkdir(', 'shutil.move(', 'os.chown(', 'os.chmod('):
            self.assertNotIn(prohibited, source)
        self.assertIn('NO_FILES_CHANGED', source)
        self.assertIn('ARCHIVE_NOT_AUTHORIZED', source)


if __name__ == '__main__':
    unittest.main()
