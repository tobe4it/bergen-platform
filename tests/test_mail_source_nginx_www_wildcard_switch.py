"""Offline safeguards for the WWW-only Nginx certificate switch."""
from pathlib import Path
import re
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-nginx-www-wildcard-switch.yml"


def plays():
    data = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 2
    return data


def tasks():
    return {t["name"]: t for t in plays()[1]["tasks"]}


def test_explicit_approval_and_exact_single_vhost_scope():
    p = plays()
    assert p[0]["hosts"] == "localhost"
    assert p[1]["hosts"] == "nginx_www_wildcard_sources"
    assert p[1]["become"] is True
    host = p[0]["tasks"][1]["ansible.builtin.add_host"]
    assert host["ansible_host"] == "{{ mail_tls_source_address }}"
    assert host["ansible_user"] == "{{ mail_tls_source_ssh_user }}"
    assertions = p[0]["tasks"][0]["ansible.builtin.assert"]["that"]
    assert any("nginx_www_config_path is match" in x and "conf[.]d" in x for x in assertions)
    assert not any("sites-available" in x for x in assertions)
    assert any("nginx_www_legacy_lineage" in x for x in assertions)
    switch = tasks()["Safely replace only two certificate references with explicit authorization"]
    assert "nginx_www_apply | default(false) | bool" in switch["when"]
    assert "nginx_www_old_pair | bool" in switch["when"]


def test_verification_before_mutation_and_safe_rollback():
    t = tasks()
    names = list(t)
    guarded = names.index("Safely replace only two certificate references with explicit authorization")
    for guard in (
        "Require prospective replacement certificate valid for another 30 days",
        "Verify replacement certificate covers only the intended WWW hostname",
        "Confirm Nginx configuration is valid before considering any change",
        "Confirm target configuration is actually included in nginx -T",
        "Verify existing replacement certificate and key form one pair",
        "Require a unique exact old or already-migrated certificate pair",
        "Prevent overwriting an older root-only safety backup",
    ):
        assert names.index(guard) < guarded
    block = t["Safely replace only two certificate references with explicit authorization"]
    steps = [item["name"] for item in block["block"]]
    assert steps.index("Preserve original Nginx vhost under root-only state directory") < steps.index(
        "Replace only old certificate chain path")
    assert steps.index("Replace only old private key path") < steps.index(
        "Require valid Nginx configuration before activation")
    assert steps.index("Require valid Nginx configuration before activation") < steps.index(
        "Activate checked Nginx configuration by graceful reload")
    assert steps.index("Activate checked Nginx configuration by graceful reload") < steps.index(
        "Verify local WWW TLS now serves the exact expected leaf certificate")
    rescue = [item["name"] for item in block["rescue"]]
    assert "Restore original WWW configuration after failed validation" in rescue
    assert "Reload restored configuration" in rescue
    assert "Refuse to report success after rollback" in rescue


def test_inline_python_diagnostics_compile_and_do_not_leak_material():
    t = tasks()
    for name in (
        "Confirm target configuration is actually included in nginx -T",
        "Verify existing replacement certificate and key form one pair",
    ):
        task = t[name]
        argv = task["ansible.builtin.command"]["argv"]
        assert argv[:2] == ["python3", "-c"]
        compile(argv[2], "<inline-diagnostic>", "exec")
        assert task["changed_when"] is False
        assert task["no_log"] is True
    command = tasks()[
        "Safely replace only two certificate references with explicit authorization"
    ]["block"][-1]
    argv = command["ansible.builtin.command"]["argv"]
    compile(argv[2], "<inline-postcheck>", "exec")
    assert command["no_log"] is True
    assert "sha256" in argv[2]
    assert "127.0.0.1" in argv[2]
    assert "server_hostname=sys.argv[2]" in argv[2]


