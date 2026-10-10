"""Offline tests for the generic selfHOST ACME DNS-01 hook."""
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("selfhost_acme_hook", HERE / "scripts/selfhost_acme_hook.py")
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def cfg():
    return {
        "api_key": "123.EXAMPLE_ONLY",
        "zone": "example.invalid",
        "record_ids": [1, 2],
        "nameservers": ["ns1.example.invalid", "ns2.example.invalid"],
    }


def env(identifier="example.invalid", value="A" * 43, output=None):
    values = {"CERTBOT_IDENTIFIER": identifier, "CERTBOT_VALIDATION": value}
    if output is not None:
        values["CERTBOT_AUTH_OUTPUT"] = str(output)
    return values


def test_exact_selfhost_api_json_shape(monkeypatch):
    captures = {}

    class Response:
        status = 202

        def read(self, _n):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    class Opener:
        def open(self, request, timeout):
            captures["body"] = json.loads(request.data)
            captures["url"] = request.full_url
            return Response()

    monkeypatch.setattr(hook.urllib.request, "build_opener", lambda *_args: Opener())
    hook.api_request(cfg(), "present", 1, "A" * 43)
    assert captures["body"] == {
        "api_key": "123.EXAMPLE_ONLY",
        "action": "present",
        "record_id": 1,
        "content": "A" * 43,
    }
    assert captures["url"].startswith("https://")


def test_simultaneous_validation_uses_distinct_slots(monkeypatch, tmp_path, capsys):
    requests = []
    inspected = []
    monkeypatch.setattr(
        hook, "api_request",
        lambda config, action, slot, value: requests.append((action, slot, value)),
    )
    monkeypatch.setattr(
        hook, "wait_for_dns",
        lambda config, value, **kwargs: inspected.append(value),
    )

    hook.present(cfg(), env(), tmp_path)
    one = capsys.readouterr().out.strip()
    assert one == "1"
    hook.present(cfg(), env("*.example.invalid", "B" * 43), tmp_path)
    two = capsys.readouterr().out.strip()
    assert two == "2"

    state = json.loads((tmp_path / "active.json").read_text())
    assert len(state) == 2
    with pytest.raises(hook.HookError, match="Both TXT slots"):
        hook.present(cfg(), env("*.example.invalid", "C" * 43), tmp_path)
    hook.cleanup(cfg(), env("example.invalid", "A" * 43, one), tmp_path)
    assert json.loads((tmp_path / "active.json").read_text()) == {"2": state["2"]}
    hook.cleanup(cfg(), env("*.example.invalid", "B" * 43, two), tmp_path)
    assert json.loads((tmp_path / "active.json").read_text()) == {}
    assert [call[0] for call in requests] == [
        "present", "present", "cleanup", "cleanup"
    ]
    assert "selfhost-api-idle-1" in inspected


def test_wrong_cleanup_does_not_modify_other_slot(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(hook, "api_request", lambda *_args: None)
    monkeypatch.setattr(hook, "wait_for_dns", lambda *_args: None)
    hook.present(cfg(), env(), tmp_path)
    assert capsys.readouterr().out.strip() == "1"
    with pytest.raises(hook.HookError, match="does not match"):
        hook.cleanup(cfg(), env("example.invalid", "C" * 43, "1"), tmp_path)


def test_ambiguous_present_does_not_free_slot(monkeypatch, tmp_path):
    def fail(*_args):
        raise hook.HookError("network result uncertain")

    monkeypatch.setattr(hook, "api_request", fail)
    with pytest.raises(hook.HookError):
        hook.present(cfg(), env(), tmp_path)
    state = json.loads((tmp_path / "active.json").read_text())
    assert state["1"]["status"] == "reserved"


def test_reject_wrong_domain_or_invalid_token():
    with pytest.raises(hook.HookError):
        hook.certbot_context(cfg(), env("evil.example", "A" * 43))
    with pytest.raises(hook.HookError):
        hook.certbot_context(cfg(), env("example.invalid", "foobar"))


def test_placeholder_only_source():
    code = (HERE / "scripts/selfhost_acme_hook.py").read_text()
    assert "example.invalid" not in code
    assert 'DEFAULT_CONFIG = "/etc/letsencrypt/selfhost-acme.json"' in code
    assert '"record_ids"' in code
    assert '"zone"' in code


def test_state_directory_requires_private_permissions(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o755)
    with pytest.raises(hook.HookError, match="mode 0700"):
        with hook.exclusive_state(state):
            pass


def test_hook_main_requires_root(monkeypatch):
    monkeypatch.setattr(hook.os, "geteuid", lambda: 1000)
    with pytest.raises(hook.HookError, match="must be executed as root"):
        hook.main(["auth"], env())
