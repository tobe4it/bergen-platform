"""Read-only safeguards and fixture execution for Certbot focused source inventory."""
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-renewal-focused-readonly.yml"


def plays():
    p = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(p, list) and len(p) == 2
    return p


def diagnostic():
    return plays()[1]["tasks"][0]["ansible.builtin.command"]["argv"]


def test_source_is_dynamic_and_remote_command_cannot_write():
    p = plays()
    assert p[0]["hosts"] == "localhost"
    assert p[1]["hosts"] == "acme_focused_audit_sources"
    assert p[1]["become"] is True
    host = p[0]["tasks"][1]["ansible.builtin.add_host"]
    assert host["ansible_host"] == "{{ mail_tls_source_address }}"
    assert host["ansible_user"] == "{{ mail_tls_source_ssh_user }}"
    assert p[1]["tasks"][0]["no_log"] is True
    assert p[1]["tasks"][0]["changed_when"] is False
    assert diagnostic()[:2] == ["python3", "-c"]
    assert diagnostic()[3] == "{{ mail_tls_source_cert_file }}"
    assert "sys.argv[1]" in diagnostic()[2]
    assert set(
        k for task in p[1]["tasks"] for k in task
        if k.startswith("ansible.builtin.")
    ) <= {"ansible.builtin.command", "ansible.builtin.debug"}
    source = PLAYBOOK.read_text(encoding="utf-8")
    assert not any(term in source for term in (
        "certbot renew", "certbot reconfigure", "systemctl reload",
        "systemctl restart", "ansible.builtin.copy", "ansible.builtin.file",
    ))
    compile(diagnostic()[2], "<readonly-audit>", "exec")


def test_no_private_infrastructure_names_or_record_ids():
    source = PLAYBOOK.read_text(encoding="utf-8").lower()
    assert not any(term in source for term in (
        "thebergens.net", "bergen-mail", "3364072", "3364073",
        "pri.asok.de", "sec.asok.de", "lxadmin", "192.168.",
    ))
    assert "print(code)" not in source
    assert "print(body)" not in source
    assert "print(str(profile))" not in source


def test_anonymous_inventory_classifies_orphans_and_hook_controls(tmp_path):
    script = diagnostic()[2]
    replacement = (
        ("/etc/letsencrypt/renewal-hooks/deploy", tmp_path / "hooks"),
        ("/etc/letsencrypt/renewal", tmp_path / "renewal"),
        ("/etc/letsencrypt/live", tmp_path / "live"),
    )
    for old, path in replacement:
        assert f'Path("{old}")' in script
        script = script.replace(f'Path("{old}")', f"Path({str(path)!r})")

    renewal = tmp_path / "renewal"
    renewal.mkdir()
    (renewal / "alpha.conf").write_text(
        "version = 3.1.0\n"
        "cert = /etc/letsencrypt/live/alpha/cert.pem\n"
        "[renewalparams]\n"
        "authenticator = manual\n"
        "manual_auth_hook = /usr/local/libexec/hook auth\n"
        "manual_cleanup_hook = /usr/local/libexec/hook cleanup\n",
        encoding="utf-8",
    )
    (renewal / "beta.conf").write_text(
        "version = 2.6.0\n"
        "[renewalparams]\n"
        "authenticator = manual\n",
        encoding="utf-8",
    )
    live = tmp_path / "live" / "alpha"
    live.mkdir(parents=True)
    (live / "cert.pem").write_text("fake cert\n", encoding="utf-8")
    (live / "fullchain.pem").write_text("fake chain\n", encoding="utf-8")
    (live / "privkey.pem").write_text("fake key\n", encoding="utf-8")
    orphan = tmp_path / "live" / "beta"
    orphan.mkdir()
    (orphan / "cert.pem").symlink_to("missing.pem")

    hookdir = tmp_path / "hooks"
    hookdir.mkdir()
    hook = hookdir / "generic-hook"
    hook.write_text(
        "#!/bin/sh\n"
        "# NEVER SHOW THIS INTERNAL SECRET 1234\n"
        "if [ -n \"$RENEWED_LINEAGE\" ]; then\n"
        "  systemctl reload postfix\n"
        "fi\n",
        encoding="utf-8",
    )
    hook.chmod(0o750)

    test_cert = tmp_path / "live" / "alpha" / "fullchain.pem"
    result = subprocess.run(
        [sys.executable, "-c", script, str(test_cert)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    s = result.stdout
    assert "profile_01_target=true" in s
    assert "profile_01_cert_pem=regular_or_valid_symlink" in s
    assert "profile_01_manual_auth_hook=present" in s
    assert "profile_02_target=false" in s
    assert "profile_02_cert_pem=broken_symlink" in s
    assert "profile_02_manual_auth_hook=absent" in s
    assert "deploy_hook_01_executable=true" in s
    assert "deploy_hook_01_mentions_renewed_lineage=true" in s
    assert "deploy_hook_01_has_conditional_syntax=true" in s
    assert "deploy_hook_01_postfix_reload_or_restart_pattern=true" in s
    assert "INTERNAL SECRET" not in s
    assert "alpha" not in s
    assert "beta" not in s
    assert str(tmp_path) not in s
