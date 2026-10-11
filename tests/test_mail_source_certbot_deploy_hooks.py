"""Offline tests for read-only-first Certbot deploy hook migration."""
from pathlib import Path
import os
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-certbot-deploy-hooks.yml"


def parsed():
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert len(plays) == 2
    return plays


def test_guards_and_backup_before_apply():
    plays = parsed()
    assert plays[0]["hosts"] == "localhost"
    assert plays[1]["hosts"] == "mx_deploy_hook_sources"
    assert plays[1]["become"] is True
    conditions = plays[0]["tasks"][0]["ansible.builtin.assert"]["that"]
    assert any("mail_tls_postfix_hook_path is match" in x for x in conditions)
    assert any("mail_tls_nginx_hook_path is match" in x for x in conditions)
    tasks = {x["name"]: x for x in plays[1]["tasks"]}
    change = tasks["Back up and install reviewed Certbot hooks on explicit approval"]
    assert "deploy_hook_apply | default(false) | bool" in change["when"]
    assert "hook_legacy_state | bool" in change["when"]
    assert any("hook_legacy_state" in x for x in
               tasks["Refuse unrecognized hook content or a partially migrated pair"][
                   "ansible.builtin.assert"]["that"])
    steps = [x["name"] for x in change["block"]]
    assert steps.index("Back up original Postfix hook under root-only directory") < steps.index(
        "Install scoped Postfix hook")
    assert steps.index("Back up original Nginx hook under root-only directory") < steps.index(
        "Install fail-closed Wildcard Nginx hook")
    for x in change["block"]:
        assert x["no_log"] is True
    for x in change["rescue"]:
        if x["name"].startswith("Restore original"):
            assert x["ansible.builtin.copy"]["remote_src"] is True
    source = PLAYBOOK.read_text(encoding="utf-8")
    assert "BEGIN PRIVATE KEY" not in source
    assert "api_key:" not in source
    assert "ansible_host: 192." not in source


def fixture_hooks(tmp_path):
    variables = parsed()[1]["vars"]
    assert variables["old_postfix_hook"] == (
        "#!/bin/sh\nsystemctl reload postfix 2>/dev/null || true\n")
    assert variables["old_nginx_hook"].startswith(
        '#!/bin/sh\nset -u\n[ "$' + '{RENEWED_LINEAGE:-}"')
    sysctl = tmp_path / "systemctl"
    sysctl.write_text(
        '#!/bin/sh\n'
        'echo "systemctl:$*" >> "$CALL_LOG"\n'
        'case "$*" in\n'
        '  "is-active --quiet postfix"|"is-active --quiet nginx") exit "$' + '{ACTIVE_RC:-0}";;\n'
        '  "reload postfix"|"reload nginx") exit "$' + '{RELOAD_RC:-0}";;\n'
        'esac\n', encoding="utf-8")
    nginx = tmp_path / "nginx"
    nginx.write_text(
        '#!/bin/sh\n'
        'echo "nginx:$*" >> "$CALL_LOG"\n'
        'exit "$' + '{NGINX_RC:-0}"\n', encoding="utf-8")
    sysctl.chmod(0o700)
    nginx.chmod(0o700)
    substitutions = {
        "{{ wildcard_lineage }}": "genericwild",
        "{{ mail_tls_postfix_rsa_lineage }}": "generic-rsa",
        "{{ mail_tls_postfix_ecdsa_lineage }}": "generic-ecdsa",
        "/usr/bin/systemctl": str(sysctl),
        "/usr/sbin/nginx": str(nginx),
    }
    scripts = []
    for name in ("new_postfix_hook", "new_nginx_hook"):
        body = variables[name]
        for original, replacement in substitutions.items():
            body = body.replace(original, replacement)
        assert "{{" not in body
        path = tmp_path / (name + ".sh")
        path.write_text(body, encoding="utf-8")
        path.chmod(0o700)
        result = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        scripts.append(path)
    return scripts, tmp_path / "calls"


@pytest.mark.parametrize(
    "hook,lineage,calls,active,nginx,rc,ok",
    [
        (0, "unrelated", [], 0, 0, 0, True),
        (0, "generic-rsa", ["systemctl:is-active --quiet postfix",
                            "systemctl:reload postfix"], 0, 0, 0, True),
        (0, "generic-ecdsa", ["systemctl:is-active --quiet postfix",
                              "systemctl:reload postfix"], 0, 0, 0, True),
        (0, "generic-rsa", ["systemctl:is-active --quiet postfix"], 1, 0, 0, False),
        (0, "generic-rsa", ["systemctl:is-active --quiet postfix",
                            "systemctl:reload postfix"], 0, 0, 1, False),
        (1, "unrelated", [], 0, 0, 0, True),
        (1, "genericwild", ["systemctl:is-active --quiet nginx",
                            "nginx:-t", "systemctl:reload nginx"], 0, 0, 0, True),
        (1, "genericwild", ["systemctl:is-active --quiet nginx"], 1, 0, 0, False),
        (1, "genericwild", ["systemctl:is-active --quiet nginx", "nginx:-t"], 0, 1, 0, False),
        (1, "genericwild", ["systemctl:is-active --quiet nginx",
                            "nginx:-t", "systemctl:reload nginx"], 0, 0, 1, False),
    ],
)
def test_offline_hook_behavior(tmp_path, hook, lineage, calls, active, nginx, rc, ok):
    scripts, logfile = fixture_hooks(tmp_path)
    env = dict(os.environ, RENEWED_LINEAGE="/etc/letsencrypt/live/" + lineage,
               CALL_LOG=str(logfile), ACTIVE_RC=str(active),
               NGINX_RC=str(nginx), RELOAD_RC=str(rc))
    result = subprocess.run([str(scripts[hook])], capture_output=True,
                            text=True, env=env, timeout=10)
    assert (result.returncode == 0) == ok, result.stderr
    observed = logfile.read_text().splitlines() if logfile.exists() else []
    assert observed == calls
