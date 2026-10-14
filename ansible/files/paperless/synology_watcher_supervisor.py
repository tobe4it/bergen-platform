#!/usr/bin/env python3
"""Unprivileged, single-instance DSM startup supervisor for Paperless inotify.

Run on DSM boot as the configured unprivileged sync user. It waits for the root-owned activation
gate and restarts the inotify worker 60 s after unexpected exit. Never runs
as root and never sends a document directly.
"""
import argparse
import os
import pwd
import signal
import stat
import subprocess
import sys
import time
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

import synology_scan_sync as sync

WATCHER = Path(__file__).resolve().with_name("synology_inotify_watch.py")
STOP = False


def stop(_signum, _frame):
    global STOP
    STOP = True


def boot():
    if os.geteuid() == 0 or os.geteuid() != pwd.getpwnam(sync.SETTINGS["sync_user"]).pw_uid:
        raise RuntimeError("RUN_AS_PAPERLESS_SYNC_ONLY")
    sync.secure_state()
    os.umask(0o077)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (sync.STATE / "watcher-supervisor.lock").open("a+") as instance:
        flock(instance, LOCK_EX | LOCK_NB)
        print("WATCHER_SUPERVISOR_STARTED", flush=True)
        while not STOP:
            try:
                sync.require_schedule_gate()
            except FileNotFoundError:
                # Wait until operator explicitly authorizes scheduled transfers.
                print("WATCHER_WAITING_FOR_ENABLE_GATE", flush=True)
                for _ in range(60):
                    if STOP:
                        break
                    time.sleep(1)
                continue
            except Exception as exc:
                print("WATCHER_GATE_ERROR", str(exc), flush=True)
                for _ in range(60):
                    if STOP:
                        break
                    time.sleep(1)
                continue

            # The inotify worker performs the startup rescan itself and every
            # 15 min afterwards. It and the sender both revalidate the gate.
            child = subprocess.Popen(
                [sys.executable, str(WATCHER), "--watch", "--commit"],
                stdout=None, stderr=None,
            )
            try:
                while not STOP:
                    rc = child.poll()
                    if rc is not None:
                        print("WATCHER_EXIT", rc, flush=True)
                        break
                    time.sleep(1)
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
            # Do not hot-loop on missing mount, unavailable keys or bad ACLs.
            if not STOP:
                for _ in range(60):
                    if STOP:
                        break
                    time.sleep(1)
    print("WATCHER_SUPERVISOR_STOPPED", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--boot", action="store_true",
                        help="DSM boot entry point; must run as paperless-sync")
    args = parser.parse_args()
    if not args.boot:
        parser.error("--boot is required")
    boot()
