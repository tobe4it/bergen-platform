#!/usr/bin/env python3
"""Create a private audit-first configuration on the actual controller."""
import argparse
import getpass
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventory', action='append', required=True)
    parser.add_argument('--ansible-bin', required=True)
    parser.add_argument('--smtp-host', required=True)
    parser.add_argument('--smtp-user', required=True)
    parser.add_argument('--sender', required=True)
    parser.add_argument('--recipient', required=True)
    parser.add_argument('--config-dir', default=str(Path.home() / '.config/bergen-updates'))
    args = parser.parse_args()
    os.umask(0o077)
    directory = Path(args.config_dir).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path, password_path = directory / 'config.json', directory / 'smtp-password'
    if config_path.exists() or password_path.exists():
        parser.error('Existing configuration/password preserved; edit the existing config instead.')
    inventories = [str(Path(p).resolve(strict=True)) for p in args.inventory]
    binary_dir = Path(args.ansible_bin).resolve(strict=True)
    for binary in ('ansible-playbook', 'ansible-inventory'):
        if not os.access(binary_dir / binary, os.X_OK):
            parser.error('Missing executable: ' + binary)
    password = getpass.getpass('Bergen-Mail SMTP password (stored privately on this controller): ')
    if not password:
        parser.error('Empty password refused')
    config = {
        'inventories': inventories,
        'ansible_inventory': str(binary_dir / 'ansible-inventory'),
        'ansible_playbook': str(binary_dir / 'ansible-playbook'),
        'state_dir': str(Path.home() / '.local/state/bergen-updates'),
        'host_timeout_seconds': 3600, 'canaries': [], 'policies': {},
        'smtp': {'host': args.smtp_host, 'port': 587, 'username': args.smtp_user,
                 'sender': args.sender, 'recipient': args.recipient, 'password_file': str(password_path)}
    }
    from system_updates import validate
    validate(config)
    with password_path.open('x') as stream:
        stream.write(password)
    with config_path.open('x') as stream:
        json.dump(config, stream, indent=2)
        stream.write('\n')
    print('Private configuration created. All inventory hosts start in AUDIT mode.')
    print('Run scripts/system_updates.py --config ' + str(config_path) + ' --audit-only')


if __name__ == '__main__':
    main()
