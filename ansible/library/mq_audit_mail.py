#!/usr/bin/python
"""Submit existing audit evidence to the controller's configured local MTA."""
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
import subprocess

from ansible.module_utils.basic import AnsibleModule


def build_message(recipient, sender, subject, body, attachments):
    for address in (recipient, sender):
        if '\r' in address or '\n' in address or parseaddr(address)[1] != address or '@' not in address:
            raise ValueError('Use one plain mailbox address without display names')
    message = EmailMessage()
    message['To'], message['From'], message['Subject'] = recipient, sender, subject
    message.set_content(body)
    for filename in attachments:
        path = Path(filename)
        message.add_attachment(path.read_bytes(), maintype='application',
                               subtype='octet-stream', filename=path.name)
    return message.as_bytes()


def main():
    module = AnsibleModule(argument_spec=dict(
        recipient=dict(type='str', required=True), sender=dict(type='str', required=True),
        subject=dict(type='str', required=True), body=dict(type='str', required=True),
        attachments=dict(type='list', elements='path', required=True),
        sendmail_path=dict(type='path', default='/usr/sbin/sendmail')),
        supports_check_mode=False)
    p = module.params
    try:
        payload = build_message(p['recipient'], p['sender'], p['subject'], p['body'], p['attachments'])
        result = subprocess.run([p['sendmail_path'], '-t', '-oi'], input=payload,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        if result.returncode:
            module.fail_json(msg='Local MTA rejected the audit email; report files remain available', changed=False)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        module.fail_json(msg='Audit email not confirmed; verify mailbox parameters and configured local sendmail/MTA. Do not retry blindly after a timeout.', changed=False)
    module.exit_json(changed=True, msg='Audit email accepted by local MTA; mailbox delivery is not independently verified')


if __name__ == '__main__':
    main()
