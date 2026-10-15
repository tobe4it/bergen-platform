#!/usr/bin/env python3
"""Read-only, point-in-time receiver-side verifier for proposed Paperless v2.

Run only as paperless-ingest inside LXC 126, via a reviewed Proxmox pct
read-only audit. No installation, transfers, receipts or deletions.
A matching digest does NOT prove fresh creation, stable future existence,
Paperless import or permission to publish SENT.
"""
import hashlib
import os
import pwd
import re
import stat
import sys
from pathlib import Path

STAGING = Path("/srv/bergen-paperless/ingest-staging")
SCOPES = ("Privat/thomas", "Privat/nadja", "Eltern", "Familie")
FILENAME = re.compile(r"nas-v2-[a-f0-9]{32}-[a-f0-9]{64}\.pdf\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
MAX_BYTES = 512 * 1024 * 1024


def require(ok, error):
    if not ok:
        raise RuntimeError(error)


def identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_uid, st.st_gid,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def validated_directory(st, uid, mode):
    return (stat.S_ISDIR(st.st_mode) and st.st_uid == uid
            and stat.S_IMODE(st.st_mode) == mode and st.st_nlink >= 1)


def open_root(root, root_uid):
    before = root.lstat()
    require(validated_directory(before, root_uid, 0o750), "UNSAFE_STAGING_ROOT")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    if identity(before) != identity(os.fstat(fd)):
        os.close(fd)
        raise RuntimeError("STAGING_ROOT_REPLACED")
    return fd


def open_child_dir(parentfd, name, uid, mode):
    before = os.stat(name, dir_fd=parentfd, follow_symlinks=False)
    require(validated_directory(before, uid, mode), "UNSAFE_RECEIVER_DIRECTORY")
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                 dir_fd=parentfd)
    if identity(before) != identity(os.fstat(fd)):
        os.close(fd)
        raise RuntimeError("RECEIVER_DIRECTORY_REPLACED")
    return fd


def verify(root, scope, basename, digest, expected_bytes, *,
           root_uid=0, ingest_uid=None):
    """Read-only verification of the file under pinned, private directory fds.

    Expected digest and size must come from a separately validated PREPARED
    journal. They are not extracted from the untrusted receiver file.
    """
    if (scope not in SCOPES or type(scope) is not str
            or not isinstance(basename, str) or not FILENAME.fullmatch(basename)
            or not isinstance(digest, str) or not SHA256.fullmatch(digest)
            or type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_BYTES):
        raise ValueError("INVALID_RECEIVER_EXPECTATIONS")
    if not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts:
        raise ValueError("INVALID_RECEIVER_ROOT")
    if ingest_uid is None:
        ingest_uid = os.geteuid()
    rootfd = open_root(root, root_uid)
    try:
        parentfd = rootfd
        privfd = None
        if scope.startswith("Privat/"):
            privfd = open_child_dir(rootfd, "Privat", root_uid, 0o750)
            parentfd = privfd
        try:
            scopefd = open_child_dir(parentfd, scope.split("/")[-1], ingest_uid, 0o700)
            try:
                before = os.stat(basename, dir_fd=scopefd, follow_symlinks=False)
                require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                        and before.st_uid == ingest_uid
                        and stat.S_IMODE(before.st_mode) == 0o600
                        and before.st_size == expected_bytes,
                        "UNSAFE_RECEIVER_FILE")
                fd = os.open(basename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=scopefd)
                try:
                    require(identity(before) == identity(os.fstat(fd)),
                            "RECEIVER_FILE_CHANGED_BEFORE_READ")
                    sha = hashlib.sha256()
                    head, tail = b"", b""
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        while True:
                            part = stream.read(1024 * 1024)
                            if not part:
                                break
                            if not head:
                                head = part[:8]
                            tail = (tail + part)[-2048:]
                            sha.update(part)
                    require(identity(before) == identity(os.fstat(fd)),
                            "RECEIVER_FILE_CHANGED_DURING_READ")
                finally:
                    os.close(fd)
                require(identity(before) == identity(os.stat(
                    basename, dir_fd=scopefd, follow_symlinks=False)),
                    "RECEIVER_PATH_CHANGED_DURING_READ")
                require(sha.hexdigest() == digest, "RECEIVER_SHA256_MISMATCH")
                require(head.startswith(b"%PDF-") and b"%%EOF" in tail,
                        "RECEIVER_PDF_INVALID")
                return {
                    "receiver_sha256": sha.hexdigest(),
                    "receiver_bytes": expected_bytes,
                    "verified_at_point_in_time": True,
                    "new_file_confirmed": False,
                    "paperless_import_confirmed": False,
                    "source_delete_authorized": False,
                }
            finally:
                os.close(scopefd)
        finally:
            if privfd is not None:
                os.close(privfd)
    finally:
        os.close(rootfd)


def main(argv):
    if len(argv) != 4:
        raise ValueError("RECEIVER_AUDIT_ARGUMENTS_REQUIRED")
    user = pwd.getpwnam("paperless-ingest")
    require(os.geteuid() == user.pw_uid and os.geteuid() != 0,
            "RESTRICTED_RECEIVER_USER_REQUIRED")
    scope, name, digest, size = argv
    if not re.fullmatch(r"[1-9][0-9]{0,9}", size):
        raise ValueError("INVALID_RECEIVER_SIZE")
    result = verify(STAGING, scope, name, digest, int(size),
                    root_uid=0, ingest_uid=user.pw_uid)
    # Correlates the verified location, receiver basename, digest and size
    # with the sender's immutable PREPARED. This is NOT an attestation:
    # the future orchestrator must authenticate the origin of the output.
    binding = hashlib.sha256(
        (scope + "\0" + name + "\0" + result["receiver_sha256"] +
         "\0" + str(result["receiver_bytes"])).encode("utf-8")
    ).hexdigest()
    print("RECEIVER_BINDING", binding)
    print("RECEIVER_SHA256", result["receiver_sha256"])
    print("RECEIVER_BYTES", result["receiver_bytes"])
    print("RECEIVER_POINT_IN_TIME_VERIFIED")
    print("NEW_FILE_NOT_ATTESTED")
    print("PAPERLESS_IMPORT_NOT_ATTESTED")
    print("SENT_NOT_AUTHORIZED")
    print("SOURCE_DELETE_NOT_AUTHORIZED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (OSError, RuntimeError, ValueError) as exc:
        # No paths, private filenames or content are printed on a failure.
        print("RECEIVER_AUDIT_FAILED", str(exc).split(" ", 1)[0], file=sys.stderr)
        sys.exit(1)
