#!/usr/bin/env python3
"""Preflight an explicitly selected cohort, then enable hourly policy runs locally."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pwd
import uuid

from system_updates import ROOT, command, inventory_args, load_hosts, private_json, run_host, validate, write_json


def prepare(config, report, policies, canary):
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(report['finished'])).total_seconds()
    if not 0 <= age <= 86400:
        raise ValueError('AUDIT_REPORT_MUST_BE_WITHIN_24_HOURS')
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    if report.get('config_sha256') != fingerprint:
        raise ValueError('CONFIG_CHANGED_SINCE_AUDIT')
    if not isinstance(policies, dict) or not policies or canary not in policies:
        raise ValueError('EXPLICIT_COHORT_AND_CANARY_REQUIRED')
    hosts = {h['host']: h for h in report['hosts']}
    proposed = json.loads(json.dumps(config))
    for name, policy in policies.items():
        prior = hosts.get(name, {})
        if prior.get('status') != 'OK' or prior.get('operations', {}).get('status') not in ('OK', 'WARNING'):
            raise ValueError('COHORT_REQUIRES_SUCCESSFUL_AUDIT_AND_OPERATIONS')
        if policy.get('mode') != 'security':
            raise ValueError('COHORT_REQUIRES_SECURITY_MODE')
        proposed['policies'][name] = {**proposed['policies'].get(name, {}), **policy}
    if any(p.get('mode') == 'security' and h not in policies for h, p in proposed['policies'].items()):
        raise ValueError('UNREVIEWED_EXISTING_SECURITY_POLICY')
    proposed['canaries'] = [canary]
    validate(proposed)
    return proposed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--policies', type=Path, required=True)
    parser.add_argument('--canary', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    path = args.config.expanduser()
    if path.is_symlink():
        raise SystemExit('STOP: CONFIG_SYMLINK')
    config = private_json(path)
    policies = private_json(args.policies)
    proposed = prepare(config, private_json(args.report), policies, args.canary)
    inventory = set(load_hosts(config))
    if not set(policies).issubset(inventory) or not set(config.get('required_hosts', [])).issubset(inventory):
        raise SystemExit('STOP: REQUIRED_INVENTORY_COVERAGE_MISSING')
    rev = command(['git', 'status', '--porcelain'], 10, True)
    if rev.returncode or rev.stdout.strip():
        raise SystemExit('STOP: CLEAN_CHECKOUT_REQUIRED')
    directory = Path(config['state_dir']) / ('release-preflight-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700, parents=True)
    if (directory.parent / 'installation-blocked.json').exists():
        raise SystemExit('STOP: UNRESOLVED_REMOTE_TRANSACTION')
    inventory_path = directory / 'controller.json'
    write_json(inventory_path, {'controllers': {'hosts': {'release_controller': {
        'ansible_connection': 'local', 'ansible_python_interpreter': '/usr/bin/python3'}}}})
    privilege = command([str(Path(config['ansible_playbook']).with_name('ansible')),
                         *inventory_args(config), '-i', str(inventory_path), 'release_controller',
                         '--become', '-m', 'ansible.builtin.command', '-a', '/usr/bin/true'], 60, True)
    if privilege.returncode:
        log = directory / 'controller-privilege.log'
        log.write_text(privilege.stdout or '')
        log.chmod(0o600)
        raise SystemExit('STOP: CONTROLLER_BECOME_FAILED; inspect=' + str(log))
    print('RELEASE_PREFLIGHT_RUNNING; NO_PACKAGE_INSTALLATION', flush=True)
    # No configuration or timer change unless every cohort member passes now.
    for index, name in enumerate(policies):
        result = run_host(proposed, name, proposed['policies'][name], False, directory / f'host-{index:02d}.json')
        write_json(directory / f'preflight-{name}.json', result)
        if result.get('status') != 'OK' or result.get('checks') != 'PASSED':
            raise SystemExit('STOP: PREFLIGHT_FAILED ' + name + '; details=' + str(directory))
    backup = path.with_name('config.before-hourly-release-' + uuid.uuid4().hex + '.json')
    write_json(backup, config)
    write_json(path, proposed)
    user = pwd.getpwuid(os.getuid()).pw_name
    variables_path = directory / 'scheduler.json'
    write_json(variables_path, {
        'system_update_scheduler_user': user,
        'system_update_scheduler_repo': str(ROOT),
        'system_update_scheduler_config': str(path.resolve()),
        'system_update_scheduler_calendar': '*-*-* *:15:00 Europe/Berlin',
        'system_update_scheduler_run_now': True,
    })
    args = [config['ansible_playbook'], *inventory_args(config), '-i', str(inventory_path),
            str(ROOT / 'ansible/playbooks/install-system-update-scheduler.yml'),
            '--limit', 'release_controller',
            '-e', '@' + str(variables_path)]
    result = command(args, 180, True)
    log = directory / 'scheduler.log'
    log.write_text(result.stdout or '')
    log.chmod(0o600)
    if result.returncode:
        raise SystemExit('STOP: POLICY_RELEASED_SCHEDULER_NOT_CONFIRMED; inspect=' + str(log))
    print('HOURLY_UPDATES_ENABLED; FIRST_RUN_REQUESTED; CANARY=' + proposed['canaries'][0])
    print('RELEASED_HOSTS=' + ','.join(policies))
    print('BACKUP=' + str(backup))


if __name__ == '__main__':
    main()
