"""Static review of the read-only certificate rotation planning playbook."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-tls-rotation-readonly-plan.yml"
ALLOWED = {
    "ansible.builtin.assert",
    "ansible.builtin.stat",
    "ansible.builtin.command",
    "ansible.builtin.shell",
    "ansible.builtin.set_fact",
    "ansible.builtin.debug",
}


def plays():
    data = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 4
    return data


def test_preflight_is_imported_first():
    assert plays()[0] == {
        "import_playbook": "mail-wildcard-tls-readonly-preflight.yml"
    }


def test_only_scoped_source_target_controller_hosts():
    p = plays()
    assert p[1]["hosts"] == "mail_tls_certificate_sources"
    assert p[2]["hosts"] == "{{ mail_tls_target_inventory_host }}"
    assert p[3]["hosts"] == "localhost"
    assert p[1]["become"] is True
    assert p[2]["become"] is True


def test_all_actions_are_read_only():
    for play in plays()[1:]:
        for task in play["tasks"]:
            modules = set(task).intersection(ALLOWED)
            assert len(modules) == 1, task["name"]
            assert set(task).difference(ALLOWED, {
                "name", "when", "register", "changed_when",
                "failed_when", "no_log", "args",
            }) == set(), task["name"]
            if "ansible.builtin.command" in task:
                assert task["ansible.builtin.command"]["argv"][0] == "openssl"
                assert task.get("changed_when") is False
            if "ansible.builtin.shell" in task:
                assert task["ansible.builtin.shell"].startswith(
                    "set -o pipefail\n"
                )
                assert task.get("changed_when") is False
                assert task.get("no_log") is True


def test_no_site_identifiers_in_versioned_playbook():
    content = PLAYBOOK.read_text(encoding="utf-8")
    for forbidden in ("thebergens", "bergen-mail", "lxadmin", "mx2"):
        assert forbidden not in content.lower()


def test_private_key_readbacks_stay_local_and_redacted():
    target_tasks = plays()[2]["tasks"]
    for task in target_tasks:
        if "private-key" in task["name"] or "private key" in task["name"]:
            assert task.get("no_log") is True


def test_report_cannot_authorize_changes():
    report = plays()[3]["tasks"][-1]["ansible.builtin.debug"]["msg"]
    assert report["private_key_transferred"] is False
    assert report["can_authorize_deployment"] is False
    assert report["service_reloaded"] is False
    assert report["changed"] is False
    for action in (
        "NO_CHANGE_REQUIRED", "CANDIDATE_FOR_ROTATION",
        "MANUAL_REMEDIATION_MISSING_TARGET_FILES",
        "MANUAL_REMEDIATION_INVALID_TARGET_PAIR",
    ):
        assert action in report["proposed_action"]


def test_uses_leaf_fingerprint_and_existing_key_pair_not_path_equality():
    tasks = plays()[2]["tasks"]
    task_names = [task["name"] for task in tasks]
    assert "Obtain installed certificate fingerprint if present" in task_names
    assert "Obtain installed private-key public digest without exporting key" in task_names
    assert "Compute sanitized read-only target assessment" in task_names
