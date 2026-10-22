#!/usr/bin/env python3
"""Bounded, no-atime, no-symlink-follow first-boot unit inspection on stopped CT790.

Reads only fixed paths under an independently verified already mounted ZFS
rootfs. Reports flags and states, never raw unit text, IDs, secrets, or keys.
No write, mount, process execution, OS configuration change or guest start.
"""
import json
import os
import re
import socket
import stat
import sys
from contextlib import ExitStack

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME | os.O_NONBLOCK
MAX_FILE_BYTES = 16384
MAX_DIR_ENTRIES = 128

class Blocked(Exception):
    pass

def require(test, reason):
    if not test:
        raise Blocked(reason)

def parent_fd(rootfd, names, stack):
    cursor = rootfd
    for name in names:
        try:
            fd = os.open(name, DIR_FLAGS, dir_fd=cursor)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise Blocked("UNREADABLE_OR_SYMLINK_PARENT") from exc
        stack.callback(os.close, fd)
        require(stat.S_ISDIR(os.fstat(fd).st_mode), "NON_DIRECTORY_PARENT")
        cursor = fd
    return cursor

def fixed_path(rootfd, path, parse_unit=False, directory=False, executable=False):
    parts = path.split("/")
    require(all(re.fullmatch(r"[A-Za-z0-9_.@-]+", part) for part in parts),
            "INVALID_FIXED_PATH")
    with ExitStack() as opened:
        parent = parent_fd(rootfd, parts[:-1], opened)
        if parent is None:
            return {"state": "ABSENT"}
        try:
            info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return {"state": "ABSENT"}
        if stat.S_ISLNK(info.st_mode):
            return {"state": "SYMLINK_PRESENT_TARGET_UNREAD"}
        if stat.S_ISDIR(info.st_mode):
            require(directory, "UNEXPECTED_DIRECTORY")
            fd = os.open(parts[-1], DIR_FLAGS, dir_fd=parent)
            opened.callback(os.close, fd)
            names = os.listdir(fd)
            require(len(names) <= MAX_DIR_ENTRIES, "DIRECTORY_ENTRY_BOUND_EXCEEDED")
            return {"state": "DIRECTORY_PRESENT",
                    "entries_count": len(names)}
        require(stat.S_ISREG(info.st_mode), "UNSUPPORTED_PATH_TYPE")
        require(not directory, "EXPECTED_DIRECTORY")
        if parse_unit:
            require(info.st_size <= MAX_FILE_BYTES, "UNIT_TOO_LARGE")
            fd = os.open(parts[-1], FILE_FLAGS, dir_fd=parent)
            opened.callback(os.close, fd)
            check = os.fstat(fd)
            require(stat.S_ISREG(check.st_mode)
                    and check.st_dev == info.st_dev
                    and check.st_ino == info.st_ino
                    and check.st_size == info.st_size,
                    "UNIT_CHANGED_DURING_READ")
            raw = os.read(fd, MAX_FILE_BYTES + 1)
            require(len(raw) == check.st_size, "UNIT_READ_INCOMPLETE")
            try:
                data = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise Blocked("INVALID_UNIT_ENCODING") from exc
            directives = [ln.strip() for ln in data.splitlines()
                          if ln.strip() and not ln.lstrip().startswith(("#", ";"))]
            return {
                "state": "REGULAR_UNIT_PRESENT",
                "sshd_keygen_target_referenced": any(
                    re.match(r"^(Wants|Requires|After|Before)=.*sshd-keygen[.]target", ln)
                    for ln in directives),
                "ssh_keygen_helper_executed": any(
                    re.match(r"^ExecStart(?:Pre)?=.*(?:sshd-keygen|ssh-keygen)", ln)
                    for ln in directives),
                "key_absence_condition_declared": any(
                    ln.startswith("ConditionPathExists=!/etc/ssh/ssh_host_")
                    for ln in directives),
                "first_boot_condition_yes": "ConditionFirstBoot=yes" in directives,
                "cloud_init_referenced": any("cloud-init" in ln for ln in directives),
                "masked_by_content": data.strip() == "/dev/null",
            }
        return {"state": "REGULAR_FILE_PRESENT",
                "executable_by_any": bool(info.st_mode & 0o111) if executable else False}

