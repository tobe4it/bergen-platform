"""Offline safety tests for the explicit Certbot production reconfigure playbook."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/selfhost-acme-production-reconfigure.yml"


def plays():
    result = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(result, list) and len(result) == 2
    return result


def remote_tasks():
    result = plays()
    assert result[0]["hosts"] == "localhost"
    assert result[1]["hosts"] == "selfhost_acme_reconfigure_sources"
    assert result[1]["become"] is True
    add = result[0]["tasks"][1]["ansible.builtin.add_host"]
    assert add["ansible_host"] == "{{ mail_tls_source_address }}"
    assert add["ansible_user"] == "{{ mail_tls_source_ssh_user }}"
    return {task["name"]: task for task in result[1]["tasks"]}


def test_no_scheduled_or_implicit_production_mutations():
    tasks = remote_tasks()
    assert not any("ansible.builtin.systemd" in t for t in tasks.values())
    assert not any("ansible.builtin.file" in t for t in tasks.values())
    assert all("certbot" not in str(t.get("ansible.builtin.shell", ""))
               for t in tasks.values())
    assert "selfhost_acme_reconfigure_apply | default(false) | bool" in str(
        tasks["Reconfigure ONLY the existing lineage using Certbot built-in staging test"]
    )
    assert all("--force-renewal" not in str(t) and "--expand" not in str(t)
               for t in tasks.values())


def test_certbot_reconfigure_is_scoped_to_existing_lineage_and_staging_based():
    task = remote_tasks()[
        "Reconfigure ONLY the existing lineage using Certbot built-in staging test"
    ]
    args = task["ansible.builtin.command"]["argv"]
    assert args[:2] == ["certbot", "reconfigure"]
    assert args[args.index("--cert-name") + 1] == "{{ acme_lineage }}"
    assert "--non-interactive" in args
    assert "--manual" in args
    assert "--manual-auth-hook" in args
    assert "--manual-cleanup-hook" in args
    assert "--preferred-challenges" in args
    assert args[args.index("--preferred-challenges") + 1] == "dns"
    assert "--run-deploy-hooks" not in args
    assert "--no-verify-ssl" not in args
    assert task["no_log"] is True
    assert task["async"] >= 600
    assert task["poll"] > 0


def test_guards_backup_and_production_immutability():
    tasks = remote_tasks()
    names = list(tasks)
    assert names.index("Back up existing renewal configuration to root-only state directory") < names.index(
        "Reconfigure ONLY the existing lineage using Certbot built-in staging test"
    )
    backup = tasks["Back up existing renewal configuration to root-only state directory"]
    assert backup["ansible.builtin.copy"]["remote_src"] is True
    assert backup["ansible.builtin.copy"]["mode"] == "0600"
    assert backup["no_log"] is True
    assert "selfhost_acme_reconfigure_apply | default(false) | bool" in backup["when"]
    assert "Check that Certbot is not currently running" in names
    assert "Verify no reserved challenges and both authoritative TXT slots idle" in names
    verify = tasks["Require unchanged live TLS files, correct saved hooks and clean DNS"]
    assertions = verify["ansible.builtin.assert"]["that"]
    assert any("acme_live_after.results[0].stat.checksum" in x for x in assertions)
    assert any("acme_live_after.results[1].stat.checksum" in x for x in assertions)
    assert any("persisted_hooks=VERIFIED" in x for x in assertions)
    assert any("both DNS slots idle" in x for x in assertions)


def test_existing_configuration_preserved_in_default_mode():
    tasks = remote_tasks()
    mutating = [tasks["Back up existing renewal configuration to root-only state directory"],
                tasks["Reconfigure ONLY the existing lineage using Certbot built-in staging test"]]
    for task in mutating:
        assert "selfhost_acme_reconfigure_apply | default(false) | bool" in task["when"]
    assert "renewal_config_status=READY" in str(tasks)
    assert "renewal_config_status=ALREADY_CONFIGURED" in str(tasks)
    assert "renewal_config_status=CONFLICTING_HOOKS" in str(tasks)


def test_no_user_site_values_or_secrets_in_tracked_playbook():
    content = PLAYBOOK.read_text(encoding="utf-8").lower()
    forbidden = ("thebergens.net", "bergen-mail", "3364072", "3364073",
                 "pri.asok.de", "sec.asok.de", "lxadmin", "api_key")
    assert not any(value in content for value in forbidden)
