#!/usr/bin/env python3
"""Validate and perform a one-time certificate pair installation in the LXC.

Only executed by the central shared TLS distributor after explicit approval.
No Nginx start or reload. Output never contains PEM data.
"""
import fcntl
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path("/etc/nginx/tls")
CERT = ROOT / "fullchain.pem"
KEY = ROOT / "privkey.pem"
STAGE = re.compile(r"/etc/nginx/tls/\.stage\.[A-Za-z0-9]{8}\Z")
FINGERPRINT = re.compile(r"[a-f0-9]{64}\Z")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,250}\Z")


def require(condition, message):
    if not condition:
        raise SystemExit("PROXY INITIAL TLS REFUSED: " + message)


def check_command(*args):
    result = subprocess.run(args, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=30, check=False)
    require(result.returncode == 0, "TLS cryptographic verification failed")
    return result.stdout.strip()


def require_nginx_absent():
    require(not Path("/usr/sbin/nginx").exists(), "Nginx binary exists")
    require(not Path("/usr/bin/nginx").exists(), "Nginx binary exists")
    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "nginx"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    require(active.returncode != 0, "Nginx is active")


def require_empty():
    require(not os.path.lexists(CERT), "Certificate already installed")
    require(not os.path.lexists(KEY), "Private key already installed")


def main(argv):
    require(os.geteuid() == 0, "Root privileges required")
    require(len(argv) >= 4, "Expected stage, fingerprint and at least one host")
    stage, fingerprint, *hostnames = argv[1:]
    require(bool(STAGE.fullmatch(stage)), "Unexpected staging directory")
    require(bool(FINGERPRINT.fullmatch(fingerprint)), "Invalid fingerprint")
    require(all(HOST.fullmatch(host) for host in hostnames), "Invalid hostname")
    require(ROOT.is_dir() and not ROOT.is_symlink(), "Invalid TLS root directory")
    root_stat = ROOT.stat()
    require(root_stat.st_uid == 0 and stat.S_IMODE(root_stat.st_mode) == 0o700,
            "TLS root directory not protected")
    lock_file = "/run/lock/proxy-tls-initial.lock"
    handle = os.open(lock_file, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(handle, "rb+"):
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_nginx_absent()
        require_empty()
        directory = Path(stage)
        dstat = directory.lstat()
        require(stat.S_ISDIR(dstat.st_mode) and dstat.st_uid == 0
                and stat.S_IMODE(dstat.st_mode) == 0o700,
                "Unprotected staging directory")
        staged_cert = directory / "fullchain.pem"
        staged_key = directory / "privkey.pem"
        for file in (staged_cert, staged_key):
            metadata = file.lstat()
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
                    and stat.S_IMODE(metadata.st_mode) == 0o600,
                    "Unprotected staged file")
        check_command("openssl", "x509", "-in", str(staged_cert),
                      "-noout", "-checkend", "2592000")
        for name in hostnames:
            match = check_command("openssl", "x509", "-in", str(staged_cert),
                                  "-noout", "-checkhost", name)
            require(b"does match certificate" in match, "Hostname not covered")
            check_command("openssl", "verify", "-purpose", "sslserver",
                          "-verify_hostname", name,
                          "-untrusted", str(staged_cert), str(staged_cert))
        reported = check_command("openssl", "x509", "-in", str(staged_cert),
                                 "-noout", "-fingerprint", "-sha256")
        reported = reported.rsplit(b"=", 1)[-1].replace(b":", b"").decode().lower()
        require(reported == fingerprint, "Source fingerprint mismatch")
        public_cert = check_command("openssl", "x509", "-in",
                                    str(staged_cert), "-noout", "-pubkey")
        public_key = check_command("openssl", "pkey", "-in",
                                   str(staged_key), "-pubout")
        require(public_cert == public_key, "Certificate/private-key mismatch")
        require_nginx_absent()
        require_empty()
        created = []
        try:
            # Exclusive creation; never overwrite another certificate or key.
            os.link(staged_cert, CERT, follow_symlinks=False)
            created.append(CERT)
            os.chmod(CERT, 0o644)
            os.link(staged_key, KEY, follow_symlinks=False)
            created.append(KEY)
            os.chmod(KEY, 0o600)
        except Exception:
            for file in reversed(created):
                file.unlink(missing_ok=True)
            raise
    print("INITIAL_TLS_INSTALLED")


if __name__ == "__main__":
    main(sys.argv)
