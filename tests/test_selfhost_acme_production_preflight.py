"""Read-only guardrails for the controller-managed production Certbot preflight."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/selfhost-acme-production-preflight.yml"


def load_plays():
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(plays, list) and len(plays) == 2
    return plays


def test_only_approved_source_is_registered_dynamically():
    plays = load_plays()
    assert plays[0]["hosts"] == "localhost"
    assert plays[1]["hosts"] == "selfhost_acme_prod_preflight_sources"
    assert plays[1]["become"] is True
    add_host = plays[0]["tasks"][1]["ansible.builtin.add_host"]
    assert add_host["ansible_host"] == "{{ mail_tls_source_address }}"
    assert add_host["ansible_user"] == "{{ mail_tls_source_ssh_user }}"


def test_all_remote_actions_are_read_only():
    tasks = load_plays()[1]["tasks"]
    readonly_modules = {
        "ansible.builtin.stat",
        "ansible.builtin.assert",
        "ansible.builtin.command",
        "ansible.builtin.debug",
    }
    assert all(
        any(key in task for key in readonly_modules) and
        not any(key.startswith("ansible.builtin.") and key not in readonly_modules
                for key in task)
        for task in tasks
    )
    for task in tasks:
        if "ansible.builtin.command" in task:
            assert task.get("changed_when") is False
    text = PLAYBOOK.read_text()
    assert "selfhost_acme_recover.py" in text
    assert "--check" in text
    assert "--apply" not in text
    assert "certbot certonly" not in text
    assert "certbot renew" not in text


def test_state_reconciliation_must_be_complete():
    text = PLAYBOOK.read_text()
    assert "ALREADY_CLEAN: No local reservations; both DNS slots idle" in text
    assert "renewal_manual_auth_hook_present" in text
    assert "renewal_manual_cleanup_hook_present" in text
    assert "certbot_related_timers=" in text


def test_tracked_preflight_has_no_infrastructure_identifiers():
    text = PLAYBOOK.read_text().lower()
    for value in ("thebergens.net", "bergen-mail", "3364072", "3364073",
                  "pri.asok.de", "sec.asok.de", "lxadmin"):
        assert value not in text
