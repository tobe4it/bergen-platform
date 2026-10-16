"""Offline safety tests for controller-managed selfHOST orphan recovery."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS))
import selfhost_acme_hook as hook

spec = importlib.util.spec_from_file_location(
    "selfhost_acme_recover", SCRIPTS / "selfhost_acme_recover.py"
)
recover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recover)


def cfg():
    return {
        "api_key": "123.NOT_A_REAL_SECRET",
        "zone": "example.invalid",
        "record_ids": [1, 2],
        "nameservers": ["ns1.example.invalid", "ns2.example.invalid"],
    }


def reservations():
    return {
        "1": {"identifier": "example.invalid", "validation": "A" * 43,
              "status": "reserved"},
        "2": {"identifier": "*.example.invalid", "validation": "B" * 43,
              "status": "reserved"},
    }


def make_state(tmp_path, state):
    hook.save_state(tmp_path / "active.json", state)
    return tmp_path / "active.json"


def trusted_dns(_server, _name):
    return {"selfhost-api-idle-1", "selfhost-api-idle-2"}


def prepped(monkeypatch):
    monkeypatch.setattr(recover, "assert_no_running_certbot", lambda: None)
    monkeypatch.setattr(hook, "authoritative_txt", trusted_dns)
    monkeypatch.setattr(hook, "api_request", lambda *_args: pytest.fail("No API mutation allowed"))


def test_read_only_then_guarded_apply_and_retained_backup(monkeypatch, tmp_path, capsys):
    prepped(monkeypatch)
    original = reservations()
    state_path = make_state(tmp_path, original)
    recover.reconcile(cfg(), apply=False, state_dir=tmp_path)
    assert json.loads(state_path.read_text()) == original
    assert not list(tmp_path.glob("reconciled-*.json"))
    assert "READY:" in capsys.readouterr().out

    recover.reconcile(cfg(), apply=True, state_dir=tmp_path)
    assert json.loads(state_path.read_text()) == {}
    backups = list(tmp_path.glob("reconciled-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == original
    assert backups[0].stat().st_mode & 0o077 == 0
    assert "RECONCILED:" in capsys.readouterr().out

    recover.reconcile(cfg(), apply=True, state_dir=tmp_path)
    assert json.loads(state_path.read_text()) == {}
    assert len(list(tmp_path.glob("reconciled-*.json"))) == 1
    assert "ALREADY_CLEAN:" in capsys.readouterr().out


@pytest.mark.parametrize("slot", ["1", "2"])
def test_single_abandoned_reservation_can_be_reconciled(monkeypatch, tmp_path, capsys, slot):
    prepped(monkeypatch)
    original = {slot: reservations()[slot]}
    state_path = make_state(tmp_path, original)

    recover.reconcile(cfg(), apply=False, state_dir=tmp_path)
    assert "READY: 1 abandoned reservation(s)" in capsys.readouterr().out
    assert json.loads(state_path.read_text()) == original
    assert not list(tmp_path.glob("reconciled-*.json"))

    recover.reconcile(cfg(), apply=True, state_dir=tmp_path)
    assert "RECONCILED: 1 orphaned reservation(s)" in capsys.readouterr().out
    assert json.loads(state_path.read_text()) == {}
    backups = list(tmp_path.glob("reconciled-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == original
    assert backups[0].stat().st_mode & 0o077 == 0


def test_refuses_single_reservation_if_dns_token_still_visible(monkeypatch, tmp_path):
    prepped(monkeypatch)
    original = {"1": reservations()["1"]}
    state_path = make_state(tmp_path, original)
    monkeypatch.setattr(hook, "authoritative_txt",
                        lambda server, name: trusted_dns(server, name) | {"A" * 43})
    with pytest.raises(hook.HookError, match="Old validation token"):
        recover.reconcile(cfg(), apply=True, state_dir=tmp_path)
    assert json.loads(state_path.read_text()) == original
    assert not list(tmp_path.glob("reconciled-*.json"))


def test_fails_closed_when_one_dns_slot_not_idle(monkeypatch, tmp_path):
    prepped(monkeypatch)
    state_path = make_state(tmp_path, reservations())
    monkeypatch.setattr(hook, "authoritative_txt",
                        lambda server, name: {"selfhost-api-idle-1"})
    with pytest.raises(hook.HookError, match="Not all configured DNS slots"):
        recover.reconcile(cfg(), apply=True, state_dir=tmp_path)
    assert json.loads(state_path.read_text()) == reservations()
    assert not list(tmp_path.glob("reconciled-*.json"))


def test_refuses_any_challenge_still_visible_in_dns(monkeypatch, tmp_path):
    prepped(monkeypatch)
    make_state(tmp_path, reservations())
    monkeypatch.setattr(hook, "authoritative_txt",
                        lambda server, name: trusted_dns(server, name) | {"A" * 43})
    with pytest.raises(hook.HookError, match="Old validation token"):
        recover.reconcile(cfg(), apply=True, state_dir=tmp_path)


@pytest.mark.parametrize("unexpected", [
    {"1": {"identifier": "example.invalid", "validation": "A" * 43,
           "status": "presented"},
     "2": {"identifier": "*.example.invalid", "validation": "B" * 43,
           "status": "reserved"}},
    {"1": {"identifier": "example.invalid", "validation": "A" * 43,
           "status": "cleaning"}},
    {"3": {"identifier": "example.invalid", "validation": "A" * 43,
           "status": "reserved"}},
    {"1": {"identifier": "unexpected.invalid", "validation": "A" * 43,
           "status": "reserved"}},
    {"1": {"identifier": "example.invalid", "validation": "A" * 43,
           "status": "reserved"},
     "2": {"identifier": "*.example.invalid", "validation": "B" * 43,
           "status": "reserved"},
     "3": {"identifier": "example.invalid", "validation": "C" * 43,
           "status": "reserved"}},
])
def test_refuses_wrong_reservation_state(monkeypatch, tmp_path, unexpected):
    prepped(monkeypatch)
    state_path = make_state(tmp_path, unexpected)
    with pytest.raises(hook.HookError):
        recover.reconcile(cfg(), apply=True, state_dir=tmp_path)
    assert json.loads(state_path.read_text()) == unexpected


def test_refuses_active_certbot_process(monkeypatch, tmp_path):
    prepped(monkeypatch)
    state_path = make_state(tmp_path, reservations())
    def active():
        raise hook.HookError("A Certbot process is running")
    monkeypatch.setattr(recover, "assert_no_running_certbot", active)
    with pytest.raises(hook.HookError, match="Certbot process"):
        recover.reconcile(cfg(), apply=True, state_dir=tmp_path)
    assert json.loads(state_path.read_text()) == reservations()


def test_isolated_instance_cli_selects_only_its_private_paths(monkeypatch):
    called = {}
    cfg_instance = {
        **cfg(),
        "state_dir": "/var/lib/selfhost-acme/instances/secondary-zone",
    }
    monkeypatch.setattr(recover.os, "geteuid", lambda: 0)

    def load(path=hook.DEFAULT_CONFIG):
        called["config"] = path
        return cfg_instance

    def reconcile_stub(loaded, *, apply=False, state_dir):
        called["state_dir"] = state_dir
        called["apply"] = apply
        assert loaded is cfg_instance

    monkeypatch.setattr(hook, "load_config", load)
    monkeypatch.setattr(recover, "reconcile", reconcile_stub)
    recover.main(["--check", "--instance", "secondary-zone"])
    assert called == {
        "config": "/etc/letsencrypt/selfhost-acme.d/secondary-zone.json",
        "state_dir": "/var/lib/selfhost-acme/instances/secondary-zone",
        "apply": False,
    }


def test_legacy_cli_keeps_default_paths(monkeypatch):
    called = {}
    monkeypatch.setattr(recover.os, "geteuid", lambda: 0)
    monkeypatch.setattr(hook, "load_config", lambda path=hook.DEFAULT_CONFIG: cfg())
    monkeypatch.setattr(recover, "reconcile",
                        lambda loaded, *, apply, state_dir: called.update(
                            state_dir=state_dir, apply=apply))
    recover.main(["--check"])
    assert called == {"state_dir": hook.DEFAULT_STATE_DIR, "apply": False}


@pytest.mark.parametrize("instance", ["../legacy", "zone.other", "", "a/b", "UpperCase"])
def test_isolated_recovery_rejects_unsafe_instance_names(monkeypatch, instance):
    monkeypatch.setattr(recover.os, "geteuid", lambda: 0)
    monkeypatch.setattr(hook, "load_config",
                        lambda *args: pytest.fail("No config access for invalid slug"))
    with pytest.raises(hook.HookError, match="Invalid isolated ACME instance slug"):
        recover.main(["--check", "--instance", instance])


def test_isolated_recovery_rejects_mismatched_state_path(monkeypatch):
    monkeypatch.setattr(recover.os, "geteuid", lambda: 0)
    monkeypatch.setattr(hook, "load_config",
                        lambda *args: {**cfg(), "state_dir": "/var/lib/selfhost-acme"})
    monkeypatch.setattr(recover, "reconcile",
                        lambda *args, **kwargs: pytest.fail("No reconciliation with wrong state"))
    with pytest.raises(hook.HookError, match="does not match"):
        recover.main(["--apply", "--instance", "secondary-zone"])


def test_recovery_playbook_requires_explicit_instance_selector():
    import yaml
    path = ROOT / "ansible/playbooks/selfhost-acme-reconcile.yml"
    plays = yaml.safe_load(path.read_text())
    controller = repr(plays[0]["tasks"])
    remote = repr(plays[1]["tasks"])
    assert "selfhost_acme_reconcile_instance" in controller
    assert "selfhost_acme_instance" in controller
    assert "--instance" in remote
    assert "selfhost_acme_reconcile_instance is defined" in remote
    assert "selfhost_acme_reconcile_apply | default(false) | bool" in remote


def test_no_site_identifiers_or_api_credentials_in_recovery_source():
    code = (SCRIPTS / "selfhost_acme_recover.py").read_text()
    assert "11111111" not in code and "22222222" not in code
    assert "primary.example.invalid" not in code and "ns1.example.invalid" not in code
    assert "api_request(" not in code
