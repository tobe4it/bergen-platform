#!/usr/bin/env python3
"""Read exactly two pinned published DELETED_BY_USER v2 records as paperless-ingest.

Read-only; checks path, ownership, mode, link count, canonical bytes and
the two independently reviewed journal SHA256 values. Rejects unknown records.
"""
import hashlib
import json
import os
import pwd
import stat
from pathlib import Path

DIRECTORY = Path("/var/lib/paperless-ingest/deletion-decisions")
EVENTS = {
    15: ("2a6d73664436c1a3e0432d7a07911feab86ba2a617a185b81bc30580fdd67e90",
         "7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b"),
    26: ("f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26",
         "5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a"),
}


def read():
    user = pwd.getpwnam("paperless-ingest")
    if (os.geteuid() != 997 or os.getegid() != 988
            or user.pw_uid != 997 or user.pw_gid != 988):
        raise RuntimeError("RESTRICTED_JOURNAL_READER_REQUIRED")
    parent = os.lstat(DIRECTORY.parent)
    root = os.lstat("/")
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
            or parent.st_gid != 988 or stat.S_IMODE(parent.st_mode) != 0o750
            or parent.st_dev != root.st_dev):
        raise RuntimeError("UNSAFE_JOURNAL_PARENT")
    st = os.lstat(DIRECTORY)
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 997 or st.st_gid != 988
            or stat.S_IMODE(st.st_mode) != 0o700 or st.st_dev != root.st_dev):
        raise RuntimeError("UNSAFE_JOURNAL_DIRECTORY")
    dirfd = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        actual = os.fstat(dirfd)
        if (actual.st_ino != st.st_ino or actual.st_dev != st.st_dev
                or actual.st_uid != 997 or actual.st_gid != 988
                or stat.S_IMODE(actual.st_mode) != 0o700):
            raise RuntimeError("JOURNAL_DIRECTORY_CHANGED")
        expected_names = {event + ".json" for event, sha in EVENTS.values()}
        if set(os.listdir(dirfd)) != expected_names:
            raise RuntimeError("UNKNOWN_OR_MISSING_DELETION_JOURNAL")
        records = []
        for document_id, (event, digest) in sorted(EVENTS.items()):
            name = event + ".json"
            entry = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
            if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != 997
                    or entry.st_gid != 988 or entry.st_nlink != 1
                    or stat.S_IMODE(entry.st_mode) != 0o600
                    or entry.st_size <= 0 or entry.st_size > 8192):
                raise RuntimeError("UNSAFE_JOURNAL_ENTRY")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
            try:
                opened = os.fstat(fd)
                if (opened.st_ino != entry.st_ino or opened.st_dev != entry.st_dev
                        or opened.st_nlink != 1 or opened.st_uid != 997
                        or opened.st_gid != 988 or opened.st_size != entry.st_size
                        or stat.S_IMODE(opened.st_mode) != 0o600):
                    raise RuntimeError("JOURNAL_ENTRY_CHANGED")
                raw = os.read(fd, 8193)
            finally:
                os.close(fd)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise RuntimeError("JOURNAL_CONTENT_SHA256_MISMATCH")
            obj = json.loads(raw)
            canonical = (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True) + "\n").encode("ascii")
            if (raw != canonical or not isinstance(obj, dict)
                    or obj.get("event") != "DELETED_BY_USER"
                    or obj.get("event_id") != event
                    or type(obj.get("document_id")) is not int
                    or obj["document_id"] != document_id):
                raise RuntimeError("JOURNAL_NOT_CANONICAL_OR_WRONG_EVENT")
            records.append(obj)
    finally:
        os.close(dirfd)
    for record in records:
        print(json.dumps(record, sort_keys=True, ensure_ascii=True))
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    read()
