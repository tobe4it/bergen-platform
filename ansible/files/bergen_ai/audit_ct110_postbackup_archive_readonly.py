#!/usr/bin/env python3
"""Read-only CT110 post-vzdump inventory after Ansible postcheck failed.

One bounded, sanitized JSON frame. No vzdump, archive reads/writes or guest
mutations. Finding a nonempty archive does NOT attest integrity or restore.
"""
import json
import re
import subprocess

FRAME = "BERGEN_AI_CT110_POSTBACKUP_INVENTORY_V1:"
STORAGE = "bergen-synology-backup"
MOUNT = "/mnt/pve/" + STORAGE
PREFIX = STORAGE + ":backup/"
ARCHIVE = re.compile(r"^vzdump-lxc-110-\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.tar\.zst$")


def command(argv, max_bytes=1200000):
    try:
        p = subprocess.run(argv, capture_output=True, timeout=20, check=False)
        if p.returncode or len(p.stdout) > max_bytes:
            return None
        return p.stdout.decode("utf-8", "strict")
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def parsed_json(argv):
    raw = command(argv)
    try:
        return json.loads(raw) if raw is not None else None
    except (ValueError, TypeError):
        return None


def check_guest():
    state = command(["pct", "status", "110"], 300)
    return "RUNNING" if state is not None and state.strip() == "status: running" else "NOT_VERIFIED_RUNNING"


def check_storage():
    mounts = parsed_json(["findmnt", "-J", "-M", MOUNT])
    fs = mounts.get("filesystems") if isinstance(mounts, dict) else None
    if not isinstance(fs, list) or len(fs) != 1 or not isinstance(fs[0], dict):
        return "UNVERIFIED"
    if fs[0].get("target") != MOUNT or fs[0].get("fstype") not in {"nfs", "nfs4"}:
        return "WRONG_OR_UNMOUNTED_TARGET"
    status = parsed_json(["pvesh", "get",
                          "/nodes/venombox/storage/" + STORAGE + "/status",
                          "--output-format", "json"])
    if not isinstance(status, dict) or status.get("active") not in (True, 1):
        return "PVE_STORAGE_UNVERIFIED"
    if "backup" not in str(status.get("content", "")).split(","):
        return "BACKUP_CONTENT_UNVERIFIED"
    return "EXPECTED_ACTIVE_NFS"


def check_archive():
    content = parsed_json(["pvesh", "get",
                           "/nodes/venombox/storage/" + STORAGE + "/content",
                           "--content", "backup", "--output-format", "json"])
    if not isinstance(content, list) or len(content) > 10000:
        return dict(CT110_ARCHIVE_COUNT="UNVERIFIED",
                    CT110_ARCHIVE_METADATA="UNVERIFIED")
    selected = []
    for item in content:
        if not isinstance(item, dict) or not isinstance(item.get("volid"), str):
            return dict(CT110_ARCHIVE_COUNT="UNVERIFIED",
                        CT110_ARCHIVE_METADATA="UNVERIFIED")
        volid = item["volid"]
        if re.search(r"(?:/|:)vzdump-lxc-110-", volid):
            selected.append(item)
    count = len(selected)
    if count != 1:
        return dict(CT110_ARCHIVE_COUNT=count,
                    CT110_ARCHIVE_METADATA="NONE" if count == 0 else "MULTIPLE")
    item = selected[0]
    volid = item["volid"]
    if not volid.startswith(PREFIX) or not ARCHIVE.fullmatch(volid[len(PREFIX):]):
        return dict(CT110_ARCHIVE_COUNT=count,
                    CT110_ARCHIVE_METADATA="UNEXPECTED_FORMAT_OR_STORAGE")
    if type(item.get("size")) is not int or item["size"] <= 0:
        return dict(CT110_ARCHIVE_COUNT=count,
                    CT110_ARCHIVE_METADATA="EMPTY_OR_UNKNOWN_SIZE")
    return dict(CT110_ARCHIVE_COUNT=1,
                CT110_ARCHIVE_METADATA="ONE_NONEMPTY_ZSTD_ARCHIVE_VISIBLE")


def report():
    guest = check_guest()
    storage = check_storage()
    archive = check_archive() if storage == "EXPECTED_ACTIVE_NFS" else dict(
        CT110_ARCHIVE_COUNT="UNVERIFIED", CT110_ARCHIVE_METADATA="UNVERIFIED")
    status = "ARCHIVE_PRESENT_NOT_VALIDATED" if (
        guest == "RUNNING" and storage == "EXPECTED_ACTIVE_NFS" and
        archive["CT110_ARCHIVE_COUNT"] == 1 and
        archive["CT110_ARCHIVE_METADATA"] == "ONE_NONEMPTY_ZSTD_ARCHIVE_VISIBLE"
    ) else "REVIEW_REQUIRED"
    return dict(AUDIT="READ_ONLY", STATUS=status, CHANGED=False,
                CT110_STATE=guest, BACKUP_TARGET=storage,
                **archive,
                BACKUP_EXECUTED_BY_THIS_AUDIT=False,
                ARCHIVE_CONTENTS_CHECKED=False,
                BACKUP_INTEGRITY="NOT_TESTED",
                RESTORE_TEST="NOT_ATTESTED",
                ROLLBACK_CLEARANCE="NOT_PROVEN",
                NETWORK_CHANGES="NONE",
                APPLY_AUTHORIZED=False)


def main():
    try:
        result = report()
    except Exception:
        result = dict(AUDIT="READ_ONLY", STATUS="UNVERIFIED",
                      CHANGED=False, CT110_STATE="UNVERIFIED",
                      BACKUP_TARGET="UNVERIFIED", CT110_ARCHIVE_COUNT="UNVERIFIED",
                      CT110_ARCHIVE_METADATA="UNVERIFIED",
                      BACKUP_EXECUTED_BY_THIS_AUDIT=False,
                      ARCHIVE_CONTENTS_CHECKED=False,
                      BACKUP_INTEGRITY="NOT_TESTED", RESTORE_TEST="NOT_ATTESTED",
                      ROLLBACK_CLEARANCE="NOT_PROVEN",
                      NETWORK_CHANGES="NONE", APPLY_AUTHORIZED=False)
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
