"""Offline tests for the generic, fail-closed TLS sync entry point."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mail_tls_sync", ROOT / "scripts/mail_tls_sync.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def config():
    return {
        "mail_tls_source_address": "mx.example.invalid",
        "mail_tls_source_ssh_user": "operator",
        "mail_tls_target_inventory_host": "mail-test",
        "mail_tls_source_cert_file": "/etc/letsencrypt/live/PLACEHOLDER/fullchain.pem",
        "mail_tls_source_key_file": "/etc/letsencrypt/live/PLACEHOLDER/privkey.pem",
        "mail_tls_target_cert_file": "/etc/ssl/certs/PLACEHOLDER-fullchain.pem",
        "mail_tls_target_key_file": "/etc/ssl/private/PLACEHOLDER-key.pem",
        "mail_tls_required_san": "*.example.invalid",
        "mail_tls_expected_fqdn": "mail.example.invalid",
    }


def write_config(tmp_path, content, mode=0o600):
    path = tmp_path / "mail-tls.local.yml"
    path.write_text(yaml.safe_dump(content))
    path.chmod(mode)
    return path


def test_requires_restricted_local_config(tmp_path):
    path = write_config(tmp_path, config(), 0o644)
    with pytest.raises(sync.SyncError, match="mode 0600"):
        sync.load_config(path)
    path.chmod(0o600)
    assert sync.load_config(path)["mail_tls_source_address"] == "mx.example.invalid"


def test_missing_or_uncovered_hostname_rejected(tmp_path):
    cfg = config()
    cfg["mail_tls_expected_fqdn"] = "mail.other.invalid"
    with pytest.raises(sync.SyncError, match="wildcard"):
        sync.load_config(write_config(tmp_path, cfg))


def test_host_injection_rejected(tmp_path):
    cfg = config()
    cfg["mail_tls_source_address"] = "-oProxyCommand=evil"
    with pytest.raises(sync.SyncError, match="Unsafe SSH identity"):
        sync.load_config(write_config(tmp_path, cfg))


def test_unsupported_ports_rejected(tmp_path):
    cfg = config()
    cfg["mail_tls_check_ports"] = [993, 1234]
    with pytest.raises(sync.SyncError, match="mail_tls_check_ports"):
        sync.load_config(write_config(tmp_path, cfg))


def test_secure_ssh_options():
    args = sync.ssh_args("mail.example.invalid", "operator", "true")
    assert "StrictHostKeyChecking=yes" in args
    assert "BatchMode=yes" in args
    assert "ForwardAgent=no" in args
    assert args[-2] == "operator@mail.example.invalid"


def test_fingerprint_is_normalized_and_checked():
    assert sync.fingerprint("sha256 Fingerprint=" + ":".join(["AB"] * 32)) == "ab" * 32
    with pytest.raises(sync.SyncError):
        sync.fingerprint("not-a-valid-fingerprint")


def test_readonly_nochange_runs_tls_probe_and_does_not_transfer(tmp_path, monkeypatch, capsys):
    cfg = write_config(tmp_path, config())
    fp = "a" * 64
    expiry = datetime(2027, 2, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(sync, "source_evidence", lambda *args: (fp, expiry))
    monkeypatch.setattr(sync, "target_evidence", lambda *args: (fp, expiry))
    called = []
    monkeypatch.setattr(sync, "run_remote_script", lambda *args: called.append(args) or "ALL_TLS_PASS")
    monkeypatch.setattr(sync, "stage_transfer", lambda *args: pytest.fail("should not transfer"))
    monkeypatch.setattr("sys.argv", ["mail_tls_sync.py", "--config", str(cfg)])
    sync.main()
    assert called[0][3][0] == "CHECK_ONLY"
    assert "NO_CHANGE" in capsys.readouterr().out


def test_readonly_candidate_never_creates_stage(tmp_path, monkeypatch, capsys):
    cfg = write_config(tmp_path, config())
    expiry = datetime(2027, 2, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(sync, "source_evidence", lambda *args: ("a" * 64, expiry))
    monkeypatch.setattr(sync, "target_evidence", lambda *args: ("b" * 64, expiry))
    monkeypatch.setattr(sync, "ssh_run", lambda *args: pytest.fail("should not mutate"))
    monkeypatch.setattr("sys.argv", ["mail_tls_sync.py", "--config", str(cfg)])
    sync.main()
    assert "READ_ONLY" in capsys.readouterr().out


def test_downgrade_refused_before_transfer(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, config())
    earlier = datetime(2027, 1, 1, tzinfo=timezone.utc)
    later = datetime(2027, 2, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(sync, "source_evidence", lambda *args: ("a" * 64, earlier))
    monkeypatch.setattr(sync, "target_evidence", lambda *args: ("b" * 64, later))
    monkeypatch.setattr("sys.argv", ["mail_tls_sync.py", "--config", str(cfg), "--apply"])
    with pytest.raises(sync.SyncError, match="downgrade"):
        sync.main()


def test_remote_script_enforces_rollback_and_health_checks():
    script = (ROOT / "scripts/mail_tls_remote_activate.sh").read_text()
    for mandatory in (
        "flock -n", "ROLLBACK_FAILED", "install -o root -g root -m 0600",
        "openssl verify -purpose sslserver", "openssl s_client",
        "postfix check", "doveconf -n >/dev/null", "systemctl stop dovecot postfix",
        "systemctl start postfix dovecot", "trap rollback EXIT",
    ):
        assert mandatory in script
    assert "StrictHostKeyChecking=no" not in script


def test_source_key_never_copied_to_controller_disk():
    script = (ROOT / "scripts/mail_tls_sync.py").read_text()
    assert "stderr=subprocess.DEVNULL" in script
    assert "stdout=subprocess.PIPE" in script
    assert "upstream.stdout.close()" in script
    assert "ForwardAgent=no" in script


def test_ssh_probe_closes_stdin_and_has_timeout(monkeypatch):
    from types import SimpleNamespace

    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=b"OK\n", stderr=b"")

    monkeypatch.setattr(sync.subprocess, "run", fake_run)
    assert sync.ssh_run("mx.example.invalid", "operator", "hostname") == "OK"
    assert seen["input"] == b""
    assert seen["timeout"] == 30
    assert seen["capture_output"] is True


def test_ssh_probe_timeout_is_fail_closed(monkeypatch):
    import subprocess

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=30)

    monkeypatch.setattr(sync.subprocess, "run", timed_out)
    with pytest.raises(sync.SyncError, match="timed out"):
        sync.ssh_run("mx.example.invalid", "operator", "hostname")


def test_ssh_multiplexing_is_scoped_to_a_private_temporary_directory(monkeypatch):
    import os
    from types import SimpleNamespace

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sync.subprocess, "run", fake_run)
    peers = (("operator", "mx.example.invalid"), ("root", "mail.example.invalid"))
    with sync.reused_ssh_connections(peers):
        args = sync.ssh_args("mx.example.invalid", "operator", "true")
        assert "ControlMaster=auto" in args
        assert "ControlPersist=20" in args
        control = next(arg for arg in args if arg.startswith("ControlPath="))
        directory = Path(control.split("=", 1)[1]).parent
        assert directory.exists()
        assert os.stat(directory).st_mode & 0o077 == 0
    assert not directory.exists()
    assert sync.SSH_CONTROL_OPTIONS == []
    assert len(calls) == 2
    assert all("-O" in args and "exit" in args for args in calls)


def test_ssh_multiplexing_closes_sockets_on_exception(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        sync.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
    )
    with pytest.raises(RuntimeError):
        with sync.reused_ssh_connections((("operator", "mx.example.invalid"),)):
            raise RuntimeError("simulated preflight failure")
    assert sync.SSH_CONTROL_OPTIONS == []
