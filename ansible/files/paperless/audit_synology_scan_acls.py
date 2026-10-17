#!/usr/bin/env python3
"""Read-only DSM ACL inspection for the four Paperless scan inputs.

Reports native Synology ACLs; it does not infer delete-child permission
from POSIX mode bits or os.access(). No filesystem or ACL mutation.
"""
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def acl_tool():
    candidates = (
        "/usr/syno/bin/synoacltool",
        "/usr/syno/sbin/synoacltool",
        shutil.which("synoacltool"),
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def classify_hidden_acl(result, info, expected_uid, source_device):
    """Allow only an exact, ACL-free POSIX-private archive; fail closed.

    Synology synoacltool returns 255 and '(synoacltool.c, N)It's Linux
    mode' when the target has no native DSM ACL. That is acceptable only
    for an actual nonsymlink directory owned by paperless-sync, mode 0700,
    on the same device as its scan parent. Native DSM ACLs require a
    separately reviewed policy: do not infer privacy from their presence.
    """
    if (not stat.S_ISDIR(info.st_mode)
            or info.st_uid != expected_uid
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_dev != source_device):
        return "UNSAFE_OWNER_MODE_TYPE_OR_DEVICE"
    combined = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    ).strip()
    if (result.returncode == 255 and
            re.fullmatch(r"\(synoacltool\.c,\s*[0-9]+\)It's Linux mode",
                         combined)):
        return "POSIX_PRIVATE"
    if result.returncode == 0:
        return "NATIVE_DSM_ACL_NEEDS_EXPLICIT_REVIEW"
    return "ACL_QUERY_FAILED"


def inspect(parent, require_hidden=False):
    if (not parent.is_absolute() or ".." in parent.parts or parent == Path("/")
            or str(parent) != os.path.normpath(str(parent))):
        raise RuntimeError("INVALID_PARENT")
    if os.geteuid() != 0:
        raise RuntimeError("ROOT_READ_ONLY_ACL_AUDIT_REQUIRED")
    bindir = parent / "bin"
    bs = bindir.lstat()
    if (not stat.S_ISDIR(bs.st_mode) or bs.st_uid != 0
            or stat.S_IMODE(bs.st_mode) != 0o755):
        raise RuntimeError("UNSAFE_CODE_DIRECTORY")
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS
    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    user = pwd.getpwnam(SETTINGS["sync_user"])
    if user.pw_uid == 0:
        raise RuntimeError("UNSAFE_SYNC_USER")
    tool = acl_tool()
    if tool is None:
        print("BLOCKER GLOBAL SYNOACLTOOL_NOT_FOUND")
        print("NO_FILES_CHANGED")
        return
    print("SYNC_IDENTITY", SETTINGS["sync_user"], "uid", user.pw_uid)
    if require_hidden:
        journal = SETTINGS["state"] / "archive-move-journal"
        try:
            journal_st = journal.lstat()
            if (not stat.S_ISDIR(journal_st.st_mode)
                    or journal_st.st_uid != user.pw_uid
                    or stat.S_IMODE(journal_st.st_mode) != 0o700):
                print("BLOCKER GLOBAL ARCHIVE_JOURNAL_UNSAFE")
            else:
                print("ARCHIVE_JOURNAL_PRESENT")
        except FileNotFoundError:
            print("BLOCKER GLOBAL ARCHIVE_JOURNAL_MISSING")
    for folder, scope in SETTINGS["sources"]:
        source = folder.lstat()
        if not stat.S_ISDIR(source.st_mode):
            raise RuntimeError("UNSAFE_SOURCE_DIRECTORY " + scope)
        candidate = folder / ".paperless-archive"
        print("SCOPE", scope)
        print("SOURCE_DEVICE", source.st_dev)
        print("SOURCE_MODE", oct(stat.S_IMODE(source.st_mode)))
        print("SOURCE_OWNER", source.st_uid, source.st_gid)
        missing = not candidate.exists() and not candidate.is_symlink()
        print("ARCHIVE_CANDIDATE", "ABSENT" if missing else "EXISTS_REVIEW")
        if require_hidden:
            if missing:
                print("BLOCKER", scope, "HIDDEN_ARCHIVE_MISSING")
            else:
                hidden = candidate.lstat()
                if (not stat.S_ISDIR(hidden.st_mode)
                        or hidden.st_uid != user.pw_uid
                        or stat.S_IMODE(hidden.st_mode) != 0o700
                        or hidden.st_dev != source.st_dev):
                    print("BLOCKER", scope, "HIDDEN_ARCHIVE_OWNER_MODE_OR_DEVICE")
        # The source ACL is what matters for creating/removing entries. The
        # parent ACL helps identify inherited grants and DSM Home behavior.
        targets = [("SOURCE", folder), ("PARENT", folder.parent)]
        if candidate.exists() or candidate.is_symlink():
            if candidate.is_symlink() or not candidate.is_dir():
                raise RuntimeError("UNSAFE_ARCHIVE_CANDIDATE " + scope)
            targets.append(("HIDDEN_ARCHIVE", candidate))
        for label, path in targets:
            st = path.lstat()
            if not stat.S_ISDIR(st.st_mode):
                raise RuntimeError("UNSAFE_ACL_PATH " + scope + " " + label)
            result = subprocess.run(
                [tool, "-get", str(path)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=20, check=False,
            )
            print("ACL_RESULT", scope, label, "rc=" + str(result.returncode))
            lines = (result.stdout + "\n" + result.stderr).splitlines()
            if not lines:
                print("ACL_EMPTY", scope, label)
            for line in lines[:100]:
                # Keep exact DSM ACE syntax for operator review, but prevent
                # multiline terminal injection and unbounded output.
                cleaned = "".join(c if c.isprintable() else "?" for c in line)
                print("ACL", scope, label, cleaned[:600])
            if len(lines) > 100:
                print("BLOCKER", scope, label, "ACL_OUTPUT_TRUNCATED")
            if label == "HIDDEN_ARCHIVE":
                status = classify_hidden_acl(result, st, user.pw_uid, source.st_dev)
                if status == "POSIX_PRIVATE":
                    print("HIDDEN_ARCHIVE_POSIX_PRIVATE", scope)
                    # Mode 0700 and no DSM ACL are strong local evidence,
                    # NOT a live effective user/SMB permissions acceptance.
                    print("EFFECTIVE_USER_ACCESS_TEST_REQUIRED", scope)
                else:
                    print("BLOCKER", scope, "HIDDEN_ARCHIVE_" + status)
            elif result.returncode != 0:
                print("BLOCKER", scope, label, "ACL_QUERY_FAILED")
        print("REVIEW_REQUIRED", scope, "SYNC_USER_DELETE_CHILD_RENAME_AND_ACL_INHERITANCE")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--require-hidden"):
        raise SystemExit("usage: audit_synology_scan_acls.py STATE_PARENT [--require-hidden]")
    inspect(Path(sys.argv[1]), require_hidden=(len(sys.argv) == 3))
