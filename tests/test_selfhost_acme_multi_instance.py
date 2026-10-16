"""Offline safety checks for optional, isolated selfHOST DNS-01 instances."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts/selfhost_acme_hook.py"
PLAYBOOK = ROOT / "ansible/playbooks/selfhost-acme-instance.yml"
DOC = ROOT / "docs/SELFHOST-ACME-MULTI-INSTANCE.md"
GITIGNORE = ROOT / ".gitignore"

spec = importlib.util.spec_from_file_location("selfhost_acme_multi_instance", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def config(zone="example.invalid", record_ids=(11, 12)):
    return {
        "api_key": "123.EXAMPLE_ONLY",
        "zone": zone,
        "record_ids": list(record_ids),
        "nameservers": ["ns1.example.invalid", "ns2.example.invalid"],
    }


def context(zone, validation="A" * 43, output=None):
    env = {"CERTBOT_IDENTIFIER": zone, "CERTBOT_VALIDATION": validation}
    if output is not None:
        env["CERTBOT_AUTH_OUTPUT"] = str(output)
    return env


def test_legacy_default_state_is_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(hook.os, "geteuid", lambda: 0)
    monkeypatch.setattr(hook.os, "umask", lambda mode: 0o022)
    monkeypatch.setattr(hook, "load_config", lambda path: config())
    monkeypatch.setattr(hook, "present", lambda cfg, env, state_dir: calls.append(state_dir))
    hook.main(["auth"], {"SELFHOST_ACME_CONFIG": "/private/config"})
    assert calls == ["/var/lib/selfhost-acme"]


def test_hook_dispatches_independent_state_directory(monkeypatch):
    calls = []
    cfg = config()
    cfg["state_dir"] = "/var/lib/selfhost-acme/instances/secondary-zone"
    monkeypatch.setattr(hook.os, "geteuid", lambda: 0)
    monkeypatch.setattr(hook.os, "umask", lambda mode: 0o022)
    monkeypatch.setattr(hook, "load_config", lambda path: cfg)
    monkeypatch.setattr(hook, "present", lambda cfg, env, state_dir: calls.append(("auth", state_dir)))
    monkeypatch.setattr(hook, "cleanup", lambda cfg, env, state_dir: calls.append(("cleanup", state_dir)))
    env = {"SELFHOST_ACME_CONFIG": "/private/config"}
    hook.main(["auth"], env)
    hook.main(["cleanup"], env)
    assert calls == [
        ("auth", cfg["state_dir"]),
        ("cleanup", cfg["state_dir"]),
    ]


@pytest.mark.parametrize("state_dir", [
    "../tmp/acme",
    "/tmp/acme",
    "/var/lib/selfhost-acme",
    "/var/lib/selfhost-acme/instances/../../legacy",
    "/var/lib/selfhost-acme/instances/zone/other",
    "/var/lib/selfhost-acme/instances/.hidden",
    "",
    123,
])
def test_rejects_unsafe_instance_state_locations(monkeypatch, tmp_path, state_dir):
    cfg = config()
    cfg["state_dir"] = state_dir
    private = tmp_path / "config.json"
    private.write_text(json.dumps(cfg))
    private.chmod(0o600)
    monkeypatch.setattr(hook, "_private_file", lambda path: private)
    with pytest.raises(hook.HookError, match="Unsafe per-instance state_dir"):
        hook.load_config(private)


def test_two_instances_do_not_share_slots_or_reservations(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        hook, "api_request",
        lambda cfg, action, record_id, validation: calls.append((cfg["zone"], action, record_id)),
    )
    monkeypatch.setattr(hook, "wait_for_dns", lambda *_args, **_kwargs: None)
    zone_a = config("zone-a.invalid", (11, 12))
    zone_b = config("zone-b.invalid", (11, 12))
    path_a = tmp_path / "a"
    path_b = tmp_path / "b"
    hook.present(zone_a, context("zone-a.invalid"), path_a)
    assert capsys.readouterr().out.strip() == "11"
    hook.present(zone_b, context("zone-b.invalid"), path_b)
    assert capsys.readouterr().out.strip() == "11"
    assert json.loads((path_a / "active.json").read_text())["11"]["identifier"] == "zone-a.invalid"
    assert json.loads((path_b / "active.json").read_text())["11"]["identifier"] == "zone-b.invalid"
    hook.cleanup(zone_a, context("zone-a.invalid", output=11), path_a)
    assert json.loads((path_a / "active.json").read_text()) == {}
    assert "11" in json.loads((path_b / "active.json").read_text())
    assert calls[:2] == [
        ("zone-a.invalid", "present", 11),
        ("zone-b.invalid", "present", 11),
    ]


def test_playbook_preserves_legacy_paths_and_limits_issuance():
    plays = yaml.safe_load(PLAYBOOK.read_text())
    assert len(plays) == 2
    assert plays[0]["hosts"] == "localhost"
    assert plays[1]["hosts"] == "selfhost_acme_instance_sources"
    assert plays[1]["become"] is True
    tasks = plays[1]["tasks"]
    # Paths and hook commands are deliberately defined as play-level vars.
    # Inspect the whole play, not just its task list.
    rendered = repr(plays[1])
    assert "selfhost-acme.d/" in rendered
    assert "/var/lib/selfhost-acme/instances/" in rendered
    assert "/var/lib/acme-staging/instances/" in rendered
    assert "SELFHOST_ACME_CONFIG=" in rendered
    assert "selfhost_acme_issue_production | default(false) | bool" in rendered
    assert "selfhost_acme_run_staging | default(false) | bool" in rendered
    assert "--force-renewal" not in rendered
    assert "--expand" not in rendered
    for task in tasks:
        if "selfhost_acme_api_key" in repr(task):
            assert task["no_log"] is True
        if task.get("name", "").startswith("Issue separate untrusted") or task.get("name", "").startswith("Explicitly issue"):
            assert task["no_log"] is True
    assert "/etc/letsencrypt/selfhost-acme.json" not in rendered


def test_local_credentials_and_instance_files_are_not_committed():
    ignored = GITIGNORE.read_text()
    assert "ansible/vars/selfhost-acme-*.local.yml" in ignored
    assert "ansible/vars/selfhost-acme-*.vault.yml" in ignored
    assert DOC.exists()
    assert (ROOT / "ansible/vars/selfhost-acme-instance.local.yml.example").exists()
    assert (ROOT / "ansible/vars/selfhost-acme-instance.vault.yml.example").exists()
