"""Static safety contracts for the additive Bergen-AI HTTPS proxy rollout."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "ansible/playbooks/preflight-bergen-ai-proxy.yml"
ACTIVATE = ROOT / "ansible/playbooks/activate-bergen-ai-proxy.yml"
TUNNEL = ROOT / "ansible/roles/nginx_reverse_proxy/templates/internal-ssh-backend-tunnel.service.j2"


class BergenAiProxyContracts(unittest.TestCase):
    def test_read_only_preflight_uses_existing_proxmox_guest(self):
        play = yaml.safe_load(PREFLIGHT.read_text())[0]
        self.assertEqual(play["hosts"], "proxmox_hosts")
        guard = play["tasks"][0]["ansible.builtin.assert"]["that"]
        self.assertIn("site_pve_inventory_host is defined", guard)
        self.assertIn("site_pve_inventory_host in groups.get('proxmox_hosts', [])", guard)
        self.assertEqual(play["tasks"][1]["ansible.builtin.meta"], "end_host")
        self.assertEqual(play["tasks"][1]["when"], "inventory_hostname != site_pve_inventory_host")
        self.assertIn("pct", str(play))
        for task in play["tasks"]:
            self.assertNotIn("ansible.builtin.template", task)
            self.assertNotIn("ansible.builtin.systemd_service", task)
        self.assertIn("changed_when", str(play))

    def test_backend_preflight_scopes_existing_proxmox_host(self):
        path = ROOT / "ansible/playbooks/preflight-bergen-ai-ssh-target.yml"
        play = yaml.safe_load(path.read_text())[0]
        self.assertEqual(play["hosts"], "proxmox_hosts")
        guard = play["tasks"][0]["ansible.builtin.assert"]["that"]
        self.assertIn("site_pve_inventory_host is defined", guard)
        self.assertIn("site_pve_inventory_host in groups.get('proxmox_hosts', [])", guard)
        self.assertEqual(play["tasks"][1]["ansible.builtin.meta"], "end_host")
        self.assertEqual(play["tasks"][1]["when"], "inventory_hostname != site_pve_inventory_host")
        self.assertIn("site_ai_backend_vmid is defined", guard)
        self.assertIn("site_ai_backend_hostname is defined", guard)

    def test_ai_lxc_hostname_comes_from_site_local_settings(self):
        path = ROOT / "ansible/group_vars/all/bergen-ai.yml"
        config = yaml.safe_load(path.read_text())
        self.assertEqual(
            config["lxc_hostname"],
            "{{ site_ai_backend_hostname | mandatory }}",
        )
        self.assertEqual(
            config["lxc_vmid"],
            "{{ site_ai_backend_vmid | mandatory }}",
        )

    def test_oidc_targets_unambiguous_logical_ai_group(self):
        path = ROOT / "ansible/playbooks/configure-open-webui-oidc.yml"
        play = yaml.safe_load(path.read_text())[0]
        self.assertEqual(play["hosts"], "ai_nodes")
        guard = next(
            task for task in play["tasks"]
            if task["name"] == "Refuse ambiguous AI inventory and missing site identity"
        )
        conditions = guard["ansible.builtin.assert"]["that"]
        self.assertIn("groups.get('ai_nodes', []) | length == 1", conditions)
        self.assertIn("site_ai_backend_hostname is defined", conditions)

    def test_activation_requires_approval_and_reuses_site_template(self):
        play = yaml.safe_load(ACTIVATE.read_text())[0]
        self.assertEqual(play["hosts"], "reverse_proxy_nodes")
        source = ACTIVATE.read_text()
        self.assertIn("ai_proxy_deployment_approved | default(false) | bool", source)
        self.assertIn("inventory_hostname == ai_proxy_expected_inventory_hostname", source)
        self.assertIn("internal-proxy-site.conf.j2", source)
        self.assertIn("ai_proxy_paperless_before.stat.checksum", source)
        self.assertIn("ai_proxy_dns.results[0].stdout == ai_proxy_dns.results[1].stdout", source)
        self.assertIn("Validate combined Nginx configuration", source)
        self.assertIn("Remove only newly staged AI vhost", source)
        self.assertNotIn("certbot certonly", source)

    def test_activation_has_no_duplicate_tasks_and_requires_non_root_user(self):
        play = yaml.safe_load(ACTIVATE.read_text())[0]
        names = [task["name"] for task in play["tasks"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("Verify the pre-provisioned dedicated AI tunnel identity", names)
        self.assertIn("ai_proxy_tunnel_user", ACTIVATE.read_text())
        unit = TUNNEL.read_text()
        self.assertIn("User={{ ai_proxy_tunnel_user }}", unit)
        self.assertIn("Group={{ ai_proxy_tunnel_user }}", unit)
        self.assertIn("ProtectHome=true", unit)
        self.assertIn("CapabilityBoundingSet=", unit)
        self.assertNotIn("User=root", unit)

    def test_ssh_config_validation_uses_runuser_without_sudo(self):
        play = yaml.safe_load(ACTIVATE.read_text())[0]
        task = next(
            task for task in play["tasks"]
            if task["name"] == "Verify reviewed SSH client configuration parses as the dedicated identity"
        )
        self.assertNotIn("become_user", task)
        argv = task["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:4], ["/usr/sbin/runuser", "-u", "{{ ai_proxy_tunnel_user }}", "--"])
        self.assertEqual(argv[4], "ssh")
        self.assertEqual(task["register"], "ai_proxy_ssh_effective")
        guard = next(
            task for task in play["tasks"]
            if task["name"] == "Require the resolved dedicated SSH identity and trust files"
        )
        conditions = guard["ansible.builtin.assert"]["that"]
        self.assertTrue(any("identityfile" in condition for condition in conditions))
        self.assertTrue(any("userknownhostsfile" in condition for condition in conditions))
        self.assertTrue(any("stricthostkeychecking true" in condition for condition in conditions))
        self.assertTrue(guard["no_log"])

    def test_ssh_tunnel_is_loopback_only_with_hostkey_enforcement(self):
        text = TUNNEL.read_text()
        self.assertIn("-L 127.0.0.1:{{ ai_proxy_local_port }}:127.0.0.1:{{ ai_proxy_remote_port }}", text)
        self.assertIn("StrictHostKeyChecking=yes", text)
        self.assertIn("ExitOnForwardFailure=yes", text)
        self.assertIn("BatchMode=yes", text)
        self.assertNotIn("StrictHostKeyChecking=no", text)
        self.assertNotIn("UserKnownHostsFile=/dev/null", text)


if __name__ == "__main__":
    unittest.main()
