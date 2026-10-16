# Bergen Paperless – Backup und Wiederherstellung (Freigabegate)

**Status: Konzept / nicht produktiv freigegeben.** Kein Archiv-Commit ohne abgeschlossenen Backup-/Restore-Nachweis. Diese Datei ist keine Anweisung, bestehende Backup-Aufträge blind zu verändern.

## Nachgewiesener Istzustand (16.10.2026)

- Auf Synology MountainCloud liegen die geschützten, noch leeren Archivstrukturen auf **zwei unterschiedlichen Btrfs-Subvolumes**:
  - `/volume1/paperless-scan/.bergen-paperless-archive` (Device 1048641, Scopes Eltern/Familie)
  - `/volume1/homes/.bergen-paperless-archive` (Device 47, Scopes Privat/thomas und Privat/nadja)
- Sender-State und Archiv-Journal liegen **separat** unter `/volume1/.bergen-platform-state/paperless-sync` (Device 40); `archive-move-journal` ist gegenwärtig leer.
- State-Inventur: 25 reguläre Dateien (200.000 Byte), eine Unterstruktur, keine Symlinks/Spezialdateien, keine regulären Dateien mit Gruppen-/Fremdrechten. Klassifizierung unter erfolgreicher `flock(LOCK_SH|LOCK_NB)`: 21 `SENT`-Receipts, 0 `PREPARED`, `sync.lock`, zwei weitere Locks, ein Log, leeres Journal.
- Hyper Backup `task_4` sichert 28 ausgewählte Synology-Anwendungen, aber `backup_folders` enthält **0 explizite Freigaben**. Keine Paperless-Archiv-/State-Sicherung nachgewiesen; eventuelle implizite App-Daten sind keine hinreichende Beweiskette.
- 2/2 NAS-Standorte bestanden gesonderte lesende Berechtigungs-, Btrfs- und Kernel-`renameat2(RENAME_NOREPLACE)`-Tests mit synthetischen Testdateien. Keine produktiven PDFs verschoben; Freigabegates bleiben abwesend.

## Sicherungsumfang

1. Geschützte Archive samt künftig archivierter Original-PDFs auf **beiden** Btrfs-Subvolumes, inklusive Verzeichnisstruktur. Nicht nur den normalen Paperless-Ingest-/Scan-Eingang sichern.
2. Den vollständigen senderseitigen State **inkl. alter und neuer Receipts, `sync.lock`, zweier weiterer Locks, Log und `archive-move-journal`**. Unbekannte reguläre Dateien nicht stillschweigend ignorieren; keine automatischen Löschaktionen.
3. Die Wiederanlaufkonfiguration (Synology-Ansible-Code, versionskontrollierte Playbooks, Vault-Wiederherstellung ohne Geheimnisse in Git). Nicht allein auf die installierte NAS-Kopie vertrauen.
4. Einen zeitlich zusammengehörigen Paperless-Datenbank-/Medien-Stand sowie NAS-Sender-/Receiver-/Importbelege berücksichtigen. Eine NAS-Original-PDF allein ersetzt keinen Paperless-Dokument-/Importnachweis.

## Konsistenzmodell

- Für einen **senderseitigen State-Export** `sync.lock` mit `flock(LOCK_SH|LOCK_NB)` erwerben und bis zum Abschluss aller Dateilesungen halten. Der Sender und der Archivierungsworker verwenden diese Sperre exklusiv. Bei Lock-Konflikt, unbekanntem Eintragstyp, Symlink, unsicherer Dateimetadatenlage oder geänderter Dateisignatur: **abbrechen**.
- Manifest mit relativen Pfaden, Dateiart, Größe, SHA-256 und restaurierbaren Eigentümer-/Modus-Metadaten erstellen; Manifest und archivierte Daten gemeinsam sichern. Niemals private Dateinamen, Receipt-Inhalte, Zugangsdaten oder Prüfsummennachweise mit privaten Identifikatoren in Git/PR-Kommentaren veröffentlichen.
- **Der shared-lock-State-Export ist allein noch KEINE transaktionale, volumeübergreifende Momentaufnahme.** Für produktive Archivierungen muss die konsistente Zuordnung von Archiv-PDFs und Journaleinträgen entweder durch koordiniertes Quiescing/Backup-Fenster oder durch eine dokumentierte, idempotente Recovery-/Reconciliation-Strategie nachgewiesen werden.
- Exportdateien enthalten vertrauliche Familien-/Dokument-Metadaten: nur in überprüften privaten Verzeichnissen, verschlüsselt und auf vom NAS unabhängiges Sicherungsziel übertragen. Kein dauerhaftes unverschlüsseltes Zwischenarchiv in einer allgemein zugänglichen Freigabe.

