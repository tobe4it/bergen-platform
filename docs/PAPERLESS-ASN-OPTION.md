# Optionale Paperless-ASN-Erkennung (nicht aktiviert)

Aus [PR #56](https://github.com/tobe4it/bergen-platform/pull/56) separat extrahierte Barcode-/ASN-Funktion. **ASN ist eine fortlaufende Dokumentreferenz, keine Berechtigung und kein Eigentumsnachweis.** Ein ASN-Wert ersetzt weder Senderquittung noch SHA-256, Benutzer-/Gruppenrechte, ACL oder Importnachweis.

Die bestehende, ausschließlich für **Erstinstallationen auf leeren Zielsystemen** geeignete Paperless-Role enthält den standardmäßig abgeschalteten Parameter `paperless_scan_asn_enabled: false`. Nur eine separat genehmigte Greenfield-Konfiguration mit `true` ergänzt die Variablen `PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE=true` und `PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX=ASN` in `paperless.env`. `PAPERLESS_CONSUMER_RECURSIVE=false` bleibt unverändert; **Barcode-basiertes Aufteilen** wird nicht aktiviert.

**Weder ein Merge noch ein Planungswert ändert die bereits betriebene Paperless-Instanz.** Ihre tatsächlichen Umgebungsvariablen, ASN-Scanqualität und die Paperless-Version sind noch nicht live abgenommen. Ein optionaler Test mit einem rein synthetischen Scan sowie Prüfung, ob ein eindeutiger ASN-Zähler über alle erlaubten Scopes gewährleistet ist, ist Voraussetzung vor einer späteren Produktionsaktivierung.

Durchführen ohne Zugriff auf Paperless:

```bash
python3 -m unittest discover -s tests -p 'test_paperless_asn_option.py' -v
```

Der zugrunde liegende Proxmox-LXC und dessen produktives Quadlet dürfen **nicht** durch diese alte Greenfield-Role verändert werden. Das Aktivieren für eine bestehende Installation wäre ein eigenes Änderungsverfahren mit vorherigem Ist-Audit, Backup und Rollbackplan.
