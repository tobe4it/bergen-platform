"""Offline safety checks for adopted Nextcloud+Collabora production configuration."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/mail-source-nextcloud-stack-audit.yml"
VARS = ROOT / "ansible/vars/mail-nextcloud-stack.local.yml.example"
TEMPLATES = ROOT / "ansible/templates/mail-nextcloud-stack"


def plays():
    parsed = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert len(parsed) == 2
    return parsed


def test_read_only_and_host_confinement():
    local, remote = plays()
    assert local["hosts"] == "localhost"
    assert remote["hosts"] == "selected_nextcloud_mail_hosts"
    assert remote["become"] is True
    assert remote["any_errors_fatal"] is True
    source = PLAYBOOK.read_text(encoding="utf-8")
    assert "target_identity.results[0].stdout == nextcloud_stack_host_fqdn" in source
    assert "target_identity.results[1].stdout == 'FUTURE'" in source
    assert "not ansible_check_mode" in source
    for forbidden in (
        "ansible.builtin.copy:", "ansible.builtin.template:",
        "ansible.builtin.dnf:", "ansible.builtin.yum:",
        "ansible.builtin.shell:", "ansible.builtin.systemd:",
        "ansible.builtin.cron:", "ansible.builtin.file:",
        "certbot delete", "systemctl restart",
    ):
        assert forbidden not in source
    assert "changed_when: false" in source


def test_audit_covers_migration_contracts():
    source = PLAYBOOK.read_text(encoding="utf-8")
    for required in (
        "php-fpm", "crond", "nginx", "php-libsmbclient",
        "imagick", "backgroundjobs_mode", "lastcron", "wopi_allowlist",
        "bergen-collabora.service", "bergen-collabora.network",
        "bergen-collabora.container", "getent", "ahostsv4",
        "status.php", "hosting/discovery", "100M", "RENEWED_LINEAGE",
        "nginx_effective", "collabora_cloud_https", "ADOPTED_READ_ONLY",
    ):
        assert required in source
    assert "lookup('template'" in source


def test_quadlet_baselines_pinned_and_loopback_only():
    files = {p.name: p.read_text(encoding="utf-8")
             for p in TEMPLATES.glob("*.j2")}
    assert set(files) == {
        "bergen-collabora.network.j2", "bergen-collabora.container.j2"
    }
    network = files["bergen-collabora.network.j2"]
    container = files["bergen-collabora.container.j2"]
    for entry in ("Driver=bridge", "Subnet={{ nextcloud_stack_collabora_subnet }}",
                  "Gateway={{ nextcloud_stack_collabora_gateway }}"):
        assert entry in network
    for entry in (
        "Image={{ nextcloud_stack_collabora_image }}", "Pull=never",
        "ContainerName=bergen-collabora", "Network=bergen-collabora.network",
        "AddHost={{ nextcloud_stack_cloud_name }}:{{ nextcloud_stack_collabora_gateway }}",
        "IP={{ nextcloud_stack_collabora_ip }}",
        "PublishPort=127.0.0.1:9980:9980",
        "Environment=aliasgroup1={{ nextcloud_stack_collabora_aliasgroup }}",
        "Environment=ssl.enable=false", "Environment=ssl.termination=true",
        "Restart=always", "RestartSec=10", "TimeoutStartSec=180"
    ):
        assert entry in container
    assert "0.0.0.0:9980" not in container
    assert ":latest" not in container


def test_only_placeholder_infrastructure_values_and_gitignore():
    example = yaml.safe_load(VARS.read_text(encoding="utf-8"))
    assert example["nextcloud_stack_host_fqdn"] == "mail.example.invalid"
    assert "REPLACE" in example["nextcloud_stack_collabora_image"]
    assert "ansible/vars/mail-nextcloud-stack.local.yml" in (
        ROOT / ".gitignore").read_text(encoding="utf-8")
    for path in [PLAYBOOK, VARS, *TEMPLATES.glob("*.j2")]:
        content = path.read_text(encoding="utf-8")
        for forbidden in (
            "BEGIN PRIVATE KEY", "mx.thebergens.net",
            "cloud.tbergen.de", "office.tbergen.de",
            "82.165.95.202", "192.168.5.3"
        ):
            assert forbidden not in content
