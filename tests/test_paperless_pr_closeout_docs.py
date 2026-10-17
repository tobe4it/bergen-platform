"""Contract tests for the historical Paperless PR closeout, without host access."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ADMIN = DOCS / "PAPERLESS-GROUP-ADMINISTRATION.md"
CLOSEOUT = DOCS / "PAPERLESS-PR-CLOSEOUT-2026-10-17.md"
OPERATIONS = DOCS / "PAPERLESS-GROUP-OPERATIONS.md"


class PaperlessLegacyCloseoutTests(unittest.TestCase):
    def test_source_and_operational_links_exist(self):
        admin = ADMIN.read_text(encoding="utf-8")
        closeout = CLOSEOUT.read_text(encoding="utf-8")
        self.assertTrue(OPERATIONS.is_file())
        self.assertIn("PAPERLESS-GROUP-OPERATIONS.md", admin)
        self.assertIn("PAPERLESS-GROUP-ADMINISTRATION.md", closeout)
        for n in (59, 60, 68, 54, 55, 62, 80, 81):
            self.assertIn(f"/pull/{n}", closeout)

    def test_no_false_release_of_deletion_or_private_archiving(self):
        closeout = CLOSEOUT.read_text(encoding="utf-8")
        admin = ADMIN.read_text(encoding="utf-8")
        for phrase in ("kein automatischer Purge", "weiterhin nicht freigegeben",
                       "keine v2-Live-Freigabe"):
            self.assertIn(phrase.lower(), closeout.lower())
        self.assertIn("nicht", admin.lower())
        self.assertIn("private Eingänge", admin)
        self.assertIn("eigen", admin.lower())

    def test_18_exact_tags_are_documented_and_mutations_not_autoenabled(self):
        admin = ADMIN.read_text(encoding="utf-8")
        tags = ("Steuer", "Haus", "Finanzen", "Versicherung", "Mobilität",
                "Gesundheit", "Bildung", "Beruf", "Reise", "IT",
                "Ehrenamt", "Behörden", "Haustiere", "Energie", "Gewährleistung",
                "Posteingang", "Aktion offen", "Frist prüfen")
        for name in tags:
            self.assertIn(name, admin)
        self.assertIn("dry", admin.lower())
        self.assertIn("keine", admin.lower())
        self.assertIn("delete_tag", admin)

    def test_no_old_document_identity_or_hardcoded_private_nas_endpoint(self):
        text = (ADMIN.read_text(encoding="utf-8") + "\n" +
                CLOSEOUT.read_text(encoding="utf-8"))
        self.assertNotIn("192.168.2.145", text)
        self.assertNotIn("Gebuehren.pdf", text)
        self.assertNotIn("Gebuehren 2.pdf", text)
        self.assertNotIn("paperless_archive_purge=true", text)


if __name__ == "__main__":
    unittest.main()
