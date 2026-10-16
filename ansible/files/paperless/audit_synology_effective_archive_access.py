#!/usr/bin/env python3
"""Read-only effective NAS POSIX/NSS access test for protected paperless-scan archive.

Root orchestration resolves exact operator-selected NSS users. Each access
probe drops supplementary groups, resets them from NSS via initgroups, then
sets gid and uid before attempting ONLY directory opens/listing and os.access
queries. No create/rename/unlink/write tests, no SMB session. The native DSM
parent ACL and non-user rights still require independent checks. No commit.
"""
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from pathlib import Path

USER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*(?:@[A-Za-z0-9_.-]+)?\Z")
SITE = "paperless-scan"
SCOPES = ("Eltern", "Familie")

# Child is executed only after root has dropped to the selected UID/GID.
# Output deliberately contains no names, paths, or original PDF contents.
READ_ONLY_PROBE = r'''
import json
import os
import sys
from pathlib import Path
path = sys.argv[1]
try:
    descriptor = os.open(
        path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
except PermissionError:
    listed = False
else:
    try:
        os.listdir(descriptor)
        listed = True
    finally:
        os.close(descriptor)
write_access = os.access(path, os.W_OK | os.X_OK, effective_ids=True)
print(json.dumps({"list": listed, "write_access": write_access},
                 separators=(",", ":"), sort_keys=True))
'''


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def parse_names(raw):
    value = json.loads(raw)
    require(isinstance(value, list) and 2 <= len(value) <= 8 and
            all(isinstance(x, str) and USER_NAME.fullmatch(x)
                for x in value) and len(value) == len(set(value)),
            "REQUIRE_TWO_TO_EIGHT_EXPLICIT_NSS_IDENTITIES")
    return value


def parse_probe(stdout):
    result = json.loads(stdout)
    require(isinstance(result, dict) and set(result) == {"list", "write_access"}
            and all(type(value) is bool for value in result.values()),
            "INVALID_EFFECTIVE_PROBE_RESULT")
    return result


def probe(identity, path):
    """Run read-only probe after dropping all root privileges and groups."""
    def drop_identity():
        os.initgroups(identity.pw_name, identity.pw_gid)
        os.setgid(identity.pw_gid)
        os.setuid(identity.pw_uid)

    response = subprocess.run(
        [sys.executable, "-I", "-c", READ_ONLY_PROBE, str(path)],
        check=False, capture_output=True, text=True, timeout=15,
        preexec_fn=drop_identity)
    require(response.returncode == 0 and not response.stderr,
            "EFFECTIVE_PROBE_FAILED")
    return parse_probe(response.stdout)


def verdict(owner_results, denied_results):
    """Pure policy check; no filesystem interaction."""
    require(len(owner_results) == 3 and
            all(row == {"list": True, "write_access": True}
                for row in owner_results), "SYNC_OWNER_ARCHIVE_ACCESS_BLOCKED")
    require(len(denied_results) >= 2 and
            all(len(rows) == 3 for rows in denied_results) and
            all(row == {"list": False, "write_access": False}
                for rows in denied_results for row in rows),
            "NONOWNER_ARCHIVE_ACCESS_NOT_DENIED")
    return ["ARCHIVE_LOCAL_OWNER_ACCESS_VERIFIED",
            "ARCHIVE_LOCAL_NEGATIVE_IDENTITIES_DENIED " + str(len(denied_results)),
            "SMB_EFFECTIVE_ACCESS_NOT_TESTED",
            "ARCHIVE_COMMIT_NOT_AUTHORIZED", "NO_FILES_CHANGED"]


def audit(parent, denied_raw):
    require(os.geteuid() == 0 and parent.is_absolute() and
            parent != Path("/") and ".." not in parent.parts,
            "NAS_ROOT_READ_ONLY_AUDIT_REQUIRED")
    names = parse_names(denied_raw)
    bindir = parent / "bin"
    binstat = bindir.lstat()
    require(stat.S_ISDIR(binstat.st_mode) and binstat.st_uid == 0 and
            stat.S_IMODE(binstat.st_mode) == 0o755,
            "UNTRUSTED_SITE_CODE_DIRECTORY")
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS
    require(SETTINGS["parent"] == parent and
            SETTINGS["sync_user"] == "paperless-sync" and
            len(SETTINGS["sources"]) == 4,
            "UNTRUSTED_SITE_SETTINGS")

    owner = pwd.getpwnam(SETTINGS["sync_user"])
    require(owner.pw_uid != 0, "SYNC_USER_MUST_BE_NONROOT")
    others = [pwd.getpwnam(name) for name in names]
    require(all(identity.pw_uid not in (0, owner.pw_uid)
                for identity in others) and
            len({identity.pw_uid for identity in others}) == len(others),
            "DUPLICATE_OR_PRIVILEGED_NEGATIVE_IDENTITY")

    # The archive is OUTSIDE the scanner-writable source folder, but on
    # the exact same device. Use the reviewed directory logic for paths.
    import synology_same_volume_archive_move as move
    code = (bindir / "synology_same_volume_archive_move.py").lstat()
    require(stat.S_ISREG(code.st_mode) and code.st_uid == 0 and
            stat.S_IMODE(code.st_mode) == 0o644,
            "UNTRUSTED_WORKER")
    sources = {scope: path for path, scope in SETTINGS["sources"]}
    require(set(sources) == {"Eltern", "Familie", "Privat/thomas",
                            "Privat/nadja"}, "UNEXPECTED_SCOPES")
    targets = [move._validated_protected_scope(
        sources[scope], scope, owner.pw_uid) for scope in SCOPES]
    archive_root = targets[0].parent
    require(targets[1].parent == archive_root and
            archive_root.name == ".bergen-paperless-archive",
            "UNEXPECTED_PROTECTED_ARCHIVE_ROOT")
    rootfd = move._check_dir(archive_root, owner.pw_uid)
    os.close(rootfd)
    paths = [archive_root, *targets]
    owner_results = [probe(owner, path) for path in paths]
    denied_results = [[probe(person, path) for path in paths]
                      for person in others]
    print("SELECTED_SITE", SITE)
    for line in verdict(owner_results, denied_results):
        print(line)


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 3, "ARGUMENTS_REQUIRED")
        audit(Path(sys.argv[1]), sys.argv[2])
    except (OSError, ValueError, RuntimeError, TypeError,
            subprocess.TimeoutExpired):
        # Never disclose usernames, NSS records, or archive paths on failures.
        print("ARCHIVE_EFFECTIVE_LOCAL_ACCESS_BLOCKED", file=sys.stderr)
        sys.exit(1)
