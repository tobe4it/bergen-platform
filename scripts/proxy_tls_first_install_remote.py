#!/usr/bin/env python3
"""Root-only, fail-closed initial proxy TLS file activation.

Called only through pinned SSH by proxy_tls_first_install.py.
Never logs or prints private-key content. Never reloads or starts Nginx.
Not a certificate rotation tool.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

PARENT = Path("/etc/nginx")
TLS_DIR = PARENT / "tls"
CERT = TLS_DIR / "fullchain.pem"
KEY = TLS_DIR / "privkey.pem"
STAGE_PATTERN = re.compile(r"^/etc/nginx/tls/\.first-install-[A-Za-z0-9_-]{6,32}$")
FP_PATTERN = re.compile(r"^[a-f0-9]{64}$")
SITE_PATTERN = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


def reject(message: str) -> None:
    raise RuntimeError(message)


def check_directory(path: Path, mode: int | None = None) -> None:
    if path.is_symlink():
        reject("Symlink in TLS directory path")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
        reject("TLS directory must be root-owned directory")
    if mode is not None and stat.S_IMODE(info.st_mode) != mode:
        reject("TLS directory has unexpected permissions")


def refuse_active_nginx() -> None:
    if Path("/usr/sbin/nginx").exists() or Path("/usr/bin/nginx").exists():
        reject("Nginx already installed; first-install-only path refused")
    proc = subprocess.run(
        ["systemctl", "is-active", "--quiet", "nginx"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False, timeout=8,
    )
    if proc.returncode == 0:
        reject("Nginx active; first-install-only path refused")


def must_be_absent() -> None:
    for dest in (CERT, KEY):
        if os.path.lexists(dest):
            reject("Existing TLS destination; first-install-only path refused")


def checked_stage(path: str) -> Path:
    if not STAGE_PATTERN.fullmatch(path):
        reject("Unexpected stage path")
    stage = Path(path)
    check_directory(TLS_DIR, 0o700)
    check_directory(stage, 0o700)
    if stage.parent != TLS_DIR:
        reject("Stage path escapes TLS directory")
    return stage


def check_staged_file(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        reject("Staged TLS file must be root-owned and regular")
    if stat.S_IMODE(info.st_mode) != 0o600 or not 16 <= info.st_size <= 131072:
        reject("Staged TLS file has invalid permissions or size")


def checked_openssl(*args: str) -> bytes:
    result = subprocess.run(
        ["openssl", *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=False, timeout=10,
    )
    if result.returncode != 0:
        reject("OpenSSL validation failed")
    return result.stdout


def validate(stage: Path, expected_fp: str, site: str) -> None:
    if not FP_PATTERN.fullmatch(expected_fp) or not SITE_PATTERN.fullmatch(site):
        reject("Invalid expected source fingerprint or hostname")
    cert = stage / "fullchain.pem"
    key = stage / "privkey.pem"
    check_staged_file(cert)
    check_staged_file(key)
    checked_openssl("x509", "-in", str(cert), "-noout", "-checkend", str(30 * 86400))
    checkhost = checked_openssl("x509", "-in", str(cert), "-noout", "-checkhost", site)
    if b"does match certificate" not in checkhost:
        reject("Certificate does not cover configured site")
    fingerprint = checked_openssl(
        "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"
    ).decode("ascii", "strict").strip().rsplit("=", 1)[-1].replace(":", "").lower()
    if fingerprint != expected_fp:
        reject("Staged certificate differs from validated source")
    cert_pub = checked_openssl("x509", "-in", str(cert), "-pubkey", "-noout")
    key_pub = checked_openssl("pkey", "-in", str(key), "-pubout")
    if cert_pub.strip() != key_pub.strip():
        reject("Staged certificate and private key do not match")


def stage() -> None:
    refuse_active_nginx()
    if not PARENT.exists():
        PARENT.mkdir(mode=0o755)
    check_directory(PARENT)
    if not TLS_DIR.exists():
        TLS_DIR.mkdir(mode=0o700)
    check_directory(TLS_DIR, 0o700)
    must_be_absent()
    path = tempfile.mkdtemp(prefix=".first-install-", dir=TLS_DIR)
    check_directory(Path(path), 0o700)
    print(path)


def activate(stage_path: str, expected_fp: str, site: str) -> None:
    refuse_active_nginx()
    stage_dir = checked_stage(stage_path)
    must_be_absent()
    validate(stage_dir, expected_fp, site)

    # Exclusive hard-links ensure existing destinations can NEVER be overwritten.
    # Nginx is absent; partial first-install is rolled back before returning.
    installed = []
    try:
        for filename, dest in (("fullchain.pem", CERT), ("privkey.pem", KEY)):
            os.link(stage_dir / filename, dest, follow_symlinks=False)
            installed.append(dest)
        for dest, mode in ((CERT, 0o600), (KEY, 0o600)):
            info = dest.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != mode:
                reject("Post-install permissions differ")
    except Exception:
        for dest in reversed(installed):
            dest.unlink()
        raise
    print("PROXY_TLS_FIRST_INSTALL_PASS")


def cleanup(stage_path: str) -> None:
    stage_dir = checked_stage(stage_path)
    # Only delete an exact stage dir with allowlisted file names.
    entries = {item.name for item in stage_dir.iterdir()}
    if not entries.issubset({"fullchain.pem", "privkey.pem"}):
        reject("Unexpected entries in staged TLS directory")
    shutil.rmtree(stage_dir)
    print("PROXY_TLS_STAGE_CLEANED")


def main() -> None:
    if os.geteuid() != 0:
        reject("Root required")
    if len(sys.argv) < 2:
        reject("Missing operation")
    action = sys.argv[1]
    if action == "stage" and len(sys.argv) == 2:
        stage()
    elif action == "activate" and len(sys.argv) == 5:
        activate(*sys.argv[2:])
    elif action == "cleanup" and len(sys.argv) == 3:
        cleanup(sys.argv[2])
    else:
        reject("Unknown operation or invalid arguments")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
        print("PROXY_TLS_FIRST_INSTALL_FAIL: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
