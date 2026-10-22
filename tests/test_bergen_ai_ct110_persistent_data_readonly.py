"""Offline regression tests for CT110 persistent data source inventory."""
import ast
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ct110_persistent_data_scope_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-ct110-persistent-data-readonly.yml"
spec = importlib.util.spec_from_file_location("ai_ct110_data_scope", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CT110PersistentScopeTests(TestCase):
    def test_known_data_mount_is_exactly_bound_from_expected_source(self):
        exact = [{"Mounts": [{"Source": "/srv/ai/open-webui",
                               "Destination": "/app/backend/data", "Type": "bind"}]}]
        self.assertEqual(mod.podman_webui(exact), "EXACT_WEBUI_DATA_BIND")
        self.assertEqual(mod.podman_webui([{"Mounts": [
            exact[0]["Mounts"][0], {"Source": "/etc", "Destination": "/etc/data"}
        ]}]), "OTHER_PODMAN_MOUNTS_REVIEW")
        self.assertEqual(mod.podman_webui([{"Mounts": [{
            "Source": "/elsewhere", "Destination": "/app/backend/data", "Type": "bind"
        }]}]), "DATA_SOURCE_NOT_EXPECTED")
        self.assertEqual(mod.podman_webui([{"Mounts": []}]), "UNVERIFIED")
        self.assertEqual(mod.podman_webui(None), "UNVERIFIED")

    def test_ollama_service_models_path_must_match_explicit_config(self):
        self.assertEqual(mod.ollama_config(
            'OLLAMA_MODELS=/srv/ai/models OLLAMA_HOST=127.0.0.1:11434',
            'active\n'), "EXPECTED_MODELS_LOCATION")
        self.assertEqual(mod.ollama_config("OLLAMA_MODELS=/data", "active"),
                         "OTHER_MODELS_LOCATION")
        self.assertEqual(mod.ollama_config(
            "OLLAMA_MODELS=/srv/ai/models OLLAMA_MODELS=/srv/ai/models", "active"),
            "MODELS_LOCATION_UNVERIFIED")
        self.assertEqual(mod.ollama_config(None, "active"), "UNVERIFIED")
        self.assertEqual(mod.ollama_config(
            "OLLAMA_MODELS=/srv/ai/models", "inactive"), "UNVERIFIED")

    def test_rootfs_and_graph_detection_remain_fail_closed(self):
        with mock.patch.object(mod, "query", side_effect=["/srv/ai/models\n", "", "/\n"]):
            self.assertEqual(mod.rootfs_dir("/srv/ai/models"), "GUEST_ROOTFS")
        with mock.patch.object(mod, "query", side_effect=["/srv/ai/models\n", "", "/data\n"]):
            self.assertEqual(mod.rootfs_dir("/srv/ai/models"), "OTHER_GUEST_MOUNT")
        with mock.patch.object(mod, "query", return_value=None):
            self.assertEqual(mod.rootfs_dir("/srv/ai/models"), "UNVERIFIED")
        self.assertEqual(mod.podman_graph_root(
            {"store": {"graphRoot": "/var/lib/containers/storage"}}),
            "/var/lib/containers/storage")
        self.assertIsNone(mod.podman_graph_root({"store": {}}))

    def test_containers_and_volumes_are_bounded(self):
        self.assertEqual(mod.podman_container_list([{"Names": ["open-webui"]}]),
                         "ONLY_OPEN_WEBUI")
        self.assertEqual(mod.podman_container_list([{"Names": "other"}]),
                         "OTHER_OR_MISSING_CONTAINERS")
        self.assertEqual(mod.podman_container_list(None), "UNVERIFIED")
        self.assertEqual(mod.podman_volume_list([]), "NONE")
        self.assertEqual(mod.podman_volume_list([{"Name": "secret"}]),
                         "ADDITIONAL_VOLUMES_REVIEW")
        self.assertEqual(mod.podman_volume_list(None), "UNVERIFIED")

    def test_script_and_playbook_are_read_only_and_no_credentials_print(self):
        source = SCRIPT.read_text()
        ast.parse(source)
        self.assertIn('BACKUP_AUTHORIZED=False', source)
        self.assertIn('ALL_PERSISTENT_DATA_PROVEN=False', source)
        for forbidden in ("vzdump", "pct set", "pct start", "pct stop", "systemctl restart",
                          "podman run", "podman volume create", "pvesh set", "rm -rf"):
            self.assertNotIn(forbidden, source)
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        command = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(command), 1)
        self.assertTrue(command[0]["no_log"])
        self.assertFalse(command[0]["changed_when"])
        self.assertFalse(command[0]["failed_when"])
        self.assertIn("not data_scope.APPLY_AUTHORIZED", PLAY.read_text())
        self.assertIn("ALL_PERSISTENT_DATA_PROVEN=False", PLAY.read_text())
