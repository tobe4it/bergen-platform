#!/usr/bin/env python3
"""Synology scan-to-Paperless staging synchronizer.

Default is a dry-run. --commit copies stable, regular PDFs via the already
restricted SSH/rsync identity. No input files are deleted or renamed.
A periodic invocation (DSM Task Scheduler) also catches missed events.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

SOURCES = (
    (Path("/volume1/homes/@LH-BERGEN.INTERN/61/thomas-1000001/Paperless"), "Privat/thomas"),
    (Path("/volume1/homes/@LH-BERGEN.INTERN/61/nadja-1000003/Paperless"), "Privat/nadja"),
    (Path("/volume1/paperless-scan/Eltern"), "Eltern"),
    (Path("/volume1/paperless-scan/Familie"), "Familie"),
)
HOME = Path.home()
STATE_ROOT = Path("/volume1")
STATE_PARENT = STATE_ROOT / ".bergen-platform-state"
STATE = STATE_PARENT / "paperless-sync"
IDENTITY = HOME / ".ssh" / "id_ed25519_paperless_ingest"
DESTINATION = "paperless-ingest@bergen-paperless"
QUIET_SECONDS = 60
MAX_SIZE = 512 * 1024 * 1024
MAX_FILES_PER_RUN = 100


def secure_state():
    os.umask(0o077)
    # DSM Home directories can appear world-writable (0777) with Synology
    # ACLs. The sync receipts must not live below such a directory.
    # Provision STATE_PARENT as root:root 0755 and STATE as
    # paperless-sync:users 0700 separately, before any sync run.
    # Nothing is auto-created or chmodded here: fail closed on bad paths.
    for path, owner, mode in (
        (STATE_ROOT, 0, 0o755),
        (STATE_PARENT, 0, 0o755),
        (STATE, os.geteuid(), 0o700),
    ):
        info = path.lstat()  # Also rejects symlink components.
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner
                or stat.S_IMODE(info.st_mode) != mode):
            raise RuntimeError("UNSAFE_STATE_DIRECTORY " + str(path))


def metadata(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
        raise RuntimeError("UNSAFE_SOURCE " + str(path))
    if not 0 < s.st_size <= MAX_SIZE:
        raise RuntimeError("INVALID_SIZE " + str(path))
    return s


def signature(s):
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def snapshot(path, target):
    before = metadata(path)
    if time.time_ns() - max(before.st_mtime_ns, before.st_ctime_ns) < QUIET_SECONDS * 1000000000:
        return None
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    first = b""
    last = b""
    try:
        opened = os.fstat(fd)
        if signature(opened) != signature(before):
            return None
        with os.fdopen(fd, "rb") as source, open(target, "xb") as dest:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                if not first:
                    first = block[:8]
                last = (last + block)[-2048:]
                digest.update(block)
                dest.write(block)
            dest.flush()
            os.fsync(dest.fileno())
        after = metadata(path)
        if signature(after) != signature(before):
            return None
        if not first.startswith(b"%PDF-") or b"%%EOF" not in last:
            raise RuntimeError("INVALID_PDF " + str(path))
        return digest.hexdigest(), signature(before)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def receipt_path(scope, name):
    key = hashlib.sha256((scope + "\0" + name).encode("utf-8")).hexdigest()
    return STATE / (key + ".json")


def read_receipt(path):
    if not path.exists():
        return None
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o600:
        raise RuntimeError("UNSAFE_RECEIPT " + str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") not in ("PREPARED", "SENT"):
        raise RuntimeError("UNKNOWN_RECEIPT_STATE " + str(path))
    return data


def write_receipt(path, item):
    with tempfile.NamedTemporaryFile(mode="w", dir=STATE, prefix=".receipt-",
                                     encoding="utf-8", delete=False) as tmp:
        temporary = Path(tmp.name)
        try:
            json.dump(item, tmp, sort_keys=True)
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)
    dirfd = os.open(str(STATE), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def send(snap, filename, scope):
    ssh = "ssh -i " + shlex.quote(str(IDENTITY)) + (
        " -o BatchMode=yes -o IdentitiesOnly=yes"
        " -o StrictHostKeyChecking=yes -o ConnectTimeout=15"
    )
    result = subprocess.run(
        ["rsync", "-av", "--ignore-existing", "--out-format=%i %n", "-e", ssh,
         str(snap), DESTINATION + ":" + scope + "/"],
        check=True, timeout=900, capture_output=True, text=True,
        encoding="utf-8", errors="surrogateescape",
    )
    # rsync --ignore-existing can return exit code 0 without writing a file!
    # On the local rsync SENDER, <f+++++++++ indicates the newly created\n    # regular file sent to the receiver (not >f+++++++++, which is inbound).\n    # Require exactly one record for the intended basename.
    # In the ambiguous crash-after-transfer-before-receipt case this rejects
    # and requires operator reconciliation instead of falsely saying SENT.
    expected = "<f+++++++++ " + filename
    if result.stdout.splitlines().count(expected) != 1:
        # Keep diagnostic output for review rather than accepting an ambiguous
        # success. Escape line endings and bound the length.
        raise RuntimeError(
            "RSYNC_NOT_CONFIRMED_NEW_FILE " + scope + "/" + filename
            + " stdout=" + repr(result.stdout[-1200:])
            + " stderr=" + repr(result.stderr[-400:])
        )


def acknowledge_verified_import(only, expected_digest, bridge_receipt):
    """Manual repair after independent receipt + SHA256 verification.

    Never transfers a file. The operator must have separately verified the
    destination checksum and a bridge receipt with status IMPORTED.
    """
    if os.geteuid() == 0:
        raise RuntimeError("DO_NOT_RUN_AS_ROOT")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise RuntimeError("INVALID_EXPECTED_SHA256")
    if not re.fullmatch(r"[a-f0-9]{24}", bridge_receipt):
        raise RuntimeError("INVALID_BRIDGE_RECEIPT")
    secure_state()
    sources = [
        (folder / only[len(scope) + 1:], scope)
        for folder, scope in SOURCES
        if only.startswith(scope + "/")
        and "/" not in only[len(scope) + 1:]
    ]
    if len(sources) != 1:
        raise RuntimeError("INVALID_APPROVED_SOURCE")
    path, scope = sources[0]
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise RuntimeError("SOURCE_NOT_FOUND")
    with (STATE / "sync.lock").open("a+") as lock:
        flock(lock, LOCK_EX | LOCK_NB)
        receipt = receipt_path(scope, path.name)
        if receipt.exists() or receipt.is_symlink():
            raise RuntimeError("MANUAL_REVIEW_EXISTING_RECEIPT " + receipt.name)
        with tempfile.TemporaryDirectory(dir=STATE, prefix="snapshot-") as tmpdir:
            checked = snapshot(path, Path(tmpdir) / "snapshot.pdf")
        if checked is None:
            raise RuntimeError("SOURCE_NOT_STABLE")
        actual_digest, source_signature = checked
        if actual_digest != expected_digest:
            raise RuntimeError("SOURCE_SHA256_CHANGED")
        stem = re.sub(r"[^\w. -]", "_", path.stem, flags=re.UNICODE).strip(" ._-")[:120] or "scan"
        filename = stem + "--nas-" + actual_digest + ".pdf"
        write_receipt(receipt, {
            "status": "SENT",
            "scope": scope,
            "source": path.name,
            "destination": scope + "/" + filename,
            "sha256": actual_digest,
            "signature": source_signature,
            "reconciled_at": time.time(),
            "manually_confirmed_imported": True,
            "bridge_receipt": bridge_receipt + ".json",
        })
        print("ACKNOWLEDGED_VERIFIED_IMPORT", only, "bridge=" + bridge_receipt)


def scan(commit, only=None):
    if os.geteuid() == 0:
        raise RuntimeError("DO_NOT_RUN_AS_ROOT")
    secure_state()
    if commit and not IDENTITY.is_file():
        raise RuntimeError("MISSING_SSH_IDENTITY")
    with (STATE / "sync.lock").open("a+") as lock:
        flock(lock, LOCK_EX | LOCK_NB)
        processed = 0
        failures = []
        for folder, scope in SOURCES:
            ds = folder.lstat()
            if not stat.S_ISDIR(ds.st_mode):
                raise RuntimeError("UNSAFE_SOURCE_DIR " + str(folder))
            for path in sorted(folder.iterdir()):
                if path.name.startswith(".") or path.suffix.lower() != ".pdf":
                    continue
                if only is not None and scope + "/" + path.name != only:
                    continue
                try:
                    st = metadata(path)
                    if time.time_ns() - max(st.st_mtime_ns, st.st_ctime_ns) < QUIET_SECONDS * 1000000000:
                        print("WAIT", scope + "/" + path.name)
                        continue
                    receipt_file = receipt_path(scope, path.name)
                    old = read_receipt(receipt_file)
                    if old is not None:
                        if old["status"] == "PREPARED":
                            raise RuntimeError("MANUAL_REVIEW_PREPARED " + scope + "/" + path.name)
                        if old.get("signature") == signature(st):
                            print("TRACKED", scope + "/" + path.name)
                            continue
                        # Do not silently overwrite proof of a different
                        # source version with the same path.
                        raise RuntimeError("MANUAL_REVIEW_SOURCE_CHANGED " + scope + "/" + path.name)
                    if processed >= MAX_FILES_PER_RUN:
                        print("DEFERRED", scope + "/" + path.name,
                              "(new-candidate limit reached)")
                        continue
                    processed += 1
                    with tempfile.TemporaryDirectory(dir=STATE, prefix="snapshot-") as tmpdir:
                        snap = Path(tmpdir) / "snapshot.pdf"
                        checked = snapshot(path, snap)
                        if checked is None:
                            print("WAIT", scope + "/" + path.name)
                            continue
                        checksum, source_signature = checked
                        stem = re.sub(r"[^\w. -]", "_", path.stem, flags=re.UNICODE).strip(" ._-")[:120] or "scan"
                        filename = stem + "--nas-" + checksum + ".pdf"
                        if not commit:
                            print("READY", scope + "/" + path.name, "->", scope + "/" + filename)
                            continue
                        if not IDENTITY.is_file():
                            raise RuntimeError("MISSING_SSH_IDENTITY")
                        remote_snapshot = Path(tmpdir) / filename
                        snap.rename(remote_snapshot)
                        # Write-ahead journal: after a crash or uncertain rsync
                        # outcome never automatically retry the same filename.
                        prepared = {
                            "status": "PREPARED",
                            "scope": scope,
                            "source": path.name,
                            "destination": scope + "/" + filename,
                            "sha256": checksum,
                            "signature": source_signature,
                            "prepared_at": time.time(),
                        }
                        write_receipt(receipt_file, prepared)
                        send(remote_snapshot, filename, scope)
                        prepared["status"] = "SENT"
                        prepared["sent_at"] = time.time()
                        write_receipt(receipt_file, prepared)
                        print("SENT", scope + "/" + path.name, "->", scope + "/" + filename)
                except Exception as exc:
                    print("REJECTED", scope + "/" + path.name, str(exc), file=sys.stderr)
                    failures.append(scope + "/" + path.name)
        if failures:
            raise RuntimeError("SYNC_FAILED: " + ", ".join(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="actually rsync eligible snapshots")
    parser.add_argument("--only", metavar="SCOPE/FILENAME",
                        help="process exactly one approved PDF (fail if not found)")
    parser.add_argument("--ack-verified-import", action="store_true",
                        help="operator-only journal repair; never sends any file")
    parser.add_argument("--expected-sha256",
                        help="verified remote SHA256, required with --ack-verified-import")
    parser.add_argument("--bridge-receipt",
                        help="24-character ID of independently verified IMPORTED bridge receipt")
    args = parser.parse_args()
    if args.only is not None:
        matches = [
            folder / name for folder, scope in SOURCES
            for name in [args.only[len(scope) + 1:]]
            if args.only.startswith(scope + "/")
            and name and "/" not in name and name not in (".", "..")
        ]
        if len(matches) != 1 or not matches[0].is_file():
            parser.error("--only must refer to an existing PDF in an enabled directory")
    if args.ack_verified_import:
        if args.commit or not args.only or not args.expected_sha256 or not args.bridge_receipt:
            parser.error("--ack-verified-import requires --only, --expected-sha256 and --bridge-receipt, never --commit")
        acknowledge_verified_import(args.only, args.expected_sha256, args.bridge_receipt)
    else:
        if args.expected_sha256 or args.bridge_receipt:
            parser.error("verified-import proof arguments require --ack-verified-import")
        scan(args.commit, args.only)
