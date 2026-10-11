"""Read-only guardrails for Certbot journal and deploy-hook audit."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-renewal-failure-readonly.yml"


def load():
    p = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(p, list) and len(p) == 2
    return p


def test_source_scope_is_dynamic_and_from_ignored_configuration():
    p = load()
    assert p[0]["hosts"] == "localhost"
    assert p[1]["hosts"] == "acme_renewal_diagnostic_sources"
    assert p[1]["become"] is True
    add = p[0]["tasks"][1]["ansible.builtin.add_host"]
    assert add["ansible_host"] == "{{ mail_tls_source_address }}"
    assert add["ansible_user"] == "{{ mail_tls_source_ssh_user }}"


def test_audit_is_read_only_and_outputs_only_classes():
    p = load()
    expected = {"ansible.builtin.command", "ansible.builtin.debug"}
    for task in p[1]["tasks"]:
        modules = {name for name in task if name.startswith("ansible.builtin.")}
        assert modules <= expected
        if "ansible.builtin.command" in task:
            assert task["changed_when"] is False
            argv = task["ansible.builtin.command"]["argv"]
            assert argv[:3] == ["python3", "-c", argv[2]]
    source = PLAYBOOK.read_text(encoding="utf-8")
    assert "journalctl" in source
    assert "journal_invalid_renewal_profile_matching_lines=" not in source
    assert "invalid_renewal_profile" in source
    assert "renewal_profiles_manual_no_auth_hook" in source
    assert "deploy_hook_" in source
    assert "renewal-hooks/deploy" in source
    for disallowed in (
        "certbot renew", "certbot certonly", "certbot reconfigure",
        "systemctl restart", "systemctl reload", "dns-api.pl",
        "selfhost_acme_reconcile_apply",
    ):
        assert disallowed not in source


def test_no_private_site_values_or_secrets_in_repo():
    source = PLAYBOOK.read_text(encoding="utf-8").lower()
    for disallowed in (
        "thebergens.net", "bergen-mail", "3364072", "3364073",
        "pri.asok.de", "sec.asok.de", "lxadmin", "192.168.",
    ):
        assert disallowed not in source
    assert "read_text" in source
    assert "print(body)" not in source
    assert "print(p.stdout)" not in source
