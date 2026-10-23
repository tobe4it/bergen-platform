#!/usr/bin/env python3
"""Repair the observed subscription-less PVE 9 source layout and email evidence."""
import argparse
import datetime as dt
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
import hashlib
import html
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1] if '__file__' in globals() else Path.cwd()


def source_plan(texts):
    """Accept exactly the reviewed single-stanza layout; preserve signing keys."""
    expected = {
        'pve-enterprise.sources': ('https://enterprise.proxmox.com/debian/pve', 'pve-enterprise'),
        'pve-no-subscription.sources': ('http://download.proxmox.com/debian/pve', 'pve-no-subscription'),
        'ceph.sources': ('https://enterprise.proxmox.com/debian/ceph-squid', 'enterprise'),
    }
    changes = {}
    for name, (uri, component) in expected.items():
        text = texts[name]
        fields = {}
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if ':' not in line or line[0].isspace():
                raise ValueError('UNREVIEWED_SOURCE_LAYOUT')
            key, value = line.split(':', 1)
            if key in fields:
                raise ValueError('MULTIPLE_OR_DUPLICATE_SOURCE_FIELDS')
            fields[key] = value.strip()
        if set(fields) - {'Types', 'URIs', 'Suites', 'Components', 'Signed-By', 'Enabled'}:
            raise ValueError('UNREVIEWED_SOURCE_OPTIONS')
        if fields.get('Types') != 'deb' or fields.get('Suites') != 'trixie':
            raise ValueError('WRONG_SOURCE_RELEASE')
        if fields.get('Signed-By') != '/usr/share/keyrings/proxmox-archive-keyring.gpg':
            raise ValueError('UNREVIEWED_SIGNING_KEY')
        if name == 'ceph.sources' and fields.get('URIs') == 'http://download.proxmox.com/debian/ceph-squid':
            uri, component = fields['URIs'], 'no-subscription'
        if fields.get('URIs') != uri or fields.get('Components') != component:
            raise ValueError('WRONG_SOURCE_CHANNEL')
        if fields.get('Enabled', 'yes') not in ('yes', 'no'):
            raise ValueError('UNREVIEWED_ENABLED_VALUE')
        if name != 'pve-enterprise.sources' and fields.get('Enabled', 'yes') != 'yes':
            raise ValueError('PUBLIC_SOURCE_DISABLED')
        if name == 'pve-enterprise.sources':
            updated = re.sub(r'^Enabled:.*$', 'Enabled: no', text, flags=re.M)
            if 'Enabled' not in fields:
                updated = text.rstrip('\n') + '\nEnabled: no\n'
        elif name == 'ceph.sources':
            updated = text.replace('https://enterprise.proxmox.com/debian/ceph-squid',
                                   'http://download.proxmox.com/debian/ceph-squid')
            updated = re.sub(r'^Components:.*$', 'Components: no-subscription', updated, flags=re.M)
        else:
            updated = text
        if updated != text:
            changes[name] = updated
    return changes


