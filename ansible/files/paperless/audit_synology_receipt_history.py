#!/usr/bin/env python3
"""Read-only, locked v1/v2 Synology sender receipt inventory.

The script is streamed over SSH/stdin; never installed on the NAS. It does
not read source PDFs, publish acknowledgements, or grant archive permission.
"""
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

SHA = re.compile(r'[a-f0-9]{64}\Z')
V1 = re.compile(r'([a-f0-9]{64})\.json\Z')
V2 = re.compile(r'(v2-[a-f0-9]{64})\.(prepared|sent)\.json\Z')
NAME = re.compile(r'[^\w. -]', flags=re.UNICODE)
MAX_ENTRIES = 10000
MAX_BYTES = 8192
LEGACY_REQUIRED = {'scope', 'source', 'status', 'sha256', 'signature', 'destination'}
LEGACY_OPTIONAL = {'prepared_at', 'sent_at', 'reconciled_at',
                   'manually_confirmed_imported', 'bridge_receipt',
                   'document_id', 'recovery_reason'}
V2_REQUIRED = {'schema_version', 'receipt_id', 'status', 'scope', 'source',
               'sha256', 'signature', 'destination', 'incarnation_nonce'}


def reject(code):
    raise RuntimeError(code)


def valid_source(scope, source, scopes):
    if (scope not in scopes or not isinstance(source, str)
            or source in ('', '.', '..') or '\x00' in source
            or '/' in source or '\\' in source
            or not source.lower().endswith('.pdf')
            or len(source.encode('utf-8')) > 255):
        reject('INVALID_RECEIPT_IDENTITY')


def signature_ok(value):
    return (isinstance(value, list) and len(value) == 5
            and all(type(part) is int and part >= 0 for part in value))


def common(record, scopes):
    if not isinstance(record, dict):
        reject('NOT_A_RECEIPT_OBJECT')
    scope, source = record.get('scope'), record.get('source')
    valid_source(scope, source, scopes)
    digest, signature = record.get('sha256'), record.get('signature')
    if not isinstance(digest, str) or not SHA.fullmatch(digest) or not signature_ok(signature):
        reject('INVALID_DIGEST_OR_SIGNATURE')
    return scope, source, digest, signature


def v2_id(scope, source, digest, signature):
    payload = ['bergen-paperless-receipt-v2', scope, source, digest, signature]
    canonical = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return 'v2-' + hashlib.sha256(canonical).hexdigest()


def strict_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            reject('DUPLICATE_JSON_FIELDS')
        out[key] = value
    return out


def read_private(dirfd, name, owner):
    old = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    if (not stat.S_ISREG(old.st_mode) or old.st_uid != owner or old.st_nlink != 1
            or stat.S_IMODE(old.st_mode) != 0o600 or not 0 < old.st_size <= MAX_BYTES):
        reject('UNSAFE_RECEIPT_FILE')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
    try:
        actual = os.fstat(fd)
        if (actual.st_dev != old.st_dev or actual.st_ino != old.st_ino
                or actual.st_mode != old.st_mode or actual.st_uid != old.st_uid
                or actual.st_nlink != 1 or actual.st_size != old.st_size):
            reject('RECEIPT_CHANGED_DURING_READ')
        with os.fdopen(fd, 'rb', closefd=False) as inp:
            raw = inp.read(MAX_BYTES + 1)
        if len(raw) != old.st_size:
            reject('RECEIPT_SHORT_READ')
    finally:
        os.close(fd)
    try:
        obj = json.loads(raw, object_pairs_hook=strict_pairs)
    except (ValueError, UnicodeError, TypeError):
        reject('RECEIPT_JSON_INVALID')
    return obj, raw


