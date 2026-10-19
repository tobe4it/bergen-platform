"""Exercise actual Proxmox guest inventory shell fragment on mock sysfs tree.

The sysfs bonding_masters control file must not count as a netdevice.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1] / "ansible/playbooks"
FILES = (
    "inspect-nextcloud-restore-701-running-readonly.yml",
    "inspect-nextcloud-restore-701-offline-runtime.yml",
)


def shell_fragment(filename):
    playbook = yaml.safe_load((ROOT / filename).read_text())
    for task in playbook[0]["tasks"]:
        call = task.get("ansible.builtin.command", {})
        argv = call.get("argv", [])
        if argv[:2] == ["pct", "exec",] and len(argv) >= 7:
            script = argv[-1]
            start = script.index("test -L /sys/class/net/lo")
            stop = script.index("printf 'NON_LOOPBACK_DEVICES=%s\\n' ", start)
            line = script[stop:].split("\n", 1)[0]
            return script[start:stop] + line + "\n"
    raise AssertionError("No guest inventory shell body found")


class TestNetworkInterfaceCounting(unittest.TestCase):
    def test_sysfs_control_file_not_counted(self):
        for filename in FILES:
            with self.subTest(playbook=filename), tempfile.TemporaryDirectory() as tmp:
                fake = Path(tmp) / "net"
                fake.mkdir()
                kernel = Path(tmp) / "devices"
                kernel.mkdir()
                lo = kernel / "lo"
                lo.mkdir()
                (fake / "lo").symlink_to(lo, target_is_directory=True)
                (fake / "bonding_masters").write_text("\n")
                fragment = shell_fragment(filename).replace(
                    "/sys/class/net", str(fake)
                )
                output = subprocess.run(
                    ["/bin/sh", "-ec", fragment],
                    capture_output=True, check=True, text=True,
                )
                self.assertEqual(output.stdout.strip(), "NON_LOOPBACK_DEVICES=0")
                eth0 = kernel / "eth0"
                eth0.mkdir()
                (fake / "eth0").symlink_to(eth0, target_is_directory=True)
                output = subprocess.run(
                    ["/bin/sh", "-ec", fragment],
                    capture_output=True, check=True, text=True,
                )
                self.assertEqual(output.stdout.strip(), "NON_LOOPBACK_DEVICES=1")


if __name__ == "__main__":
    unittest.main()
