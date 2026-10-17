"""Subset of isolated LXC SSH transport safety tests used by Paperless."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"ansible/scripts/pct_ssh_proxy.py"
spec=importlib.util.spec_from_file_location("paperless_pct_ssh", SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class PaperlessPCTTransportTest(unittest.TestCase):
    def test_no_ssh_host_key_bypass_or_host_exec_shell_injection(self):
        cmd=mod.build_command("pve.example.invalid",126)
        self.assertIn("StrictHostKeyChecking=yes",cmd)
        self.assertIn("BatchMode=yes",cmd)
        self.assertIn("pct exec 126 -- /usr/bin/python3 -c ",cmd[-1])
        self.assertIn("127.0.0.1",cmd[-1])
        self.assertNotIn("socat",cmd[-1])
    def test_invalid_ids_and_hosts_rejected(self):
        for host in ("invalid host","foo;whoami","../../etc",""):
            with self.subTest(host=host), self.assertRaises(ValueError):
                mod.build_command(host,126)
        for vmid in (-1,0,99,9999999999):
            with self.subTest(vmid=vmid), self.assertRaises(ValueError):
                mod.build_command("pve.example.invalid",vmid)
    def test_not_write_to_guest_or_ignore_host_keys(self):
        x=SCRIPT.read_text()
        self.assertNotIn("StrictHostKeyChecking=no",x)
        self.assertNotIn("pct set ",x)
        self.assertNotIn("pct create ",x)
