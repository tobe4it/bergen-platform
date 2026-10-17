#!/usr/bin/env python3
"""Conservative staging-to-consume publisher for Bergen Paperless.

No source files are deleted. A durable journal precedes publication.
A PREPARED receipt with no destination must be reconciled manually.
"""
import argparse
import hashlib
import json
import os
import pwd
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from fcntl import flock, LOCK_EX, LOCK_NB

STAGING = Path('/srv/bergen-paperless/ingest-staging')
CONSUME = Path('/srv/bergen-paperless/consume')
STATE = Path('/srv/bergen-paperless/ingest-bridge-state')
ENABLED = ('Privat/thomas', 'Privat/nadja', 'Eltern', 'Familie')
WAIT_SECONDS = 60
MAX_BYTES = 512 * 1024 * 1024


def check_dir(path, uid, mode):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or (info.st_mode & 0o777) != mode:
        raise RuntimeError(f'UNSAFE_DIRECTORY {path}')


def fingerprint(path, owner):
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1 or initial.st_uid != owner:
        raise RuntimeError(f'UNSAFE_FILE {path}')
    if not (0 < initial.st_size <= MAX_BYTES):
        raise RuntimeError(f'INVALID_SIZE {path}')
    if (time.time_ns() - max(initial.st_mtime_ns, initial.st_ctime_ns)) < WAIT_SECONDS * 1_000_000_000:
        return None
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns
        ):
            return None
        digest = hashlib.sha256()
        head = b''
        tail = b''
        with os.fdopen(fd, 'rb', closefd=False) as src:
            while part := src.read(1024 * 1024):
                if not head:
                    head = part[:8]
                tail = (tail + part)[-2048:]
                digest.update(part)
        final = path.lstat()
        if (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns,
            final.st_ctime_ns) != (initial.st_dev, initial.st_ino, initial.st_size,
                                    initial.st_mtime_ns, initial.st_ctime_ns):
            return None
        if not head.startswith(b'%PDF-') or b'%%EOF' not in tail:
            raise RuntimeError(f'INVALID_PDF {path}')
        return initial, digest.hexdigest()
    finally:
        os.close(fd)


def publish(source, relative, fingerprint_data):
    info, digest = fingerprint_data
    token = hashlib.sha256(
        f'{relative}\0{info.st_size}\0{info.st_mtime_ns}\0{digest}'.encode()
    ).hexdigest()[:24]
    receipt = STATE / 'receipts' / f'{token}.json'
    target_name = f'{source.stem[:150]}--bp-{token}.pdf'
    dest = CONSUME / relative.parent / target_name
    if receipt.exists():
        print(f'TRACKED {relative}: {receipt.name}')
        return
    if dest.exists():
        raise RuntimeError(f'DESTINATION_ALREADY_EXISTS {dest}')
    if DRY_RUN:
        print(f'READY {relative} -> {dest.relative_to(CONSUME)}')
        return
    # Write in a private sibling directory, never in the consumer's watched tree.
    fd, tmp_name = tempfile.mkstemp(prefix='pending-', dir=STATE / 'tmp')
    tmp = Path(tmp_name)
    try:
        src_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(src_fd, 'rb') as src, os.fdopen(fd, 'wb') as out:
            shutil.copyfileobj(src, out, length=1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        with tmp.open('rb') as check:
            copied_hasher = hashlib.sha256()
            while chunk := check.read(1024 * 1024):
                copied_hasher.update(chunk)
        copied = copied_hasher.hexdigest()
        if copied != digest:
            raise RuntimeError(f'CHANGED_DURING_COPY {source}')
        new_info = source.lstat()
        if (new_info.st_dev, new_info.st_ino, new_info.st_size,
            new_info.st_mtime_ns, new_info.st_ctime_ns) != (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
        ):
            raise RuntimeError(f'SOURCE_CHANGED {source}')
        os.chown(tmp, 1000, 1000)
        os.chmod(tmp, 0o640)
        receipt_obj = dict(source=str(relative), destination=str(dest.relative_to(CONSUME)),
                           sha256=digest, status='PREPARED', created=time.time())
        # Journal is committed BEFORE the file becomes visible to the consumer.
        write_receipt(receipt, receipt_obj)
        os.link(tmp, dest)  # Atomic publication, never overwrite another document.
        fsync_dir(dest.parent)
        receipt_obj['status'] = 'SUBMITTED'
        write_receipt(receipt, receipt_obj)
        print(f'SUBMITTED {relative} -> {dest.relative_to(CONSUME)}')
    finally:
        tmp.unlink(missing_ok=True)


def write_receipt(receipt, obj):
    with tempfile.NamedTemporaryFile(mode='w', dir=receipt.parent,
                                     prefix='.receipt-', delete=False) as out:
        temp = Path(out.name)
        json.dump(obj, out)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, receipt)
    fsync_dir(receipt.parent)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise RuntimeError('RUN_AS_ROOT_REQUIRED')
    ingest_uid = pwd.getpwnam('paperless-ingest').pw_uid
    check_dir(STAGING, 0, 0o750)
    check_dir(STAGING / 'Privat', 0, 0o750)
    check_dir(CONSUME, 1000, 0o750)
    check_dir(CONSUME / 'Privat', 1000, 0o750)
    for subdir in ENABLED:
        check_dir(STAGING / subdir, ingest_uid, 0o700)
        check_dir(CONSUME / subdir, 1000, 0o750)
    check_dir(STATE, 0, 0o700)
    for child in ('tmp', 'receipts'):
        check_dir(STATE / child, 0, 0o700)
    if STATE.stat().st_dev != CONSUME.stat().st_dev:
        raise RuntimeError('STATE_AND_CONSUME_MUST_SHARE_FILESYSTEM')
    lock = STATE / 'bridge.lock'
    with open(lock, 'a+') as lockfd:
        flock(lockfd, LOCK_EX | LOCK_NB)
        for subdir in ENABLED:
            for source in sorted((STAGING / subdir).iterdir()):
                rel = source.relative_to(STAGING)
                if source.name.startswith('.') or source.suffix.lower() != '.pdf':
                    print(f'IGNORED {rel} (not a PDF candidate)')
                    continue
                try:
                    details = fingerprint(source, ingest_uid)
                    if details is None:
                        print(f'WAIT {rel} (not stable for {WAIT_SECONDS}s)')
                    else:
                        publish(source, rel, details)
                except Exception as exc:
                    print(f'REJECTED {rel}: {exc}', file=sys.stderr)
                    ERRORS.append(str(rel))
        if ERRORS:
            raise RuntimeError('UNSAFE_OR_FAILED_INPUTS: ' + ', '.join(ERRORS))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', action='store_true', help='Journal and deliver eligible PDFs')
    args = parser.parse_args()
    DRY_RUN = not args.commit
    ERRORS = []
    main()
