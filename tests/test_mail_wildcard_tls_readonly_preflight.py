"""Structural guardrails for the wildcard TLS *read-only* preflight.

These tests do not connect to MX2 or bergen-mail. Runtime certificate and
SSH verification is performed only when the Ansible playbook is run.
"""
from pathlib import Path

import yaml


PLAYBOOK = (
    Path(__file__).resolve().parents[1]
    / "ansible/playbooks/mail-wildcard-tls-readonly-preflight.yml"
)

ALLOWED_MODULES = {
    "ansible.builtin.assert",
    "ansible.builtin.add_host",
    "ansible.builtin.stat",
    "ansible.builtin.command",
    "ansible.builtin.shell",
    "ansible.builtin.set_fact",
    "ansible.builtin.debug",
}


def plays():
    value = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(value, list) and len(value) == 4
    return value


def tasks():
    for play in plays():
        for task in play["tasks"]:
            yield play, task


def test_no_mutation_or_sensitive_copy_modules():
    for _, task in tasks():
        selected = set(task).intersection(ALLOWED_MODULES)
        assert len(selected) == 1, task.get("name")
        assert not any(key in task for key in (
            "ansible.builtin.copy",
            "ansible.builtin.fetch",
            "ansible.builtin.slurp",
            "ansible.builtin.template",
            "ansible.builtin.file",
            "ansible.builtin.service",
            "ansible.builtin.systemd",
            "ansible.builtin.raw",
            "ansible.builtin.script",
            "ansible.builtin.uri",
        )), task.get("name")
        if "ansible.builtin.command" in task:
            argv = task["ansible.builtin.command"]["argv"]
            assert argv[0] in ("openssl", "postconf", "doveconf")
        if "ansible.builtin.shell" in task:
            code = task["ansible.builtin.shell"]
            assert code.startswith("set -o pipefail\n")
            assert "openssl" in code
            assert not any(token in code for token in ("> /", ">>", "scp ", "cp "))
            assert task.get("no_log") is True


def test_exact_host_scopes_and_absence_of_live_service_changes():
    result = plays()
    assert [p["hosts"] for p in result] == [
        "localhost", "mail_tls_certificate_sources",
        "bergen-mail", "localhost",
    ]
    assert result[1]["become"] is True
    assert result[2]["become"] is True
    assert "ansible.builtin.service" not in PLAYBOOK.read_text()
    assert "ansible.builtin.copy" not in PLAYBOOK.read_text()


def test_source_uses_existing_certbot_wildcard_lineage():
    source = plays()[1]
    assert source["vars"]["mail_tls_source_cert_file"] == (
        "/etc/letsencrypt/live/thebergens.net-wildcard/fullchain.pem"
    )
    assert source["vars"]["mail_tls_source_key_file"] == (
        "/etc/letsencrypt/live/thebergens.net-wildcard/privkey.pem"
    )
    assert source["vars"]["mail_tls_required_san"] == "*.thebergens.net"
    assert plays()[0]["vars"]["mail_tls_source_address"] == "mx.thebergens.net"


def test_existing_backend_tls_paths_are_preserved():
    target = plays()[2]["vars"]
    assert target["mail_tls_expected_fqdn"] == "mail.thebergens.net"
    assert target["mail_tls_target_cert_file"] == (
        "/etc/ssl/certs/mail-backend-fullchain.pem"
    )
    assert target["mail_tls_target_key_file"] == (
        "/etc/ssl/private/mail-backend-key.pem"
    )


def test_private_key_never_collected_into_controller_facts():
    source = plays()[1]
    for task in source["tasks"]:
        if "key" in task["name"].lower():
            if "ansible.builtin.assert" not in task:
                assert task.get("no_log") is True or (
                    "ansible.builtin.stat" in task
                    and task.get("no_log") is True
                ), task["name"]
    final = plays()[-1]["tasks"][-1]["ansible.builtin.debug"]["msg"]
    assert final["private_key_transferred"] is False
    assert final["can_authorize_deployment"] is False
    assert final["service_reloaded"] is False
