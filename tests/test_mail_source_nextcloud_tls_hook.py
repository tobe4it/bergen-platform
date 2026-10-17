"""Offline guardrails for the optional Nextcloud wildcard Nginx deploy hook."""
from pathlib import Path
import os
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-nextcloud-tls-hook.yml"


def plays():
    result = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert len(result) == 2
    return result


def test_read_only_default_and_narrow_scope():
    setup, remote = plays()
    assert setup["hosts"] == "localhost"
    assert remote["hosts"] == "selected_cloud_tls_sources"
    assert remote["become"] is True
    checks = setup["tasks"][0]["ansible.builtin.assert"]["that"]
    for value in ("mail_cloud_tls_hostname", "mail_cloud_tls_cert_lineage",
                  "mail_cloud_tls_vhost_path", "mail_cloud_tls_link_path",
                  "mail_cloud_tls_hook_path"):
        assert any(value in str(c) for c in checks)
    source = PLAYBOOK.read_text(encoding="utf-8")
    assert "mail_cloud_tls_hook_apply | default(false) | bool" in source
    assert "BEGIN PRIVATE KEY" not in source
    assert "selfhost-dns-tbergen" not in source
    assert "cloud.tbergen.de" not in source
    assert "mail_cloud_tls_hook_apply: true" not in source


def test_never_overwrite_existing_hook():
    tasks = {t["name"]: t for t in plays()[1]["tasks"]}
    check = tasks["Refuse any pre-existing hook other than the exact reviewed content"]
    assert "expected_hook" in str(check["ansible.builtin.assert"]["that"])
    install = tasks["Install new dedicated hook only when explicitly approved and absent"]
    assert "not (cloud_tls_paths.results[2].stat.exists | default(false))" in install["when"]
    block = {t["name"]: t for t in install["block"]}
    copy = block["Create only the new scoped deploy hook"]["ansible.builtin.copy"]
    assert copy["force"] is False
    assert copy["owner"] == "root"
    assert copy["group"] == "root"
    assert copy["mode"] == "0700"
    assert "systemctl reload nginx" not in str(install["block"])


def hook_fixture(tmp_path):
    source = plays()[1]["vars"]["expected_hook"]
    assert "{{ mail_cloud_tls_cert_lineage }}" in source
    systemctl = tmp_path / "systemctl"
    nginx = tmp_path / "nginx"
    systemctl.write_text(
        '#!/bin/sh\necho "systemctl:$*" >> "$CALL_LOG"\n'
        'exit "${RELOAD_RC:-0}"\n', encoding="utf-8"
    )
    nginx.write_text(
        '#!/bin/sh\necho "nginx:$*" >> "$CALL_LOG"\n'
        'exit "${NGINX_RC:-0}"\n', encoding="utf-8"
    )
    for path in (systemctl, nginx):
        path.chmod(0o700)
    hook = tmp_path / "deploy.sh"
    hook.write_text(
        source.replace("{{ mail_cloud_tls_cert_lineage }}", "generic-zone")
        .replace("/usr/sbin/nginx", str(nginx))
        .replace("/usr/bin/systemctl", str(systemctl)),
        encoding="utf-8",
    )
    hook.chmod(0o700)
    result = subprocess.run(["sh", "-n", str(hook)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return hook, tmp_path / "calls"


@pytest.mark.parametrize(
    "lineage,nginx_rc,reload_rc,expected_calls,expected_rc",
    [
        ("unrelated", 0, 0, [], 0),
        ("generic-zone", 0, 0, ["nginx:-t", "systemctl:reload nginx"], 0),
        ("generic-zone", 1, 0, ["nginx:-t"], 1),
        ("generic-zone", 0, 1, ["nginx:-t", "systemctl:reload nginx"], 1),
    ],
)
def test_scoped_hook_executes_only_on_target(
    tmp_path, lineage, nginx_rc, reload_rc, expected_calls, expected_rc
):
    hook, calls = hook_fixture(tmp_path)
    env = dict(os.environ,
               RENEWED_LINEAGE=f"/etc/letsencrypt/live/{lineage}",
               CALL_LOG=str(calls), NGINX_RC=str(nginx_rc),
               RELOAD_RC=str(reload_rc))
    proc = subprocess.run([str(hook)], env=env, capture_output=True, text=True,
                          timeout=10)
    assert proc.returncode == expected_rc, proc.stderr
    assert (calls.read_text().splitlines() if calls.exists() else []) == expected_calls