def remote_run():
    import shutil
    import tempfile
    info = {'status': 'FAILED', 'source_changes': [], 'packages_installed': False,
            'rollback': 'NOT_NEEDED', 'apt_rc': None}
    originals, touched = {}, []
    source_dir = Path('/etc/apt/sources.list.d')
    try:
        if os.geteuid() != 0:
            raise ValueError('ROOT_REQUIRED')
        version = subprocess.run(['pveversion'], capture_output=True, text=True, timeout=20)
        if version.returncode or not version.stdout.startswith('pve-manager/9.'):
            raise ValueError('PVE9_REQUIRED')
        subscription = subprocess.run(['pvesubscription', 'get'], capture_output=True, text=True, timeout=30)
        if not re.search(r'^status:\s*notfound\s*$', subscription.stdout, re.M):
            raise ValueError('SUBSCRIPTION_STATE_CHANGED_OR_UNKNOWN')
        if not Path('/usr/share/keyrings/proxmox-archive-keyring.gpg').is_file():
            raise ValueError('SIGNING_KEY_MISSING')
        names = ('pve-enterprise.sources', 'pve-no-subscription.sources', 'ceph.sources')
        if any((source_dir / n).is_symlink() for n in names):
            raise ValueError('SOURCE_SYMLINK_REFUSED')
        originals = {n: (source_dir / n).read_text() for n in names}
        changes = source_plan(originals)
        if changes:
            backup = Path('/var/backups/bergen-platform') / ('update-sources-' + uuid.uuid4().hex)
            backup.mkdir(parents=True, mode=0o700)
            for name in changes:
                shutil.copy2(source_dir / name, backup / name)
            info['backup'] = str(backup)
            for name, content in changes.items():
                target = source_dir / name
                fd, temporary = tempfile.mkstemp(prefix='.bergen-', dir=source_dir)
                try:
                    with os.fdopen(fd, 'w') as stream:
                        stream.write(content)
                    shutil.copystat(target, temporary)
                    os.replace(temporary, target)
                    touched.append(name)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        info['source_changes'] = touched.copy()
        result = subprocess.run(['apt-get', '-o', 'APT::Update::Error-Mode=any', 'update'],
                                capture_output=True, text=True, timeout=240)
        info['apt_rc'] = result.returncode
        # Only this bounded command output is mailed, never inventory or credentials.
        output = result.stdout + '\n' + result.stderr
        output = re.sub(r'(https?://)[^\s/@]+(?::[^\s/@]*)?@', r'\1[REDACTED]@', output)
        info['apt_output'] = output[-16000:]
        if result.returncode:
            raise ValueError('APT_METADATA_REFRESH_FAILED')
        info['status'] = 'OK'
    except Exception as exc:
        info['error'] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        if touched:
            try:
                for name in touched:
                    shutil.copy2(Path(info['backup']) / name, source_dir / name)
                info['rollback'] = 'RESTORED_SOURCE_FILES'
            except Exception:
                info['rollback'] = 'FAILED_REQUIRES_MANUAL_REVIEW'
    print(json.dumps(info))
    return 0 if info['status'] == 'OK' else 1