def audit_directory(directory, scopes, *, expected_owner=None):
    """Offline-testable audit. Caller must ensure sender uses this same lock."""
    if (not isinstance(directory, Path) or not directory.is_absolute()
            or directory == Path('/') or '..' in directory.parts):
        reject('INVALID_STATE_DIRECTORY')
    owner = os.geteuid() if expected_owner is None else expected_owner
    ds = directory.lstat()
    if (not stat.S_ISDIR(ds.st_mode) or ds.st_uid != owner
            or stat.S_IMODE(ds.st_mode) != 0o700):
        reject('UNSAFE_STATE_DIRECTORY')
    dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(dirfd)
        if (opened.st_dev != ds.st_dev or opened.st_ino != ds.st_ino
                or opened.st_uid != ds.st_uid or opened.st_mode != ds.st_mode):
            reject('STATE_DIRECTORY_CHANGED')
        lock_stat = os.stat('sync.lock', dir_fd=dirfd, follow_symlinks=False)
        if (not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != owner
                or lock_stat.st_nlink != 1 or stat.S_IMODE(lock_stat.st_mode) != 0o600):
            reject('UNSAFE_SYNC_LOCK')
        lockfd = os.open('sync.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
        try:
            locked = os.fstat(lockfd)
            if (locked.st_dev != lock_stat.st_dev or locked.st_ino != lock_stat.st_ino
                    or locked.st_uid != lock_stat.st_uid or locked.st_mode != lock_stat.st_mode):
                reject('SYNC_LOCK_CHANGED')
            flock(lockfd, LOCK_EX | LOCK_NB)
            names = os.listdir(dirfd)
            if len(names) > MAX_ENTRIES:
                reject('STATE_ENTRY_LIMIT_EXCEEDED')
            counts = {scope: {'v1_sent': 0, 'v1_prepared': 0,
                              'v2_sent': 0, 'v2_prepared': 0} for scope in scopes}
            v2_events = {}
            for name in sorted(names):
                v1, v2 = V1.fullmatch(name), V2.fullmatch(name)
                if not v1 and not v2:
                    if (name.endswith('.json') or name.startswith('.receipt-')
                            or name.startswith('.v2-receipt-')):
                        reject('UNKNOWN_OR_ORPHANED_JOURNAL_ENTRY')
                    continue  # existing sync/watcher locks and non-receipt state
                item, raw = read_private(dirfd, name, owner)
                scope, source, digest, signature = common(item, counts)
                if v1:
                    if (not LEGACY_REQUIRED <= set(item)
                            or not set(item) <= LEGACY_REQUIRED | LEGACY_OPTIONAL
                            or item['status'] not in ('PREPARED', 'SENT')):
                        reject('INVALID_LEGACY_RECEIPT_SCHEMA')
                    # Historical recovery script publishes additional metadata
                    # only after independently verified Paperless IMPORTED proof.
                    # Accept that known shape, but reject partial/forged repairs.
                    if 'document_id' in item or 'recovery_reason' in item:
                        if (item['status'] != 'SENT'
                                or item.get('manually_confirmed_imported') is not True
                                or type(item.get('document_id')) is not int
                                or item['document_id'] <= 0
                                or item.get('recovery_reason') != 'verified_paperless_import'
                                or not isinstance(item.get('bridge_receipt'), str)
                                or not re.fullmatch(r'[a-f0-9]{24}\.json', item['bridge_receipt'])
                                or type(item.get('sent_at')) not in (int, float)
                                or type(item.get('reconciled_at')) not in (int, float)):
                            reject('INVALID_LEGACY_REPAIR_METADATA')
                    legacy_key = hashlib.sha256((scope + '\0' + source).encode('utf-8')).hexdigest()
                    if v1.group(1) != legacy_key:
                        reject('LEGACY_FILENAME_MISMATCH')
                    stem = NAME.sub('_', Path(source).stem).strip(' ._-')[:120] or 'scan'
                    if item['destination'] != scope + '/' + stem + '--nas-' + digest + '.pdf':
                        reject('LEGACY_DESTINATION_MISMATCH')
                    counts[scope]['v1_' + item['status'].lower()] += 1
                else:
                    stage = v2.group(2).upper()
                    keys = V2_REQUIRED | ({'transfer_evidence'} if stage == 'SENT' else set())
                    if set(item) != keys or type(item['schema_version']) is not int or item['schema_version'] != 2:
                        reject('INVALID_V2_RECEIPT_SCHEMA')
                    event_id = v2_id(scope, source, digest, signature)
                    if (v2.group(1) != event_id or item['receipt_id'] != event_id
                            or item['status'] != stage
                            or item['destination'] != scope + '/nas-' + event_id + '.pdf'
                            or not isinstance(item['incarnation_nonce'], str)
                            or not re.fullmatch(r'[0-9a-f]{32}', item['incarnation_nonce'])):
                        reject('INVALID_V2_RECEIPT_IDENTITY')
                    if stage == 'SENT':
                        proof = item['transfer_evidence']
                        if (not isinstance(proof, dict) or set(proof) != {
                                'receiver_source', 'receiver_sha256', 'new_file_confirmed'}
                                or proof['receiver_source'] != item['destination']
                                or proof['receiver_sha256'] != digest
                                or proof['new_file_confirmed'] is not True):
                            reject('INVALID_V2_TRANSFER_EVIDENCE')
                    expected = (json.dumps(item, sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
                    if raw != expected:
                        reject('NONCANONICAL_V2_EVENT')
                    v2_events.setdefault(event_id, {})[stage] = item
                    counts[scope]['v2_' + stage.lower()] += 1
            for event in v2_events.values():
                if 'SENT' in event and 'PREPARED' not in event:
                    reject('SENT_WITHOUT_PREPARED')
                if 'SENT' in event:
                    sent = dict(event['SENT'])
                    sent.pop('transfer_evidence')
                    sent['status'] = 'PREPARED'
                    if sent != event['PREPARED']:
                        reject('PREPARED_SENT_MISMATCH')
            blockers = sum(c['v1_prepared'] + (c['v2_prepared'] - c['v2_sent'])
                           for c in counts.values())
            return {'counts': counts, 'total_receipts': sum(sum(c.values()) for c in counts.values()),
                    'total_v1_sent': sum(c['v1_sent'] for c in counts.values()),
                    'unresolved': blockers, 'can_archive': False}
        finally:
            os.close(lockfd)
    finally:
        os.close(dirfd)


def main(parent):
    if (not parent.is_absolute() or '..' in parent.parts or parent == Path('/')
            or str(parent) != os.path.normpath(str(parent))):
        reject('INVALID_STATE_PARENT')
    sys.path.insert(0, str(parent / 'bin'))
    from synology_config import SETTINGS
    from synology_scan_sync import secure_state
    if SETTINGS['parent'] != parent:
        reject('CONFIG_PARENT_MISMATCH')
    user = pwd.getpwnam(SETTINGS['sync_user'])
    if user.pw_uid == 0 or os.geteuid() != user.pw_uid:
        reject('SYNC_USER_REQUIRED')
    secure_state()
    report = audit_directory(SETTINGS['state'], tuple(scope for _path, scope in SETTINGS['sources']))
    for scope, stats in report['counts'].items():
        print('SCOPE', scope, 'V1_SENT', stats['v1_sent'], 'V1_PREPARED', stats['v1_prepared'],
              'V2_PREPARED', stats['v2_prepared'], 'V2_SENT', stats['v2_sent'])
    print('TOTAL_JOURNAL_EVENTS', report['total_receipts'])
    print('TOTAL_V1_SENT', report['total_v1_sent'])
    print('UNRESOLVED_JOURNAL_EVENTS', report['unresolved'])
    print('HISTORY_AUDIT_COMPLETE')
    print('ARCHIVE_NOT_AUTHORIZED')
    print('NO_FILES_CHANGED')


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            reject('STATE_PARENT_REQUIRED')
        main(Path(sys.argv[1]))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        # Do not echo any source path or private record contents.
        print('HISTORY_AUDIT_FAILED', str(exc).split(' ', 1)[0], file=sys.stderr)
        sys.exit(1)
