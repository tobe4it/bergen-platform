#!/usr/bin/env python3
"""Offline-only crash-safe, no-overwrite store for DELETED_BY_USER v2.

No CLI, production path, directory creation, Ansible invocation or live
integration. Call only after independently obtaining *fresh* live proofs and
separate explicit approval to persist a record.
"""
import os
import stat
import tempfile
from pathlib import Path

from deleted_by_user_decision_journal import canonical, validate


def _open_private_directory(directory):
    if (not isinstance(directory, Path) or not directory.is_absolute()
            or directory == Path("/") or ".." in directory.parts):
        raise ValueError("ABSOLUTE_PRIVATE_JOURNAL_DIRECTORY_REQUIRED")
    st = directory.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o700):
        raise RuntimeError("UNSAFE_JOURNAL_DIRECTORY")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    actual = os.fstat(fd)
    if (actual.st_dev != st.st_dev or actual.st_ino != st.st_ino
            or not stat.S_ISDIR(actual.st_mode)
            or actual.st_uid != os.geteuid()
            or stat.S_IMODE(actual.st_mode) != 0o700):
        os.close(fd)
        raise RuntimeError("JOURNAL_DIRECTORY_CHANGED")
    return fd


def _existing_matches(dirfd, filename, payload):
    st = os.stat(filename, dir_fd=dirfd, follow_symlinks=False)
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
            or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600
            or st.st_size != len(payload)):
        raise RuntimeError("UNSAFE_OR_CONFLICTING_JOURNAL_RECORD")
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
    try:
        actual = os.fstat(fd)
        if (actual.st_dev != st.st_dev or actual.st_ino != st.st_ino
                or actual.st_nlink != 1 or actual.st_size != len(payload)):
            raise RuntimeError("JOURNAL_RECORD_CHANGED")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            if stream.read(len(payload) + 1) != payload:
                raise RuntimeError("CONFLICTING_JOURNAL_RECORD")
    finally:
        os.close(fd)


def publish_once(directory, record):
    """Publish canonical JSON durably and idempotently.

    Returns (path, created). Only the temporary file created by *this call*
    may be unlinked. Never removes or overwrites a published decision. A
    failure after hard-link publication may still leave a valid decision:
    retry with the same record and inspect it before taking further action.
    """
    event_id = validate(record)
    payload = canonical(record)
    dirfd = _open_private_directory(directory)
    temporary = None
    try:
        target = event_id + ".json"
        fd, temporary = tempfile.mkstemp(
            prefix=".deleted-by-user-", suffix=".tmp", dir=directory
        )
        try:
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb", closefd=False) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(fd)
            try:
                # Hard-link is an atomic, no-overwrite publication within
                # the same filesystem. Never use os.replace here.
                os.link(temporary, target, dst_dir_fd=dirfd,
                        follow_symlinks=False)
                created = True
            except FileExistsError:
                _existing_matches(dirfd, target, payload)
                created = False
            os.fsync(dirfd)
            return directory / target, created
        finally:
            if temporary is not None:
                os.unlink(temporary)
                os.fsync(dirfd)
    finally:
        os.close(dirfd)


__all__ = ["publish_once"]
