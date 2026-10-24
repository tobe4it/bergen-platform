"""Read-only, bounded operating metrics and central syslog summaries (stdlib only)."""
import base64
from collections import Counter
import datetime as dt
import glob
import inspect
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import socket
import stat
import subprocess
import sys
import time

SAFE_NAME = re.compile(r'^[A-Za-z0-9_.@:-]{1,128}$')


def bounded(argv, timeout=10, limit=524288):
    """Never invoke a shell; stop a read-only probe on timeout/output overflow."""
    if not shutil.which(argv[0]):
        return {'status': 'NOT_INSTALLED', 'rc': None, 'text': ''}
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    chunks, size, status = [], 0, 'OK'
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = 'TIMEOUT'
                break
            if not selector.select(remaining):
                status = 'TIMEOUT'
                break
            chunk = os.read(proc.stdout.fileno(), min(8192, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                status = 'TRUNCATED'
                break
        if status != 'OK':
            proc.kill()
        try:
            rc = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc, status = None, 'TIMEOUT'
        if status == 'OK' and rc != 0:
            status = 'FAILED'
        return {'status': status, 'rc': rc,
                'text': b''.join(chunks)[:limit].decode('utf-8', errors='replace')}
    finally:
        selector.close()
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def disk_usage(mounts_path='/proc/mounts'):
    disks, seen = [], set()
    excluded = {'tmpfs', 'devtmpfs', 'overlay', 'proc', 'sysfs', 'cgroup', 'cgroup2',
                'devpts', 'squashfs', 'securityfs', 'pstore', 'debugfs', 'tracefs',
                'mqueue', 'hugetlbfs', 'fusectl', 'configfs', 'autofs', 'binfmt_misc'}
    for line in Path(mounts_path).read_text().splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[2] in excluded:
            continue
        mount = fields[1].replace('\\040', ' ').replace('\\134', '\\')
        if mount.startswith(('/var/lib/containers/', '/var/lib/docker/', '/run/')):
            continue
        try:
            usage = os.statvfs(mount)
            identity = (os.stat(mount).st_dev, usage.f_blocks)
            if identity in seen or usage.f_blocks == 0:
                continue
            seen.add(identity)
            used = usage.f_blocks - usage.f_bfree
            percent = round(100 * used / max(1, used + usage.f_bavail), 1)
            disks.append({'mount': mount[:160], 'used_percent': percent,
                          'available_bytes': usage.f_bavail * usage.f_frsize})
        except OSError:
            continue
    return disks[:32]


def service_states():
    result = bounded(['systemctl', 'list-units', '--all', '--type=service', '--no-legend', '--plain'], timeout=8)
    if result['status'] != 'OK':
        return {'status': result['status'], 'failed': [], 'selected': []}
    selected, failed = [], []
    names = {'nginx.service', 'httpd.service', 'apache2.service', 'postfix.service',
             'rspamd.service', 'dovecot.service', 'mailman.service', 'mailman3.service',
             'mailman-web.service', 'rsyslog.service', 'ssh.service', 'sshd.service'}
    for line in result['text'].splitlines():
        fields = line.split()
        if len(fields) < 4 or not SAFE_NAME.fullmatch(fields[0]):
            continue
        name, load, active, sub = fields[:4]
        if active == 'failed':
            failed.append(name)
        if name in names:
            selected.append({'name': name, 'load': load, 'active': active, 'sub': sub})
    return {'status': 'OK', 'failed': failed[:50], 'selected': selected[:20]}


def queue_summary():
    result = bounded(['postqueue', '-j'])
    if result['status'] == 'NOT_INSTALLED':
        return {'status': 'NOT_INSTALLED'}
    count, invalid = 0, False
    for line in result['text'].splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            invalid = invalid or bool(line.strip())
            continue
        if isinstance(item, dict) and 'queue_id' in item:
            count += 1
    return {'status': 'INVALID_RESULT' if invalid and result['status'] == 'OK' else result['status'],
            'observed_messages': count, 'count_exact': result['status'] == 'OK' and not invalid}


def containers(runtime):
    fmt = 'json' if runtime == 'podman' else '{{json .}}'
    result = bounded([runtime, 'ps', '-a', '--format', fmt])
    rows = []
    if result['status'] == 'OK':
        try:
            source = json.loads(result['text']) if runtime == 'podman' else [json.loads(s) for s in result['text'].splitlines()]
            for item in source[:100]:
                names = item.get('Names', [])
                name = names[0] if isinstance(names, list) and names else names
                state = str(item.get('State', 'unknown'))
                status = str(item.get('Status', ''))
                if isinstance(name, str) and SAFE_NAME.fullmatch(name):
                    rows.append({'name': name, 'state': state if SAFE_NAME.fullmatch(state) else 'unknown',
                                 'unhealthy': 'unhealthy' in status.lower()})
        except (ValueError, TypeError, AttributeError):
            return {'status': 'INVALID_RESULT', 'scope': 'ROOT_RUNTIME', 'containers': []}
    return {'status': result['status'], 'scope': 'ROOT_RUNTIME', 'containers': rows,
            'truncated': result['status'] == 'TRUNCATED' or len(rows) == 100}


def wireguard_summary():
    result = bounded(['wg', 'show', 'all', 'dump'])
    interfaces, peers, recent = 0, 0, 0
    now = int(time.time())
    for line in result['text'].splitlines():
        fields = line.split('\t')
        if len(fields) == 5:
            interfaces += 1  # Never retain the interface private key.
        elif len(fields) >= 9:
            peers += 1  # Never retain peer keys, PSKs, endpoints or allowed IPs.
            try:
                recent += 0 <= now - int(fields[5]) <= 180
            except ValueError:
                pass
    return {'status': result['status'], 'interfaces': interfaces, 'peers': peers,
            'handshakes_within_180s': recent, 'idle_peer_health': 'NOT_INFERRED'}


def advisories():
    if shutil.which('dnf'):
        result = bounded(['dnf', '-q', '--cacheonly', 'updateinfo', 'info', '--security'], timeout=20)
        source = 'DNF_CACHED_AVAILABLE_SECURITY_ADVISORIES'
    elif shutil.which('debsecan'):
        result = bounded(['debsecan', '--format', 'simple'], timeout=20)
        source = 'DEBSECAN'
    else:
        return {'status': 'NOT_COLLECTED', 'reason': 'NO_SUPPORTED_CVE_TOOL_INSTALLED'}
    cves = sorted(set(re.findall(r'\bCVE-\d{4}-\d{4,9}\b', result['text'])))
    ids = sorted(set(re.findall(r'\b(?:RLSA|RHSA|ALSA)-\d{4}:\d+\b', result['text'])))
    return {'status': result['status'], 'source': source, 'freshness': 'NOT_VERIFIED',
            'cves': cves[:100], 'advisories': ids[:100],
            'truncated': result['status'] == 'TRUNCATED' or len(cves) > 100 or len(ids) > 100,
            'coverage': 'CVE presence only; absence does not prove patched or unaffected'}


def kernel_summary():
    running = os.uname().release
    virtualization = bounded(['systemd-detect-virt', '--container'], timeout=3)
    if virtualization['status'] == 'OK':
        return {'running': running, 'status': 'CONTAINER_HOST_KERNEL', 'reboot': 'HOST_MANAGED'}
    result = bounded(['rpm', '-q', '--qf', '%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n', 'kernel-core'])
    if result['status'] != 'OK':
        return {'running': running, 'status': 'NOT_DETERMINED'}
    try:
        import rpm
        from functools import cmp_to_key
        rows = [line.split('\t') for line in result['text'].splitlines()]
        rows = [row for row in rows if len(row) == 4 and row[3] == os.uname().machine]
        newest = sorted(rows, key=cmp_to_key(lambda a, b: rpm.labelCompare(tuple(a[:3]), tuple(b[:3]))))[-1]
        installed = newest[1] + '-' + newest[2] + '.' + newest[3]
        current = next((row for row in rows if row[1] + '-' + row[2] + '.' + row[3] == running), None)
        if current is None:
            return {'running': running, 'latest_installed': installed, 'status': 'RUNNING_KERNEL_NOT_IN_PACKAGE_INVENTORY'}
        newer = rpm.labelCompare(tuple(newest[:3]), tuple(current[:3])) > 0
        return {'running': running, 'latest_installed': installed, 'status': 'VERIFIED_RPM_COMPARISON',
                'reboot': 'REQUIRED' if newer else 'NOT_REQUIRED'}
    except (ImportError, ValueError, IndexError):
        return {'running': running, 'status': 'NOT_DETERMINED'}


def collect_system():
    result = {'status': 'OK', 'fqdn': socket.getfqdn(), 'hostname': socket.gethostname(),
              'load_1m': round(os.getloadavg()[0], 2), 'cpu_count': os.cpu_count(), 'issues': []}
    try:
        memory = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            memory[key] = int(value.strip().split()[0])
        result['memory_used_percent'] = round(100 * (1 - memory['MemAvailable'] / memory['MemTotal']), 1)
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        result['memory_status'] = 'UNKNOWN'
    try:
        result['disks'] = disk_usage()
    except OSError:
        result['disks'] = []
    result['services'] = service_states()
    result['postfix_queue'] = queue_summary()
    result['containers'] = {name: containers(name) for name in ('podman', 'docker')}
    result['wireguard'] = wireguard_summary()
    result['advisories'] = advisories()
    result['kernel'] = kernel_summary()
    rspamd = bounded(['rspamadm', 'control', 'stat'], timeout=5)
    result['rspamd'] = {'status': rspamd['status']}
    # Export numeric counters only; no raw Rspamd/control output.
    try:
        counters = json.loads(rspamd['text'])
        result['rspamd']['counters'] = {k: counters[k] for k in
            ('messages_scanned', 'messages_learned', 'spam_count', 'ham_count')
            if k in counters and type(counters[k]) in (int, float)}
    except (ValueError, TypeError):
        pass
    if any(d['used_percent'] >= 90 for d in result['disks']):
        result['status'] = 'CRITICAL'
        result['issues'].append('FILESYSTEM_AT_LEAST_90_PERCENT')
    elif any(d['used_percent'] >= 80 for d in result['disks']):
        result['status'] = 'WARNING'
        result['issues'].append('FILESYSTEM_AT_LEAST_80_PERCENT')
    if result['services']['failed']:
        result['issues'].append('FAILED_SYSTEMD_UNITS')
    if result['services']['status'] != 'OK' or not result['disks']:
        result['issues'].append('OPERATING_METRICS_INCOMPLETE')
    if result['kernel'].get('reboot') == 'REQUIRED':
        result['issues'].append('INSTALLED_KERNEL_NOT_RUNNING')
    if result['advisories']['status'] in ('FAILED', 'TIMEOUT', 'TRUNCATED'):
        result['issues'].append('CVE_QUERY_INCOMPLETE')
    if any(result[name]['status'] in ('FAILED', 'TIMEOUT', 'TRUNCATED')
           for name in ('rspamd', 'postfix_queue', 'wireguard')):
        result['issues'].append('SERVICE_PROBE_INCOMPLETE')
    if any(value['status'] in ('FAILED', 'TIMEOUT', 'TRUNCATED', 'INVALID_RESULT')
           for value in result['containers'].values()):
        result['issues'].append('CONTAINER_PROBE_INCOMPLETE')
    if any(c.get('unhealthy') or c.get('state') in ('dead', 'restarting')
           for runtime in result['containers'].values() for c in runtime['containers']):
        result['issues'].append('CONTAINER_RUNTIME_PROBLEM')
    if result['issues'] and result['status'] == 'OK':
        result['status'] = 'WARNING'
    return result


EVENTS = [
    ('DNF_CACHE_FAILED', re.compile(r'failed to start.*dnf.*makecache|failed to download metadata|cannot download.*repomd', re.I)),
    ('SELINUX_DENIAL', re.compile(r'SELinux is preventing|avc:.*denied', re.I)),
    ('SSH_HANDSHAKE_FAILED', re.compile(r'kex_exchange_identification|invalid user|failed password', re.I)),
    ('HTTP_PROBE', re.compile(r'unknown resource:.*(?:/\.git/|/\.env)', re.I)),
    ('SERVICE_START_FAILED', re.compile(r'failed to start', re.I)),
    ('MAIL_DEFERRED', re.compile(r'status=deferred', re.I)),
    ('MAIL_REJECTED', re.compile(r'NOQUEUE: reject', re.I)),
    ('OTHER_WARNING_OR_ERROR', re.compile(r'\b(?:error|fatal|panic|critical|warning)\b', re.I)),
]


def log_record(line):
    # Do not guess time zones or years for legacy RFC3164 records.
    fields = line.split(None, 3)
    if line.startswith('<') and re.match(r'^<\d+>1 ', line):
        fields = line.split(None, 4)[1:]
    if len(fields) < 3:
        return None
    try:
        stamp = dt.datetime.fromisoformat(fields[0].replace('Z', '+00:00'))
        if stamp.tzinfo is None or not SAFE_NAME.fullmatch(fields[1]):
            return None
    except ValueError:
        return None
    return stamp.timestamp(), fields[1].lower().rstrip('.'), line


def collect_logs(host_names, since, until, log_dir='/var/log/remote'):
    root = Path(log_dir)
    if root.is_symlink() or not root.is_dir():
        return {'status': 'ERROR', 'reason': 'CENTRAL_LOG_DIRECTORY_UNAVAILABLE', 'hosts': {}}
    names = {}
    for alias, values in host_names.items():
        for name in values:
            names.setdefault(name.lower().rstrip('.'), set()).add(alias)
    results = {alias: {'status': 'NO_RECENT_DATA', 'recent_records': 0,
                       'events': {}, 'source_files': [], 'association': 'SYSLOG_HEADER_HOSTNAME'}
               for alias in host_names}
    files = sorted(set(glob.glob(str(root / '*.log')) + glob.glob(str(root / '*.log.1'))))
    truncated, unparsed, scanned, unreadable = len(files) > 128, 0, 0, 0
    deadline = time.monotonic() + 15
    for filename in files[:128]:
        if time.monotonic() > deadline:
            truncated = True
            break
        path = Path(filename)
        try:
            if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                continue
            with path.open('rb') as stream:
                size = os.fstat(stream.fileno()).st_size
                offset = max(0, size - 4 * 1024 * 1024)
                stream.seek(offset)
                if offset:
                    stream.readline()  # discard a possible partial record
                    truncated = True
                data = stream.read(4 * 1024 * 1024)
        except OSError:
            unreadable += 1
            continue
        scanned += 1
        for index, line in enumerate(data.decode('utf-8', errors='replace').splitlines()):
            if index % 1000 == 0 and time.monotonic() > deadline:
                truncated = True
                break
            record = log_record(line)
            if record is None:
                unparsed += 1
                continue
            timestamp, hostname, _ = record
            if not since <= timestamp <= until:
                continue
            aliases = names.get(hostname, set())
            if len(aliases) != 1:
                for alias in aliases:
                    results[alias]['status'] = 'AMBIGUOUS_HOSTNAME'
                continue
            result = results[next(iter(aliases))]
            result['recent_records'] += 1
            result['first_seen'] = min(result.get('first_seen', timestamp), timestamp)
            result['last_seen'] = max(result.get('last_seen', timestamp), timestamp)
            if path.name not in result['source_files'] and len(result['source_files']) < 8:
                result['source_files'].append(path.name)
            for category, pattern in EVENTS:
                if pattern.search(line):
                    result['events'][category] = result['events'].get(category, 0) + 1
                    break
    for result in results.values():
        if result['recent_records'] and result['status'] != 'AMBIGUOUS_HOSTNAME':
            result['status'] = 'WARNING' if result['events'] else 'OK'
    return {'status': 'PARTIAL' if truncated or unparsed or unreadable else 'OK', 'hosts': results,
            'scanned_files': scanned, 'unparsed_records': unparsed, 'truncated': truncated,
            'unreadable_files': unreadable,
            'since': since, 'until': until, 'scope': 'Bounded tails of current logs and first uncompressed rotation; not an exhaustive 24h count',
            'identity': 'Header-based association; syslog sender identity not authenticated by this probe'}


def collect_logs_via_pct(ctid, expected_hostname, host_names, since, until):
    # The utility is stdlib-only; transport its source opaquely into the guest.
    source = inspect.getsource(sys.modules[__name__])
    payload = base64.b64encode(source.encode()).decode('ascii')
    code = "import base64;exec(compile(base64.b64decode('" + payload + "'), '<bergen-operations>', 'exec'));"
    code += "p=json.loads(sys.argv[1]);assert socket.gethostname().split('.')[0]==p.pop('expected_hostname');print(json.dumps(collect_logs(**p)))"
    args = {'expected_hostname': expected_hostname, 'host_names': host_names, 'since': since, 'until': until}
    result = bounded(['pct', 'exec', str(ctid), '--', '/usr/bin/python3', '-c', code, json.dumps(args)], timeout=45)
    if result['status'] != 'OK':
        return {'status': 'ERROR', 'reason': 'CENTRAL_LOG_GUEST_PROBE_FAILED', 'hosts': {}}
    try:
        return json.loads(result['text'])
    except ValueError:
        return {'status': 'ERROR', 'reason': 'CENTRAL_LOG_RESULT_INVALID', 'hosts': {}}