def send(config, evidence, directory):
    mail = config['smtp']
    password = Path(mail['password_file'])
    if password.stat().st_mode & 0o077:
        raise ValueError('SMTP_PASSWORD_FILE_MUST_BE_0600')
    status = 'OK' if evidence['result']['status'] == 'OK' else 'FEHLER'
    detail = evidence['result']
    lines = ['Bergen Platform – Change-Bericht Paketquellen',
             'Host: venombox', 'Gesamtstatus: ' + status,
             'Lauf-ID: ' + evidence['run_id'], 'Git-Commit: ' + evidence['commit'],
             'Beginn (UTC): ' + evidence['started'], 'Ende (UTC): ' + evidence['finished'],
             'Ziel: PVE-Enterprise deaktivieren; Ceph Squid auf no-subscription umstellen.',
             'Dateiänderungen: ' + (', '.join(detail.get('source_changes', [])) or 'keine'),
             'Sicherung: ' + detail.get('backup', 'nicht erforderlich'),
             'APT-Metadatenprüfung RC: ' + str(detail.get('apt_rc')),
             'Rollback: ' + detail.get('rollback', 'NOT_NEEDED'),
             'Fehler: ' + detail.get('error', 'NONE'),
             'Keine Paketinstallation, Dienstneustarts, Reboots oder Crypto-Policy-Änderung.',
             'Der tägliche Sicherheitslauf deckt weiterhin nur Distributions-Sicherheitsquellen ab.',
             'PVE-/Ceph-Paketupdates sind durch diesen Change nicht installiert oder nachgewiesen.',
             '', detail.get('apt_output', '')]
    plain = '\n'.join(lines)
    (directory / 'report.txt').write_text(plain)
    message = EmailMessage()
    message['From'], message['To'] = mail['sender'], mail['recipient']
    message['Subject'] = '[Bergen Platform][Change][' + status + '] venombox – Paketquellen'
    message['Date'] = format_datetime(dt.datetime.now(dt.timezone.utc))
    message['Message-ID'] = make_msgid()
    message.set_content(plain)
    message.add_alternative('<html lang="de"><body><h1>Bergen Platform</h1><pre style="white-space:pre-wrap">'
                            + html.escape(plain) + '</pre></body></html>', subtype='html')
    message.add_attachment(json.dumps(evidence, indent=2).encode(), maintype='application',
                           subtype='json', filename='repository-change-report.json')
    with smtplib.SMTP(mail['host'], int(mail['port']), timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(mail['username'], password.read_text().rstrip('\r\n'))
        if smtp.send_message(message):
            raise RuntimeError('RECIPIENT_REFUSED')
    (directory / 'delivery.json').write_text(json.dumps({'status': 'SMTP_ACCEPTED'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    if args.remote:
        return remote_run()
    if not args.config:
        parser.error('--config is required')
    os.umask(0o077)
    if args.config.stat().st_mode & 0o077:
        raise ValueError('CONFIG_MUST_BE_PRIVATE_0600')
    config = json.loads(args.config.read_text())
    run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    directory = Path(config['state_dir']) / ('source-repair-' + run_id)
    directory.mkdir(parents=True, mode=0o700)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    if dirty.strip():
        raise ValueError('CLEAN_COMMITTED_CHECKOUT_REQUIRED')
    code = Path(__file__).read_text()
    evidence = {'run_id': run_id, 'commit': commit, 'started': dt.datetime.now(dt.timezone.utc).isoformat(),
                'script_sha256': hashlib.sha256(code.encode()).hexdigest()}
    capture = directory / 'remote-result.json'
    play = [{'name': 'Repair reviewed PVE 9 sources only', 'hosts': 'venombox',
             'gather_facts': False, 'become': True, 'tasks': [
                 {'name': 'Repair exact source layout and verify APT metadata',
                  'ansible.builtin.command': {'argv': ['/usr/bin/python3', '-c', code, '--remote']},
                  'register': 'source_repair', 'failed_when': False, 'no_log': True},
                 {'name': 'Keep evidence private on controller', 'ansible.builtin.copy': {
                     'content': '{{ source_repair | to_json }}', 'dest': str(capture), 'mode': '0600'},
                  'delegate_to': 'localhost', 'become': False, 'no_log': True}]}]
    play_path = directory / 'repair.yml'
    play_path.write_text(json.dumps(play))
    command = [config['ansible_playbook']]
    for inventory in config['inventories']:
        command += ['-i', inventory]
    if config.get('vault_password_file'):
        command += ['--vault-password-file', config['vault_password_file']]
    command += [str(play_path), '--limit', 'venombox']
    print('VENOMBOX_SOURCE_REPAIR_RUNNING', flush=True)
    try:
        with (directory / 'ansible.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                           env={**os.environ, 'ANSIBLE_HOST_KEY_CHECKING': 'True'}, timeout=360)
        remote = json.loads(capture.read_text())
        evidence['result'] = json.loads(remote['stdout'])
        if remote.get('rc') != 0 and evidence['result']['status'] == 'OK':
            raise ValueError('INCONSISTENT_REMOTE_RESULT')
    except Exception as exc:
        evidence['result'] = {'status': 'FAILED', 'error': type(exc).__name__,
                              'rollback': 'REMOTE_RESULT_UNKNOWN_CHECK_LOCAL_LOG'}
    evidence['finished'] = dt.datetime.now(dt.timezone.utc).isoformat()
    (directory / 'report.json').write_text(json.dumps(evidence, indent=2))
    try:
        send(config, evidence, directory)
        print('CHANGE_REPORT_SMTP_ACCEPTED ' + run_id + ' ' + evidence['result']['status'])
    except Exception as exc:
        print('CHANGE_REPORT_DELIVERY_FAILED ' + type(exc).__name__)
        print('LOCAL_REPORT=' + str(directory / 'report.json'))
        return 2
    return 0 if evidence['result']['status'] == 'OK' else 1


if __name__ == '__main__':
    sys.exit(main())
