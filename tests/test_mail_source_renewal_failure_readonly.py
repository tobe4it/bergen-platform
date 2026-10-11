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



def test_renewal_hook_diagnostics_passes_required_lineage_argument():
    tasks = load()[1]["tasks"]
    task = next(
        t for t in tasks
        if t["name"] == (
            "Assess renewal profiles and two existing deploy hooks without "
            "printing their paths or contents"
        )
    )
    argv = task["ansible.builtin.command"]["argv"]
    assert len(argv) == 4
    assert argv[:2] == ["python3", "-c"]
    assert argv[3] == "{{ mail_tls_source_cert_file }}"
    assert "sys.argv[1]" in argv[2]
    compile(argv[2], "<safe-renewal-diagnostics>", "exec")


def test_embedded_diagnostic_executes_with_synthetic_local_fixtures(tmp_path):
    import subprocess
    import sys

    task = next(
        t for t in load()[1]["tasks"]
        if t["name"].startswith("Assess renewal profiles")
    )
    script = task["ansible.builtin.command"]["argv"][2]

    for old, new in (
        ("/etc/letsencrypt/renewal-hooks/deploy", tmp_path / "hooks"),
        ("/etc/letsencrypt/renewal", tmp_path / "renewal"),
        ("/etc/letsencrypt/live", tmp_path / "live"),
    ):
        script = script.replace(f'Path("{old}")', f"Path({str(new)!r})")

    renewal_dir = tmp_path / "renewal"
    renewal_dir.mkdir()
    (renewal_dir / "test-lineage.conf").write_text(
        "version = 3.1.0\n"
        "[renewalparams]\n"
        "authenticator = manual\n"
        "manual_auth_hook = /usr/local/bin/test-auth\n",
        encoding="utf-8",
    )
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "sample"
    hook.write_text(
        "#!/bin/sh\n# secret-marker-never-echo\n"
        "systemctl reload postfix\n",
        encoding="utf-8",
    )
    hook.chmod(0o700)
    live = tmp_path / "live" / "test-lineage"
    live.mkdir(parents=True)
    (live / "cert.pem").write_text("dummy\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", script, str(live / "fullchain.pem")],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "renewal_profiles_total=1" in result.stdout
    assert "renewal_profiles_invalid_format=0" in result.stdout
    assert "renewal_profiles_manual_no_auth_hook=0" in result.stdout
    assert "renewal_profiles_missing_live_cert=0" in result.stdout
    assert "global_deploy_files=1" in result.stdout
    assert "deploy_hook_1_executable=true" in result.stdout
    assert "deploy_hook_1_mentions_postfix=true" in result.stdout
    assert "target_renewal_profile_present=true" in result.stdout
    assert "secret-marker-never-echo" not in result.stdout + result.stderr
