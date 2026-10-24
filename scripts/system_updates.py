#!/usr/bin/env python3
"""Sequential Ansible patch runner, bounded reports and verified-TLS SMTP."""
import argparse
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import smtplib
import shlex
import ssl
import subprocess
import sys
import uuid
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

ROOT = Path(__file__).resolve().parents[1]
HOST_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temp.chmod(0o600)
    temp.replace(path)


def private_json(path):
    path = Path(path)
    if path.stat().st_mode & 0o077:
        raise ValueError('CONFIG_MUST_BE_PRIVATE_0600')
    return json.loads(path.read_text())


def command(argv, timeout, capture=False, extra_env=None):
    return subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, text=True, timeout=timeout,
                          env={**os.environ, 'ANSIBLE_NOCOLOR': '1',
                               'ANSIBLE_HOST_KEY_CHECKING': 'True',
                               'ANSIBLE_RETRY_FILES_ENABLED': 'False', **(extra_env or {})})


def inventory_args(config):
    args = []
    for path in config['inventories']:
        args += ['-i', str(Path(path).resolve())]
    if config.get('vault_password_file'):
        args += ['--vault-password-file', config['vault_password_file']]
    return args


def load_hosts(config):
    result = command([config['ansible_inventory'], *inventory_args(config), '--list'], 120, True)
    if result.returncode:
        raise RuntimeError('INVENTORY_FAILED')
    inventory = json.loads(result.stdout)
    hosts = set(inventory.get('_meta', {}).get('hostvars', {}))
    for name, group in inventory.items():
        if name != '_meta':
            hosts.update(group.get('hosts', []))
    if not hosts or any(not HOST_RE.fullmatch(h) for h in hosts):
        raise ValueError('EMPTY_OR_UNSUPPORTED_HOST_NAMES')
    return sorted(hosts)


def validate(config):
    for key in ('inventories', 'ansible_inventory', 'ansible_playbook', 'state_dir', 'smtp', 'policies'):
        if key not in config:
            raise ValueError('CONFIG_MISSING_' + key.upper())
    if not config['inventories'] or not isinstance(config['policies'], dict):
        raise ValueError('INVALID_INVENTORY_OR_POLICIES')
    required = config.get('required_hosts', [])
    if not isinstance(required, list) or any(not isinstance(h, str) or not HOST_RE.fullmatch(h) for h in required):
        raise ValueError('INVALID_REQUIRED_HOSTS')
    for host, policy in config['policies'].items():
        if not HOST_RE.fullmatch(host) or policy.get('mode') not in ('security', 'audit', 'excluded'):
            raise ValueError('INVALID_HOST_POLICY')
        if policy['mode'] == 'security' and (not policy.get('restart_services') or not policy.get('health_urls')):
            raise ValueError('SECURITY_POLICY_REQUIRES_RESTARTS_AND_HEALTH_URLS')
        if policy['mode'] == 'excluded' and not policy.get('reason'):
            raise ValueError('EXCLUSION_REQUIRES_REASON')
    mail = config['smtp']
    for key in ('host', 'port', 'username', 'password_file', 'sender', 'recipient'):
        if not mail.get(key):
            raise ValueError('SMTP_MISSING_' + key.upper())
    for key in ('sender', 'recipient'):
        if not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+', mail[key]):
            raise ValueError('INVALID_MAIL_ADDRESS')


def failure_details(stdout, host, task=None):
    prefix = 'BERGEN_UPDATE_DIAGNOSTIC='
    frames = [line[len(prefix):] for line in stdout.splitlines() if line.startswith(prefix)]
    if len(frames) != 1:
        return {}
    try:
        events = json.loads(frames[0])
        if not isinstance(events, list) or len(events) > 32:
            return {}
        events = [e for e in events if isinstance(e, dict) and e.get('host') == host]
        matching = [e for e in events if e.get('task') == task]
        event = (matching or [e for e in events if not e.get('ignored')] or events)[0]
        if not re.fullmatch(r'[A-Z0-9_]{1,80}', event.get('code', '')):
            return {}
        # The callback uses fixed task names; never import arbitrary messages.
        result = {'failure_code': event['code']}
        name = event.get('task', '')
        if re.fullmatch(r'[A-Za-z ]{1,120}', name):
            result['failed_task'] = name
        if type(event.get('rc')) is int:
            result['failure_rc'] = event['rc']
        return result
    except (ValueError, TypeError, IndexError):
        return {}