def inspect(root):
    require(os.geteuid() == 0
            and socket.gethostname().split(".")[0] == "venombox",
            "HOST_IDENTITY_OR_PRIVILEGE_MISMATCH")
    require(re.fullmatch(r"/rpool/data/subvol-790-disk-[0-9]+", root) is not None,
            "UNAPPROVED_ROOTFS_PATH")
    require(hasattr(os, "O_NOATIME"), "NOATIME_REQUIRED")
    units = {
        "sshd_vendor_service": "usr/lib/systemd/system/sshd.service",
        "sshd_vendor_keygen_target": "usr/lib/systemd/system/sshd-keygen.target",
        "sshd_vendor_keygen_template": "usr/lib/systemd/system/sshd-keygen@.service",
        "systemd_vendor_machine_id_commit": "usr/lib/systemd/system/systemd-machine-id-commit.service",
        "systemd_vendor_firstboot": "usr/lib/systemd/system/systemd-firstboot.service",
        "cloud_init_vendor_service": "usr/lib/systemd/system/cloud-init.service",
        "sshd_local_override": "etc/systemd/system/sshd.service",
        "sshd_keygen_template_override": "etc/systemd/system/sshd-keygen@.service",
    }
    links = {
        "sshd_enabled_multiuser": "etc/systemd/system/multi-user.target.wants/sshd.service",
        "vendor_keygen_rsa": "usr/lib/systemd/system/sshd-keygen.target.wants/sshd-keygen@rsa.service",
        "vendor_keygen_ecdsa": "usr/lib/systemd/system/sshd-keygen.target.wants/sshd-keygen@ecdsa.service",
        "vendor_keygen_ed25519": "usr/lib/systemd/system/sshd-keygen.target.wants/sshd-keygen@ed25519.service",
        "local_keygen_rsa": "etc/systemd/system/sshd-keygen.target.wants/sshd-keygen@rsa.service",
        "local_keygen_ecdsa": "etc/systemd/system/sshd-keygen.target.wants/sshd-keygen@ecdsa.service",
        "local_keygen_ed25519": "etc/systemd/system/sshd-keygen.target.wants/sshd-keygen@ed25519.service",
        "local_keygen_template_mask": "etc/systemd/system/sshd-keygen@.service",
    }
    dropins = {
        "sshd_local_dropins": "etc/systemd/system/sshd.service.d",
        "keygen_local_dropins": "etc/systemd/system/sshd-keygen@.service.d",
        "keygen_vendor_dropins": "usr/lib/systemd/system/sshd-keygen@.service.d",
    }
    executables = {
        "sshd_keygen_helper": "usr/libexec/openssh/sshd-keygen",
        "sshd_daemon": "usr/sbin/sshd",
        "ssh_keygen_binary": "usr/bin/ssh-keygen",
    }
    with ExitStack() as opened:
        fd = os.open(root, DIR_FLAGS)
        opened.callback(os.close, fd)
        require(stat.S_ISDIR(os.fstat(fd).st_mode), "UNEXPECTED_ROOTFS_TYPE")
        results = {
            "units": {key: fixed_path(fd, path, parse_unit=True)
                      for key, path in units.items()},
            "activation_links": {key: fixed_path(fd, path)
                                 for key, path in links.items()},
            "dropin_directories": {key: fixed_path(fd, path, directory=True)
                                   for key, path in dropins.items()},
            "executables": {key: fixed_path(fd, path, executable=True)
                            for key, path in executables.items()},
        }
    require(sum(len(section) for section in results.values()) == 22,
            "FIXED_ITEM_COUNT_MISMATCH")
    return {
        "result": "ROCKY_9_8_CT790_FIRSTBOOT_IDENTITY_UNITS_READ_ONLY_INVENTORIED",
        "vmid": 790,
        "fixed_paths": 22,
        **results,
        "firstboot_regeneration_proven": False,
        "sanitation_permitted": False,
        "raw_unit_text_or_secrets_disclosed": False,
        "files_written": 0,
        "mount_operations": 0,
        "guest_started": False,
        "pct_template_authorized": False,
    }

def main():
    try:
        require(len(sys.argv) == 2, "ONE_ROOTFS_PATH_REQUIRED")
        print(json.dumps(inspect(sys.argv[1]), sort_keys=True))
    except (Blocked, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, Blocked) else "UNEXPECTED_READ_ONLY_UNIT_AUDIT_ERROR"
        print(json.dumps({
            "result": "ROCKY_9_8_CT790_FIRSTBOOT_IDENTITY_UNITS_READ_ONLY_BLOCKED",
            "reason": code,
            "files_written": 0,
            "mount_operations": 0,
            "guest_started": False,
            "pct_template_authorized": False,
        }, sort_keys=True))
        raise SystemExit(1)

if __name__ == "__main__":
    main()
