"""Offline safety tests for scoped, read-only-first MTA-STS adoption."""
from pathlib import Path
import os
import subprocess
import re

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-mta-sts-vhost.yml"


def load():
    plays = yaml.safe_load(PLAYBOOK.read_text())
    assert len(plays) == 2
    return plays


def test_scoped_and_read_only_by_default():
    plays = load()
    assert plays[0]["hosts"] == "localhost"
    assert plays[1]["hosts"] == "selected_mta_sts_sources"
    assert plays[1]["become"] is True
    guards = plays[0]["tasks"][0]["ansible.builtin.assert"]["that"]
    assert any("mail_mta_sts_name is match" in x for x in guards)
    assert any("mail_mta_sts_conf_path ==" in x for x in guards)
    assert any("mail_mta_sts_hook_path is match" in x for x in guards)
    tasks = {x["name"]: x for x in plays[1]["tasks"]}
    assert "ansible.builtin.assert" in tasks[
        "Require exactly one existing HTTP and HTTPS server block for this name"]
    change = tasks["Reconcile only the missing listeners and the exact lineage hook"]
    assert change["when"] == "mail_mta_sts_apply | default(false) | bool"
    assert any("Back up vhost" in x["name"] for x in change["block"])
    assert any("Restore vhost" in x["name"] for x in change["rescue"])
    assert any(x["name"] == "Refuse overwriting a previous safety backup"
               for x in plays[1]["tasks"])
    source = PLAYBOOK.read_text()
    assert "BEGIN PRIVATE KEY" not in source
    assert re.search(r"\\b(?:[0-9]{1,3}\\.){3}[0-9]{1,3}\\b", source) is None
    assert re.search(r"\\b(?:[0-9a-fA-F]{1,4}:){2,}", source) is None


@pytest.mark.parametrize("lineage,expected,nginx_rc,expected_rc", [
    ("unrelated", [], 0, 0),
    ("mta-sts.example.test", ["nginx:-t", "systemctl:reload nginx"], 0, 0),
    ("mta-sts.example.test", ["nginx:-t"], 1, 1),
])
def test_deploy_hook_is_scoped_and_fails_closed(
        tmp_path, lineage, expected, nginx_rc, expected_rc):
    body = load()[1]["vars"]["expected_hook"].replace(
        "{{ mail_mta_sts_name }}", "mta-sts.example.test")
    for filename, script in {
        "nginx": '#!/bin/sh\necho nginx:$* >> "$CALL_LOG"\nexit "$NGINX_RC"\n',
        "systemctl": '#!/bin/sh\necho systemctl:$* >> "$CALL_LOG"\n',
    }.items():
        file = tmp_path / filename
        file.write_text(script)
        file.chmod(0o700)
    body = body.replace("/usr/sbin/nginx", str(tmp_path / "nginx")).replace(
        "/usr/bin/systemctl", str(tmp_path / "systemctl"))
    hook = tmp_path / "hook.sh"
    hook.write_text(body)
    hook.chmod(0o700)
    assert subprocess.run(["sh", "-n", str(hook)]).returncode == 0
    calls = tmp_path / "calls"
    env = dict(os.environ, RENEWED_LINEAGE="/etc/letsencrypt/live/" + lineage,
               CALL_LOG=str(calls), NGINX_RC=str(nginx_rc))
    result = subprocess.run([str(hook)], env=env, capture_output=True, text=True)
    assert result.returncode == expected_rc, result.stderr
    observed = calls.read_text().splitlines() if calls.exists() else []
    assert observed == expected
