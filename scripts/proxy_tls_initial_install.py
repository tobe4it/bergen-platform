#!/usr/bin/env python3
"""Fail-closed FIRST install of existing Certbot wildcard TLS into an isolated LXC.

Read-only by default. With --apply, stream source PEMs between pinned SSH peers
without writing private-key material to controller disk. Never touches nginx.
"""
import argparse
from pathlib import Path
import re
import shlex
import subprocess
import sys

import yaml

MIN_VALIDITY = 30 * 86400
STAGE_RE = re.compile(r"^/etc/nginx/tls/\.stage\.[A-Za-z0-9]{8}$")
FP_RE = re.compile(r"^[a-f0-9]{64}$")
SSH_SAFE = ["-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-o", "ClearAllForwardings=yes",
            "-o", "ForwardAgent=no", "-o", "LogLevel=ERROR"]


class InstallError(Exception):
    pass


def q(value):
    return shlex.quote(str(value))


def load_private_yaml(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise InstallError(f"Ignored local file must be mode 0600 or tighter: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise InstallError("Expected YAML mapping")
    return data


def load_inventory(path):
    content = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise InstallError("Invalid inventory")
    return content.get("all", {}).get("children", {})


def validate(source, proxy, shared_inventory, local_inventory):
    # Validate before any subprocess or other side effect.
    for field in ("mail_tls_source_address", "mail_tls_source_ssh_user",
                  "mail_tls_source_cert_file", "mail_tls_source_key_file",
                  "mail_tls_required_san"):
        if not isinstance(source.get(field), str) or not source[field]:
            raise InstallError(f"Source setting missing: {field}")
    for field in ("lxc_hostname", "pve_inventory_host", "lxc_vmid",
                  "reverse_proxy_tls_cert_path", "reverse_proxy_tls_key_path"):
        if field not in proxy:
            raise InstallError(f"Proxy setting missing: {field}")
    fqdn_re = r"[A-Za-z0-9][A-Za-z0-9.-]{0,250}"
    for name in [source["mail_tls_source_address"], proxy["pve_inventory_host"],
                 proxy["lxc_hostname"]]:
        if not re.fullmatch(fqdn_re, name):
            raise InstallError("Unsafe source/PVE/proxy host identity")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", source["mail_tls_source_ssh_user"]):
        raise InstallError("Unsafe source SSH user")
    if type(proxy["lxc_vmid"]) is not int or not 100 <= proxy["lxc_vmid"] <= 999999999:
        raise InstallError("Invalid LXC VMID")
    prefix = "/etc/letsencrypt/live/[A-Za-z0-9._-]+/"
    for name, suffix in (("mail_tls_source_cert_file", "fullchain.pem"),
                         ("mail_tls_source_key_file", "privkey.pem")):
        if not re.fullmatch(prefix + suffix.replace(".", r"\."), source[name]):
            raise InstallError("Source must be the existing Certbot live lineage")
    if source["mail_tls_source_cert_file"].rsplit("/", 1)[0] != source["mail_tls_source_key_file"].rsplit("/", 1)[0]:
        raise InstallError("Source certificate and key must share a lineage")
    if proxy["reverse_proxy_tls_cert_path"] != "/etc/nginx/tls/fullchain.pem" or proxy["reverse_proxy_tls_key_path"] != "/etc/nginx/tls/privkey.pem":
        raise InstallError("Initial installer only supports reviewed Nginx TLS paths")
    wildcard = source["mail_tls_required_san"]
    if not re.fullmatch(r"\*\.[A-Za-z0-9.-]+", wildcard):
        raise InstallError("Invalid wildcard SAN")
    sites = proxy.get("reverse_proxy_sites")
    if not isinstance(sites, list) or not sites:
        raise InstallError("No proxy virtual hosts")
    names = []
    for site in sites:
        host = site.get("hostname") if isinstance(site, dict) else None
        if (not isinstance(host, str) or not re.fullmatch(fqdn_re, host)
                or not host.endswith(wildcard[1:]) or host.count(".") != wildcard.count(".")):
            raise InstallError("Proxy site outside single-level wildcard")
        names.append(host)
    if len(set(names)) != len(names):
        raise InstallError("Duplicate proxy host")
    if proxy.get("lxc_inventory_group") != "reverse_proxy_nodes":
        raise InstallError("Expected dedicated reverse_proxy_nodes group")
    pve_hosts = shared_inventory.get("proxmox_hosts", {}).get("hosts", {})
    pve = pve_hosts.get(proxy["pve_inventory_host"], {})
    target_hosts = local_inventory.get("reverse_proxy_nodes", {}).get("hosts", {})
    if list(target_hosts) != [proxy["lxc_hostname"]]:
        raise InstallError("Dedicated local reverse_proxy_nodes must have exactly the selected LXC")
    target = target_hosts[proxy["lxc_hostname"]]
    if not isinstance(pve, dict) or not isinstance(target, dict):
        raise InstallError("PVE/target inventory malformed")
    pve_ip, guest_ip = pve.get("ansible_host"), target.get("ansible_host")
    for address in (pve_ip, guest_ip):
        if not isinstance(address, str) or not re.fullmatch(fqdn_re, address):
            raise InstallError("Missing trusted PVE / guest address")
    # Verify that the same already-known SSH transport was reviewed by Ansible.
    transport = target.get("ansible_ssh_common_args", "")
    if (target.get("ansible_user") != "root"
            or target.get("ansible_port", 22) != 22
            or f"--pve-host {pve_ip}" not in transport
            or "pct_ssh_proxy.py" not in transport
            or f"--vmid {proxy['lxc_vmid']}" not in transport
            or f"HostKeyAlias=lxc-{proxy['lxc_vmid']}" not in transport
            or "StrictHostKeyChecking=yes" not in transport):
        raise InstallError("Target lacks reviewed PCT SSH transport")
    return pve_ip, guest_ip, names


def source_ssh(host, user):
    return ["ssh", *SSH_SAFE, f"{user}@{host}"]


def proxy_ssh(host, pve_host, vmid, proxy_script):
    script = Path(proxy_script).resolve(strict=True)
    command = f"python3 {q(script)} --pve-host {q(pve_host)} --vmid {vmid}"
    return ["ssh", *SSH_SAFE, "-o", "ProxyCommand=" + command,
            "-o", f"HostKeyAlias=lxc-{vmid}", f"root@{host}"]


def remote(ssh, cmd, *, input_data=b"", timeout=45):
    try:
        p = subprocess.run([*ssh, cmd], input=input_data, capture_output=True,
                           check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise InstallError("SSH operation timed out") from exc
    if p.returncode:
        # Never print remote stderr: remote systems can contain private material.
        raise InstallError(f"SSH remote check failed (exit {p.returncode})")
    return p.stdout.decode("utf-8", "replace").strip()


def digest(stdout):
    result = stdout.rsplit("=", 1)[-1].strip().replace(":", "").lower()
    if not FP_RE.fullmatch(result):
        raise InstallError("Invalid certificate fingerprint")
    return result


def source_evidence(ssh, src, names, wildcard):
    cert, key = src["mail_tls_source_cert_file"], src["mail_tls_source_key_file"]
    def run(command):
        return remote(ssh, command)
    run(f"sudo -n openssl x509 -in {q(cert)} -noout -checkend {MIN_VALIDITY}")
    sans = run(f"sudo -n openssl x509 -in {q(cert)} -noout -ext subjectAltName")
    if wildcard not in re.findall(r"DNS:([^,\s]+)", sans):
        raise InstallError("Required wildcard absent")
    for name in names:
        if "does match certificate" not in run(f"sudo -n openssl x509 -in {q(cert)} -noout -checkhost {q(name)}"):
            raise InstallError("Certificate hostname mismatch")
    fp = digest(run(f"sudo -n openssl x509 -in {q(cert)} -noout -fingerprint -sha256"))
    cert_digest = run("bash -o pipefail -c " + q(
        f"sudo -n openssl x509 -in {q(cert)} -noout -pubkey | openssl pkey -pubin -outform DER | openssl dgst -sha256"))
    key_digest = run("bash -o pipefail -c " + q(
        f"sudo -n openssl pkey -in {q(key)} -pubout -outform DER | openssl dgst -sha256"))
    if cert_digest != key_digest or not FP_RE.fullmatch(digest(cert_digest)):
        raise InstallError("Source certificate/key mismatch")
    expiry = run(f"sudo -n openssl x509 -in {q(cert)} -noout -enddate")
    return fp, expiry


def ensure_empty(ssh, cert, key):
    code = ("set -eu; "
            "! systemctl is-active --quiet nginx; "
            "test ! -x /usr/sbin/nginx; "
            "test ! -L /etc/nginx/tls; "
            f"test ! -e {q(cert)} && test ! -L {q(cert)}; "
            f"test ! -e {q(key)} && test ! -L {q(key)}")
    remote(ssh, code)


def transfer(source, target, source_file, stage_file):
    """A two-SSH pipe: bytes stay in memory, never logged or persisted here."""
    upstream = None
    downstream = None
    try:
        upstream = subprocess.Popen([*source, "sudo -n cat -- " + q(source_file)],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        downstream = subprocess.Popen([*target, "umask 077; cat > " + q(stage_file)],
                                      stdin=upstream.stdout, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        upstream.stdout.close()
        try:
            down_rc = downstream.wait(timeout=120)
            up_rc = upstream.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise InstallError("Protected certificate transfer timed out") from exc
        if up_rc or down_rc:
            raise InstallError("Protected SSH certificate transfer failed")
    finally:
        for process in (downstream, upstream):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()


def install(source, target, source_cfg, proxy_cfg, names, fp, root):
    cert = proxy_cfg["reverse_proxy_tls_cert_path"]
    key = proxy_cfg["reverse_proxy_tls_key_path"]
    ensure_empty(target, cert, key)
    stage = remote(target, "set -eu; install -d -o root -g root -m 0700 /etc/nginx/tls; "
                   "umask 077; mktemp -d /etc/nginx/tls/.stage.XXXXXXXX")
    if not STAGE_RE.fullmatch(stage):
        raise InstallError("Unexpected destination staging directory; inspect manually")
    try:
        transfer(source, target, source_cfg["mail_tls_source_cert_file"], stage + "/fullchain.pem")
        transfer(source, target, source_cfg["mail_tls_source_key_file"], stage + "/privkey.pem")
        script = (root / "scripts/proxy_tls_remote_initial_activate.py").read_bytes()
        cmd = ("python3 - " + " ".join(q(x) for x in [stage, fp, *names]))
        result = remote(target, cmd, input_data=script, timeout=90)
        if result != "INITIAL_TLS_INSTALLED":
            raise InstallError("Unexpected target TLS activation response")
    finally:
        try:
            remote(target, f"rm -f -- {q(stage + '/fullchain.pem')} {q(stage + '/privkey.pem')}; "
                           f"rmdir -- {q(stage)}")
        except InstallError:
            print("WARNING: restricted staging directory may require manual cleanup", file=sys.stderr)
    confirmed = digest(remote(target, f"openssl x509 -in {q(cert)} -noout -fingerprint -sha256"))
    if confirmed != fp:
        raise InstallError("Installed TLS leaf fingerprint mismatch")
    print("INITIAL_TLS_INSTALLED: verified matching source and target fingerprints")
    print("Nginx was not installed, started or reloaded by this operation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-vars", required=True)
    parser.add_argument("--proxy-vars", required=True)
    parser.add_argument("--inventory", default="ansible/inventory.yml")
    parser.add_argument("--local-inventory", default="ansible/inventory.local.yml")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    source_cfg = load_private_yaml(args.source_vars)
    proxy_cfg = load_private_yaml(args.proxy_vars)
    pve_ip, guest_ip, names = validate(source_cfg, proxy_cfg,
                                       load_inventory(args.inventory),
                                       load_inventory(args.local_inventory))
    base = Path(__file__).resolve().parents[1]
    src = source_ssh(source_cfg["mail_tls_source_address"], source_cfg["mail_tls_source_ssh_user"])
    dst = proxy_ssh(guest_ip, pve_ip, proxy_cfg["lxc_vmid"],
                    base / "ansible/scripts/pct_ssh_proxy.py")
    fp, expiry = source_evidence(src, source_cfg, names, source_cfg["mail_tls_required_san"])
    ensure_empty(dst, proxy_cfg["reverse_proxy_tls_cert_path"],
                 proxy_cfg["reverse_proxy_tls_key_path"])
    print("Source: existing verified Certbot wildcard")
    print("Expiry: " + expiry)
    print("Target: reviewed isolated LXC, first TLS install, Nginx inactive")
    print("Decision: FIRST_INSTALL")
    if not args.apply:
        print("READ_ONLY: no TLS files transferred; explicit --apply needed")
        return
    install(src, dst, source_cfg, proxy_cfg, names, fp, base)


if __name__ == "__main__":
    try:
        main()
    except (InstallError, OSError, ValueError, yaml.YAMLError) as exc:
        print("PROXY TLS INITIAL INSTALL FAILED: " + str(exc), file=sys.stderr)
        sys.exit(1)
