#!/usr/bin/env python3
"""Read-only, no-atime, no-symlink-follow CT790 stopped-rootfs sanitation survey.

Execute only on the already verified Proxmox host via python3 -c with one
exact volume path. Never print file contents, identifiers, filenames from
untrusted directory listings, file hashes, host keys, URLs or timestamps.
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
MAX_DIR_ENTRIES = 1024
MAX_MACHINE_ID_BYTES = 128

class Refused(Exception):
    pass

def demand(value, reason):
    if not value:
        raise Refused(reason)

def check_root(root):
    demand(re.fullmatch(r"/rpool/data/subvol-790-disk-[0-9]+", root) is not None,
           "UNAPPROVED_ROOTFS_PATH")
    demand(os.geteuid() == 0 and socket.gethostname().split(".")[0] == "venombox",
           "UNAPPROVED_HOST_OR_UID")
    demand(hasattr(os, "O_NOATIME"), "NOATIME_UNAVAILABLE")

def open_parent(rootfd, components, opened):
    cursor = rootfd
    for name in components:
        try:
            nextfd = os.open(name, DIR_FLAGS, dir_fd=cursor)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise Refused("NONREGULAR_OR_UNREADABLE_PATH_COMPONENT") from exc
        opened.callback(os.close, nextfd)
        demand(stat.S_ISDIR(os.fstat(nextfd).st_mode), "NON_DIRECTORY_COMPONENT")
        cursor = nextfd
    return cursor

def inspect_path(rootfd, rel, want_machine_id=False, count_dir=False, ssh_keys=False):
    parts = rel.split("/")
    demand(all(re.fullmatch(r"[a-zA-Z0-9_.-]+", p) for p in parts),
           "UNSAFE_FIXED_PATH")
    with ExitStack() as opened:
        parent = open_parent(rootfd, parts[:-1], opened)
        if parent is None:
            return {"state": "ABSENT"}
        try:
            st = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return {"state": "ABSENT"}
        if stat.S_ISLNK(st.st_mode):
            return {"state": "SYMLINK_NOT_FOLLOWED"}
        if stat.S_ISREG(st.st_mode):
            if count_dir or ssh_keys:
                raise Refused("EXPECTED_DIRECTORY")
            result = {"state": "REGULAR_FILE_PRESENT", "size_nonzero": st.st_size > 0}
            if want_machine_id:
                demand(st.st_size <= MAX_MACHINE_ID_BYTES, "MACHINE_ID_SIZE_UNEXPECTED")
                fd = os.open(parts[-1], FILE_FLAGS, dir_fd=parent)
                opened.callback(os.close, fd)
                fst = os.fstat(fd)
                demand(stat.S_ISREG(fst.st_mode) and fst.st_ino == st.st_ino
                       and fst.st_dev == st.st_dev and fst.st_size == st.st_size,
                       "MACHINE_ID_CHANGED_DURING_READ")
                raw = os.read(fd, MAX_MACHINE_ID_BYTES + 1)
                demand(len(raw) == fst.st_size, "MACHINE_ID_READ_MISMATCH")
                try:
                    value = raw.decode("ascii").strip()
                except UnicodeDecodeError:
                    value = None
                result = {"state": (
                    "EMPTY" if not value and value is not None
                    else "UNINITIALIZED" if value == "uninitialized"
                    else "ZERO_32HEX" if value == "0" * 32
                    else "SET_32HEX" if value is not None and
                         re.fullmatch(r"[0-9a-fA-F]{32}", value)
                    else "NONSTANDARD_PRESENT"
                )}
            return result
        if not stat.S_ISDIR(st.st_mode):
            return {"state": "OTHER_TYPE_PRESENT"}
        fd = os.open(parts[-1], DIR_FLAGS, dir_fd=parent)
        opened.callback(os.close, fd)
        demand(stat.S_ISDIR(os.fstat(fd).st_mode), "DIRECTORY_CHANGED_DURING_READ")
        names = os.listdir(fd)
        demand(len(names) <= MAX_DIR_ENTRIES, "DIRECTORY_ENTRIES_EXCEED_BOUND")
        if ssh_keys:
            host_private = sum(bool(re.fullmatch(r"ssh_host_[A-Za-z0-9_-]+_key", name))
                               for name in names)
            host_public = sum(bool(re.fullmatch(r"ssh_host_[A-Za-z0-9_-]+_key[.]pub", name))
                               for name in names)
            return {"state": "DIRECTORY_PRESENT",
                    "ssh_host_private_key_name_count": host_private,
                    "ssh_host_public_key_name_count": host_public}
        if count_dir:
            return {"state": "DIRECTORY_PRESENT", "top_level_entries": len(names)}
        return {"state": "DIRECTORY_PRESENT"}

def survey(root):
    check_root(root)
    with ExitStack() as opened:
        rootfd = os.open(root, DIR_FLAGS)
        opened.callback(os.close, rootfd)
        demand(stat.S_ISDIR(os.fstat(rootfd).st_mode), "ROOTFS_NOT_DIRECTORY")
        exact = {
            "etc_machine_id": ("etc/machine-id", True, False, False),
            "dbus_machine_id": ("var/lib/dbus/machine-id", True, False, False),
            "systemd_random_seed": ("var/lib/systemd/random-seed", False, False, False),
            "ssh_host_keys": ("etc/ssh", False, False, True),
            "persistent_journal": ("var/log/journal", False, True, False),
            "dnf_package_cache": ("var/cache/dnf", False, True, False),
            "dnf_runtime_state": ("var/lib/dnf", False, True, False),
            "network_manager_runtime": ("var/lib/NetworkManager", False, True, False),
            "network_manager_connections": ("etc/NetworkManager/system-connections",
                                            False, True, False),
            "dhcp_state": ("var/lib/dhcp", False, True, False),
            "cloud_init_state": ("var/lib/cloud", False, True, False),
            "systemd_timers_state": ("var/lib/systemd/timers", False, True, False),
        }
        result = {label: inspect_path(rootfd, rel, machine, directory, ssh)
                  for label, (rel, machine, directory, ssh) in exact.items()}
        return {
            "result": "ROCKY_9_8_CT790_STOPPED_ROOTFS_SANITATION_READ_ONLY_INVENTORIED",
            "vmid": 790,
            "inspected_fixed_paths": len(exact),
            "categories": result,
            "template_sanitation": "REVIEW_REQUIRED_NO_CHANGES_AUTHORIZED",
            "raw_machine_ids_disclosed": False,
            "raw_host_key_material_disclosed": False,
            "files_written": 0,
            "atime_updates_requested": False,
            "mount_operations": 0,
            "pct_start_authorized": False,
            "pct_template_authorized": False,
        }

def main():
    try:
        demand(len(sys.argv) == 2, "ONE_ROOTFS_PATH_REQUIRED")
        print(json.dumps(survey(sys.argv[1]), sort_keys=True))
    except (Refused, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, Refused) else "UNEXPECTED_READ_ONLY_INVENTORY_ERROR"
        print(json.dumps({
            "result": "ROCKY_9_8_CT790_STOPPED_ROOTFS_SANITATION_READ_ONLY_BLOCKED",
            "reason": code,
            "files_written": 0,
            "mount_operations": 0,
            "pct_start_authorized": False,
            "pct_template_authorized": False,
        }, sort_keys=True))
        raise SystemExit(1)

if __name__ == "__main__":
    main()
