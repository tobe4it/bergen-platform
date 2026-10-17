#!/usr/bin/env python3
"""Read-only SHA-256 check for two pinned Paperless deletion journals in vzdump."""
import argparse
import hashlib
import re
import stat
import subprocess
import sys
from pathlib import Path

VMID = "126"
STORAGE = Path("/mnt/pve/bergen-synology-backup")
DUMP = STORAGE / "dump"
ARCHIVE_RE = re.compile(r"vzdump-lxc-126-\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.tar\.zst\Z")
JOURNALS = {
    15: ("2a6d73664436c1a3e0432d7a07911feab86ba2a617a185b81bc30580fdd67e90",
         "7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b"),
    26: ("f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26",
         "5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a"),
}


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def parse_guest_config(raw):
    data = dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)
    require(data.get("hostname") == "bergen-paperless", "WRONG_GUEST")
    require(data.get("unprivileged") == "1", "UNPRIVILEGED_REQUIRED")
    root = data.get("rootfs", "")
    mp0 = data.get("mp0", "")
    require(root.startswith("local-zfs:subvol-126-disk-0,")
            and "backup=0" not in root.split(","), "ROOTFS_BACKUP_INVALID")
    require(mp0.startswith("local-zfs:subvol-126-disk-1,")
            and "mp=/srv/bergen-paperless" in mp0.split(",")
            and "backup=1" in mp0.split(","), "MP0_BACKUP_INVALID")
    require("lxc.apparmor.profile: unconfined" not in raw, "UNCONFINED_GUEST")


def stdout(argv):
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    require(proc.returncode == 0, "COMMAND_FAILED_" + argv[0])
    return proc.stdout


def digest_stream(stream):
    digest = hashlib.sha256()
    while True:
        part = stream.read(131072)
        if not part:
            return digest.hexdigest()
        digest.update(part)


def archive_digest(archive, event):
    member = "./var/lib/paperless-ingest/deletion-decisions/" + event + ".json"
    # tar -xO streams the member to stdout only; never extracts to disk.
    proc = subprocess.Popen(["tar", "--zstd", "-xOf", str(archive), member],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        digest = digest_stream(proc.stdout)
        proc.stdout.close()
        err = proc.stderr.read(8192)
        proc.stderr.close()
        rc = proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    require(rc == 0 and not err, "ARCHIVE_MEMBER_MISSING_OR_TAR_WARNING")
    return digest


def audit(archive_name):
    require(Path("/usr/sbin/pct").is_file(), "PROXMOX_HOST_REQUIRED")
    parse_guest_config(stdout(["pct", "config", VMID]))
    require(stdout(["pct", "status", VMID]).strip() == "status: running",
            "PAPERLESS_GUEST_NOT_RUNNING")
    mount = stdout(["findmnt", "-T", str(STORAGE), "-n", "-o", "TARGET,FSTYPE"]).strip().split()
    require(len(mount) == 2 and mount[0] == str(STORAGE)
            and mount[1] in ("nfs", "nfs4"), "BACKUP_NFS_NOT_MOUNTED")
    archive = Path(archive_name)
    require(archive.is_absolute() and archive.parent == DUMP
            and ARCHIVE_RE.fullmatch(archive.name), "INVALID_ARCHIVE_PATH")
    st = archive.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size > 0,
            "UNSAFE_ARCHIVE_FILE")
    for document_id, (event, expected) in sorted(JOURNALS.items()):
        path = "/var/lib/paperless-ingest/deletion-decisions/" + event + ".json"
        result = stdout(["pct", "exec", VMID, "--", "sha256sum", path]).strip().split()
        require(len(result) == 2 and result[1] == path
                and re.fullmatch("[0-9a-f]{64}", result[0]), "BAD_LIVE_SHA256_OUTPUT")
        require(result[0] == expected, "LIVE_JOURNAL_HASH_MISMATCH_DOC_" + str(document_id))
        require(archive_digest(archive, event) == expected,
                "BACKUP_JOURNAL_HASH_MISMATCH_DOC_" + str(document_id))
        print("DOC", document_id, "LIVE_AND_BACKUP_SHA256_IDENTICAL")
    print("JOURNAL_HASHES_VERIFIED 2")
    print("ARCHIVE_NOT_AUTHORIZED")
    print("MAIN_MERGE_NOT_AUTHORIZED")
    print("NO_FILES_CHANGED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    args = parser.parse_args()
    try:
        audit(args.archive)
    except (OSError, RuntimeError, ValueError) as exc:
        print("BACKUP_JOURNAL_AUDIT_FAILED", str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
