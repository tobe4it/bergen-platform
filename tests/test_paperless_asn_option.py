"""ASN label flag remains disabled and independent from recursive ingestion."""
import json
import unittest
from pathlib import Path
import yaml
from jinja2 import Environment

ROOT=Path(__file__).resolve().parents[1]
ROLE=ROOT/"ansible/roles/paperless"
FILE=ROLE/"templates/paperless.env.j2"

class ASNSettingsContract(unittest.TestCase):
    def render(self, enabled):
        env=Environment()
        env.filters["to_json"]=json.dumps
        env.filters["bool"]=bool
        vars=dict(
            paperless_url="https://example.invalid",
            vault_paperless_secret_key="example-key",
            vault_paperless_db_password="example-db",
            vault_paperless_admin_password="example-admin",
            paperless_timezone="Europe/Berlin", paperless_ocr_language="deu+eng",
            paperless_uid=1000, paperless_gid=1000,
            paperless_admin_user="admin", paperless_scan_asn_enabled=enabled)
        return env.from_string(FILE.read_text()).render(**vars)

    def test_asn_is_off_by_default(self):
        defaults=yaml.safe_load((ROLE/"defaults/main.yml").read_text())
        self.assertIs(defaults["paperless_scan_asn_enabled"],False)

    def test_disabled_does_not_enable_asn(self):
        output=self.render(False)
        self.assertNotIn("PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE=true",output)
        self.assertNotIn("PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX=ASN",output)
        self.assertIn("PAPERLESS_CONSUMER_RECURSIVE=false",output)

    def test_opt_in_adds_only_number_recognition_not_barcode_split(self):
        output=self.render(True)
        self.assertIn("PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE=true",output)
        self.assertIn("PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX=ASN",output)
        self.assertIn("PAPERLESS_CONSUMER_RECURSIVE=false",output)
        self.assertNotIn("PAPERLESS_CONSUMER_ENABLE_BARCODES=true",output)
        self.assertNotIn("PAPERLESS_CONSUMER_ENABLE_BARCODES_ASN=true",output)

    def test_first_install_gate_remains_strict(self):
        tasks=(ROLE/"tasks/main.yml").read_text()
        self.assertIn("paperless_first_install_approved | default(false) | bool",tasks)
        self.assertIn("PAPERLESS_EXISTING_INSTALLATION_PROTECTED",tasks)

if __name__=="__main__":
    unittest.main()