## Vorgeschlagene Hyper-Backup-Strategie (noch nicht konfiguriert)

- Bestehenden Synology-Anwendungsauftrag `task_4` **unverändert lassen**.
- Separaten versionierten Sicherungsauftrag für `paperless-scan`, `homes` und einen kontrollierten, **eigens vorbereiteten** State-Export anlegen. Prüfen, ob die versteckten geschützten Archive und die State-Export-Dateien vom tatsächlichen Lauf erfasst sind; reine Freigabeauswahl reicht als Nachweis nicht.
- Unabhängiges Sicherungsziel außerhalb des primären NAS und Wiederherstellungspunkte (Retention) nachweisen. Bei nicht zugänglicher Quelle `/volume1/.bergen-platform-state` keinen stillschweigenden Ausschluss akzeptieren.
- Die Backup-Methode für die getrennten Subvolumes muss Journal-/PDF-Konsistenz erhalten; automatische Snapshot-Synchronität über Subvolumes nicht behaupten.

## Abnahme / isolierter Restore (noch offen)

1. Exporter-Code und negative Unit-Tests für Lock-Konflikte, unbekannte Dateitypen, Symlinks, veränderte Dateien, Manipulation von Manifest/Hash sowie sichere Zielpfade im Draft-PR reviewen.
2. Mit **synthetischen** Receipts, Journalereignissen und Test-PDFs eine definierte, sichere Export-/Restore-Probe außerhalb aller Live-Pfade durchführen; Hashes, Eigentümer und Berechtigungen vergleichen.
3. Realen externen Sicherungslauf des ausgewählten Jobs nachweisen (Job, Version, Zieltyp, Abdeckungsumfang, Datum), ohne Geheimnisse preiszugeben.
4. Backup-Version in **separates, isoliertes** Testverzeichnis zurückholen und Manifest/SHA-256/Dateimodus/Identitäten prüfen; keine Wiederherstellung in laufende Paperless-, Scan- oder NAS-State-Verzeichnisse.
5. Wiederanlauf einschließlich Journalzuständen `ARCHIVE_PREPARED` / `ARCHIVED`, fehlender Datei, verwaister Archiv-PDF, Replay und altem v1-Receipt-Fall prüfen. Unklare Fälle bleiben manuell gesperrt.
6. Erst nach bestandener Nachweiskette separate schriftliche Freigabe pro Site erwägen. **Weder `archive-move.paperless-scan.enabled` noch `archive-move.homes.enabled` erstellen**; `archive-move.enabled` muss ebenfalls fehlen.

**Offen:** tatsächliches externes Backup-Ziel, zulässiger geschützter Exportpfad, Laufplan, Verschlüsselung/Retention, Wiederherstellungsnachweis und produktive Import-/Journal-End-to-End-Proben.

## Akuter Speicherplatz-Blocker auf vorhandenem USB-Ziel (16.10.2026)

Die NAS-seitige, **lesende** Mount-/statvfs-Prüfung ergab für `/volumeUSB1/usbshare1-2`: `fuseblk.ntfs`, ca. **14.901,9 GiB Gesamtkapazität**, lediglich **7,1 GiB verfügbar** (99,95 % belegt), Mount nicht read-only. Die vorhandene USB-Festplatte ist damit **nicht als zusätzlicher Backup-/Restore-Arbeitsbereich freigegeben**. Noch unbekannt: tatsächlich durch Hyper Backup genutzter Anteil, letztes erfolgreiches `task_4`-Backup, vorhandene Versionierung/Retention und Lösch-/Rotationsstrategie. **Kein manuelles Löschen von `.hbk`-Dateien oder Backup-Verzeichnissen**; bei Freiraumbedarf nur kontrollierte Maßnahmen anhand des Hyper-Backup-Auftrags nach zusätzlicher unabhängiger Sicherungsprüfung. Der State-Exporter kann mit synthetischen Daten entwickelt werden, aber produktive State-Snapshots und der externe Restore-Test dürfen nicht von diesem faktisch vollen Medium abhängen.
