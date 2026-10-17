#!/usr/bin/env python3
"""Explicit opt-in synthetic Synology Btrfs renameat2 check.

Default is READ ONLY. --probe creates a disposable private fixture directly
under one chosen filesystem root, runs the installed worker's renameat2
helper as paperless-sync, and deletes ONLY the fixture created in this run.
NEVER touches scanner input, protected archives, receipts, journals or gates.
"""
import argparse
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SITES = {
    "homes": ("Privat/thomas", "Privat/nadja"),
    "paperless-scan": ("Eltern", "Familie"),
}
ARCHIVE_NAME = ".bergen-paperless-archive"
GATES = ("archive-move.enabled", "archive-move.homes.enabled",
         "archive-move.paperless-scan.enabled")

UNPRIVILEGED_FIXTURE = r'''
import errno
import hashlib
import os
import pwd
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
site = sys.argv[2]
bindir = Path(sys.argv[3])
uid = pwd.getpwnam("paperless-sync").pw_uid
assert os.geteuid() == uid, "INCORRECT_UNPRIVILEGED_IDENTITY"
st = root.lstat()
assert stat.S_ISDIR(st.st_mode) and st.st_uid == uid
assert stat.S_IMODE(st.st_mode) == 0o700
sys.path.insert(0, str(bindir))
import synology_same_volume_archive_move as worker

src = root / "scan-fixture"
dst = root / "archive-fixture"
src.mkdir(mode=0o700)
dst.mkdir(mode=0o700)
payload = b"%PDF-1.4\nbergen-platform disposable rename proof\n%%EOF\n"
s = src / "test.pdf"
with s.open("xb") as f:
    f.write(payload)
    f.flush()
    os.fsync(f.fileno())
original = s.stat()
assert original.st_nlink == 1
existing = dst / "collision.pdf"
existing_payload = b"existing target must remain unmodified"
with existing.open("xb") as f:
    f.write(existing_payload)
    f.flush()
    os.fsync(f.fileno())

flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
srcfd = os.open(src, flags)
dstfd = os.open(dst, flags)
try:
    try:
        worker._noreplace_rename(srcfd, "test.pdf", dstfd, "collision.pdf")
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise
    else:
        raise RuntimeError("RENAME_NOREPLACE_COLLISION_NOT_REJECTED")
    assert s.read_bytes() == payload
    assert existing.read_bytes() == existing_payload
    print("SYNODB_RENAME_COLLISION_PROTECTED", site)

    worker._noreplace_rename(srcfd, "test.pdf", dstfd, "renamed.pdf")
    os.fsync(srcfd)
    os.fsync(dstfd)
    moved = dst / "renamed.pdf"
    updated = moved.stat()
    assert not s.exists(), "SOURCE_STILL_PRESENT"
    assert updated.st_ino == original.st_ino, "INODE_CHANGED"
    assert updated.st_dev == original.st_dev, "DEVICE_CHANGED"
    assert hashlib.sha256(moved.read_bytes()).digest() == hashlib.sha256(payload).digest()
    assert existing.read_bytes() == existing_payload
    print("SYNODB_RENAME_NOREPLACE_OK", site)
finally:
    os.close(srcfd)
    os.close(dstfd)
'''


def require(ok, error):
    if not ok:
        raise RuntimeError(error)


def check_dir(path, *, uid=None, mode=None, dev=None):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode), "UNSAFE_PROBE_DIRECTORY")
    require(uid is None or info.st_uid == uid, "WRONG_PROBE_OWNER")
    require(mode is None or stat.S_IMODE(info.st_mode) == mode, "WRONG_PROBE_MODE")
    require(dev is None or info.st_dev == dev, "PROBE_DEVICE_MISMATCH")
    with os.scandir(path):
        pass
    return info


def get_btrfs_command():
    for name in (shutil.which("btrfs"), "/sbin/btrfs", "/usr/sbin/btrfs",
                 "/usr/syno/bin/btrfs"):
        if name and Path(name).is_file() and os.access(name, os.X_OK):
            return name
    raise RuntimeError("BTRFS_TOOL_NOT_FOUND")


def subvol_id(binary, path):
    r = subprocess.run([binary, "inspect-internal", "rootid", str(path)],
                       check=False, capture_output=True, text=True, timeout=20)
    out = r.stdout.strip()
    require(r.returncode == 0 and re.fullmatch(r"[1-9][0-9]*", out),
            "UNVERIFIED_BTRFS_SUBVOLUME_ID")
    return out


def _synology_acl_tool():
    for path in ("/usr/syno/bin/synoacltool",
                 "/usr/syno/sbin/synoacltool", shutil.which("synoacltool")):
        if path and Path(path).is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError("SYNOACLTOOL_NOT_FOUND")


def _linux_acl_only(tool, fixture):
    result = subprocess.run([tool, "-get", str(fixture)], capture_output=True,
                            text=True, check=False, timeout=20)
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 255 and re.fullmatch(
        r"\(synoacltool\.c,\s*[0-9]+\)It's Linux mode", output) is not None