def run_host(config, host, policy, apply, result_path):
    variables = {
        'system_updates_apply': apply,
        'system_updates_result_file': str(result_path),
        'system_updates_restart_services': policy.get('restart_services', []),
        'system_updates_health_urls': policy.get('health_urls', []),
        'system_updates_dnf_metadata_verified': policy.get('dnf_metadata_verified', False),
    }
    variables_path = result_path.with_suffix('.vars.json')
    write_json(variables_path, variables)
    try:
        result = command([config['ansible_playbook'], *inventory_args(config),
                          str(ROOT / 'ansible/playbooks/system-updates.yml'),
                          '--limit', host, '--extra-vars', '@' + str(variables_path)],
                         config.get('host_timeout_seconds', 3600), True,
                         extra_env={'ANSIBLE_STDOUT_CALLBACK': 'bergen_update_diagnostic',
                                    'ANSIBLE_CALLBACK_PLUGINS': str(ROOT / 'ansible/callback_plugins')})
        if result_path.exists():
            report = json.loads(result_path.read_text())
        else:
            report = {'status': 'UNREACHABLE' if result.returncode == 4 else 'FAILED',
                      'reason': 'NO_HOST_REPORT', 'packages': []}
        if result.returncode and report.get('status') == 'OK':
            report.update(status='FAILED', reason='ANSIBLE_NONZERO_EXIT')
        if report.get('status') in ('FAILED', 'UNREACHABLE'):
            report.update(failure_details(getattr(result, 'stdout', '') or '', host, report.get('failed_task')))
        return report
    except subprocess.TimeoutExpired:
        # Never retry a package transaction blindly: remote work may still be running.
        return {'status': 'FAILED', 'reason': 'TIMEOUT_REMOTE_STATE_UNKNOWN', 'packages': []}
    finally:
        variables_path.unlink(missing_ok=True)


def process_hosts(config, hosts, run_dir, audit_only=False):
    results, stopped = [], bool(missing_required_hosts(config, hosts))
    order = config.get('canaries', [])
    if not audit_only and any(p['mode'] == 'security' for p in config['policies'].values()):
        if not order or any(config['policies'].get(h, {}).get('mode') != 'security' for h in order):
            raise ValueError('EXPLICIT_SECURITY_CANARY_REQUIRED')
    if any(h not in hosts for h in order):
        raise ValueError('CANARY_NOT_IN_INVENTORY')
    hosts = list(dict.fromkeys(order + hosts))
    for index, host in enumerate(hosts):
        policy = config['policies'].get(host, {'mode': 'audit'})
        mode = policy['mode']
        if mode == 'excluded':
            report = {'status': 'EXCLUDED', 'reason': policy['reason'], 'packages': []}
        else:
            apply = mode == 'security' and not stopped and not audit_only
            try:
                report = run_host(config, host, policy, apply, run_dir / f'host-{index:04d}.json')
            except Exception as exc:
                report = {'status': 'FAILED', 'reason': type(exc).__name__, 'packages': []}
            report['mode'] = 'APPLY' if apply else 'AUDIT'
            if stopped and mode == 'security':
                report['deferred'] = 'Host failure or missing required inventory target; installation deferred'
            if report['status'] != 'OK':
                stopped = True
        report['host'] = host
        report['policy'] = mode
        results.append(report)
        write_json(run_dir / 'hosts.json', results)
    return results


def overall(report):
    if report.get('error') or not report.get('hosts') or any(h['status'] in ('FAILED', 'UNREACHABLE') for h in report['hosts']):
        return 'FEHLER'
    if any(h['status'] != 'OK' or h.get('reboot', 'UNKNOWN') not in ('NOT_REQUIRED', 'NO_MARKER') or
           h.get('held') or h.get('deferred') or h.get('checks') != 'PASSED' or
           (h.get('mode') == 'AUDIT' and (h.get('candidates') or h.get('dnf_updates_available')))
           for h in report['hosts']):
        return 'WARNUNG'
    return 'OK'


def missing_required_hosts(config, inventory_hosts):
    return [{'host': host, 'policy': 'audit', 'mode': 'AUDIT', 'status': 'FAILED',
             'reason': 'REQUIRED_HOST_MISSING_FROM_INVENTORY',
             'failure_code': 'REQUIRED_HOST_MISSING_FROM_INVENTORY', 'packages': []}
            for host in sorted(set(config.get('required_hosts', [])) - set(inventory_hosts))]