def test_no_private_identifiers_or_credential_disclosure():
    text = PLAYBOOK.read_text(encoding="utf-8").lower()
    for forbidden in (
        "thebergens.net", "tbergen.de", "bergen.family", "lxadmin",
        "3364072", "3364073", "pri.asok.de", "sec.asok.de",
        "192.168.", "api_key",
    ):
        assert forbidden not in text
    assert "cloud_virtual_host_modified: false" in text
    assert "legacy_certificate_removed: false" in text
    assert "certbot renew" not in text
    assert "certbot certonly" not in text



def test_no_accidental_duplicate_yaml_tail_or_truncated_config_guard():
    source = PLAYBOOK.read_text(encoding="utf-8")
    assert source.count(
        "- name: Preflight or expressly switch one nginx WWW vhost"
    ) == 1
    assert source.count(
        "- name: Register approved source and validate local scope"
    ) == 1
    assert source.count("    - name: Show status after guarded switch") == 1
    assert source.rstrip().endswith("legacy_certificate_removed: false")
    assertions = plays()[0]["tasks"][0]["ansible.builtin.assert"]["that"]
    assert (
        "nginx_www_config_path is match("
        "'^/etc/nginx/conf[.]d/[A-Za-z0-9._-]+[.]conf$')"
    ) in assertions
    assert len(plays()[0]["tasks"]) == 2
    assert len(plays()[1]["tasks"]) >= 12



def test_symlink_guard_accepts_only_the_approved_file(tmp_path):
    t = tasks()
    guard = t["Require a direct symlink to precisely the matching sites-available file"]
    argv = guard["ansible.builtin.command"]["argv"]
    assert argv[:2] == ["python3", "-c"]
    compile(argv[2], "<safe-symlink-guard>", "exec")
    assert guard["changed_when"] is False
    assert guard["no_log"] is True
    assert guard["when"] == "nginx_www_config_stat.stat.islnk | default(false)"
    conf_d = tmp_path / "conf.d"
    sites_available = tmp_path / "sites-available"
    conf_d.mkdir()
    sites_available.mkdir()
    target = sites_available / "www.conf"
    target.write_text("server { }\n", encoding="utf-8")
    link = conf_d / "www.conf"
    link.symlink_to(target)
    check = lambda candidate: subprocess.run(
        [sys.executable, "-c", argv[2], str(link), str(candidate)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert check(target).returncode == 0
    wrong = sites_available / "wrong.conf"
    wrong.write_text("server { }\n", encoding="utf-8")
    assert check(wrong).returncode != 0
    target.unlink()
    target.symlink_to(wrong)
    assert check(target).returncode != 0


def test_backup_and_all_mutations_target_checked_regular_file_not_symlink():
    t = tasks()
    resolve = t["Resolve only the approved sites-available counterpart for a symlink"]
    assert "nginx_www_edit_path" in resolve["ansible.builtin.set_fact"]
    assert "/etc/nginx/sites-available/" in str(resolve)
    validate = t["Require a regular approved edit target and no symlink at that path"]
    assertions = validate["ansible.builtin.assert"]["that"]
    assert any("nginx_www_edit_stat.stat.isreg" in x for x in assertions)
    assert any("not (nginx_www_edit_stat.stat.islnk" in x for x in assertions)
    assert t["Load exact WWW nginx configuration privately"]["ansible.builtin.slurp"]["src"] == (
        "{{ nginx_www_edit_path }}"
    )
    scope = t["Safely replace only two certificate references with explicit authorization"]
    block = scope["block"]
    backup = block[0]["ansible.builtin.copy"]
    assert backup["src"] == "{{ nginx_www_edit_path }}"
    assert backup["mode"] == "0600"
    for step in block[1:3]:
        assert step["ansible.builtin.replace"]["path"] == "{{ nginx_www_edit_path }}"
    rescue = scope["rescue"][0]["ansible.builtin.copy"]
    assert rescue["dest"] == "{{ nginx_www_edit_path }}"
    assert rescue["mode"] == "{{ nginx_www_edit_stat.stat.mode }}"
