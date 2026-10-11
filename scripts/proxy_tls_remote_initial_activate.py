#!/usr/bin/env python3
"""Executed in guest via verified SSH STDIN; validate staged key and install once.

Never invoke this standalone without the guarded controller driver. It refuses
existing live paths and a running Nginx, and never prints private PEM contents.
"""
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


def fail(message):
    raise SystemExit(message)


def check(argv):
    if len(argv) < 4:
        fail("Missing required stage, fingerprint or hostname")
    stage = Path(argv[1])
    expected_fp = argv[2]
    names = argv[3:]
    if not re.fullmatch(r"/etc/nginx/tls/\.stage\.[A-Za-z0-9]{8}", str(stage)):
        fail("Bad TLS stage")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_fp):
        fail("Bad TLS fingerprint")
    if not names or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]+", n) for n in names):
        fail("Bad TLS hostname")
    if os.geteuid() != 0:
        fail("Must run as root")
    if Path("/usr/sbin/nginx").exists():
        fail("Nginx already installed: initial TLS provisioning must come first")
    if subprocess.run(["systemctl", "is-active", "--quiet", "nginx"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        fail("Nginx must not be running for first install")
    root = Path("/etc/nginx/tls")
    if root.is_symlink() or not root.is_dir():
        fail("Invalid destination directory")
    root_stat = root.stat()
    if root_stat.st_uid or stat.S_IMODE(root_stat.st_mode) & 0o077:
        fail("Destination TLS directory must be root-owned, private")
    staged = stage.lstat()
    if not stat.S_ISDIR(staged.st_mode) or staged.st_uid != 0 or stat.S_IMODE(staged.st_mode) != 0o700:
        fail("Invalid staging directory permissions")
    cert, key = stage / "fullchain.pem", stage / "privkey.pem"
    for file in (cert, key):
        status = file.lstat()
        if not stat.S_ISREG(status.st_mode) or status.st_uid or stat.S_IMODE(status.st_mode) != 0o600:
            fail("Staged TLS file must be root-owned regular file, mode 0600")
    final_cert, final_key = root / "fullchain.pem", root / "privkey.pem"
    for path in (final_cert, final_key):
        if os.path.lexists(path):
            fail("TLS files already installed: first-install only")

    def run(*args):
        result = subprocess.run(args, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, check=False, timeout=20)
        if result.returncode:
            fail("TLS file validation failed")
        return result.stdout.strip()
    run("openssl", "x509", "-in", str(cert), "-noout", "-checkend", "2592000")
    for name in names:
        match = run("openssl", "x509", "-in", str(cert), "-noout", "-checkhost", name)
        if b"does match certificate" not in match:
            fail("TLS name not covered")
        run("openssl", "verify", "-purpose", "sslserver", "-verify_hostname", name,
            "-untrusted", str(cert), str(cert))
    fingerprint = run("openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256")
    value = fingerprint.rsplit(b"=", 1)[-1].replace(b":", b"").decode("ascii").lower()
    if value != expected_fp:
        fail("Staged certificate fingerprint not equal to source")
    cert_pub = run("openssl", "x509", "-in", str(cert), "-noout", "-pubkey")
    key_pub = run("openssl", "pkey", "-in", str(key), "-pubout")
    if cert_pub != key_pub:
        fail("Staged private key mismatch")

    wrote_cert = wrote_key = False
    try:
        os.replace(cert, final_cert)
        wrote_cert = True
        os.chmod(final_cert, 0o644)
        os.replace(key, final_key)
        wrote_key = True
        os.chmod(final_key, 0o600)
    except Exception:
        # Target was verified empty and nginx inactive, so removing only our
        # newly moved files safely rolls back a failed first installation.
        if wrote_key:
            final_key.unlink(missing_ok=True)
        if wrote_cert:
            final_cert.unlink(missing_ok=True)
        raise
    print("INITIAL_TLS_INSTALLED")


if __name__ == "__main__":
    check(sys.argv)
