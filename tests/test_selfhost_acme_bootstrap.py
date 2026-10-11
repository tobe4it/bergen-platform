"""Guardrails for the controller-managed selfHOST Certbot bootstrap."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/selfhost-acme-bootstrap.yml"
LOCAL_EXAMPLE = ROOT / "ansible/vars/selfhost-acme.local.yml.example"
GITIGNORE = ROOT / ".gitignore"


def plays():
    data = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 2
    return data


def test_both_plays_scoped_to_controller_and_ephemeral_source():
    p = plays()
    assert p[0]["hosts"] == "localhost"
    assert p[1]["hosts"] == "selfhost_acme_sources"
    assert p[1]["become"] is True
    registration = p[0]["tasks"][-1]["ansible.builtin.add_host"]
    assert registration["ansible_host"] == "{{ mail_tls_source_address }}"
    assert registration["ansible_user"] == "{{ mail_tls_source_ssh_user }}"


def test_site_data_and_vault_credential_are_required_and_not_logged():
    gate = plays()[0]["tasks"][0]
    assertions = gate["ansible.builtin.assert"]["that"]
    assert gate["no_log"] is True
    for name in (
        "selfhost_acme_zone", "selfhost_acme_contact_email",
        "selfhost_acme_api_key", "selfhost_acme_record_ids",
        "selfhost_acme_nameservers", "mail_tls_source_address",
    ):
        assert name + " is defined" in assertions
    tasks = plays()[1]["tasks"]
    secrets = [t for t in tasks if "selfhost_acme_api_key" in repr(t)]
    assert len(secrets) == 1
    assert secrets[0]["no_log"] is True
    assert secrets[0]["ansible.builtin.copy"]["mode"] == "0600"


def test_default_bootstrap_does_not_renew_or_change_production():
    tasks = plays()[1]["tasks"]
    certification = [t for t in tasks if "certbot" in repr(t.get("ansible.builtin.command", {}))]
    assert certification
    for t in certification:
        if "--staging" in repr(t):
            assert "selfhost_acme_run_staging | default(false) | bool" == t["when"]
            cmd = t["ansible.builtin.command"]["argv"]
            for required in (
                "--staging", "--non-interactive",
                "--config-dir", "/var/lib/acme-staging/config",
                "--work-dir", "--logs-dir", "--manual-auth-hook",
                "--manual-cleanup-hook",
            ):
                assert required in cmd
            assert "--force-renewal" not in cmd
            assert "--expand" not in cmd


def test_protected_state_and_authoritative_dns_idle_checks():
    tasks = plays()[1]["tasks"]
    names = [t["name"] for t in tasks]
    assert "Query idle ACME TXT slots at each authoritative nameserver" in names
    assert "Require both selfHOST TXT slots to be idle on all nameservers" in names
    assert "Check existing productive certificate lineage exists" in names


def test_no_site_identifiers_are_committed():
    play = PLAYBOOK.read_text(encoding="utf-8").lower()
    sample = LOCAL_EXAMPLE.read_text(encoding="utf-8")
    # Generic configuration must be supplied by variables, not fixed names.
    assert "{{ mail_tls_source_address }}" in play
    assert "{{ mail_tls_source_ssh_user }}" in play
    assert "{{ selfhost_acme_zone }}" in play
    assert "selfhost_acme_record_ids" in play
    assert "CHANGE_ME_" in sample
    assert "example.invalid" not in play
    assert "selfhost_acme_zone: CHANGE_ME_" in sample
    ignored = GITIGNORE.read_text(encoding="utf-8")
    assert "ansible/vars/selfhost-acme.local.yml" in ignored
    assert "ansible/vars/selfhost-acme.vault.yml" in ignored
