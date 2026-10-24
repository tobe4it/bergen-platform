#!/usr/bin/env python3
"""Register explicit SSH targets in a private audit-only inventory overlay."""
import argparse
import copy
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import re
import uuid

from system_updates import HOST_RE, command, inventory_args, private_json, validate, write_json


def endpoint(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(HOST_RE.fullmatch(value))


def registration(config, existing, overlay, additions, required, user, port, overlay_path):
    proposed = copy.deepcopy(config)
    hosts = copy.deepcopy(overlay)
    for alias, address in additions:
        if not HOST_RE.fullmatch(alias) or not endpoint(address):
            raise ValueError('INVALID_HOST_OR_ADDRESS')
        entry = {'ansible_host': address, 'ansible_user': user, 'ansible_port': port,
                 'ansible_connection': 'ssh'}
        for candidate in (existing.get(alias), hosts.get(alias)):
            if candidate is not None and any(candidate.get(key, 'ssh' if key == 'ansible_connection' else 22 if key == 'ansible_port' else alias if key == 'ansible_host' else None) != value
                                             for key, value in entry.items()):
                raise ValueError('EXISTING_ALIAS_HAS_DIFFERENT_SSH_SETTINGS')
        hosts[alias] = entry
        # Existing policies are preserved; new targets always start audit-only.
        proposed['policies'].setdefault(alias, {'mode': 'audit'})
    proposed['required_hosts'] = sorted(set(proposed.get('required_hosts', [])) | set(required))
    if str(overlay_path) not in proposed['inventories']:
        proposed['inventories'].append(str(overlay_path))
    validate(proposed)
    return proposed, hosts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--host', action='append', default=[], help='Explicit alias=hostname-or-IP')
    parser.add_argument('--require-host', action='append', default=[])
    parser.add_argument('--ssh-user', required=True)
    parser.add_argument('--ssh-port', type=int, default=22)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', args.ssh_user) or not 1 <= args.ssh_port <= 65535:
        parser.error('Invalid SSH user or port')
    os.umask(0o077)
    config_path = args.config.expanduser().resolve(strict=True)
    config = private_json(config_path)
    validate(config)
    additions = []
    for value in args.host:
        if value.count('=') != 1:
            parser.error('--host requires alias=address')
        additions.append(tuple(value.split('=', 1)))
    result = command([config['ansible_inventory'], *inventory_args(config), '--list'], 120, True)
    if result.returncode:
        raise ValueError('CURRENT_INVENTORY_FAILED')
    existing = json.loads(result.stdout).get('_meta', {}).get('hostvars', {})
    overlay_path = config_path.parent / 'extra-update-hosts.json'
    if overlay_path.is_symlink():
        raise ValueError('OVERLAY_SYMLINK_REFUSED')
    if overlay_path.exists():
        data = private_json(overlay_path)
        overlay = data['all']['children']['external_mail_nodes']['hosts']
        if data != {'all': {'children': {'external_mail_nodes': {'hosts': overlay}}}}:
            raise ValueError('UNREVIEWED_OVERLAY_LAYOUT')
    else:
        overlay = {}
    proposed, hosts = registration(config, existing, overlay, additions, args.require_host,
                                   args.ssh_user, args.ssh_port, overlay_path)
    document = {'all': {'children': {'external_mail_nodes': {'hosts': hosts}}}}
    if proposed == config and overlay == hosts:
        print('UPDATE_HOST_REGISTRATION_UNCHANGED')
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    # Preserve private configuration and overlay before changing either file.
    backup = config_path.parent / ('before-host-registration-' + stamp)
    backup.mkdir(mode=0o700)
    write_json(backup / 'config.json', config)
    if overlay_path.exists():
        write_json(backup / 'extra-update-hosts.json', data)
    write_json(overlay_path, document)
    write_json(config_path, proposed)
    print('UPDATE_HOSTS_REGISTERED_AUDIT_ONLY ' + ','.join(alias for alias, _ in additions))
    missing = set(proposed['required_hosts']) - (set(existing) | set(hosts))
    if missing:
        print('REQUIRED_HOSTS_STILL_MISSING ' + ','.join(sorted(missing)))


if __name__ == '__main__':
    main()
