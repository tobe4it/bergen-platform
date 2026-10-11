"""Offline read-only checks for anonymous Certbot lineage consumer audit."""
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-lineage-consumers-readonly.yml"


def plays():
    result = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(result, list) and len(result) == 2
    return result


def test_scoping_and_immutability():
    value = plays()
    assert value[0]["hosts"] == "localhost"
    assert value[1]["hosts"] == "acme_lineage_consumers_sources"
    assert value[1]["become"] is True
    host = value[0]["tasks"][1]["ansible.builtin.add_host"]
    assert host["ansible_host"] == "{{ mail_tls_source_address }}"
    assert host["ansible_user"] == "{{ mail_tls_source_ssh_user }}"
    task = value[1]["tasks"][0]
    assert task["changed_when"] is False
    assert task["no_log"] is True
    argv = task["ansible.builtin.command"]["argv"]
    assert argv[:2] == ["python3", "-c"]
    assert argv[-1] == "{{ mail_tls_source_cert_file }}"
    compile(argv[2], "<readonly-consumer-audit>", "exec")
    for task in value[1]["tasks"]:
        assert {field for field in task if field.startswith("ansible.builtin.")} <= {
            "ansible.builtin.command", "ansible.builtin.debug"
        }


def test_no_secrets_or_mutating_calls():
    code = PLAYBOOK.read_text(encoding="utf-8").lower()
    for value in ("thebergens.net", "bergen-mail", "3364072", "3364073",
                  "pri.asok.de", "sec.asok.de", "lxadmin", "192.168.",
                  "certbot renew", "certbot reconfigure", "systemctl restart",
                  "systemctl reload", "dns-api.pl"):
        assert value not in code
    assert "print(source)" not in code
    assert "print(tokens)" not in code


def test_detects_static_references_without_printing_sensitive_data(tmp_path):
    argv = plays()[1]["tasks"][0]["ansible.builtin.command"]["argv"]
    script = argv[2]
    for name in ("renewal", "live", "archive"):
        destination = tmp_path / name
        destination.mkdir()
        original = "Path('/etc/letsencrypt/" + name + "')"
        assert original in script
        script = script.replace(original, "Path(" + repr(str(destination)) + ")")
    for name in ("postfix", "dovecot", "nginx", "httpd", "haproxy", "rspamd"):
        destination = tmp_path / name
        destination.mkdir()
        original = "Path('/etc/" + name + "')"
        assert original in script
        script = script.replace(original, "Path(" + repr(str(destination)) + ")")
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    original = "Path('/etc/letsencrypt/renewal-hooks/deploy')"
    assert original in script
    script = script.replace(original, "Path(" + repr(str(hooks_dir)) + ")")

    profile = tmp_path / "renewal" / "alpha.conf"
    profile.write_text(
        "version = 3.1.0\n"
        "cert = /etc/letsencrypt/live/alpha/cert.pem\n"
        "[renewalparams]\nauthenticator = manual\n",
        encoding="utf-8",
    )
    (tmp_path / "postfix" / "main.cf").write_text(
        "smtpd_tls_cert_file = "
        + str(tmp_path / "live" / "alpha" / "cert.pem")
        + "\nsecret = never-print-this\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-c", script,
         str(tmp_path / "live" / "selected" / "fullchain.pem")],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "profile_01_suspect_reason=missing_live_files" in result.stdout
    assert "profile_01_postfix_direct_reference_files=1" in result.stdout
    assert "profile_01_target=false" in result.stdout
    assert "audit_scope=allowlisted_config_files_only" in result.stdout
    assert "never-print-this" not in result.stdout
    assert "alpha" not in result.stdout