def render(report):
    status = overall(report)
    hosts = report.get('hosts', [])
    checked = sum(h['status'] == 'OK' for h in hosts)
    changed = sum(bool(h.get('packages')) for h in hosts)
    subject = f"[Bergen Platform][Updates][{status}] {report['started'][:10]} – {checked}/{len(hosts)} erfolgreich geprüft"
    lines = ['Bergen Platform – Update- und Change-Bericht',
             f"Gesamtstatus: {status}", f"Lauf-ID: {report['run_id']}",
             f"Beginn (UTC): {report['started']}", f"Ende (UTC): {report['finished']}",
             f"Git-Commit: {report['commit']}", f"Konfigurationsfingerabdruck: {report['config_sha256']}",
             f"Verfahren: {report['mode']}; OS-Sicherheitsupdates, keine automatischen Reboots",
             f"Systeme: {len(hosts)}; erfolgreich geprüft: {checked}; verändert: {changed}", '']
    if report.get('error'):
        lines += ['Lauffehler: ' + report['error'], 'Handlung: Controller-Konfiguration und Journal prüfen.', '']
    rows = []
    for host in hosts:
        row = [host['host'], host.get('mode', host.get('policy', '')), host['status'],
               str(len(host.get('packages', []))), ', '.join(host.get('restarted', [])) or '–',
               host.get('reboot', 'UNKNOWN'), host.get('checks', 'NOT_RUN')]
        rows.append('<tr>' + ''.join('<td>' + html.escape(v) + '</td>' for v in row) + '</tr>')
        lines += [' | '.join(row), '  Befund: ' + host.get('reason', 'NONE')]
        if host.get('failed_task'):
            lines.append('  Fehlgeschlagener Task: ' + host['failed_task'])
        if host.get('failure_code'):
            lines.append('  Fehlerursache: ' + host['failure_code'])
        if 'failure_rc' in host:
            lines.append('  Task-Rückgabecode: ' + str(host['failure_rc']))
        for package in host.get('packages', []):
            lines.append(f"  {package['name']}: {package['old']} → {package['new']}")
        if host.get('deferred'):
            lines.append('  Zurückgestellt: ' + host['deferred'])
        if host['status'] in ('FAILED', 'UNREACHABLE'):
            lines.append('  PRIORITÄT 1: Gemeldete Fehlerursache beheben und betroffenen Host erneut prüfen.')
        if host.get('reason') == 'TIMEOUT_REMOTE_STATE_UNKNOWN':
            lines.append('  Transaktionszustand vor Wiederholung klären; Remote-Arbeit kann noch laufen.')
        if host.get('held'):
            lines.append('  PRIORITÄT 1: Zurückgehaltene Sicherheitsupdates prüfen.')
        if host.get('mode') == 'AUDIT' and (host.get('candidates') or host.get('dnf_updates_available')):
            lines.append('  PRIORITÄT 1: Sicherheitsupdates verfügbar; Installation ausstehend.')
        if host.get('reboot') == 'REQUIRED':
            lines.append('  PRIORITÄT 2: Neustart im Wartungsfenster planen.')
        if host.get('reboot') == 'NO_MARKER':
            lines.append('  Kein Debian-Neustartmarker; daraus folgt kein Nachweis über alle laufenden Bibliotheken.')
        if host.get('reboot', 'UNKNOWN') == 'UNKNOWN':
            lines.append('  PRIORITÄT 2: Neustartbedarf nicht ermittelbar; manuell prüfen.')
    lines += ['', 'Abdeckung: ausschließlich konfigurierte Inventory-Hosts und Distributions-Sicherheitsquellen.',
              'Drittanbieterpakete, Container-Images, Firmware und Anwendungsupdates benötigen separate Prüfung.',
              'Keine CVE-Schließung aus einer bloßen Paketversion abgeleitet. Details im bereinigten JSON-Anhang.',
              'SMTP-Annahme bestätigt keine Zustellung ins Postfach.']
    plain = '\n'.join(lines)
    body = ('<!doctype html><html lang="de"><meta charset="utf-8"><body style="font-family:Arial,sans-serif;color:#183044">'
            '<h1>Bergen Platform</h1><h2>Update- und Change-Bericht · ' + status + '</h2>'
            '<p>' + html.escape(f"{checked}/{len(hosts)} Systeme erfolgreich geprüft · {changed} verändert") + '</p>'
            '<table cellpadding="8" border="1" style="border-collapse:collapse"><tr>'
            '<th>System</th><th>Modus</th><th>Status</th><th>Pakete</th><th>Neustarts Dienste</th><th>Reboot</th><th>Prüfung</th></tr>'
            + ''.join(rows) + '</table><h2>Nachweis und Folgemaßnahmen</h2><pre style="white-space:pre-wrap">'
            + html.escape(plain) + '</pre></body></html>')
    return subject, plain, body


