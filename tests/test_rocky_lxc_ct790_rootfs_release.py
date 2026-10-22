#!/usr/bin/env python3
"""Synthetic release-file and CI mutation boundary tests for CT790 read-only gate."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/nextcloud/read_ct790_rootfs_release.py"
PLAYBOOK = ROOT / "ansible/playbooks/audit-rocky-9-8-ct790-rootfs-release-readonly.yml"
spec = importlib.util.spec_from_file_location("read_ct790_rootfs_release", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RockyReleaseReadOnlyTests(unittest.TestCase):
    def make_image(self, root):
        (root / "etc").mkdir()
        (root / "usr/lib").mkdir(parents=True)
        (root / "etc/rocky-release").write_text(
            "Rocky Linux release 9.8 (Blue Onyx)\n"
        )
        (root / "usr/lib/os-release").write_text(
            'NAME="Rocky Linux"\nID="rocky"\nVERSION_ID="9.8"\n'
        )
        (root / "etc/os-release").symlink_to("../usr/lib/os-release")

    def test_release_identity_and_fixed_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_image(root)
            result = mod.read_release_tree(str(root))
            self.assertEqual(
                result["result"],
                "ROCKY_9_8_CT790_ROOTFS_RELEASE_READ_ONLY_VERIFIED",
            )
            self.assertEqual(result["rootfs_files_read"], 2)
            self.assertEqual(result["os_version_id"], "9.8")
            self.assertFalse(result["runtime_tested"])
            self.assertFalse(result["pct_start_authorized"])

    def test_refuses_unexpected_release_and_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_image(root)
            (root / "usr/lib/os-release").write_text(
                'ID="rocky"\nVERSION_ID="9.7"\n'
            )
            with self.assertRaisesRegex(mod.ReadBlocked, "OS_RELEASE_VERSION_MISMATCH"):
                mod.read_release_tree(str(root))
            (root / "usr/lib/os-release").write_text(
                'ID="rocky"\nVERSION_ID="9.8"\n'
            )
            (root / "etc/os-release").unlink()
            (root / "etc/os-release").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(mod.ReadBlocked, "ETC_OS_RELEASE_SYMLINK_CHANGED"):
                mod.read_release_tree(str(root))

    def test_does_not_follow_symlinked_release_file_or_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_image(root)
            (root / "etc/rocky-release").unlink()
            (root / "etc/rocky-release").symlink_to("/etc/passwd")
            with self.assertRaises(OSError):
                mod.read_release_tree(str(root))
            (root / "etc/rocky-release").unlink()
            (root / "etc/rocky-release").write_text(
                "Rocky Linux release 9.8 (Blue Onyx)\n")
            (root / "usr/lib/os-release").unlink()
            (root / "usr/lib/os-release").symlink_to("/etc/passwd")
            with self.assertRaises(OSError):
                mod.read_release_tree(str(root))

    def test_no_atime_and_no_follow_flags(self):
        for required in (
            "os.O_NOATIME",
            "os.O_NOFOLLOW",
            "os.O_CLOEXEC",
            "os.O_NONBLOCK",
            "dir_fd=",
            "os.readlink(",
        ):
            self.assertIn(required, SCRIPT.read_text())
        for forbidden in ("os.makedirs(", "os.chown(", "os.chmod(", "os.rename(",
                          "os.unlink(", "os.replace(", "subprocess", "os.system("):
            self.assertNotIn(forbidden, SCRIPT.read_text())

    def test_playbook_only_observational_tasks_and_premount_gate(self):
        source = PLAYBOOK.read_text()
        plays = yaml.safe_load(source)
        self.assertEqual(len(plays), 2)
        self.assertEqual(plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-postcreate-readonly.yml"
        })
        play = plays[1]
        self.assertEqual(play["hosts"], "venombox")
        self.assertIs(play["become"], True)
        self.assertIs(play["gather_facts"], False)
        self.assertIs(play["any_errors_fatal"], True)
        allowed = {"ansible.builtin.command", "ansible.builtin.assert",
                   "ansible.builtin.debug"}
        allowed_calls = (
            ["zfs", "get"], ["findmnt", "-rn"], ["python3", "-c"],
            ["pct", "status"],
        )
        for task in play["tasks"]:
            modules = {key for key in task if key.startswith("ansible.builtin.")}
            self.assertEqual(len(modules), 1, task["name"])
            self.assertTrue(modules <= allowed, task["name"])
            cmd = task.get("ansible.builtin.command")
            if cmd:
                self.assertIs(task["changed_when"], False)
                argv = cmd["argv"]
                self.assertTrue(
                    any(argv[:len(prefix)] == prefix for prefix in allowed_calls),
                    task["name"],
                )
        self.assertIn("rocky_release_zfs_mounted.stdout | trim == 'yes'", source)
        self.assertIn("rocky_release_findmnt.stdout.split()[0] == rocky_post_dataset", source)
        self.assertIn("rocky_release_findmnt.stdout.split()[1] == 'zfs'", source)
        self.assertIn("rocky_release_findmnt.stdout.split()[2] == rocky_post_rootfs_path.stdout | trim", source)
        self.assertIn("pct_start_authorized: false", source)
        self.assertIn("pct_template_authorized: false", source)
        self.assertIn("new_mount_created: false", source)
        self.assertNotIn("pct, start", source)
        self.assertNotIn("zfs, mount", source)


if __name__ == "__main__":
    unittest.main()
