"""Actual Ansible transport/bundling tests against a TLS mock, not real IBM MQ."""
import base64
import datetime
import ipaddress
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from test_mq import FakeClient, mq

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = shutil.which("ansible-playbook") or str(Path.home() / ".local/bin/ansible-playbook")
PASSWORD = "offline-test-password-not-a-real-secret"
USERNAME = "offline-test-identity"


class HTTPSIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(ANSIBLE).is_file():
            raise unittest.SkipTest("ansible-core required for integration tests")
        cls.tmp = tempfile.TemporaryDirectory(prefix="bergen-mq-test-")
        cls.directory = Path(cls.tmp.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                .sign(key, hashes.SHA256()))
        cls.ca_path = cls.directory / "ca.pem"
        cls.ca_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path = cls.directory / "key.pem"
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        key_path.chmod(0o600)
        cls.client = FakeClient()
        cls.requests = []
        cls.mode = "normal"

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                body = json.loads(raw)
                cls.requests.append((self.path, dict(self.headers), body))
                expected = "Basic " + base64.b64encode((USERNAME + ":" + PASSWORD).encode()).decode()
                if cls.mode == "auth_failure" or self.headers.get("Authorization") != expected:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(PASSWORD.encode())  # must not reach Ansible output
                    return
                if cls.mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://localhost:1/credential-trap")
                    self.end_headers()
                    return
                if cls.mode == "bad_request":
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": [{"msgId": "MQWB9999E", "message": "Invalid parameter chltable " + PASSWORD,
                                                            "explanation": PASSWORD}], "headers": {"Authorization": expected}}).encode())
                    return
                if cls.mode == "invalid_json":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"not json")
                    return
                data = cls.client.command(body["command"], body["qualifier"], body["name"], body.get("parameters"), body.get("responseParameters"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cls.ca_path), str(key_path))
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.endpoint = "https://localhost:%s/ibmmq/rest/v3" % cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def setUp(self):
        type(self).client = FakeClient()
        type(self).requests = []
        type(self).mode = "normal"

    def run_playbook(self, check=False, ca=True):
        if os.environ.get("BERGEN_MQ_RUN_ANSIBLE_INTEGRATION") != "1":
            raise unittest.SkipTest("Opt-in Ansible runtime tests require permitted local RPC/IPC: BERGEN_MQ_RUN_ANSIBLE_INTEGRATION=1")
        variables = dict(mq_rest_endpoint=self.endpoint, mq_qmgr="QM1", mq_rest_username=USERNAME,
                         mq_rest_password=PASSWORD,
                         mq_objects=[dict(name="BERGEN.TEST", type="qlocal", attributes=dict(maxdepth=5000, defpsist="yes"))])
        if ca:
            variables["mq_rest_ca_path"] = str(self.ca_path)
        args = [ANSIBLE, "ansible/playbooks/mq-objects.yml", "-i", "localhost,", "-e", json.dumps(variables), "--diff"]
        if check:
            args.append("--check")
        env = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / "ansible.cfg"), ANSIBLE_NOCOLOR="1",
                   ANSIBLE_LOCAL_TEMP=str(self.directory / "ansible-tmp"))
        result = subprocess.run(args, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        self.assertNotIn(PASSWORD, result.stdout)
        self.assertNotIn(USERNAME, result.stdout)
        return result

    def test_ansible_check_apply_and_second_apply(self):
        result = self.run_playbook(check=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('"state": "absent"', result.stdout)
        self.assertTrue(all(req[2]["command"] == "display" for req in self.requests))
        self.assertFalse(self.client.objects)
        result = self.run_playbook()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Completed mutations: 1", result.stdout)
        result = self.run_playbook()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Drift/changes: False", result.stdout)
        self.assertEqual(sum(req[2]["command"] == "define" for req in self.requests), 1)
        for path, headers, body in self.requests:
            self.assertEqual(path, "/ibmmq/rest/v3/admin/action/qmgr/QM1/mqsc")
            self.assertIn("Ibm-Mq-Rest-Csrf-Token", headers)
            self.assertEqual(body["type"], "runCommandJSON")

    def test_untrusted_certificate_fails_without_request(self):
        result = self.run_playbook(ca=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MQ REST connection failed", result.stdout)
        self.assertFalse(self.requests)

    def test_auth_failure_body_is_not_logged(self):
        type(self).mode = "auth_failure"
        result = self.run_playbook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MQ REST HTTP 401", result.stdout)
        self.assertFalse(self.client.objects)

    def test_redirect_is_refused(self):
        type(self).mode = "redirect"
        result = self.run_playbook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REST redirects are refused", result.stdout)
        self.assertEqual(len(self.requests), 1)

    def test_invalid_json_fails_closed(self):
        type(self).mode = "invalid_json"
        result = self.run_playbook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MQ REST returned invalid JSON", result.stdout)
        self.assertFalse(self.client.objects)

    def rest_client(self, ca=True):
        return mq.RestClient(self.endpoint, "QM1", USERNAME, PASSWORD,
                             str(self.ca_path) if ca else None)

    def test_https_transport_check_apply_idempotence(self):
        client = self.rest_client()
        objects = [dict(name="BERGEN.TEST", type="qlocal", attributes=dict(maxdepth=5000, defpsist="yes"))]
        self.assertTrue(mq.reconcile(client, objects, check_mode=True)["changed"])
        self.assertFalse(self.client.objects)
        self.assertTrue(mq.reconcile(client, objects)["changed"])
        self.assertFalse(mq.reconcile(client, objects)["changed"])
        self.assertEqual(sum(req[2]["command"] == "define" for req in self.requests), 1)
        for path, headers, body in self.requests:
            self.assertEqual(path, "/ibmmq/rest/v3/admin/action/qmgr/QM1/mqsc")
            self.assertIn("Ibm-Mq-Rest-Csrf-Token", headers)
            self.assertEqual(body["type"], "runCommandJSON")

    def test_https_transport_untrusted_ca_rejected(self):
        with self.assertRaises(mq.MQError):
            self.rest_client(ca=False).command("display", "queue", "BERGEN.TEST")
        self.assertFalse(self.requests)

    def test_https_delete_channel_table_wire_values(self):
        # IBM DELETE CHANNEL CHLTABLE accepts CLNTTBL/QMGRTBL, not channel types.
        for channel_type, table in [('CLNTCONN', 'clnttbl'), ('RCVR', 'qmgrtbl')]:
            name = 'BERGEN.WIRE'
            type(self).client.objects[name] = dict(channel=name, chltype=channel_type)
            start = len(self.requests)
            mq.reconcile(self.rest_client(), [dict(name=name, type='channel', state='absent')],
                         allow_deletion=True)
            deletes = [body for _, _, body in self.requests[start:] if body['command'] == 'delete']
            self.assertEqual(len(deletes), 1)
            self.assertEqual(deletes[0]['parameters'], {'chltable': table})
            self.assertNotIn(name, type(self).client.objects)

    def test_https_transport_auth_error_body_redacted(self):
        type(self).mode = "auth_failure"
        with self.assertRaises(mq.MQError) as caught:
            self.rest_client().command("display", "queue", "BERGEN.TEST")
        self.assertIn("401", str(caught.exception))
        self.assertNotIn(PASSWORD, str(caught.exception))

    def test_https_400_keeps_error_id_and_redacts_credentials(self):
        type(self).mode = "bad_request"
        with self.assertRaises(mq.MQError) as caught:
            self.rest_client().command("display", "queue", "BERGEN.TEST")
        message = str(caught.exception)
        self.assertIn("MQWB9999E", message)
        self.assertNotIn(PASSWORD, message)
        self.assertNotIn("Authorization", message)
        self.assertEqual(len(self.requests), 1)  # no automatic retry

    def test_https_transport_no_redirect(self):
        type(self).mode = "redirect"
        with self.assertRaises(mq.MQError):
            self.rest_client().command("display", "queue", "BERGEN.TEST")
        self.assertEqual(len(self.requests), 1)

    def test_https_transport_invalid_json(self):
        type(self).mode = "invalid_json"
        with self.assertRaises(mq.MQError):
            self.rest_client().command("display", "queue", "BERGEN.TEST")


if __name__ == "__main__":
    unittest.main()
