"""Static, offline safety contracts for staged Paperless backend SSH tunnel."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "ansible/playbooks/prepare-paperless-backend-tunnel.yml"
READONLY = ROOT / "ansible/playbooks/preflight-paperless-backend-tunnel.yml"
UNIT = ROOT / "ansible/roles/paperless_ssh_tunnel/templates/bergen-paperless-tunnel.service.j2"


class BackendTunnelStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prep_raw = PREP.read_text(encoding="utf-8")
        cls.plays = yaml.safe_load(cls.prep_raw)
        cls.readonly = yaml.safe_load(READONLY.read_text(encoding="utf-8"))
        cls.unit = UNIT.read_text(encoding="utf-8")

    def test_two_staged_hosts_and_explicit_approval(self):
        self.assertEqual([p["hosts"] for p in self.plays],
                         ["reverse_proxy_nodes", "paperless_nodes",
                          "reverse_proxy_nodes"])
        self.assertIn("paperless_tunnel_prepare_approved | default(false) | bool",
                      self.prep_raw)
        self.assertIn("paperless_tunnel_activation_approved | default(false) | bool",
                      self.prep_raw)
        self.assertIn("paperless_tunnel_dhcp_reservations_confirmed | default(false) | bool",
                      self.prep_raw)
        self.assertIn("when: paperless_tunnel_activation_approved | default(false) | bool",
                      self.prep_raw)

    def test_direct_private_loopback_only(self):
        self.assertIn("127.0.0.1:18000:127.0.0.1:8000", self.unit)
        self.assertIn("-b {{ paperless_tunnel_proxy_ip }}", self.unit)
        self.assertIn("paperless-tunnel@{{ paperless_tunnel_backend_ip }}", self.unit)
        self.assertNotIn("0.0.0.0:18000", self.unit)
        self.assertNotIn("192.0.2.10", self.unit)
        self.assertNotIn("paperless-tunnel@192.168.", self.unit)

    def test_client_uses_pinned_host_key_and_nonroot_identity(self):
        for expected in (
            "User=paperless-tunnel-client",
            "StrictHostKeyChecking=yes",
            "BatchMode=yes",
            "IdentitiesOnly=yes",
            "PasswordAuthentication=no",
            "UserKnownHostsFile=/var/lib/bergen-paperless-tunnel/.ssh/known_hosts",
            "GlobalKnownHostsFile=/dev/null",
            "HostKeyAlgorithms=ssh-ed25519",
            "ExitOnForwardFailure=yes",
            "ForwardAgent=no",
            "ForwardX11=no",
            "ProtectSystem=strict",
            "NoNewPrivileges=true",
        ):
            self.assertIn(expected, self.unit)
        self.assertNotIn("StrictHostKeyChecking=no", self.unit)
        self.assertNotIn("User=root", self.unit)

    def test_server_match_uses_no_shell_no_general_forwarding(self):
        for expected in (
            "Match User paperless-tunnel",
            "AuthenticationMethods publickey",
            "PasswordAuthentication no",
            "KbdInteractiveAuthentication no",
            "AllowTcpForwarding local",
            "AllowStreamLocalForwarding no",
            "PermitOpen 127.0.0.1:8000",
            "PermitTTY no",
            "MaxSessions 0",
            "AllowAgentForwarding no",
            "X11Forwarding no",
            "PermitTunnel no",
            "PermitListen none",
        ):
            self.assertIn(expected, self.prep_raw)
        self.assertIn('restrict,port-forwarding,permitopen="127.0.0.1:8000"',
                      self.prep_raw)
        self.assertIn('from="{{ paperless_tunnel_proxy_ip }}"', self.prep_raw)
        self.assertIn("shell: /usr/sbin/nologin", self.prep_raw)
        self.assertIn("password_lock: true", self.prep_raw)

    def test_key_creation_uses_ansible_user_not_shell_login(self):
        raw = self.prep_raw
        self.assertIn("generate_ssh_key: true", raw)
        self.assertIn("ssh_key_type: ed25519", raw)
        self.assertIn("ssh_key_file: .ssh/id_ed25519", raw)
        self.assertIn("group: paperless-tunnel-client", raw)
        self.assertIn("group: paperless-tunnel", raw)
        self.assertNotIn("become_user: paperless-tunnel-client", raw)
        self.assertNotIn("ssh-keygen -q", raw)

    def test_authorized_keys_has_one_finite_line_and_trailing_newline(self):
        task = next(t for t in self.plays[1]["tasks"]
                    if t["name"] == "Install source-IP-bound, destination-restricted public key")
        content = task["ansible.builtin.copy"]["content"]
        self.assertEqual(content.count("\n"), 1)
        self.assertTrue(content.endswith("\n"))
        self.assertIn('from="{{ paperless_tunnel_proxy_ip }}"', content)
        self.assertIn('restrict,port-forwarding,permitopen="127.0.0.1:8000"', content)
        self.assertIn("paperless_tunnel_forward_public_key", content)

    def test_validate_and_rollback_prior_to_public_key_authorization(self):
        raw = self.prep_raw
        i_valid = raw.index("validate: /usr/sbin/sshd -t -f %s")
        i_policy = raw.index("Fail closed if dedicated account")
        i_admin = raw.index("Ensure root SSH access policy was not modified")
        i_rescue = raw.index("Restore original SSH configuration")
        i_reload = raw.index("Reload validated SSH policy")
        i_key = raw.index("Install source-IP-bound, destination-restricted public key")
        self.assertTrue(i_valid < i_policy < i_admin < i_rescue < i_reload < i_key)
        self.assertIn("backup: true", raw)
        self.assertIn("remote_src: true", raw)
        self.assertIn("paperless_tunnel_admin_policy_after.stdout ==", raw)

    def test_no_key_or_dns_or_firewall_value_is_hardcoded(self):
        for raw in (self.unit, self.prep_raw):
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", raw)
            self.assertNotIn("ssh-keyscan", raw)
            self.assertNotIn("iptables -A", raw)
            self.assertNotIn("ufw allow", raw)
            self.assertNotIn("postconf", raw)
            self.assertNotIn("systemctl stop ssh", raw)

    def test_readonly_preflight_does_not_mutate(self):
        raw = READONLY.read_text(encoding="utf-8")
        self.assertIn("PROXY_PREFLIGHT_PASS", raw)
        self.assertIn("BACKEND_PREFLIGHT_PASS", raw)
        for forbidden in (
            "ansible.builtin.user:", "ansible.builtin.copy:",
            "ansible.builtin.blockinfile:", "ansible.builtin.systemd:",
        ):
            self.assertNotIn(forbidden, raw)


if __name__ == "__main__":
    unittest.main()