def _has_expected_inherited_dsm_acl(result):
    """Require exact version and archive flags, allowing only line-end padding.

    DSM appends spaces before the newline in its printed ACL header.
    Whitespace at the beginning, changed flags, wrong line order, stderr,
    and nonzero exit statuses still fail closed.
    """
    if result.returncode != 0 or result.stderr:
        return False
    lines = result.stdout.splitlines()
    return (len(lines) >= 2
            and lines[0].rstrip(" \t") == "ACL version: 1"
            and lines[1].rstrip(" \t") ==
            "Archive: is_inherit,is_support_ACL")


def _allowed_initial_fixture_mode(root, parent_info, mode):
    """Admit the confirmed 0711 DSM homes inheritance only at that site.

    /volume1/homes has a DSM-native ACL and POSIX mode 0711; newly created
    children inherit 0711 even if mkdtemp requests 0700. The special case
    is limited to the exact trusted home subvolume root and its verified
    root-owned 0711 parent. All other sites retain the previous policy.
    """
    if mode in (0o000, 0o700):
        return True
    return (root == Path("/volume1/homes")
            and parent_info.st_uid == 0
            and stat.S_ISDIR(parent_info.st_mode)
            and stat.S_IMODE(parent_info.st_mode) == 0o711
            and mode == 0o711)


def secure_new_fixture(fixture, root, original, service, device, btrfs, rootid):
    """Normalize only a newly created, inode-pinned, EMPTY fixture.

    Synology DSM may inherit native ACLs and report mode 0000 for a new
    directory under /volume1/<site>. Remove ACLs ONLY on our private,
    uniquely-created fixture, not on the device root or protected archives.
    Fail closed if DSM does not return strict Linux-mode afterwards.
    """
    require(fixture.parent == root and
            fixture.name.startswith(".bergen-rename-probe-"),
            "FIXTURE_NOT_ISOLATED")
    current = fixture.lstat()
    parent_info = root.lstat()
    require(stat.S_ISDIR(current.st_mode)
            and current.st_uid == 0
            and current.st_dev == device
            and current.st_ino == original.st_ino
            and _allowed_initial_fixture_mode(
                root, parent_info, stat.S_IMODE(current.st_mode)),
            "UNSAFE_NEW_FIXTURE")
    with os.scandir(fixture) as entries:
        require(next(entries, None) is None, "NONEMPTY_NEW_FIXTURE")

    tool = _synology_acl_tool()
    linux_mode = _linux_acl_only(tool, fixture)
    if stat.S_IMODE(current.st_mode) == 0o711:
        require(not linux_mode, "HOMES_INHERITED_ACL_REQUIRED")
    if not linux_mode:
        result = subprocess.run([tool, "-get", str(fixture)],
                                capture_output=True, text=True,
                                check=False, timeout=20)
        require(_has_expected_inherited_dsm_acl(result),
                "UNEXPECTED_INHERITED_FIXTURE_ACL")
        # Only the fixture just allocated by mkdtemp; no descendant entries.
        removed = subprocess.run([tool, "-del", str(fixture)],
                                 capture_output=True, text=True,
                                 check=False, timeout=20)
        require(removed.returncode == 0, "FIXTURE_ACL_REMOVAL_FAILED")
    os.chown(fixture, service.pw_uid, service.pw_gid)
    os.chmod(fixture, 0o700)
    updated = fixture.lstat()
    require(stat.S_ISDIR(updated.st_mode)
            and updated.st_ino == original.st_ino
            and updated.st_dev == device
            and updated.st_uid == service.pw_uid
            and stat.S_IMODE(updated.st_mode) == 0o700,
            "FIXTURE_NOT_PRIVATE_AFTER_ACL_NORMALIZATION")
    require(_linux_acl_only(tool, fixture),
            "FIXTURE_NATIVE_ACL_STILL_PRESENT")
    require(subvol_id(btrfs, fixture) == rootid,
            "FIXTURE_NOT_SAME_SUBVOLUME")


def cleanup_fixture(fixture, root, original, invoked, site):
    """Never delete beyond a single verified new synthetic fixture."""
    # Cleanup is guaranteed to be attempted even when the immediately
    # created fixture fails its initial UID/mode/device validation.
    # Only delete the precise directory created by this invocation.
    require(fixture.parent == root and
            fixture.name.startswith(".bergen-rename-probe-") and
            original is not None,
            "FIXTURE_CLEANUP_REQUIRES_MANUAL_REVIEW")
    current = fixture.lstat()
    require(stat.S_ISDIR(current.st_mode) and
            current.st_ino == original.st_ino and
            current.st_dev == original.st_dev,
            "FIXTURE_CLEANUP_REQUIRES_MANUAL_REVIEW")
    if not invoked:
        # Must be empty: do not recursively delete any unknown files
        # if the root-level directory was unsafe from the beginning.
        os.rmdir(fixture)
        print("ISOLATED_EMPTY_FIXTURE_CLEANED", site)
    else:
        # Known fixture structure only; unexpected paths block deletion.
        expected = {
            "scan-fixture": {"test.pdf"},
            "archive-fixture": {"collision.pdf", "renamed.pdf"},
        }
        with os.scandir(fixture) as stream:
            children = list(stream)
        require(all(c.name in expected and not c.is_symlink()
                    and c.is_dir(follow_symlinks=False) for c in children),
                "FIXTURE_UNEXPECTED_CONTENT_REQUIRES_MANUAL_REVIEW")
        for child in children:
            with os.scandir(child.path) as stream:
                require(all(f.name in expected[child.name] and
                            f.is_file(follow_symlinks=False) for f in stream),
                        "FIXTURE_UNEXPECTED_CONTENT_REQUIRES_MANUAL_REVIEW")
        shutil.rmtree(fixture)
        print("ISOLATED_RENAME_FIXTURE_CLEANED", site)
    require(not fixture.exists() and not fixture.is_symlink(),
            "FIXTURE_CLEANUP_INCOMPLETE")


