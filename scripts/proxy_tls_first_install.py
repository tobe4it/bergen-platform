#!/usr/bin/env python3
"""Independent, opt-in first certificate install into an EMPTY proxy LXC.

Default is read-only. --apply requires an exact approval string.
Does not install/start Nginx, change the existing mail timer, open ports or
configure DNS. Private-key bytes are streamed between pinned SSH processes,
never stored on or printed by the controller.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import shlex
import subprocess
import sys

import mail_tls_sync as mail
import tls_proxy_target as proxy

SITE = "paperless.thebergens.net"
APPROVAL = "INSTALL_PROXY_TLS_FIRST_TIME"
ACTOR = Path(__file__).with_name("proxy_tls_first_install_remote.py")
CERT_NAME = "fullchain.pem"
KEY_NAME = "privkey.pem"


class FirstInstallError(Exception):
    pass


def run_actor(ssh: list[str], args: list[str]) -> str:
    script = ACTOR.read_bytes()
    cmd = [*ssh, "python3 - " + " ".join(shlex.quote(str(x)) for x in args)]
    try:
        result = subprocess.run(cmd, input=script, capture_output=True, check=False, timeout=45)
    except subprocess.TimeoutExpired as exc:
        raise FirstInstallError("Remote TLS actor timed out") from exc
    if result.returncode:
        # Never echo remote stdout or stderr in error paths.
        raise FirstInstallError(f"Remote TLS actor rejected {args[0]}")
    return result.stdout.decode("utf-8", "strict").strip()


def restricted_stage(value: str) -> str:
    import re
    if not re.fullmatch(r"/etc/nginx/tls/\.first-install-[A-Za-z0-9_-]{6,32}", value):
        raise FirstInstallError("Remote stage path did not match fixed restriction")
    return value


def transfer_secret(
    source: list[str], destination: list[str], source_path: str,
    staged_path: str,
) -> None:
    # The receiving Python opens the path with O_EXCL|O_NOFOLLOW, mode 0600.
    # The SSH stdin is reserved for the streamed bytes; this command is static
    # apart from the prevalidated, shell-quoted stage path.
    reader = [*source, "sudo -n cat -- " + shlex.quote(source_path)]
    receiver = [
        *destination,
        "python3 -c " + shlex.quote(
            "import os,sys; f=os.open(sys.argv[1],"
            "os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600); "
            "out=os.fdopen(f,'wb'); "
            "import shutil; shutil.copyfileobj(sys.stdin.buffer,out); out.close()"
        ) + " " + shlex.quote(staged_path),
    ]
    upstream = None
    downstream = None
    try:
        upstream = subprocess.Popen(reader, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        downstream = subprocess.Popen(receiver, stdin=upstream.stdout,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        upstream.stdout.close()
        try:
            dest_rc = downstream.wait(timeout=45)
            source_rc = upstream.wait(timeout=45)
        except subprocess.TimeoutExpired as exc:
            raise FirstInstallError("TLS stage transport timed out") from exc
        if dest_rc or source_rc:
            raise FirstInstallError("TLS source-to-proxy transfer failed")
    finally:
        for process in (downstream, upstream):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()


def reviewed_target(mail_cfg, proxy_path, local_path, shared_path):
    config = proxy.load_restricted_yaml(proxy_path)
    guest, pve, vmid, sites = proxy.checked_target(
        mail_cfg, config, proxy.inventory_children(local_path),
        proxy.inventory_children(shared_path)
    )
    if sites != [SITE]:
        raise FirstInstallError("Expected exactly the reviewed Paperless HTTPS site")
    ssh = proxy.proxy_ssh_arguments(mail, guest, pve, vmid)
    return ssh, config


def preflight(mail_cfg, ssh, source_fp: str, source_expiry, proxy_path,
              local_path, shared_path) -> None:
    status = proxy.audit_proxy_target(
        mail_cfg, source_fp, source_expiry, proxy_path, local_path, shared_path
    )
    proxy.plan_proxy_first_install(
        mail_cfg, proxy_path, local_path, shared_path, status
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--proxy-vars", required=True, type=Path)
    parser.add_argument("--proxy-local-inventory", default=Path("ansible/inventory.local.yml"), type=Path)
    parser.add_argument("--proxy-pve-inventory", default=Path("ansible/inventory.yml"), type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval", default="")
    args = parser.parse_args()
    if args.apply and args.approval != APPROVAL:
        raise FirstInstallError("Explicit first-install approval missing")
    if not args.apply and args.approval:
        raise FirstInstallError("Approval is only valid with --apply")
    cfg = mail.load_config(args.config)
    source = mail.ssh_args(cfg["mail_tls_source_address"],
                           cfg["mail_tls_source_ssh_user"], "true")[:-1]
    ssh, _proxy_cfg = reviewed_target(cfg, args.proxy_vars,
                                      args.proxy_local_inventory, args.proxy_pve_inventory)
    source_fp, source_expiry = mail.source_evidence(
        cfg["mail_tls_source_address"], cfg["mail_tls_source_ssh_user"], cfg
    )
    # In both modes, re-audit the target and source directly before any work.
    preflight(cfg, ssh, source_fp, source_expiry, args.proxy_vars,
              args.proxy_local_inventory, args.proxy_pve_inventory)
    if not args.apply:
        print("PROXY_TLS_FIRST_INSTALL_PLAN_ONLY")
        return
    stage = restricted_stage(run_actor(ssh, ["stage"]))
    activated = False
    try:
        for name, source_key in (
            (CERT_NAME, "mail_tls_source_cert_file"),
            (KEY_NAME, "mail_tls_source_key_file"),
        ):
            transfer_secret(source, ssh, cfg[source_key], f"{stage}/{name}")
        result = run_actor(ssh, ["activate", stage, source_fp, SITE])
        if result != "PROXY_TLS_FIRST_INSTALL_PASS":
            raise FirstInstallError("Unexpected activation result")
        activated = True
    finally:
        try:
            cleaned = run_actor(ssh, ["cleanup", stage])
            if cleaned != "PROXY_TLS_STAGE_CLEANED":
                raise FirstInstallError("Unexpected staging cleanup response")
        except FirstInstallError:
            print("PROXY_TLS_CLEANUP_FAILED: manual inspection of protected stage required",
                  file=sys.stderr)
            raise
    if activated:
        print("PROXY_TLS_FIRST_INSTALL_PASS: certificate/key installed")
        print("NGINX_UNCHANGED=true MAIL_UNCHANGED=true DNS_UNCHANGED=true")


if __name__ == "__main__":
    try:
        main()
    except (FirstInstallError, proxy.ProxyAuditError, mail.SyncError,
            OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print("PROXY_TLS_FIRST_INSTALL_FAIL: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
