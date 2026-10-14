#!/usr/bin/env python3
"""Long-running, fail-closed Synology inotify trigger for Bergen Paperless.

No third-party Python modules or inotifywait needed (Linux libc via ctypes).
--probe validates kernel watches without transferring PDFs or requiring the
activation gate. --watch --commit requires that gate; it invokes the existing
sender with --scheduled --commit. A full rescan runs at least every 15 minutes.

Run unprivileged as paperless-sync. Start at boot through DSM Task Scheduler,
with an external restart policy so a crashed watcher is not left stopped.
"""
import argparse
import ctypes
import errno
import os
import select
import stat
import struct
import subprocess
import sys
import tempfile
import time
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

import synology_scan_sync as sync

# Linux inotify API constants.
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_UNMOUNT = 0x00002000
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ONLYDIR = 0x01000000
IN_ISDIR = 0x40000000

WATCH_MASK = (IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE
              | IN_DELETE_SELF | IN_MOVE_SELF | IN_UNMOUNT | IN_ONLYDIR)
SIGNAL_MASK = IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE
LOST_MASK = IN_DELETE_SELF | IN_MOVE_SELF | IN_UNMOUNT | IN_IGNORED

QUIET_AFTER_EVENT = 65    # Sender requires 60 seconds since last mtime/ctime.
FULL_SCAN_SECONDS = 900  # Recovery from missed/overflowed events.
SYNC_TIMEOUT_SECONDS = 3600
EVENT_HEADER = struct.Struct("iIII")
SCRIPT = Path(__file__).resolve().with_name("synology_scan_sync.py")


class Inotify:
    def __init__(self):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.inotify_init1.argtypes = [ctypes.c_int]
        self.libc.inotify_init1.restype = ctypes.c_int
        self.libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p,
                                                ctypes.c_uint32]
        self.libc.inotify_add_watch.restype = ctypes.c_int
        fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.fd = fd
        self.scopes = {}

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def add(self, directory, scope):
        st = directory.lstat()
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError("UNSAFE_WATCH_DIRECTORY " + str(directory))
        wd = self.libc.inotify_add_watch(self.fd, os.fsencode(str(directory)),
                                         WATCH_MASK)
        if wd < 0:
            raise OSError(ctypes.get_errno(), "inotify_add_watch: " + str(directory))
        self.scopes[wd] = scope
        return wd

    def add_sources(self):
        for directory, scope in sync.SOURCES:
            self.add(directory, scope)

    def events(self, timeout_seconds):
        poller = select.poll()
        poller.register(self.fd, select.POLLIN | select.POLLERR | select.POLLHUP)
        ready = poller.poll(max(0, int(timeout_seconds * 1000)))
        if not ready:
            return []
        if ready[0][1] & (select.POLLERR | select.POLLHUP):
            raise RuntimeError("INOTIFY_FD_LOST")
        out = []
        while True:
            try:
                data = os.read(self.fd, 1024 * 64)
            except BlockingIOError:
                break
            if not data:
                raise RuntimeError("INOTIFY_FD_EOF")
            offset = 0
            while offset + EVENT_HEADER.size <= len(data):
                wd, mask, _cookie, name_len = EVENT_HEADER.unpack_from(data, offset)
                offset += EVENT_HEADER.size
                if offset + name_len > len(data):
                    raise RuntimeError("INOTIFY_EVENT_TRUNCATED")
                name = os.fsdecode(data[offset:offset + name_len].split(b"\x00", 1)[0])
                offset += name_len
                out.append((wd, mask, name))
            if offset != len(data):
                raise RuntimeError("INOTIFY_EVENT_CORRUPT")
        return out


def verify_unprivileged():
    if os.geteuid() == 0:
        raise RuntimeError("DO_NOT_RUN_AS_ROOT")
    sync.secure_state()


def probe():
    """Verify kernel delivery using only a temporary private STATE directory."""
    verify_unprivileged()
    watcher = Inotify()
    try:
        watcher.add_sources()
        with tempfile.TemporaryDirectory(dir=sync.STATE, prefix="inotify-probe-") as tmp:
            wd = watcher.add(Path(tmp), "SELF_TEST")
            with open(Path(tmp) / "probe.txt", "wb") as stream:
                stream.write(b"inotify self test\n")
            seen = any(event_wd == wd and mask & IN_CLOSE_WRITE
                       and name == "probe.txt"
                       for event_wd, mask, name in watcher.events(5))
            if not seen:
                raise RuntimeError("INOTIFY_PROBE_NO_CLOSE_WRITE")
        print("INOTIFY_PROBE_OK", len(sync.SOURCES), "source watches", flush=True)
    finally:
        watcher.close()


def scan(reason):
    # Never change the worker's permissions or bypass its activation gate.
    print("SYNC_START", reason, flush=True)
    result = subprocess.run([sys.executable, str(SCRIPT), "--scheduled", "--commit"],
                            check=False, timeout=SYNC_TIMEOUT_SECONDS)
    print("SYNC_END", reason, "rc=" + str(result.returncode), flush=True)


def watch():
    verify_unprivileged()
    sync.require_schedule_gate()
    # A single watcher per NAS. Independent of the sender's own sync.lock.
    with (sync.STATE / "watcher.lock").open("a+") as lock:
        flock(lock, LOCK_EX | LOCK_NB)
        watcher = Inotify()
        try:
            # Register BEFORE startup scan, so changes during the scan queue up.
            watcher.add_sources()
            print("INOTIFY_WATCH_READY", len(sync.SOURCES), flush=True)
            scan("STARTUP")
            next_full = time.monotonic() + FULL_SCAN_SECONDS
            next_event = None
            while True:
                now = time.monotonic()
                if now >= next_full:
                    scan("PERIODIC_15_MIN")
                    next_full = time.monotonic() + FULL_SCAN_SECONDS
                    # Drain and process any events that occurred during scan.
                    continue
                if next_event is not None and now >= next_event:
                    next_event = None
                    scan("INOTIFY_QUIET")
                    continue
                due = min(next_full, next_event if next_event is not None else next_full)
                incoming = watcher.events(min(max(0, due - now), 60))
                now = time.monotonic()
                for wd, mask, name in incoming:
                    if mask & IN_Q_OVERFLOW:
                        print("INOTIFY_QUEUE_OVERFLOW_RESCAN", flush=True)
                        next_event = now  # immediate recovery scan
                    if wd in watcher.scopes and mask & LOST_MASK:
                        raise RuntimeError("INOTIFY_WATCH_LOST " + watcher.scopes[wd])
                    if (wd in watcher.scopes and mask & SIGNAL_MASK
                            and not mask & IN_ISDIR
                            and name.lower().endswith(".pdf")
                            and not name.startswith(".")):
                        print("INOTIFY_EVENT", watcher.scopes[wd] + "/" + name,
                              "mask=" + hex(mask), flush=True)
                        # Debounce burst, then let sender enforce PDF quiescence.
                        next_event = now + QUIET_AFTER_EVENT
        finally:
            watcher.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true",
                      help="test source watches and inotify delivery, no transfers")
    mode.add_argument("--watch", action="store_true",
                      help="watch and run gated sender after events and every 15 min")
    parser.add_argument("--commit", action="store_true",
                        help="required with --watch; does not bypass sender gate")
    args = parser.parse_args()
    if args.probe:
        if args.commit:
            parser.error("--probe cannot be combined with --commit")
        probe()
    else:
        if not args.commit:
            parser.error("--watch requires --commit")
        watch()