def inspect(state_parent, site, probe):
    require(os.geteuid() == 0 and state_parent.is_absolute()
            and ".." not in state_parent.parts, "ROOT_REQUIRED")
    check_dir(state_parent, uid=0, mode=0o755)
    bindir = state_parent / "bin"
    check_dir(bindir, uid=0, mode=0o755)
    for name in GATES:
        gate = state_parent / name
        require(not gate.exists() and not gate.is_symlink(),
                "ARCHIVE_COMMIT_GATE_PRESENT")
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS
    require(SETTINGS["parent"] == state_parent
            and SETTINGS["sync_user"] == "paperless-sync"
            and len(SETTINGS["sources"]) == 4,
            "SITE_CONFIG_MISMATCH")
    service = pwd.getpwnam("paperless-sync")
    require(service.pw_uid != 0, "ROOT_SERVICE_IDENTITY")
    root = Path("/volume1") / site
    root_info = check_dir(root, uid=0)
    btrfs = get_btrfs_command()
    rootid = subvol_id(btrfs, root)
    sources = {scope: Path(folder) for folder, scope in SETTINGS["sources"]}
    require(len(sources) == 4
            and set(sources) == set(SITES["homes"] + SITES["paperless-scan"]),
            "BAD_CONFIGURED_SCOPES")
    archive = root / ARCHIVE_NAME
    check_dir(archive, uid=service.pw_uid, mode=0o700, dev=root_info.st_dev)
    require(subvol_id(btrfs, archive) == rootid,
            "PROTECTED_ARCHIVE_SUBVOLUME_CHANGED")
    for scope in SITES[site]:
        source = sources[scope]
        scopepath = archive.joinpath(*scope.split("/"))
        check_dir(source, dev=root_info.st_dev)
        check_dir(scopepath, uid=service.pw_uid, mode=0o700,
                  dev=root_info.st_dev)
        require(subvol_id(btrfs, source) == rootid
                and subvol_id(btrfs, scopepath) == rootid,
                "SOURCE_SCOPE_SUBVOLUME_CHANGED")
    print("SELECTED_SITE", site)
    print("PROTECTED_SUBVOLUME_ID", rootid)
    print("PROTECTED_SOURCE_SCOPES_VERIFIED", len(SITES[site]))
    if not probe:
        print("PROBE_DISABLED")
        print("NO_FILES_CHANGED")
        print("ARCHIVE_COMMIT_NOT_AUTHORIZED")
        return

    # Only mutable fixture: unique new private sibling of protected archive.
    fixture = Path(tempfile.mkdtemp(prefix=".bergen-rename-probe-", dir=root))
    original = None
    invoked = False
    try:
        original = fixture.lstat()
        secure_new_fixture(fixture, root, original, service,
                           root_info.st_dev, btrfs, rootid)
        invoked = True
        r = subprocess.run([
            "sudo", "-n", "-u", "paperless-sync", "/usr/bin/python3", "-c",
            UNPRIVILEGED_FIXTURE, str(fixture), site, str(bindir)],
            check=False, text=True, capture_output=True, timeout=60)
        if r.stdout:
            print(r.stdout, end="" if r.stdout.endswith("\n") else "\n")
        require(r.returncode == 0, "SYNODB_RENAME_PROBE_FAILED_" +
                str(r.returncode) + "_" +
                r.stderr.strip()[:220].replace(" ", "_"))
    finally:
        cleanup_fixture(fixture, root, original, invoked, site)
    print("PROTECTED_ARCHIVE_UNCHANGED")
    print("SCAN_AND_RECEIPTS_UNCHANGED")
    print("ARCHIVE_COMMIT_NOT_AUTHORIZED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Read-only audit or synthetic Synology rename probe")
    parser.add_argument("state_parent")
    parser.add_argument("--site", choices=tuple(SITES), required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--audit", action="store_true")
    modes.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    try:
        inspect(Path(args.state_parent), args.site, args.probe)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print("SYNODB_RENAME_PROBE_BLOCKED", str(exc)[:300], file=sys.stderr)
        sys.exit(1)
