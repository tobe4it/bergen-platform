#!/usr/bin/env python3
"""No-write exact first-boot sanitation target proof for stopped CT790.

Runs via python3 -c after same-run stopped/ZFS provenance checks. No host-key,
machine-ID or arbitrary directory entry content or names in results. Never
follows a symlink, modifies atime, mounts, executes guest processes or writes.
"""
import json
import os
import re
import socket
import stat
import sys
from contextlib import ExitStack

D = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME
MAX_DIR = 1024
KEY_TYPES = ("rsa", "ecdsa", "ed25519")
EXACT_FILES = (
    "etc/machine-id",
    "var/lib/systemd/random-seed",
    "var/lib/systemd/timers/stamp-dnf-makecache.timer",
) + tuple("etc/ssh/ssh_host_" + t + "_key" + suffix
          for t in KEY_TYPES for suffix in ("", ".pub"))
DIRECTORIES = (
    "etc/ssh",
    "var/lib/systemd/timers",
    "var/cache/dnf",
    "var/lib/dnf",
    "var/lib/NetworkManager",
)
class Refusal(Exception):
    pass

def require(cond, code):
    if not cond:
        raise Refusal(code)

def parent_dirfd(rootfd, parts, stack):
    cur = rootfd
    for p in parts:
        try:
            fd = os.open(p, D, dir_fd=cur)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise Refusal("PARENT_UNSAFE_OR_UNREADABLE") from exc
        stack.callback(os.close, fd)
        require(stat.S_ISDIR(os.fstat(fd).st_mode), "NON_DIRECTORY_PARENT")
        cur = fd
    return cur

def target_stat(rootfd, rel, root_uid):
    parts = rel.split("/")
    require(all(re.fullmatch("[A-Za-z0-9_.-]+", p) for p in parts),
            "FIXED_PATH_INVALID")
    with ExitStack() as stack:
        fd = parent_dirfd(rootfd, parts[:-1], stack)
        if fd is None:
            return {"state": "ABSENT"}
        try:
            s = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return {"state": "ABSENT"}
        if stat.S_ISLNK(s.st_mode):
            return {"state": "SYMLINK_NOT_FOLLOWED"}
        require(stat.S_ISREG(s.st_mode), "UNEXPECTED_SPECIAL_FILE")
        return {
            "state": "REGULAR_FILE_PRESENT",
            "size_nonzero": s.st_size > 0,
            "one_hardlink": s.st_nlink == 1,
            "uid_matches_rootfs": s.st_uid == root_uid,
            "private_permissions_ok": (s.st_mode & 0o077) == 0,
        }

def fixed_directory(rootfd, rel, expected_names=None):
    parts = rel.split("/")
    with ExitStack() as stack:
        p = parent_dirfd(rootfd, parts[:-1], stack)
        if p is None:
            return {"state": "ABSENT"}
        try:
            fd = os.open(parts[-1], D, dir_fd=p)
        except FileNotFoundError:
            return {"state": "ABSENT"}
        except OSError as exc:
            raise Refusal("DIRECTORY_UNREADABLE_OR_SYMLINK") from exc
        stack.callback(os.close, fd)
        require(stat.S_ISDIR(os.fstat(fd).st_mode), "NON_DIRECTORY")
        names = os.listdir(fd)
        require(len(names) <= MAX_DIR, "DIRECTORY_LISTING_UNBOUNDED")
        result = {"state": "DIRECTORY_PRESENT", "top_level_entries": len(names)}
        if expected_names is not None:
            matched = set(names) & set(expected_names)
            result["expected_key_names_count"] = len(matched)
            result["unrecognized_host_key_name_count"] = sum(
                name.startswith("ssh_host_") and
                (name.endswith("_key") or name.endswith("_key.pub")) and
                name not in expected_names for name in names)
        return result

def inventory(root):
    require(os.geteuid() == 0 and
            socket.gethostname().split(".")[0] == "venombox",
            "HOST_OR_PRIVILEGE_MISMATCH")
    require(re.fullmatch(r"/rpool/data/subvol-790-disk-[0-9]+", root) is not None,
            "UNAUTHORIZED_CT790_ROOTFS")
    require(hasattr(os, "O_NOATIME"), "NOATIME_NOT_AVAILABLE")
    with ExitStack() as stack:
        rootfd = os.open(root, D)
        stack.callback(os.close, rootfd)
        rs = os.fstat(rootfd)
        require(stat.S_ISDIR(rs.st_mode), "ROOTFS_NOT_DIRECTORY")
        exact = {rel: target_stat(rootfd, rel, rs.st_uid)
                 for rel in EXACT_FILES}
        keynames = tuple("ssh_host_" + t + "_key" + suff
                         for t in KEY_TYPES for suff in ("", ".pub"))
        dirs = {rel: fixed_directory(rootfd, rel, keynames if rel == "etc/ssh" else None)
                for rel in DIRECTORIES}
        keyfiles = {k: exact[k] for k in exact if k.startswith("etc/ssh/")}
        pairs = all(
            keyfiles["etc/ssh/ssh_host_" + t + "_key"]["state"] == "REGULAR_FILE_PRESENT"
            and keyfiles["etc/ssh/ssh_host_" + t + "_key.pub"]["state"] == "REGULAR_FILE_PRESENT"
            for t in KEY_TYPES
        )
        return {
            "result": "ROCKY_9_8_CT790_EXACT_SANITATION_TARGETS_READ_ONLY_INVENTORIED",
            "vmid": 790,
            "fixed_files_inspected": len(EXACT_FILES),
            "fixed_directories_inspected": len(DIRECTORIES),
            "machine_id_metadata": exact["etc/machine-id"],
            "random_seed_metadata": exact["var/lib/systemd/random-seed"],
            "dnf_timer_stamp_metadata": exact["var/lib/systemd/timers/stamp-dnf-makecache.timer"],
            "host_key_files": keyfiles,
            "host_key_exact_pairs_present": pairs,
            "directory_metadata": dirs,
            "ssh_key_contents_read": False,
            "machine_id_contents_read": False,
            "arbitrary_names_disclosed": False,
            "files_written": 0,
            "mount_operations": 0,
            "guest_started": False,
            "sanitation_authorized": False,
            "template_authorized": False,
        }

def main():
    try:
        require(len(sys.argv) == 2, "EXACTLY_ONE_ROOTDIR_REQUIRED")
        print(json.dumps(inventory(sys.argv[1]), sort_keys=True))
    except (Refusal, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Refusal) else "METADATA_READ_ERROR"
        print(json.dumps({
            "result": "ROCKY_9_8_CT790_EXACT_SANITATION_TARGETS_READ_ONLY_BLOCKED",
            "reason": reason,
            "files_written": 0,
            "guest_started": False,
            "template_authorized": False,
        }, sort_keys=True))
        raise SystemExit(1)

if __name__ == "__main__":
    main()
