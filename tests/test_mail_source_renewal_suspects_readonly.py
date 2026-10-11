"""Offline regression tests for Certbot renewal suspect diagnosis."""
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-renewal-suspects-readonly.yml"


def load():
    value = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert len(value) == 2
    return value


def test_source_scope_and_pure_read_only():
    value = load()
    assert value[0]["hosts"] == "localhost"
    assert value[1]["hosts"] == "acme_suspects_sources"
    assert value[1]["become"] is True
    task = value[1]["tasks"][0]
    assert task["changed_when"] is False
    assert task["no_log"] is True
    args = task["ansible.builtin.command"]["argv"]
    assert args[:2] == ["python3", "-c"]
    assert args[-1] == "{{ mail_tls_source_cert_file }}"
    compile(args[2], "<readonly>", "exec")
    for t in value[1]["tasks"]:
        assert set(k for k in t if k.startswith("ansible.builtin.")) <= {
            "ansible.builtin.command", "ansible.builtin.debug"
        }


def test_script_is_exercised_with_a_missing_profile(tmp_path):
    args = load()[1]["tasks"][0]["ansible.builtin.command"]["argv"]
    source = args[2]
    for key in ("renewal", "live", "archive"):
        path = tmp_path / key
        path.mkdir()
        original = "Path('/etc/letsencrypt/" + key + "')"
        assert original in source
        source = source.replace(original, "Path(" + repr(str(path)) + ")")
    profile = tmp_path / "renewal" / "missing.conf"
    profile.write_text("version = 3.1.0\n[renewalparams]\nauthenticator = manual\n")
    result = subprocess.run(
        [sys.executable, "-c", source,
         str(tmp_path / "live" / "selected" / "fullchain.pem")],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "suspect_profile_01_live_cert=missing" in result.stdout
    assert "suspect_profile_01_manual_without_auth_hook=true" in result.stdout
    assert "suspect_profile_count=1" in result.stdout
    assert "selected_lineage_profile_count=0" in result.stdout
    assert "missing.conf" not in result.stdout
