#!/usr/bin/env python3
"""Read-only CT110 backup policy and mountpoint coverage discovery.

Reads only pct config and the cluster's PVE backup job definitions.
Does not read data, run vzdump, touch disks, or conclude restore readiness.
"""
import json
import re
import subprocess

FRAME = "BERGEN_AI_CT110_BACKUP_POLICY_V1:"
NODE = "venombox"
VMID = "110"
PATTERN = re.compile(r"^[0-9]+(?:-[0-9]+)?$")
MOUNT_PATTERN = re.compile(r"^mp[0-9]+: ")


def command(argv, timeout=15, limit=350000):
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        if p.returncode != 0 or len(p.stdout) > limit:
            return None
        return p.stdout.decode("utf-8", "strict")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def frame(**values):
    result = dict(AUDIT="READ_ONLY", CHANGED=False,
                  CT110_BACKUP_VALIDATED=False, CT110_RESTORE_VALIDATED=False,
                  CT110_BACKUP_SCHEDULE_EFFECTIVE="NOT_PROVEN",
                  MOUNT_CONTENT_BACKUP="NOT_PROVEN",
                  FULL_NETWORK_CLEARANCE="NOT_PROVEN",
                  ROLLBACK_CLEARANCE="NOT_PROVEN",
                  APPLY_AUTHORIZED=False, BACKUP_OPERATIONS="NONE",
                  NETWORK_CHANGES="NONE")
    result.update(values)
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


def vmid_in_spec(spec, vmid=110):
    if not isinstance(spec, str) or len(spec) > 5000:
        return None
    tokens = spec.split(",")
    if not tokens or len(tokens) > 500:
        return None
    for token in tokens:
        token = token.strip()
        if not PATTERN.fullmatch(token):
            return None
    for token in tokens:
        if "-" in token:
            low, high = (int(x) for x in token.split("-"))
            if low > high:
                return None
            if low <= vmid <= high:
                return True
        elif int(token) == vmid:
            return True
    return False


def inspect_mounts(config):
    if not isinstance(config, str) or len(config) > 80000:
        return ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
    rows = config.splitlines()
    if "hostname: bergen-ai" not in rows:
        return ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
    rootfs = [x for x in rows if x.startswith("rootfs: ")]
    if len(rootfs) != 1:
        return ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
    mounts = [x.split(": ", 1)[1] for x in rows if MOUNT_PATTERN.match(x)]
    if len(mounts) > 32:
        return ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
    if not mounts:
        return ("CONFIGURED", "NONE", "NO_EXTRA_MOUNTS")
    backup_flags = []
    bind_count = 0
    for value in mounts:
        source = value.split(",", 1)[0]
        if source.startswith("/"):
            bind_count += 1
        flag = re.search(r"(?:^|,)backup=([01])(?:,|$)", value)
        backup_flags.append(flag.group(1) if flag else None)
    flags = ("ALL_EXPLICIT_BACKUP_1" if all(flag == "1" for flag in backup_flags)
             else "ONE_OR_MORE_UNSET_OR_DISABLED")
    return ("CONFIGURED", "BIND_PRESENT" if bind_count else "VOLUME_MOUNTS_ONLY", flags)


def audit_jobs(jobs):
    if not isinstance(jobs, list) or len(jobs) > 300:
        return ("UNVERIFIED", "UNVERIFIED")
    explicit = False
    all_guest = False
    unresolved = False
    for job in jobs:
        if not isinstance(job, dict):
            return ("UNVERIFIED", "UNVERIFIED")
        # Skip configured disabled jobs. Valid effective state still needs review.
        if job.get("enabled") in (False, 0, "0") or job.get("disable") in (True, 1, "1"):
            continue
        selected_node = job.get("node")
        if selected_node is not None and selected_node != NODE:
            continue
        excluded = job.get("exclude")
        if excluded:
            match = vmid_in_spec(str(excluded))
            if match is None:
                unresolved = True
                continue
            if match:
                continue
        include = job.get("vmid")
        if include is not None:
            match = vmid_in_spec(str(include))
            if match is None:
                unresolved = True
            elif match:
                explicit = True
        elif job.get("all") in (True, 1, "1"):
            all_guest = True
        else:
            # Pool or nonstandard selection may apply; don't report no schedule.
            unresolved = True
    result = ("EXPLICIT_VMID_SELECTION" if explicit else
              "ALL_GUESTS_SELECTION" if all_guest else
              "SELECTION_UNRESOLVED" if unresolved else
              "NO_MATCH_IN_VISIBLE_PVE_JOBS")
    return (result, len(jobs))


def main():
    config = command(["pct", "config", VMID])
    rootfs, mount_type, flags = inspect_mounts(config)
    jobs_data = command(["pvesh", "get", "/cluster/backup",
                         "--output-format", "json"])
    try:
        jobs = json.loads(jobs_data) if jobs_data is not None else None
    except (ValueError, TypeError):
        jobs = None
    jobs_result, jobs_count = audit_jobs(jobs)
    status = ("REVIEW_INCOMPLETE" if "UNVERIFIED" in
              (rootfs, mount_type, flags, jobs_result) else "POLICY_INVENTORY_ONLY")
    frame(STATUS=status, CT110_ROOTFS=rootfs,
          CT110_EXTRA_MOUNTS=mount_type,
          CT110_EXTRA_MOUNT_BACKUP_FLAGS=flags,
          PVE_BACKUP_JOB_SELECTION=jobs_result,
          VISIBLE_PVE_BACKUP_JOB_COUNT=jobs_count,
          OTHER_BACKUP_SYSTEMS="NOT_INSPECTED",
          NEXT_ACTION="VERIFY_BACKUP_PLAN_INCLUSION_AND_APPROVE_BACKUP_SEPARATELY")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        frame(STATUS="REVIEW_INCOMPLETE", CT110_ROOTFS="UNVERIFIED",
              CT110_EXTRA_MOUNTS="UNVERIFIED",
              CT110_EXTRA_MOUNT_BACKUP_FLAGS="UNVERIFIED",
              PVE_BACKUP_JOB_SELECTION="UNVERIFIED",
              VISIBLE_PVE_BACKUP_JOB_COUNT="UNVERIFIED",
              OTHER_BACKUP_SYSTEMS="NOT_INSPECTED")
