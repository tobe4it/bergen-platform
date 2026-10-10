#!/usr/bin/env python3
"""Certificate sync over pinned SSH, with no controller-side private-key file.

Only site-local, Git-ignored YAML supplies deployment identities and paths.
Default invocation is read-only; --apply is required to transfer/activate.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import shlex
import subprocess
import sys

import yaml

SOURCE_VALID_SECONDS = 30 * 24 * 3600
STAGE_PATTERN = re.compile(r"^/etc/ssl/private/\.mail-tls-stage\.[A-Za-z0-9]{8}$")
FP_PATTERN = re.compile(r"^[a-f0-9]{64}$")
SSH_OPTIONS = [
    "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
    "-o", "ConnectTimeout=10", "-o", "ClearAllForwardings=yes",
    "-o", "ForwardAgent=no",
]


class SyncError(Exception):
    pass


def q(value):
    return shlex.quote(str(value))


def load_config(path):
    file = Path(path)
    if not file.is_file() or file.stat().st_mode & 0o077:
        raise SyncError("Local config must exist and be mode 0600 (or stricter)")
    config = yaml.safe_load(file.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SyncError("Local YAML must contain a mapping")
    required = (
        "mail_tls_source_address", "mail_tls_source_ssh_user",
        "mail_tls_target_inventory_host", "mail_tls_source_cert_file",
        "mail_tls_source_key_file", "mail_tls_target_cert_file",
        "mail_tls_target_key_file", "mail_tls_required_san",
        "mail_tls_expected_fqdn",
    )
    for key in required:
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise SyncError("Missing required site-local variable: " + key)
    for key in (
        "mail_tls_source_cert_file", "mail_tls_source_key_file",
        "mail_tls_target_cert_file", "mail_tls_target_key_file",
    ):
        value = config[key]
        if not value.startswith("/") or "\n" in value or "\x00" in value:
            raise SyncError("Invalid absolute path setting: " + key)
    if config["mail_tls_source_cert_file"] == config["mail_tls_source_key_file"]:
        raise SyncError("Source certificate and key paths must differ")
    if config["mail_tls_target_cert_file"] == config["mail_tls_target_key_file"]:
        raise SyncError("Target certificate and key paths must differ")
    fqdn = config["mail_tls_expected_fqdn"]
    san = config["mail_tls_required_san"]
    if not (san.startswith("*.") and fqdn.endswith(san[1:])
            and fqdn.count(".") == san.count(".")):
        raise SyncError("Expected hostname is not covered by required wildcard")
    for key in ("mail_tls_source_address", "mail_tls_target_ssh_address",
                "mail_tls_target_inventory_host", "mail_tls_source_ssh_user",
                "mail_tls_target_ssh_user"):
        value = config.get(key, "root" if key == "mail_tls_target_ssh_user" else "")
        if value and (not isinstance(value, str) or
                      not re.fullmatch(r"[A-Za-z0-9._-]+", value) or value.startswith("-")):
            raise SyncError("Unsafe SSH identity: " + key)
    ports = config.get("mail_tls_check_ports", [993, 587, 465])
    if not isinstance(ports, list) or not ports or any(
        type(port) is not int or port not in (993, 587, 465) for port in ports
    ) or len(set(ports)) != len(ports):
        raise SyncError("mail_tls_check_ports must be a unique list of 993, 587 and/or 465")
    return config


def ssh_args(host, user, command):
    return ["ssh", *SSH_OPTIONS, f"{user}@{host}", command]


def ssh_run(host, user, command, input_data=None):
    # Do not inherit a controller terminal or heredoc as SSH stdin.
    # Bound failed or stalled network operations rather than hanging the timer.
    try:
        result = subprocess.run(
            ssh_args(host, user, command),
            input=b"" if input_data is None else input_data,
            capture_output=True, check=False, timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise SyncError(f"SSH command timed out on {host} (30s)") from exc
    if result.returncode:
        # Never echo stderr: remote tools may inadvertently expose credentials.
        raise SyncError(f"SSH command failed on {host} (exit {result.returncode})")
    return result.stdout.decode("utf-8", "replace").strip()


def digest_command(path, from_key=False, sudo=False):
    prefix = "sudo -n " if sudo else ""
    if from_key:
        openssl = f"{prefix}openssl pkey -in {q(path)} -pubout -outform DER"
    else:
        openssl = f"{prefix}openssl x509 -in {q(path)} -noout -pubkey"
        openssl += " | openssl pkey -pubin -outform DER"
    return f"set -o pipefail; {openssl} | openssl dgst -sha256"


def fingerprint(output):
    value = output.rsplit("=", 1)[-1].replace(":", "").strip().lower()
    if not FP_PATTERN.fullmatch(value):
        raise SyncError("Unexpected certificate fingerprint")
    return value


def cert_expiry(output):
    if not output.startswith("notAfter="):
        raise SyncError("Unexpected certificate expiration")
    value = output.removeprefix("notAfter=")
    return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)


def source_evidence(host, user, cfg):
    cert = cfg["mail_tls_source_cert_file"]
    key = cfg["mail_tls_source_key_file"]
    fqdn = cfg["mail_tls_expected_fqdn"]
    san = cfg["mail_tls_required_san"]
    ssh_run(host, user,
        "sudo -n openssl x509 -in " + q(cert) + " -noout -checkend " + str(SOURCE_VALID_SECONDS))
    out = ssh_run(host, user, "sudo -n openssl x509 -in " + q(cert) +
                  " -noout -checkhost " + q(fqdn))
    if "does match certificate" not in out:
        raise SyncError("Source certificate hostname mismatch")
    sans = ssh_run(host, user, "sudo -n openssl x509 -in " + q(cert) +
                   " -noout -ext subjectAltName")
    if san not in re.findall(r"DNS:([^,\s]+)", sans):
        raise SyncError("Required wildcard SAN absent on source")
    fp = fingerprint(ssh_run(host, user, "sudo -n openssl x509 -in " +
                             q(cert) + " -noout -fingerprint -sha256"))
    cert_digest = ssh_run(host, user, "bash -o pipefail -c " +
                          q(digest_command(cert, sudo=True)))
    key_digest = ssh_run(host, user, "bash -o pipefail -c " +
                         q(digest_command(key, from_key=True, sudo=True)))
    if cert_digest != key_digest:
        raise SyncError("Source private key does not match certificate")
    expiry = cert_expiry(ssh_run(host, user, "sudo -n openssl x509 -in " +
                                 q(cert) + " -noout -enddate"))
    return fp, expiry


def target_evidence(host, user, cfg):
    cert = cfg["mail_tls_target_cert_file"]
    key = cfg["mail_tls_target_key_file"]
    expected = {
        "postconf -h smtpd_tls_cert_file": cert,
        "postconf -h smtpd_tls_key_file": key,
        "doveconf -h ssl_server/cert_file": cert,
        "doveconf -h ssl_server/key_file": key,
        "postconf -h myhostname": cfg["mail_tls_expected_fqdn"],
    }
    for command, want in expected.items():
        if ssh_run(host, user, command) != want:
            raise SyncError("Effective mail configuration differs: " + command)
    fp = fingerprint(ssh_run(host, user, "openssl x509 -in " + q(cert) +
                             " -noout -fingerprint -sha256"))
    cert_digest = ssh_run(host, user, "bash -o pipefail -c " +
                          q(digest_command(cert)))
    key_digest = ssh_run(host, user, "bash -o pipefail -c " +
                         q(digest_command(key, from_key=True)))
    if cert_digest != key_digest:
        raise SyncError("Installed target certificate and key do not match")
    expiry = cert_expiry(ssh_run(host, user, "openssl x509 -in " +
                                 q(cert) + " -noout -enddate"))
    return fp, expiry


def stage_transfer(src_host, src_user, dst_host, dst_user, src_path, stage_path):
    # SSH-to-SSH pipe, not via any file on the controller. Output is suppressed.
    # Source sudo must already be authorized non-interactively.
    source_cmd = "sudo -n cat -- " + q(src_path)
    destination_cmd = "umask 077; cat > " + q(stage_path)
    upstream = subprocess.Popen(ssh_args(src_host, src_user, source_cmd),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        downstream = subprocess.Popen(
            ssh_args(dst_host, dst_user, destination_cmd),
            stdin=upstream.stdout, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        upstream.stdout.close()
        downstream_rc = downstream.wait()
        upstream_rc = upstream.wait()
        if upstream_rc != 0 or downstream_rc != 0:
            raise SyncError("Protected certificate/key transfer failed")
    finally:
        if upstream.poll() is None:
            upstream.kill()
            upstream.wait()


def run_remote_script(host, user, script_path, args):
    script = script_path.read_bytes()
    command = "bash -se -- " + " ".join(q(arg) for arg in args)
    result = subprocess.run(ssh_args(host, user, command), input=script,
                            capture_output=True, check=False)
    if result.returncode:
        # Relay ONLY the explicit rollback status, never arbitrary remote stderr.
        status = [line for line in result.stderr.decode("utf-8", "replace").splitlines()
                  if re.fullmatch(r"ROLLBACK_(OK|FAILED): [A-Za-z0-9 :;.,/_-]+", line)]
        suffix = "; ".join(status)
        raise SyncError(f"Target activation failed (exit {result.returncode})"
                        + (f"; {suffix}" if suffix else ""))
    return result.stdout.decode("utf-8", "replace").strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="Authorize live certificate/key transfer and service rotation")
    args = parser.parse_args()
    cfg = load_config(args.config)
    src_host = cfg["mail_tls_source_address"]
    src_user = cfg["mail_tls_source_ssh_user"]
    dst_host = cfg.get("mail_tls_target_ssh_address", cfg["mail_tls_target_inventory_host"])
    dst_user = cfg.get("mail_tls_target_ssh_user", "root")
    if dst_user != "root":
        raise SyncError("Target SSH user must be root for protected atomic activation")
    source_fp, source_expiry = source_evidence(src_host, src_user, cfg)
    target_fp, target_expiry = target_evidence(dst_host, dst_user, cfg)
    print(f"Source expires (UTC): {source_expiry.isoformat()}")
    print(f"Installed certificate expires (UTC): {target_expiry.isoformat()}")
    if source_fp != target_fp and source_expiry < target_expiry:
        raise SyncError("Refusing certificate downgrade to an earlier expiry")
    action = "NO_CHANGE" if source_fp == target_fp else "ROTATE"
    print(f"Decision: {action}")
    remote_script = Path(__file__).with_name("mail_tls_remote_activate.sh")
    remote_args = ["", source_fp, target_fp, cfg["mail_tls_expected_fqdn"],
                   cfg["mail_tls_target_cert_file"], cfg["mail_tls_target_key_file"],
                   ",".join(str(p) for p in cfg.get("mail_tls_check_ports", [993, 587, 465]))]
    if action == "NO_CHANGE":
        remote_args[0] = "CHECK_ONLY"
        print(run_remote_script(dst_host, dst_user, remote_script, remote_args))
        return
    if not args.apply:
        print("READ_ONLY: Use --apply to authorize staging and rotation.")
        return
    stage = ssh_run(dst_host, dst_user,
                    "umask 077; mktemp -d /etc/ssl/private/.mail-tls-stage.XXXXXXXX")
    if not STAGE_PATTERN.fullmatch(stage):
        raise SyncError("Unexpected stage path; manual cleanup may be necessary")
    try:
        stage_transfer(src_host, src_user, dst_host, dst_user,
                       cfg["mail_tls_source_cert_file"], stage + "/fullchain.pem")
        stage_transfer(src_host, src_user, dst_host, dst_user,
                       cfg["mail_tls_source_key_file"], stage + "/privkey.pem")
        remote_args[0] = stage
        print(run_remote_script(dst_host, dst_user, remote_script, remote_args))
    finally:
        # Exact expected mktemp directory only; never remove the rollback backup.
        try:
            ssh_run(dst_host, dst_user,
                    "rm -f -- " + q(stage + "/fullchain.pem") + " " +
                    q(stage + "/privkey.pem") + "; rmdir -- " + q(stage))
        except SyncError:
            print("WARNING: Restricted staging directory requires manual cleanup", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (SyncError, OSError, yaml.YAMLError, ValueError) as exc:
        print("MAIL TLS SYNC FAILED: " + str(exc), file=sys.stderr)
        sys.exit(1)
