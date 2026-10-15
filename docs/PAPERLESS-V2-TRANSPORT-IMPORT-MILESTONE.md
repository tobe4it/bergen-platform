# Paperless v2 – Abschnitt A: Transport und Import

**Stand 15.10.2026: Entwicklungsbranch, nicht freigegeben.**

Dieser Branch fasst die bisherige nonce-gebundene Senderentwicklung
(PR #74–#79) zu einem späteren, zusammenhängenden
Transport-zu-Import-Ablauf zusammen. Er aktiviert keinen v2-Sender,
führt keine neue NAS-Übertragung aus und löscht keine Originaldateien.

## Einmalige und crashsichere Übertragungsentscheidung

`synology_receipt_v2_store.py` versteht jetzt drei kanonische Ereignisse:
`PREPARED`, `ATTEMPTED` und `SENT`. Die
`ATTEMPTED`-Datei wird vor dem eigentlichen Prozessstart unter
dem bereits vorhandenen exklusiven `sync.lock` mit
Create-only-Veröffentlichung und `fsync` gespeichert. Auch eine
wiederholte identische `ATTEMPTED`-Publikation wird zurückgewiesen.

Das unabhängige, lesende
`audit_synology_receipt_history.py` erkennt und zählt `ATTEMPTED`
und prüft dessen exakte Beziehung zum `PREPARED`-Datensatz.
Verwaiste, manipulierte oder widersprüchliche Ereignisse
führen zum Abbruch. Die 19 v1-Receipts werden nicht umgeschrieben.

Die bisherige **rein simulierte** Sitzung in
`v2_sender_session_offline.py` veröffentlicht jetzt
`ATTEMPTED` bereits vor dem Transport-Callback, prüft das
Journal nach Transport und Empfängerprüfung erneut und verbietet
automatisches Resenden. Es bleibt eine Offline-Bibliothek,
die keine echten Prozesse startet und nie `SENT` schreibt.

Ein **echter** NAS-Sender muss diesen Ablauf erst mit
dem geprüften SSH-/rsync-Prozessplan und dem unabhängig
ausgeführten Empfänger-Audit verbinden. Er ist **noch nicht**
implementiert oder aktiviert. Vor einem Live-Test fehlen
insbesondere geprüfte DSM-/SSH-Berechtigungen,
Dateimodus/Eigentümer am LXC-Eingang sowie kontrollierte
Prozess-/Absturztests auf isolierten Testdateien.

## Papierloser Import mit eindeutiger v2-Identität

Die bisherigen v1-Importer erkennen nur
`<stem>--nas-<datei-sha256>.pdf`. Beim v2-Schema ist
`nas-v2-<128-bit-nonce>-<receipt-identity-sha256>.pdf`
maßgeblich. Der zweite Hash ist **nicht** der Inhalts-Hash
des PDFs. Eine reine Hashzuordnung wäre zudem mehrdeutig,
wenn zwei Dokumente identischen Inhalt haben.

Das neue `export_imported_scans_v2.py` ist deshalb
ein eigenständiger, **nur lesender** Paperless-Exporter.
Er prüft für jeden passenden v2-Bridge-Beleg das live
vorhandene Dokument einschließlich ID, Besitzer und
effektiver ACL über die bestehende Reconciliation
(`verify(...)`). Absichtlich gelöschte Dokumente
werden nicht als vorhanden gemeldet.

`match_v2_import_proof_offline.py` verknüpft nur ein
vollständig validiertes nonce-gebundenes `SENT`-Receipt
mit genau dem passenden v2-Importnachweis:
Receipt-ID, Receiver-Zielpfad, Original-PDF-SHA-256
und Dokument-ID. Unterschiedliche Nonces und Scopes
mit identischem PDF-Inhalt sind kein Treffer.

Die Match-Funktion akzeptiert derzeit eingereichte
Datenobjekte. Sie authentifiziert **nicht** selbst, dass
sie unmittelbar aus den beiden lebenden Systemen stammen.
Jede erfolgreiche Rückgabe enthält daher ausdrücklich:

- `origin_authenticated = false`
- `fresh_acl_verified_by_this_function = false`
- `archive_authorized = false`
- `source_delete_authorized = false`

Die Live-Belege müssen später separat über die
vorhandenen SSH-/Proxmox-Pfade mit erneutem Journal-Lock
geholt und als vollständiger Beweissatz gekoppelt werden.

## Abnahme

Die neue ATTEMPTED-Suite (13 Tests) sowie die
v2-Import-Verknüpfung (15 Tests) sind offline zu prüfen.
Die geänderte Sitzungssuite umfasst jetzt 32 Tests.
Die bisherigen 25 Prozess-Preflight-, 19 Nachweis- und
18 Empfängerprüfungen sollten ebenfalls laufen.
Zusätzlich bleibt der ältere Journal-Auditor-Test
relevant, um v1-Kompatibilität nachzuweisen.

```bash
python3 -m unittest discover -s tests -p 'test_paperless_v2_attempt_barrier.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_v2_import_join.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_v2_session_offline.py' -q
python3 -m unittest discover -s tests -p 'test_paperless_receipt_history_audit.py' -q
```

**Abschluss Abschnitt A erst nach:** Testdatei von der
Synology über nonce-gebundenes PREPARED/ATTEMPTED und
authentifiziertes SENT in den LXC gebracht, Paperless
importiert sie korrekt, und unabhängige Live-Abfragen
bestätigen Dokument-ID, Owner, Scope, ACL und Hash.
Absturztests verhindern Wiederholung und Löschung.

## Abschnitt B und Release-Gate

Archivierung/Quarantäne muss vor jedem Entfernen
der Quelle eine private, fsync- und SHA-256-geprüfte
Kopie über Synology-Btrfs-Subvolumes hinweg erzeugen,
dauerhaft journalingfähig sein und den verifizierten
Paperless-Import unabhängig erneut prüfen.
Anschließend dürfen ausschließlich unveränderte
Originale kontrolliert entfernt werden.
Backup/Restore und mindestens 30 vollständige Tage
Quarantäne müssen zusätzlich nachgewiesen sein.

**Kein Merge nach main**, bevor die gesamte Kette
inklusive sicherer Quelllöschung und Wiederherstellung
im Testbetrieb bestanden ist.
