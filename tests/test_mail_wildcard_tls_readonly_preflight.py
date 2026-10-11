"""Static guardrails: TLS preflight is read-only and receives only local site data."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-wildcard-tls-readonly-preflight.yml"
EXAMPLE = ROOT / "ansible/vars/mail-tls.local.yml.example"
IGNORE = ROOT / ".gitignore"

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
    data = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 4
    return data


def tasks():
    for play in plays():
        yield from play["tasks"]


def test_only_readonly_ansible_actions():
    for task in tasks():
        used = set(task).intersection(ALLOWED_MODULES)
        assert len(used) == 1, task.get("name")
        assert not any(module in task for module in (
            "ansible.builtin.copy", "ansible.builtin.fetch",
            "ansible.builtin.slurp", "ansible.builtin.service",
            "ansible.builtin.file", "ansible.builtin.template",
            "ansible.builtin.systemd", "ansible.builtin.uri",
        ))
        if "ansible.builtin.command" in task:
            assert task["ansible.builtin.command"]["argv"][0] in (
                "openssl", "postconf", "doveconf",
            )
        if "ansible.builtin.shell" in task:
            script = task["ansible.builtin.shell"]
            assert script.startswith("set -o pipefail\n")
            assert "openssl" in script
            assert task.get("no_log") is True


def test_dynamic_host_selection():
    p = plays()
    assert p[0]["hosts"] == "localhost"
    assert p[1]["hosts"] == "mail_tls_certificate_sources"
    assert p[2]["hosts"] == "{{ mail_tls_target_inventory_host }}"
    assert p[3]["hosts"] == "localhost"
    assert p[1]["become"] is True and p[2]["become"] is True


def test_source_and_target_identity_are_local_variables():
    p = plays()
    assert "vars" not in p[0]
    assert "vars" not in p[1]
    assert "vars" not in p[2]
    first_gate = p[0]["tasks"][0]["ansible.builtin.assert"]["that"]
    for var in (
        "mail_tls_source_address",
        "mail_tls_target_inventory_host",
        "mail_tls_source_cert_file",
        "mail_tls_source_key_file",
        "mail_tls_required_san",
        "mail_tls_expected_fqdn",
        "mail_tls_target_cert_file",
        "mail_tls_target_key_file",
    ):
        assert var + " is defined" in first_gate
    source = p[0]["tasks"][1]["ansible.builtin.add_host"]
    assert source["ansible_host"] == "{{ mail_tls_source_address }}"
    assert source["ansible_user"] == (
        "{{ mail_tls_source_ssh_user | default(omit) }}"
    )


def test_fail_closed_gate_before_target_queries():
    gate = plays()[2]["tasks"][0]
    assert gate["ansible.builtin.assert"]["that"] == [
        "hostvars['mail-tls-source'].source_mail_tls_public_evidence is defined"
    ]
    assert gate.get("changed_when") is False


def test_dovecot_24_queries_named_ssl_settings():
    t = plays()[2]["tasks"]
    queries = [task["ansible.builtin.command"]["argv"] for task in t
               if task["name"].startswith("Read effective Dovecot TLS")]
    assert queries == [
        ["doveconf", "-h", "ssl_server/cert_file"],
        ["doveconf", "-h", "ssl_server/key_file"],
    ]


def test_private_key_not_extracted_or_printed():
    for task in plays()[1]["tasks"]:
        if "private" in task["name"].lower():
            assert task.get("no_log") is True
    report = plays()[3]["tasks"][-1]["ansible.builtin.debug"]["msg"]
    assert report["private_key_transferred"] is False
    assert report["service_reloaded"] is False
    assert report["can_authorize_deployment"] is False


def test_ignored_local_file_and_placeholder_only_template():
    assert "ansible/vars/mail-tls.local.yml" in IGNORE.read_text()
    example = EXAMPLE.read_text()
    assert "CHANGE_ME" in example
    assert "example.invalid" in example
    assert "*.example.invalid" in example
    assert "mail_tls_target_inventory_host:" in example
