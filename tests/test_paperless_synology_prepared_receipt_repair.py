"""Safety regression gates for the single NAS PREPARED receipt repair."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/repair_synology_prepared_receipt.py"
PLAY = ROOT / "ansible/playbooks/repair-paperless-synology-prepared-receipt.yml"


class RepairPreparedReceiptPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.play = PLAY.read_text(encoding="utf-8")

    def test_script_compiles(self):
        compile(self.script, str(SCRIPT), "exec")

    def test_single_known_receipt_and_document(self):
        self.assertIn("66f0963d8a6c97c910be44208ae637b3b5f5dc77ec062ae83dadaa7dd97282f6", self.script)
        self.assertIn("f622de2cd7aa2829f6716f09", self.script)
        self.assertIn("DOCUMENT_ID = 23", self.script)
        self.assertIn("SOURCE_SHA256_MISMATCH", self.script)
        self.assertIn("SOURCE_CHANGED_DURING_READ", self.script)

    def test_no_document_mutation(self):
        for forbidden in ("os.unlink(", "os.rename(", "shutil.move(", "subprocess.run(", "os.chown("):
            self.assertNotIn(forbidden, self.script)
        self.assertIn("if not commit:", self.script)
        self.assertIn("ALREADY_REPAIRED", self.script)
        self.assertIn("write_receipt(receipt_file, updated)", self.script)
        self.assertIn("flock(lock, LOCK_EX | LOCK_NB)", self.script)

    def test_fresh_live_proof_before_mutation(self):
        self.assertLess(self.play.index("--audit-imported"), self.play.index("Audit or repair the one NAS"))
        self.assertIn("PAPERLESS_IMPORT_PROOF_VERIFIED", self.play)
        self.assertIn("paperless_nas_receipt_repair_apply | default(false) | bool", self.play)
        self.assertIn("changed_when: false", self.play)
        self.assertIn("delegate_to: localhost", self.play)


if __name__ == "__main__":
    unittest.main()
