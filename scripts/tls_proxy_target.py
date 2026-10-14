#!/usr/bin/env python3
"""Read-only Nginx target adapter for the existing Mail TLS distributor.

Source validation and mail target synchronization are handled unchanged by
mail_tls_sync.py. This adapter only audits a reviewed isolated LXC via its
already trusted Proxmox-mediated SSH transport. No certificate/key transfers.
"""
import json
from pathlib import Path
import re
import shlex
import subprocess

import yaml

CERT_PATH = "/etc/nginx/tls/fullchain.pem"
KEY_PATH = "/etc/nginx/tls/privkey.pem"
SAFE_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,250}")
VALID_FP = re.compile(r"[a-f0-9]{64}")

# Executes as root inside the specific LXC, reached through pinned guest SSH.
# The only output is status flags; certificate/key bytes are never returned.
STATE_SCRIPT = r'''
import json
from pathlib import Path
import stat

root = Path("/etc/nginx/tls")
cert = root / "fullchain.pem"
key = root / "privkey.pem"

if root.is_symlink():
    raise SystemExit("TLS directory must not be a symlink")
if root.exists():
    s = root.stat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or stat.S_IMODE(s.st_mode) & 0o077:
        raise SystemExit("TLS directory not root-owned/private")

def inspect(path, key_file):
    try:
        s = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0:
        raise SystemExit("TLS file is not a root-owned regular file")
    mode = stat.S_IMODE(s.st_mode)
    if key_file and mode not in (0o400, 0o600):
        raise SystemExit("Unprotected TLS private key")
    if not key_file and mode & 0o022:
        raise SystemExit("Writable TLS certificate")
    return True

print(json.dumps({"cert": inspect(cert, False), "key": inspect(key, True)}))
'''


class ProxyAuditError(Exception):
    pass


