#!/usr/bin/env python3
"""Conservatively reconcile abandoned selfHOST DNS-01 reservations.

This is an operator-only recovery tool. It never writes to the selfHOST API,
and it refuses to modify local state unless the *two exact* reserved slots are
confirmed idle on *all* configured authoritative DNS servers.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import selfhost_acme_hook as hook


def assert_no_running_certbot():
    """Fail closed when a certbot process could own an active DNS challenge."""
    proc = Path("/proc")
    if not proc.is_dir():
        raise hook.HookError("Cannot inspect running Certbot processes")
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            data = (entry / "cmdline").read_bytes()
        except FileNotFoundError:
            continue  # exited during enumeration
        except OSError as exc:
            raise hook.HookError("Cannot inspect all running processes") from exc
        args = [a.decode("utf-8", errors="replace") for a in data.split(b"\0") if a]
        first = args[:4]
        if any(Path(a).name in ("certbot", "certbot-auto") for a in first):
            raise hook.HookError("A Certbot process is running; refuse reconciliation")
        if any(a == "certbot" for a in first):
            raise hook.HookError("A Certbot process is running; refuse reconciliation")


def check_exact_orphans(cfg, state):
    """Permit exactly two known 'reserved' entries, never presented/cleaning."""
    ids = {str(i) for i in cfg["record_ids"]}
    if set(state) != ids:
        raise hook.HookError("Reservations differ from the exact two configured slots")
    for slot, entry in state.items():
        if not isinstance(entry, dict) or entry.get("status") != "reserved":
            raise hook.HookError("Non-reserved reservation found; manual review required")
        if entry.get("identifier") not in (cfg["zone"], "*." + cfg["zone"]):
            raise hook.HookError("Unexpected reservation identifier")
        if not isinstance(entry.get("validation"), str) or not hook.DNS01.fullmatch(entry["validation"]):
            raise hook.HookError("Invalid reserved validation token")
    if len({item["validation"] for item in state.values()}) != 2:
        raise hook.HookError("Two independent validation values required")


def assert_remote_slots_idle(cfg, state):
    name = "_acme-challenge." + cfg["zone"]
    idle = {"selfhost-api-idle-" + str(slot) for slot in cfg["record_ids"]}
    validations = {item["validation"] for item in state.values()}
    for server in cfg["nameservers"]:
        records = hook.authoritative_txt(server, name)
        if not idle.issubset(records):
            raise hook.HookError("Not all configured DNS slots are idle on every nameserver")
        if records & validations:
            raise hook.HookError("Old validation token still appears in authoritative DNS")


def create_private_backup(path, state):
    backup = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         prefix="reconciled-", suffix=".json",
                                         dir=path.parent, delete=False) as handle:
            backup = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            json.dump(state, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        return backup
    except BaseException:
        if backup is not None:
            backup.unlink(missing_ok=True)
        raise


def reconcile(cfg, *, apply=False, state_dir=hook.DEFAULT_STATE_DIR):
    assert_no_running_certbot()
    with hook.exclusive_state(state_dir) as (state, path):
        if not state:
            assert_remote_slots_idle(cfg, state)
            print("ALREADY_CLEAN: No local reservations; both DNS slots idle")
            return
        check_exact_orphans(cfg, state)
        assert_remote_slots_idle(cfg, state)
        assert_no_running_certbot()
        if not apply:
            print("READY: Exactly two abandoned reservations; both DNS slots idle")
            return
        create_private_backup(path, state)
        hook.save_state(path, {})
        print("RECONCILED: Two orphaned reservations cleared; private backup retained")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe local selfHOST orphan recovery")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise hook.HookError("Recovery must run as root")
    os.umask(0o077)
    cfg = hook.load_config()
    reconcile(cfg, apply=args.apply)


if __name__ == "__main__":
    try:
        main()
    except (hook.HookError, OSError, ValueError, json.JSONDecodeError) as exc:
        print("selfHOST reservation recovery refused: " + str(exc), file=sys.stderr)
        sys.exit(1)
