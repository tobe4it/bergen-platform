"""Synthetic CLI regression tests for a read-only, evidence-bound syslog Advisor."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/roles/syslog/files/bergen_syslog_analyzer.py"
MAC = "aa:bb:cc:dd:ee:ff"


class SyslogOperationsAdvisor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbpath = Path(self.tmp.name) / "analyzer.db"
        self.env = dict(os.environ,
                        BERGEN_ANALYZER_DB=str(self.dbpath),
                        BERGEN_ANALYZER_LOCK=str(Path(self.tmp.name) / "analyzer.lock"),
                        BERGEN_REMOTE_LOG_GLOB=str(Path(self.tmp.name) / "nonexistent*"))
        db = sqlite3.connect(self.dbpath)
        db.execute("CREATE TABLE incidents(mac TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, "
                   "severity TEXT, event_count INTEGER, handshake_failures INTEGER, "
                   "eapol_timeouts INTEGER, leaves INTEGER, sources TEXT, summary TEXT)")
        db.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, ts TEXT, source TEXT, "
                   "mac TEXT, kind TEXT, rssi INTEGER, raw TEXT)")
        self.now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (MAC, self.now, self.now, "ACTION", 12, 8, 3, 2,
                    '["sensitive-ap-name-1","sensitive-ap-name-2"]', "metadata"))
        for value in (-77, -75):
            db.execute("INSERT INTO events(ts,source,mac,kind,rssi,raw) VALUES(?,?,?,?,?,?)",
                       (self.now, "sensitive-ap-name-1", MAC,
                        "wpa_invalid_state", value, "SECRET_RAW_WIFI_PAYLOAD"))
        db.commit()
        db.close()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_action_advisor_evidence_without_raw_log_leak(self):
        result = self.run_cli("advise", MAC.upper())
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("ACTION", "11 WPA/EAPOL-Fehler", "2 Logquelle(n)",
                         "RSSI", "Konfidenz", "Keine automatische Konfigurationsänderung"):
            self.assertIn(expected, result.stdout)
        self.assertNotIn("SECRET_RAW_WIFI_PAYLOAD", result.stdout)
        self.assertNotIn("sensitive-ap-name", result.stdout)
        self.assertNotIn("Keine automatische Konfigurationsänderung", result.stderr)

    def test_missing_client_fails_closed(self):
        result = self.run_cli("advise", "11:22:33:44:55:66")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incident/client not found", result.stderr)

    def test_missing_recent_rssi_makes_no_signal_claim(self):
        with sqlite3.connect(self.dbpath) as db:
            db.execute("DELETE FROM events")
            db.execute("UPDATE incidents SET severity='OBSERVE' WHERE mac=?", (MAC,))
        result = self.run_cli("advise", MAC)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Signalqualität unbekannt", result.stdout)
        self.assertIn("noch nichts ändern", result.stdout)

    def test_other_commands_and_no_config_mutation(self):
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        for command in ("run-once", "list", "show", "advise"):
            self.assertIn(command, help_result.stdout)
        source = SCRIPT.read_text()
        self.assertNotIn("subprocess.run(", source)
        self.assertNotIn("os.system(", source)
        self.assertNotIn("systemctl", source)


if __name__ == "__main__":
    unittest.main()
