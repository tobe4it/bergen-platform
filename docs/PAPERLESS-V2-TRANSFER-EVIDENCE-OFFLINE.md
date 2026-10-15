# Paperless v2 – Offline-Korrelation von Transport- und Empfangsnachweis

**Stand 15.10.2026: OFFLINE ONLY, kein Live-Sender, kein SENT-Commit.**

Nach der erfolgreichen Offline-Abnahme von PR #75 (18/18 Tests,
Ansible-Syntax gültig) wird die Vertrauenskette für einen zukünftigen
Sender technisch beschrieben und isoliert geprüft.

## Zweck

Zwei getrennte Ergebnisse müssen zu derselben **dauerhaft gespeicherten**
Nonce-Inkarnation gehören:

1. Der lokale rsync-Prozess meldet nach einem Aufruf mit
   `--ignore-existing --out-format=%i %n` erfolgreich genau eine
   neu angelegte reguläre Datei
   (`<f+++++++++ nas-v2-<nonce>-<hash>.pdf`).
2. Ein separater, read-only Prüfer in LXC 126 liest unter der
   berechtigten Identität `paperless-ingest` genau diese Datei und
   bestätigt unveränderte sichere Metadaten, erwartete Größe,
   SHA-256 und plausibles PDF.

Das neue Feld `RECEIVER_BINDING` wird aus

```text
sha256(UTF8(scope + NUL + receiver_basename + NUL + sha256 + NUL + size))
```

gebildet. Es verbindet die lesende Rückmeldung mit dem in
`PREPARED` verankerten Scope, Nonce-Dateinamen, Hash und Umfang.

**Dies ist keine Signatur und keine Authentifizierung!** Der Wert ist
öffentlich berechenbar und kann ohne vertraute Transportstrecke
gefälscht werden. Die Prüfung belegt nur, dass die übergebenen
Textbeweise *inhaltlich konsistent* sind.

## Umsetzung im Branch

- `verify_receiver_v2_staging.py` ergänzt genau eine Zeile
  `RECEIVER_BINDING <64hex>` in der erfolgreichen Ausgabe. Die
  bisherigen Verbote von `SENT`, Import- und Quelllöschung gelten
  unverändert.
- `audit-paperless-v2-receiver.yml` verlangt zusätzlich das
  formal gültige Bindungsfeld.
- `compare_v2_transfer_evidence_offline.py` validiert eine
  **streng formatierte, vom Aufrufer übergebene** rsync-Ausgabe,
  Rückgabewerte, fehlende Warnungen und alle neun erwarteten
  Zeilen des Receiver-Audits. Jeder Fehler führt zum Abbruch.
  Die Identität des PREPARED-Ereignisses wird erneut rein rechnerisch
  geprüft. Das Modul hat keine I/O-Schnittstelle und keinen
  `SENT`-Publikationsaufruf.
- `test_paperless_v2_transfer_evidence_offline.py` enthält
  18 Offline-Tests für Race-/Replay-relevante Identitäten,
  Prüfsummen, Größen, Vertauschung der Scopes/Nonces,
  fehlende oder doppelte Marker und unzulässige Ausgaben.

Die Rückgabe `compare_offline(...)` enthält immer:

```text
origin_authenticated = false
durable_prepared_reverified_under_lock = false
sent_authorized = false
source_delete_authorized = false
```

Diese Werte sind **harte Grenzen** und dürfen nicht durch ein
nachträgliches Mapping oder einen Template-Schritt zu `true` werden.

## Was für einen produktiven SENT-Commit noch fehlt

- Einen getesteten, vertrauenswürdigen Orchestrator mit unverwechselbar
  an das dauerhafte PREPARED gebundenen Transportsitzungen.
- Nachweis, dass die rsync-Antwort vom **tatsächlich gestarteten**
  lokalen Prozess mit korrektem Zielsystem und Zielpfad stammt.
- Authentifizierte Ausführung des Empfängerprüfers über den bereits
  etablierten Proxmox-/LXC-Kanal – keine eingereichten Textbeweise.
- Frischer Vergleich der Quelle (unveränderte Dateisignatur und
  Digest) und der unveränderlichen PREPARED-Bytes **unter derselben
  Sendersperre** vor dem `SENT`-Commit.
- Gezielt getestetes Verhalten bei Abbruch nach erfolgreichem
  rsync, vor dem Receiver-Audit und nach positiver Verifikation.
  Ein zweiter automatischer Transfer bleibt verboten.
- Festlegung der benötigten Dateimode und Eigentümer am rsync-Ziel:
  Der Receiver erwartet reguläre 0600-Dateien des technischen
  Ingest-Benutzers. Das muss später mit dem kontrollierten
  rsync-Aufruf und der tatsächlichen DSM/SSH-Restriktion
  abgestimmt werden.

Auch ein authentisch bestätigtes SENT ist **keine**
`IMPORTED`-Freigabe. Der spätere Dokumentenimport muss unabhängig
am Paperless-Beleg, Besitzer, privaten ACLs und eventuellen
bewussten Benutzerlöschungen nachgewiesen werden.

## Tests auf bp-controller (nur offline)

```bash
python3 -m unittest discover -s tests -p 'test_paperless_v2_transfer_evidence_offline.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_v2_receiver_readonly.py' -v
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-v2-receiver.yml --syntax-check
```

Die 19 historischen v1-SENT-Receipts bleiben unangetastet;
kein rsync, keine LXC-Schreiboperation und keine PDF-Löschung
sind Teil dieses PR. `main`, Quarantäne, Archivierung und
30-Tage-Purge bleiben gesperrt.
