"""Guardrails for source renewal timer and deploy-hook read-only audit."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-renewal-runtime-readonly.yml"


def audit_plays():
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(plays, list) and len(plays) == 2
    return plays


def test_only_configured_remote_source_is_audited():
    plays = audit_plays()
    assert plays[0]["hosts"] == "localhost"
    assert plays[1]["hosts"] == "acme_runtime_source_group"
    assert plays[1]["become"] is True
    host = plays[0]["tasks"][1]["ansible.builtin.add_host"]
    assert host["ansible_host"] == "{{ mail_tls_source_address }}"
    assert host["ansible_user"] == "{{ mail_tls_source_ssh_user }}"


def test_only_read_only_ansible_modules():
    tasks = audit_plays()[1]["tasks"]
    permitted = {"ansible.builtin.command", "ansible.builtin.find", "ansible.builtin.debug"}
    for task in tasks:
        ops = set(task).intersection(permitted)
        assert len(ops) == 1
        assert not set(task).intersection({
            "ansible.builtin.copy", "ansible.builtin.file", "ansible.builtin.shell",
            "ansible.builtin.systemd", "ansible.builtin.service",
        })
        if "ansible.builtin.command" in task:
            assert task.get("changed_when") is False


def test_renewal_and_certificate_consumers_observed_not_reloaded():
    content = PLAYBOOK.read_text(encoding="utf-8")
    for expected in (
        "certbot-renew.timer",
        "certbot-renew.service",
        "LastTriggerUSec",
        "NextElapseUSecRealtime",
        "ExecMainStatus",
        "renewal-hooks/deploy",
        "deploy_hook",
        "postconf",
        "doveconf",
    ):
        assert expected in content
    for forbidden in ("certbot renew", "certbot reconfigure",
                      "systemctl restart", "systemctl reload", "certbot certonly"):
        assert forbidden not in content


def test_no_site_identifiers_committed():
    content = PLAYBOOK.read_text(encoding="utf-8").lower()
    for forbidden in ("thebergens.net", "tbergen.de", "bergen-mail",
                      "3364072", "3364073", "pri.asok.de", "sec.asok.de",
                      "lxadmin", "192.168."):
        assert forbidden not in content
