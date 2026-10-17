#!/usr/bin/env python3
"""READ ONLY Synology watcher status by restricted UID and /proc cmdline.

Executed through the same NAS SSH control path as existing lifecycle audits.
No filenames, process arguments or secret paths are ever printed.
This checks whether the expected supervised inotify worker is running,
NOT whether inotify events have actually fired.
"""
import os
import pwd
import stat
import sys
from pathlib import Path

MAX_PROCS = 32768


def is_running(parent, filename, required_args, uid, proc=Path("/proc")):
    count = 0
    seen = 0
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        seen += 1
        if seen > MAX_PROCS:
            raise RuntimeError("PROCESS_LIMIT_EXCEEDED")
        try:
            details = entry.stat()
            if details.st_uid != uid:
                continue
            raw = (entry / "cmdline").read_bytes()[:8192]
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        args = [os.fsdecode(x) for x in raw.split(b"\0") if x]
        if (str(parent / "bin" / filename) in args
                and all(flag in args for flag in required_args)):
            count += 1
    return count


def state(parent):
    if not parent.is_absolute() or ".." in parent.parts or parent == Path("/"):
        raise RuntimeError("INVALID_STATE_PARENT")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS

    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    uid = pwd.getpwnam(SETTINGS["sync_user"]).pw_uid
    if os.geteuid() != uid or uid == 0:
        raise RuntimeError("RUN_AS_RESTRICTED_SYNC_USER")
    supervisor_count = is_running(
        parent, "synology_watcher_supervisor.py", ("--boot",), uid)
    watcher_count = is_running(
        parent, "synology_inotify_watch.py", ("--watch", "--commit"), uid)

    try:
        gate_st = SETTINGS["gate"].lstat()
        gate = (stat.S_ISREG(gate_st.st_mode) and gate_st.st_uid == 0
                and gate_st.st_nlink == 1
                and stat.S_IMODE(gate_st.st_mode) == 0o644)
    except FileNotFoundError:
        gate = False

    return (supervisor_count, watcher_count, gate)


def main(parent):
    supervisor, watcher, gate = state(parent)
    if supervisor > 1 or watcher > 1:
        print("WATCHER_PROCESS_STATE=DUPLICATE")
    elif supervisor == 1 and watcher == 1:
        print("WATCHER_PROCESS_STATE=SUPERVISED_AND_RUNNING")
    elif supervisor == 1:
        print("WATCHER_PROCESS_STATE=SUPERVISOR_ONLY")
    elif watcher == 1:
        print("WATCHER_PROCESS_STATE=UNSUPERVISED_WATCHER")
    else:
        print("WATCHER_PROCESS_STATE=NOT_RUNNING")
    print("SENDER_ACTIVATION_GATE=" + ("ACTIVE" if gate else "ABSENT_OR_UNSAFE"))
    print("WATCHER_PROBE_READ_ONLY=true")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: diagnose_synology_watcher_processes.py STATE_PARENT")
    main(Path(sys.argv[1]))
