"""Exercise the real Ansible topology audit acceptance assertion offline.

Only synthetic evidence is used; no MQ hosts or credentials are involved.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "ansible/playbooks/mq-topology-audit.yml"
BASELINE = (
    "client:api-preflight",
    "a:tls-authenticated-connect",
    "b:tls-authenticated-connect",
)


@unittest.skipUnless(shutil.which("ansible-playbook") and yaml is not None,
                     "Ansible CLI and PyYAML required for offline gate tests")
class TopologyAcceptanceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plays = yaml.safe_load(AUDIT.read_text(encoding="utf-8"))
        matching = [task for play in plays for task in play["tasks"]
                    if task.get("name") ==
                    "Require sound evidence and explicit consent for partial audit acceptance"]
        if len(matching) != 1:
            raise AssertionError("Expected exactly one topology acceptance gate")
        cls.gate = matching[0]

    def check_gate(self, status, *, opt_in=False, failures=0, residuals=None,
                   missing_baseline=None, passed=3, accept=False):
        rows = [{"id": name, "status": "NOT_TESTED" if name == missing_baseline else "PASS"}
                for name in BASELINE]
        report = {
            "status": status,
            "failed": failures,
            "passed": passed,
            "residual_objects": residuals if residuals is not None else [],
            "tests": rows + [{"id": "qmgr-restart-persistence", "status": "NOT_TESTED"}],
        }
        with tempfile.TemporaryDirectory(prefix="mq-audit-gate-") as directory:
            playbook = Path(directory) / "gate.yml"
            playbook.write_text(
                yaml.safe_dump([{"hosts": "localhost", "gather_facts": False,
                                 "tasks": [self.gate]}], sort_keys=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook),
                 "--extra-vars", json.dumps({
                     "topology_run": {"report": report},
                     "mq_topology_accept_partial": opt_in,
                 })],
                cwd=ROOT, capture_output=True, text=True, timeout=45,
                check=False,
            )
        self.assertEqual(result.returncode == 0, accept,
                         f"Unexpected gate result for {status}, opt_in={opt_in}:\n"
                         f"{result.stdout}\n{result.stderr}")

    def test_pass_without_opt_in(self):
        self.check_gate("PASS", accept=True)

    def test_partial_requires_explicit_opt_in(self):
        self.check_gate("PARTIAL", accept=False)
        self.check_gate("PARTIAL", opt_in=True, accept=True)

    def test_fail_never_accepted(self):
        self.check_gate("FAIL", opt_in=True, failures=1, accept=False)

    def test_residual_objects_block_partial(self):
        self.check_gate("PARTIAL", opt_in=True, residuals=[{"name": "BGT.LEAK"}],
                        accept=False)

    def test_missing_tls_or_api_baseline_blocks_partial(self):
        for name in BASELINE:
            with self.subTest(name=name):
                self.check_gate("PARTIAL", opt_in=True, missing_baseline=name,
                                accept=False)

    def test_zero_passed_checks_block_partial(self):
        self.check_gate("PARTIAL", opt_in=True, passed=0, accept=False)


if __name__ == "__main__":
    unittest.main()
