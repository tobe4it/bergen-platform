"""Independent read-only system probes and central log summaries for daily email."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def probe(config, host, variables, path):
    inputs = path.with_suffix('.vars.json')
    inputs.write_text(json.dumps({**variables, 'operations_result_file': str(path)}))
    inputs.chmod(0o600)
    command = [config['ansible_playbook']]
    for inventory in config['inventories']:
        command += ['-i', inventory]
    if config.get('vault_password_file'):
        command += ['--vault-password-file', config['vault_password_file']]
    command += [str(ROOT / 'ansible/playbooks/system-update-operations.yml'), '--limit', host,
                '--extra-vars', '@' + str(inputs)]
    try:
        result = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=150,
                                env={**os.environ, 'ANSIBLE_HOST_KEY_CHECKING': 'True',
                                     'ANSIBLE_STDOUT_CALLBACK': 'default'})
        if result.returncode or not path.is_file():
            return {'status': 'ERROR', 'reason': 'OPERATIONS_ANSIBLE_FAILED'}
        return json.loads(path.read_text())
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {'status': 'ERROR', 'reason': type(exc).__name__}
    finally:
        inputs.unlink(missing_ok=True)


def collect(config, report, directory):
    options = config.get('operations', {})
    if not options.get('enabled'):
        return
    print('OPERATIONS_REPORT_COLLECTING', flush=True)
    names = {}
    for index, host in enumerate(report.get('hosts', [])):
        if host.get('status') == 'EXCLUDED':
            continue
        if host.get('status') == 'UNREACHABLE' or host.get('reason') == 'REQUIRED_HOST_MISSING_FROM_INVENTORY':
            host['operations'] = {'status': 'NOT_RUN', 'reason': 'HOST_NOT_REACHABLE_OR_NOT_IN_INVENTORY'}
        else:
            host['operations'] = probe(config, host['host'], {}, directory / f'operations-{index:04d}.json')
        evidence = host['operations']
        labels = {host['host']}
        labels.update(options.get('log_names', {}).get(host['host'], []))
        for key in ('fqdn', 'hostname'):
            if isinstance(evidence.get(key), str) and evidence[key]:
                labels.add(evidence[key])
        names[host['host']] = sorted(labels)
        if evidence.get('kernel', {}).get('reboot') == 'REQUIRED':
            host['reboot'] = 'REQUIRED'
            host['reboot_evidence'] = 'RUNNING_KERNEL_OLDER_THAN_INSTALLED_KERNEL'
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    syslog = probe(config, options['syslog_host'], {
        'operations_mode': 'syslog', 'operations_host_names': names,
        'operations_since': now - 86400, 'operations_until': now,
        'operations_via_ctid': options.get('syslog_ctid', 0),
        'operations_expected_hostname': options.get('syslog_expected_hostname', 'bergen-syslog'),
    }, directory / 'central-syslog.json')
    report['central_syslog'] = syslog
    for host in report.get('hosts', []):
        if 'operations' in host:
            host['operations']['central_logs'] = syslog.get('hosts', {}).get(host['host'], {
                'status': 'UNKNOWN', 'reason': syslog.get('reason', 'CENTRAL_LOG_HOST_RESULT_MISSING')})


def report_lines(report):
    if 'central_syslog' not in report and not any('operations' in h for h in report.get('hosts', [])):
        return []
    lines = ['', 'Betrieb und zentrale Logs (nach dem Paketlauf)',
             'Logquelle: Bergen-syslog; 24h-Zeitfenster, begrenzte Dateiausschnitte.',
             'Nur Ereigniskategorien/Zähler; keine rohen Logzeilen, Mailadressen oder Schlüssel.']
    central = report.get('central_syslog', {})
    lines.append('Zentrale Logprüfung: ' + central.get('status', 'UNKNOWN'))
    if central.get('reason'):
        lines.append('  Befund: ' + central['reason'])
    if central.get('unparsed_records'):
        lines.append('  Nicht zeitlich zuordenbare Zeilen: ' + str(central['unparsed_records']))
    if central.get('truncated'):
        lines.append('  Umfang begrenzt; Ereigniszähler sind Stichproben, keine vollständigen Tageszahlen.')
    for host in report.get('hosts', []):
        ops = host.get('operations')
        if not ops:
            continue
        lines += ['', host['host'] + ' | Betrieb: ' + ops.get('status', 'UNKNOWN')]
        if ops.get('reason'):
            lines.append('  Befund: ' + ops['reason'])
        if 'load_1m' in ops:
            lines.append(f"  CPU Load 1m: {ops['load_1m']} bei {ops.get('cpu_count')} CPUs; RAM: {ops.get('memory_used_percent', 'UNKNOWN')} %")
        for disk in ops.get('disks', []):
            lines.append(f"  Dateisystem {disk['mount']}: {disk['used_percent']} % belegt; {disk['available_bytes'] // (1024**2)} MiB frei")
        for issue in ops.get('issues', []):
            lines.append('  HANDLUNGSBEDARF: ' + issue)
        services = ops.get('services', {})
        for service in services.get('selected', []):
            lines.append('  Dienst ' + service['name'] + ': ' + service['active'] + '/' + service['sub'])
        if services.get('failed'):
            lines.append('  Fehlgeschlagene Units: ' + ', '.join(services['failed']))
        queue = ops.get('postfix_queue', {})
        if queue.get('status') != 'NOT_INSTALLED' and queue:
            lines.append(f"  Postfix-Queue: {queue.get('observed_messages', 'UNKNOWN')}; Prüfung={queue.get('status')}; exakte Anzahl={queue.get('count_exact', False)}")
        rspamd = ops.get('rspamd', {})
        if rspamd.get('status') != 'NOT_INSTALLED' and rspamd:
            lines.append('  Rspamd: ' + rspamd.get('status', 'UNKNOWN') + '; Zähler: ' + json.dumps(rspamd.get('counters', {})))
        for runtime, state in ops.get('containers', {}).items():
            if state.get('status') == 'NOT_INSTALLED':
                continue
            lines.append('  ' + runtime + ': ' + state.get('status', 'UNKNOWN') + ' (Root-Runtime)')
            for container in state.get('containers', []):
                lines.append('    ' + container['name'] + ': ' + container['state'] + (' UNHEALTHY' if container['unhealthy'] else ''))
        wg = ops.get('wireguard', {})
        if wg.get('status') != 'NOT_INSTALLED' and wg:
            lines.append(f"  WireGuard: {wg.get('status')}; Interfaces={wg.get('interfaces')}; Peers={wg.get('peers')}; jüngste Handshakes={wg.get('handshakes_within_180s')}; ruhende Peers nicht als Fehler bewertet")
        kernel = ops.get('kernel', {})
        if kernel:
            lines.append('  Kernel läuft: ' + kernel.get('running', 'UNKNOWN') + '; neuester installierter: ' + kernel.get('latest_installed', 'nicht ermittelt'))
        advisory = ops.get('advisories', {})
        if advisory:
            lines.append('  CVE-Abfrage: ' + advisory.get('status', 'UNKNOWN') + '; Quelle: ' + advisory.get('source', advisory.get('reason', 'UNKNOWN')))
            lines.append('  CVEs: ' + (', '.join(advisory.get('cves', [])) or 'keine erfasst; kein Entwarnungsnachweis'))
            if advisory.get('advisories'):
                lines.append('  Advisories: ' + ', '.join(advisory['advisories']))
            if advisory.get('freshness'):
                lines.append('  Metadatenaktualität der CVE-Abfrage: ' + advisory['freshness'])
        logs = ops.get('central_logs', {})
        lines.append('  Bergen-syslog: ' + logs.get('status', 'UNKNOWN') + '; jüngere Stichprobenzeilen: ' + str(logs.get('recent_records', 0)))
        if logs.get('events'):
            lines.append('  Logereignisse: ' + ', '.join(k + '=' + str(v) for k, v in sorted(logs['events'].items())))
        if logs.get('status') in ('NO_RECENT_DATA', 'UNKNOWN', 'AMBIGUOUS_HOSTNAME'):
            lines.append('  Logabdeckung nicht bestätigt; Quelle, Weiterleitung und Hostzuordnung prüfen.')
    return lines
