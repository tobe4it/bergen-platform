import importlib.util
from pathlib import Path
from email import policy
from email.parser import BytesParser
import unittest

SPEC = importlib.util.spec_from_file_location('audit_mail', Path(__file__).resolve().parents[1] / 'ansible/library/mq_audit_mail.py')
mail = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mail)


class MailTests(unittest.TestCase):
    def test_message_and_attachment(self):
        path = Path(__file__)
        payload = mail.build_message('audit@example.org', 'ansible@bp-controller', 'FAIL', 'Evaluation', [str(path)])
        message = BytesParser(policy=policy.default).parsebytes(payload)
        self.assertEqual(message['To'], 'audit@example.org')
        self.assertEqual(list(message.iter_attachments())[0].get_payload(decode=True), path.read_bytes())

    def test_mailbox_injection_and_multiple_recipients_rejected(self):
        for address in ['x@example.org\nBcc: other@example.org', 'x@example.org,y@example.org', 'User <x@example.org>', 'invalid']:
            with self.assertRaises(ValueError):
                mail.build_message(address, 'ansible@bp-controller', 'FAIL', 'Evaluation', [])

    def test_mail_precedes_final_assertion(self):
        playbook = (Path(__file__).resolve().parents[1] / 'ansible/playbooks/mq-audit.yml').read_text()
        self.assertLess(playbook.index('mq_audit_mail:'), playbook.index('Require all scoped cases'))


if __name__ == '__main__':
    unittest.main()
