"""Offline contract tests: no NAS, network or host power operations."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "ansible/files/power-recovery/synology-venombox-wol-onboot.sh"
)


class SynologyWakeOnLanTest(unittest.TestCase):
    def _fixture(self, base: Path) -> tuple[Path, Path, Path]:
        """Redirect every external effect to a private temporary directory."""
        source = SOURCE.read_text(encoding="utf-8")
        fake_synonet = base / "fake-synonet"
        calls = base / "calls.txt"
        fake_synonet.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "' + str(calls) + '"\n',
            encoding="utf-8",
        )
        fake_synonet.chmod(0o700)
        target = base / "mac"
        target.write_text("aa:bb:cc:dd:ee:ff\n", encoding="ascii")
        carrier = base / "carrier"
        carrier.write_text("1\n", encoding="ascii")
        source = source.replace("/usr/syno/sbin/synonet", str(fake_synonet))
        source = source.replace("/volume1/bergen-recovery/venombox-wol.mac", str(target))
        source = source.replace("/sys/class/net/$WAKE_IF/carrier", str(carrier))
        # Offline stub: no real sleeps and no system ID dependency.
        source = source.replace("set -eu\n", "set -eu\nsleep() { :; }\n")
        source = source.replace("$(id -u)", "$(printf 0)")
        runner = base / "runner.sh"
        runner.write_text(source, encoding="utf-8")
        return runner, target, calls

    @staticmethod
    def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/sh", str(script), *args],
            check=False,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_syntax(self) -> None:
        result = subprocess.run(
            ["/bin/sh", "-n", str(SOURCE)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_flag_refuses_to_send(self) -> None:
        result = self._run(SOURCE)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)

    def test_check_sends_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            script, _, calls = self._fixture(Path(temp))
            result = self._run(script, "--check")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("packet_send=NONE", result.stdout)
            self.assertFalse(calls.exists())

    def test_rejects_invalid_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script, mac, calls = self._fixture(root)
            mac.write_text("bad-mac\n", encoding="ascii")
            self.assertNotEqual(self._run(script, "--check").returncode, 0)
            mac.write_text("aa:bb:cc:dd:ee:ff\nsecond\n", encoding="ascii")
            self.assertNotEqual(self._run(script, "--check").returncode, 0)
            mac.unlink()
            actual = root / "actual"
            actual.write_text("aa:bb:cc:dd:ee:ff\n", encoding="ascii")
            mac.symlink_to(actual)
            self.assertNotEqual(self._run(script, "--check").returncode, 0)
            self.assertFalse(calls.exists())

    def test_send_is_bounded_and_mock_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            script, _, calls = self._fixture(Path(temp))
            result = self._run(script, "--send")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(calls.read_text().splitlines()), 12)
            self.assertTrue(all(
                x == "--wake aa:bb:cc:dd:ee:ff eth0"
                for x in calls.read_text().splitlines()
            ))
            self.assertIn("host wake not independently verified", result.stdout)


if __name__ == "__main__":
    unittest.main()
