#!/usr/bin/env python3
"""Restricted Proxmox-host timer worker for Paperless metadata view-only policy.

Runs the approved root-owned Django policy through the exact existing
unprivileged CT126; never receives credentials, user input or document text.
Default deployment is disabled until separately reviewed and approved.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

FRAME = "BERGEN_PAPERLESS_METADATA_AUTO_V1:"
CHILD_FRAME = "BERGEN_PAPERLESS_METADATA_RECONCILER_V1:"
ROOT = Path("/etc/bergen-platform/paperless-metadata")
SRC = ROOT / "reconcile_metadata_with_provenance.py"
POLICY = ROOT / "policy.json"
PROTOCOL = "bergen-paperless-metadata-reconciler-v1"
MAX_ADDS = 25
MAX_REVOKES = 25


class Blocked(Exception):
    pass


def require(flag, code):
    if not flag:
        raise Blocked(code)


def execute(args, stdin=None, timeout=100):
    result = subprocess.run(
        args, input=stdin, text=True, capture_output=True,
        timeout=timeout, check=False)
    require(result.returncode == 0, "PROCESS_FAILURE")
    return result.stdout


def parse(raw):
    matches = [x[len(CHILD_FRAME):] for x in raw.splitlines()
               if x.startswith(CHILD_FRAME)]
    require(len(matches) == 1 and len(matches[0]) <= 1800,
            "POLICY_FRAME_INVALID")
    data = json.loads(matches[0])
    require(type(data) is dict and data.get("STATUS") == "INSPECTED"
            and data.get("MODE") == "AUDIT" and
            data.get("CHANGED") is False and
            data.get("DOCUMENT_ACLS_CHANGED") == "NO",
            "POLICY_AUDIT_REFUSED")
    return data


def call_policy(script, request):
    args = ["pct", "exec", "126", "--", "podman", "exec", "-i",
            "bergen-paperless", "python",
            "/usr/src/paperless/src/manage.py", "shell", "--verbosity=0",
            "-c", script]
    return execute(args, json.dumps(request), 90)


def announce(status, **kw):
    print(FRAME + json.dumps(dict(STATUS=status, **kw),
                             sort_keys=True, separators=(",", ":")), flush=True)


def main():
    try:
        require(os.geteuid() == 0, "ROOT_REQUIRED")
        require(os.uname().nodename.split(".")[0] == "venombox",
                "HOST_NOT_REVIEWED")
        ct = execute(["pct", "config", "126"], timeout=10)
        require("hostname: bergen-paperless\n" in ct and
                "unprivileged: 1\n" in ct and
                "lxc.apparmor.profile: unconfined" not in ct and
                re.search(r"^rootfs: local-zfs:", ct, flags=re.M) and
                re.search(r"^mp0: local-zfs:.*mp=/srv/bergen-paperless,backup=1(,|$)",
                          ct, flags=re.M), "GUEST_NOT_REVIEWED")
        for file in (SRC, POLICY):
            st = file.stat()
            require(file.is_file() and not file.is_symlink() and
                    st.st_uid == 0 and st.st_gid == 0 and
                    (st.st_mode & 0o077) == 0 and st.st_size <= 45000,
                    "POLICY_FILE_UNTRUSTED")
        config = json.loads(POLICY.read_text())
        require(type(config) is dict and
                set(config) == {"protocol", "approved", "policy_sha256",
                                "max_additions", "max_revocations"} and
                config["protocol"] == "bergen-paperless-metadata-auto-v1" and
                config["approved"] is True and
                config["max_additions"] == MAX_ADDS and
                config["max_revocations"] == MAX_REVOKES and
                re.fullmatch(r"[a-f0-9]{64}", config["policy_sha256"]),
                "TIMER_APPROVAL_INVALID")
        source = SRC.read_text()
        require(hashlib.sha256(source.encode("utf-8")).hexdigest() ==
                config["policy_sha256"], "POLICY_FINGERPRINT_DRIFT")

        filesystem = execute(["findmnt", "--mountpoint",
                              "/mnt/pve/bergen-synology-backup", "-n", "-o",
                              "FSTYPE"], timeout=10).strip()
        require(filesystem in ("nfs", "nfs4"), "NFS_BACKUP_UNAVAILABLE")
        dump = Path("/mnt/pve/bergen-synology-backup/dump")
        require(dump.is_dir(), "BACKUP_DIRECTORY_NOT_FOUND")
        now = time.time()
        latest = [x for x in dump.iterdir()
                  if re.fullmatch(r"vzdump-lxc-126-.*\.tar\.zst", x.name)
                  and x.is_file() and x.stat().st_size > 1000000
                  and 0 <= now - x.stat().st_mtime <= 48 * 3600]
        require(latest, "BACKUP_NOT_RECENT")
        audit = parse(call_policy(source, dict(
            protocol=PROTOCOL, mode="audit", approved=False)))
        require(audit.get("LEDGER") == "VALID",
                "LEDGER_BOOTSTRAP_REQUIRED")
        require(audit.get("CHILD_SEES_ELTERN_DOCUMENTS") == 0 and
                audit.get("CHILD_SEES_THOMAS_PRIVATE_DOCUMENTS") == 0,
                "PRIVACY_BOUNDARY_UNVERIFIED")
        names = ("DOCUMENTS", "USERS", "TAGS", "TYPE_GAPS",
                 "CORR_GAPS", "TAG_GAPS", "MANAGED_REVOCATIONS",
                 "THOMAS_PRIVATE")
        require(all(type(audit.get(n)) is int for n in names),
                "POLICY_COUNTERS_INVALID")
        adds = (audit["TYPE_GAPS"] + audit["CORR_GAPS"] +
                audit["TAG_GAPS"])
        removes = audit["MANAGED_REVOCATIONS"]
        require(0 <= adds <= MAX_ADDS and 0 <= removes <= MAX_REVOKES,
                "AUTOMATIC_CHANGE_BUDGET_EXCEEDED")
        require(audit["THOMAS_PRIVATE"] >= 1 and
                audit["USERS"] >= 3 and audit["DOCUMENTS"] > 0,
                "PRIVACY_OR_SCOPE_UNVERIFIED")
        if adds == 0 and removes == 0:
            announce("UNCHANGED", ADDED=0, REVOKED=0, CHANGED=False)
            return

        expected = {
            "documents": audit["DOCUMENTS"], "users": audit["USERS"],
            "tags": audit["TAGS"], "type_gaps": audit["TYPE_GAPS"],
            "corr_gaps": audit["CORR_GAPS"], "tag_gaps": audit["TAG_GAPS"],
            "managed_revocations": audit["MANAGED_REVOCATIONS"],
            "thomas_private": audit["THOMAS_PRIVATE"],
        }
        raw = call_policy(source, dict(
            protocol=PROTOCOL, mode="apply", approved=True,
            expected=expected))
        matched = [x[len(CHILD_FRAME):] for x in raw.splitlines()
                   if x.startswith(CHILD_FRAME)]
        require(len(matched) == 1 and len(matched[0]) < 1800,
                "APPLY_FRAME_INVALID")
        result = json.loads(matched[0])
        require(result.get("STATUS") == "APPLIED" and
                result.get("LEDGER") == "VALID" and
                result.get("DOCUMENT_ACLS_CHANGED") == "NO" and
                result.get("DOCUMENT_TAGS_CHANGED") == "NO" and
                result.get("THOMAS_PRIVATE_DENIED_TO_NADJA") ==
                expected["thomas_private"] and
                result.get("REMOVED_MANAGED_GRANTS") == removes and
                result.get("ADDED_TAG_GRANTS") == expected["tag_gaps"] and
                result.get("ADDED_TYPE_GRANTS") == expected["type_gaps"] and
                result.get("ADDED_CORRESPONDENT_GRANTS") ==
                expected["corr_gaps"], "APPLY_POSTCHECK_REFUSED")
        announce("APPLIED", ADDED=adds, REVOKED=removes,
                 CHANGED=True, DOCUMENT_ACLS_CHANGED="NO")
    except (Blocked, OSError, subprocess.TimeoutExpired, ValueError) as err:
        code = err.args[0] if isinstance(err, Blocked) else "UNCLASSIFIED"
        announce("BLOCKED", REASON=code, CHANGED=False)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