def send_report(config, report, run_dir):
    subject, plain, body = render(report)
    (run_dir / 'report.txt').write_text(plain)
    (run_dir / 'report.html').write_text(body)
    mail = config['smtp']
    secret = Path(mail['password_file'])
    if secret.stat().st_mode & 0o077:
        raise ValueError('SMTP_PASSWORD_FILE_MUST_BE_0600')
    message = EmailMessage()
    message['From'], message['To'] = mail['sender'], mail['recipient']
    message['Subject'] = subject
    message['Date'] = format_datetime(dt.datetime.now(dt.timezone.utc))
    message['Message-ID'] = make_msgid()
    message.set_content(plain)
    message.add_alternative(body, subtype='html')
    message.add_attachment(json.dumps(report, indent=2, ensure_ascii=False).encode(),
                           maintype='application', subtype='json', filename='update-change-report.json')
    (run_dir / 'message.eml').write_bytes(message.as_bytes())
    with smtplib.SMTP(mail['host'], int(mail['port']), timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(mail['username'], secret.read_text().rstrip('\r\n'))
        refused = smtp.send_message(message)
        if refused:
            raise RuntimeError('SMTP_RECIPIENT_REFUSED')
    write_json(run_dir / 'delivery.json', {'status': 'SMTP_ACCEPTED', 'at': now(),
                                           'message_id': message['Message-ID']})


def run(config, audit_only=False):
    state = Path(config['state_dir']).resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    with (state / 'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('UPDATE_RUN_ALREADY_ACTIVE', file=sys.stderr)
            return 3
        run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        directory = state / run_id
        directory.mkdir(mode=0o700)
        report = {'run_id': run_id, 'started': now(), 'commit': 'UNKNOWN',
                  'config_sha256': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                  'mode': 'AUDIT_ONLY' if audit_only else 'POLICY', 'hosts': []}
        try:
            validate(config)
            rev = command(['git', 'rev-parse', 'HEAD'], 10, True)
            dirty = command(['git', 'status', '--porcelain', '--untracked-files=normal'], 10, True)
            if rev.returncode or dirty.returncode or dirty.stdout.strip():
                raise ValueError('RUN_REQUIRES_CLEAN_COMMITTED_CHECKOUT')
            report['commit'] = rev.stdout.strip()
            hosts = load_hosts(config)
            unknown = set(config['policies']) - set(hosts)
            if unknown:
                raise ValueError('POLICY_HOST_MISSING_FROM_INVENTORY')
            report['hosts'] = process_hosts(config, hosts, directory, audit_only)
            report['hosts'].extend(missing_required_hosts(config, hosts))
        except Exception as exc:
            # Exception text can contain credentials/URLs: retain only category.
            report['error'] = type(exc).__name__
            if (directory / 'hosts.json').exists():
                report['hosts'] = json.loads((directory / 'hosts.json').read_text())
        report['finished'] = now()
        write_json(directory / 'report.json', report)
        try:
            send_report(config, report, directory)
        except Exception as exc:
            write_json(directory / 'delivery.json', {'status': 'FAILED', 'error_type': type(exc).__name__, 'at': now()})
            print('REPORT_DELIVERY_FAILED ' + run_id, file=sys.stderr)
            return 2
        write_json(state / 'last-completed.json', {'run_id': run_id, 'finished': report['finished'], 'status': overall(report)})
        print('UPDATE_REPORT_SMTP_ACCEPTED ' + run_id + ' ' + overall(report))
        return 1 if overall(report) == 'FEHLER' else 0


def watchdog(config):
    """Run on another machine so controller loss is detectable."""
    watch = config['watchdog']
    target = watch['ssh_target']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+', target):
        raise ValueError('INVALID_WATCHDOG_TARGET')
    stale = True
    try:
        result = command(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                          '-o', 'ConnectTimeout=10', target,
                          'cat -- ' + shlex.quote(watch['heartbeat_path'])], 30, True)
        if result.returncode == 0:
            heartbeat = json.loads(result.stdout)
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(heartbeat['finished'])).total_seconds()
            stale = not 0 <= age <= watch.get('max_age_hours', 30) * 3600
    except Exception:
        pass
    if not stale:
        print('CONTROLLER_HEARTBEAT_CURRENT')
        return 0
    state = Path(config['state_dir']).resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    run_id = 'watchdog-' + uuid.uuid4().hex
    directory = state / run_id
    directory.mkdir(mode=0o700)
    report = {'run_id': run_id, 'started': now(), 'finished': now(), 'commit': 'WATCHDOG',
              'config_sha256': 'NOT_APPLICABLE', 'mode': 'INDEPENDENT_WATCHDOG',
              'hosts': [], 'error': 'Controller heartbeat missing, stale or unreachable; daily update report not confirmed'}
    write_json(directory / 'report.json', report)
    try:
        send_report(config, report, directory)
    except Exception:
        write_json(directory / 'delivery.json', {'status': 'FAILED', 'at': now()})
        return 2
    return 1


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--audit-only', action='store_true')
    parser.add_argument('--watchdog', action='store_true', help='Run on an independent host; alert on stale controller heartbeat')
    parser.add_argument('--retry-report', help='Existing report.json; retries mail only, never updates')
    args = parser.parse_args()
    config = private_json(args.config)
    if args.watchdog:
        return watchdog(config)
    if args.retry_report:
        path = Path(args.retry_report).resolve()
        send_report(config, json.loads(path.read_text()), path.parent)
        return 0
    return run(config, args.audit_only)


if __name__ == '__main__':
    sys.exit(main())