def load_restricted_yaml(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise ProxyAuditError("Proxy variables must be a git-ignored mode-0600 regular file")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProxyAuditError("Proxy variables are not a YAML mapping")
    return data


def inventory_children(path):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProxyAuditError("Invalid Ansible inventory")
    children = data.get("all", {}).get("children", {})
    if not isinstance(children, dict):
        raise ProxyAuditError("Invalid Ansible group structure")
    return children


def checked_target(mail_cfg, proxy, local, shared):
    """Validate only the exact previously reviewed PCT SSH target."""
    name = proxy.get("lxc_hostname")
    node = proxy.get("pve_inventory_host")
    vmid = proxy.get("lxc_vmid")
    wildcard = mail_cfg["mail_tls_required_san"]
    if (not isinstance(name, str) or not SAFE_HOST.fullmatch(name)
            or not isinstance(node, str) or not SAFE_HOST.fullmatch(node)
            or type(vmid) is not int or not 100 <= vmid <= 999999999):
        raise ProxyAuditError("Unexpected proxy LXC identity")
    if proxy.get("lxc_inventory_group") != "reverse_proxy_nodes":
        raise ProxyAuditError("Proxy must use the dedicated inventory group")
    if proxy.get("reverse_proxy_tls_cert_path") != CERT_PATH or proxy.get("reverse_proxy_tls_key_path") != KEY_PATH:
        raise ProxyAuditError("Unexpected proxy TLS destination paths")
    sites = proxy.get("reverse_proxy_sites")
    if not isinstance(sites, list) or not sites:
        raise ProxyAuditError("No configured proxy hostnames")
    names = []
    for site in sites:
        hostname = site.get("hostname") if isinstance(site, dict) else None
        if (not isinstance(hostname, str) or not SAFE_HOST.fullmatch(hostname)
                or not hostname.endswith(wildcard[1:])
                or hostname.count(".") != wildcard.count(".")):
            raise ProxyAuditError("Site not covered by source wildcard")
        names.append(hostname)
    if len(set(names)) != len(names):
        raise ProxyAuditError("Duplicate proxy hostnames")
    hosts = local.get("reverse_proxy_nodes", {}).get("hosts", {})
    if not isinstance(hosts, dict) or list(hosts) != [name]:
        raise ProxyAuditError("Exactly one reviewed reverse proxy LXC is required")
    target = hosts[name]
    pve = shared.get("proxmox_hosts", {}).get("hosts", {}).get(node)
    if not isinstance(target, dict) or not isinstance(pve, dict):
        raise ProxyAuditError("Missing target or Proxmox inventory record")
    guest_address = target.get("ansible_host")
    pve_address = pve.get("ansible_host")
    if any(not isinstance(x, str) or not SAFE_HOST.fullmatch(x)
           for x in (guest_address, pve_address)):
        raise ProxyAuditError("Unsafe or missing Proxmox/guest SSH address")
    opts = target.get("ansible_ssh_common_args")
    if not isinstance(opts, str):
        raise ProxyAuditError("Missing trusted guest ProxyCommand")
    if (target.get("ansible_user") != "root"
            or target.get("ansible_port", 22) != 22
            or "pct_ssh_proxy.py" not in opts
            or f"--pve-host {pve_address}" not in opts
            or f"--vmid {vmid}" not in opts
            or f"HostKeyAlias=lxc-{vmid}" not in opts
            or "StrictHostKeyChecking=yes" not in opts):
        raise ProxyAuditError("PCT transport differs from validated Ansible inventory")
    return guest_address, pve_address, vmid, names


def proxy_ssh_arguments(sync, guest, pve, vmid):
    script = (Path(__file__).resolve().parents[1] /
              "ansible/scripts/pct_ssh_proxy.py").resolve(strict=True)
    proxy_command = f"python3 {shlex.quote(str(script))} --pve-host {pve} --vmid {vmid}"
    return ["ssh", *sync.SSH_OPTIONS, "-o", "LogLevel=ERROR",
            "-o", "ProxyCommand=" + proxy_command,
            "-o", f"HostKeyAlias=lxc-{vmid}", f"root@{guest}"]


def checked_remote(sync, ssh_args, command):
    try:
        result = subprocess.run(
            [*ssh_args, command], input=b"", capture_output=True,
            check=False, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise ProxyAuditError("Isolated LXC SSH timed out") from exc
    if result.returncode != 0:
        # Do not relay stderr; never leak private file contents.
        raise ProxyAuditError(f"Isolated LXC SSH audit failed (exit {result.returncode})")
    return result.stdout.decode("utf-8", "replace").strip()


def audit_proxy_target(mail_cfg, source_fp, source_expiry,
                       proxy_vars, local_inventory, shared_inventory):
    import mail_tls_sync as sync

    if not VALID_FP.fullmatch(source_fp):
        raise ProxyAuditError("No valid verified source fingerprint")
    proxy = load_restricted_yaml(proxy_vars)
    guest, pve, vmid, names = checked_target(
        mail_cfg, proxy, inventory_children(local_inventory),
        inventory_children(shared_inventory))
    ssh = proxy_ssh_arguments(sync, guest, pve, vmid)
    raw = checked_remote(sync, ssh, "/usr/bin/python3 -c " + shlex.quote(STATE_SCRIPT))
    try:
        state = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProxyAuditError("Bad TLS status returned by the reviewed LXC") from exc
    if not isinstance(state, dict) or set(state) != {"cert", "key"} or any(
        type(state[name]) is not bool for name in ("cert", "key")
    ):
        raise ProxyAuditError("Malformed or incomplete proxy TLS status")
    if state["cert"] != state["key"]:
        raise ProxyAuditError("Partial certificate/key installation requires manual review")
    if not state["cert"]:
        print("PROXY TLS: MISSING_EXPECTED_FIRST_INSTALL")
        print("PROXY TLS: AUDIT_ONLY; no files transferred or services changed")
        return "MISSING_EXPECTED_FIRST_INSTALL"

    def probe(command):
        return checked_remote(sync, ssh, command)

    fp = sync.fingerprint(probe(
        f"openssl x509 -in {shlex.quote(CERT_PATH)} -noout -fingerprint -sha256"))
    cert_pub = probe(f"openssl x509 -in {shlex.quote(CERT_PATH)} -noout -pubkey")
    key_pub = probe(f"openssl pkey -in {shlex.quote(KEY_PATH)} -pubout")
    if cert_pub != key_pub:
        raise ProxyAuditError("Proxy certificate and private key do not match")
    for hostname in names:
        match = probe(f"openssl x509 -in {shlex.quote(CERT_PATH)} -noout -checkhost {shlex.quote(hostname)}")
        if "does match certificate" not in match:
            raise ProxyAuditError("Installed proxy certificate does not cover configured hostname")
    expiry_raw = probe(f"openssl x509 -in {shlex.quote(CERT_PATH)} -noout -enddate")
    expiry = sync.cert_expiry(expiry_raw)
    if source_fp != fp and source_expiry < expiry:
        raise ProxyAuditError("Refusing source certificate downgrade")
    decision = "NO_CHANGE" if source_fp == fp else "ROTATION_CANDIDATE"
    print("PROXY TLS: " + decision)
    print("PROXY TLS: installed expiry UTC " + expiry.isoformat())
    print("PROXY TLS: AUDIT_ONLY; no files transferred or services changed")
    return decision
