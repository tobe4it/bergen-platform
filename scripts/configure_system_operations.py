#!/usr/bin/env python3
"""Enable read-only system reporting and an explicit central syslog source."""
import argparse
from pathlib import Path
import uuid
from system_updates import private_json, write_json, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--syslog-host', required=True, help='Inventory alias of collector or its Proxmox host')
    parser.add_argument('--syslog-ctid', type=int, default=0, help='Read through pct exec on this exact CT')
    parser.add_argument('--expected-hostname', default='bergen-syslog')
    args = parser.parse_args()
    path = args.config.expanduser().resolve(strict=True)
    config = private_json(path)
    proposed = {**config, 'operations': {'enabled': True, 'syslog_host': args.syslog_host,
                'syslog_ctid': args.syslog_ctid, 'syslog_expected_hostname': args.expected_hostname,
                'log_names': config.get('operations', {}).get('log_names', {})}}
    validate(proposed)
    if proposed == config:
        print('OPERATIONS_REPORT_CONFIG_UNCHANGED')
        return
    write_json(path.with_name('config.before-operations-' + uuid.uuid4().hex + '.json'), config)
    write_json(path, proposed)
    print('OPERATIONS_REPORT_ENABLED; OLD_CRON_UNCHANGED')


if __name__ == '__main__':
    main()
