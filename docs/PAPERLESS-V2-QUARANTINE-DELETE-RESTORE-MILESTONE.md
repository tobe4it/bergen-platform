# Paperless v2 – Abschnitt B: Quarantäne, Originalentfernung und Restore

**Stand: 15.10.2026 – AUSSCHLIESSLICH OFFLINE-TEST, keine
Produktivfreigabe und noch kein Release.**

Der neue Branch ist auf Abschnitt A (Transport und Import, PR #80)
aufgebaut. Die Originale auf MountainCloud, die aktiven NAS-Skripte
und alle 19 historischen v1-`SENT`-Receipts bleiben unangetastet.

## Der jetzt implementierte Testablauf

`ansible/files/paperless/v2_quarantine_fixture_only.py`
hat **keinen CLI-Einstieg**, keine Ansible-Installation und keine
Anbindung an `synology_scan_sync.py`. Jeder aufrufbare Schreibpfad
muss ein vom laufenden Benutzer gehaltenes Verzeichnis mit Modus
`0700` direkt unter `/tmp` und dem Präfix
`bergen-paperless-archive-fixture-` sein. Damit sind DSM-Homes,
`/volume1` und reale Benutzerdateien explizit ausgeschlossen.

Die Testdatei muss regulär, einzeln verlinkt, `0600`,
UID-eigen und SHA-256-geprüft sein; außerdem muss die
Original-Inkarnation exakt der fünfteiligen NAS-Signatur
(Gerät/Inode/Größe/mtime_ns/ctime_ns) im zugehörigen
nonce-gebundenen v2-`SENT` entsprechen. Der v2-Paperless-
Importbeleg muss exakt den gleichen Receipt-Identifier,
Receiver-Pfad und Inhalts-Hash haben. Dies ist **nur die
inhaltliche Validierung übergebener Testbelege**, keine
Beglaubigung ihrer Herkunft.

Der Ablauf unter einem exklusiven privaten `sync.lock`:

1. Dauerhaftes `QUARANTINE_PREPARED`-Ereignis mit
   `fsync` **vor** jeder Kopie.
2. Stream-Kopie in ein zufälliges privates temporäres Ziel
   **innerhalb des Quarantäne-Verzeichnisses**. So ist
   keinerlei Rename zwischen NAS-Btrfs-Subvolumes erforderlich.
3. `fsync` des Zielinhalts, SHA-256/Größen- und
   PDF-Formatkontrolle, erneute Prüfung des Original-Dateiobjekts,
   atomare create-only Hardlink-Publikation **innerhalb
   desselben Quarantäne-Verzeichnisses** und dessen `fsync`.
4. Unveränderliches `ARCHIVED`-Ereignis erst nach erneuter
   Kopien- und Originalprüfung.
5. Eine **separate, explizite Testschnittstelle** prüft das
   bereits publizierte Archiv sowie `QUARANTINE_PREPARED`
   und `ARCHIVED`. Mit einer rein für Tests vorgesehenen
   Bestätigung wird ein `SOURCE_REMOVE_INTENT`-Ereignis
   geschrieben, Quelle und Kopie werden erneut geprüft,
   und **ausschließlich die /tmp-Testquelle** wird gelöscht.
   Nach Directory-`fsync` wird `SOURCE_REMOVED` publiziert.
6. Ein eigenständiger Fixture-Restore rekonstruiert die
   Testquelle aus der erhaltenen Quarantäne-Kopie, prüft den
   Hash und schreibt ein einmaliges `RESTORED`-Ereignis.

Nach jedem Abbruch bleibt der Originalbestand, soweit vor
`SOURCE_REMOVE_INTENT` möglich, erhalten. Ein vorhandenes
oder unvollständiges Journal verhindert automatisches erneutes
Archivieren, Entfernen und Wiederherstellen. Insbesondere
wird niemals das Vorhandensein einer gleichnamigen Datei
als positives Import- oder Löschsignal behandelt.

## Abgesicherte Testfälle

`tests/test_paperless_v2_quarantine_fixture.py` umfasst
22 Offline-Tests: erfolgreiche Kopie, Quellbestandsschutz,
Originalidentität trotz identischem Inhalt nach Dateiwechsel,
Dateimodus und Symlink/Hardlink, Hashmanipulation,
Kopierabbruch und Wiederanlauf, fehlendes oder manipuliertes
Quarantäne-Journal, konkurrierende Zielnamen,
einmalige Entfernung, verweigerte Wiederholung,
Wiederherstellung und Ablehnung jeder Quelle außerhalb
des privaten /tmp-Fixture-Namensraums.

Ausführung:

```bash
python3 -m unittest discover -s tests -p 'test_paperless_v2_quarantine_fixture.py' -v
```

## Erste Zielstufe: geschützter NAS-Archiv-Move, ohne Auto-Purge

**Freigaben trennen:** Ein nachweislich in Paperless importiertes Original
kann auch zwischen zwei täglichen Backups in einen geschützten NAS-Archivpfad
verschoben werden. Der Ortswechsel erzeugt keine gewollte Datenvernichtung;
das Original bleibt erhalten. Ein unmittelbar zuvor erfolgreiches Backup
ist daher **kein hartes Gate für diesen ersten Schritt**.

Auf MountainCloud sind für alle vier Scopes geschützte Archivpfade **auf
dem jeweiligen gleichen Btrfs-Subvolume wie der Scanner-Eingang**
vorbereitet. Der bereits installierte, aber deaktivierte v1-Worker
`synology_same_volume_archive_move.py` verwendet dafür ausschließlich
atomisches `renameat2(RENAME_NOREPLACE)`, niemals Copy-Delete.
Die beiden produktiven Commit-Gates sind weiterhin **nicht gesetzt**.

Die v2-Funktion `v2_quarantine_fixture_only.py` testet dagegen einen
**anderen**, früher konzipierten Copy-/Unlink-Pfad ausschließlich unter
`/tmp`. Ihre Sicherheitsnachweise sind **kein** Produktionsnachweis für
eine v2-Archivverschiebung. Vor der ersten produktiven Freigabe müssen
v2-Receipt, authentifizierter IMPORTED-Beleg, Dateisignatur,
Paperless-Eigentümer/ACL, Lock, Archivjournal, Rename-Race-/Crash-Recovery
und ein isolierter Live-Canary überprüft sein. Ein bloßer erfolgreicher
Transportstatus `SENT` reicht nicht.

Die Bezeichnung „30-Tage-Archiv“ bedeutet zunächst **mindestens** 30 Tage
Aufbewahrung. Es gibt keinen freigegebenen automatischen Purge; nach Ablauf
von 30 Tagen bleibt die PDF erhalten, bis der eigene, strengere
Lösch-/Backup-/Restore-Freigabeprozess nachweislich bestanden ist.

## Was für die produktive Archivierung zwingend noch fehlt

Diese Tests reichen **nicht** für eine Löschfreigabe! Die folgenden
realen Vertrauens- und Recovery-Grenzen sind vor Aktivierung
abzunehmen:

- **Frisch authentifizierter Paperless-Import** mit lebendem
  Dokument, exakt gebundenem nonce-Receipt und nachgewiesen
  effektivem Eigentümer und ACL, nicht ein frei übergebener JSON-Beleg.
- **Sender-Provenienz und Journale** über die vorhandene
  geschützte Synology-SSH- und `sync.lock`-Strecke;
  v2-`PREPARED`, `ATTEMPTED`, `SENT` und Archivstatus
  müssen dauerhaft abgestimmt sein.
- **DSM-ACLs und tatsächliche Verzeichnisstruktur**: least-privilege
  für `paperless-sync`, sichere Quarantäne-Eigentümer/-ACL,
  eindeutige Geräte-/Subvolume-Identität; keine Annahme eines
  atomaren Cross-Subvolume-Renames.
- **Präzise Source-unlink-Sperre** gegen konkurrierende DSM-
  Scanner-/Dateioperationen. Ein einfacher finaler `lstat`/
  `unlink`-Abstand ist für eine unkontrollierte parallele
  Umgebung nicht ausreichend; positive und negative Tests
  müssen dies beweisen oder durch eine gesperrte Inbox beheben.
- **Wirklich wiederherstellbares Backup** von Paperless-Daten,
  NAS-Journal und Originalarchiv ist für den **späteren endgültigen Purge**
  ein hartes Gate, **nicht** für den zuvor unabhängig geprüften atomaren
  Ortswechsel in das geschützte NAS-Archiv. Backups sind dennoch weiterhin
  operativ dringend erforderlich.
- **Mindestens 30 volle Tage Archivaufbewahrung** ab einem
  unveränderlichen, dauerhaft aufgezeichneten ARCHIVED-Zeitstempel.
  Für die erste Betriebsfreigabe bleibt eine automatische
  Bereinigung explizit deaktiviert: die Dateien verbleiben
  auch nach Ablauf der 30 Tage, bis ein eigener, separat geprüfter
  und freigegebener Expiry-Worker implementiert ist.
- **Crash-Reconciliation**, insbesondere nach create-only-
  Archivpublikation vor `ARCHIVED`, nach `SOURCE_REMOVE_INTENT`
  vor `unlink` sowie nach `unlink` vor `SOURCE_REMOVED`.
  Bis zur manuellen Klärung: fail closed, nie blind wiederholen.
- **Isolierter Live-Test mit eigens erzeugter Test-PDF**:
  Scanner-Inbox → authenticated `SENT` → Paperless `IMPORTED`
  → geschützter same-subvolume-Move/Archivjournal → Nachweis, dass
  Original sicher im Archiv liegt → Recovery-Test, einschließlich
  Absturz- und negativer ACL-Prüfungen. Separat, erst für den
  Lösch-Release: Backup/Restore → Mindestaufbewahrung → kontrollierter
  Purge-Test. Die /tmp-Copy-Unlink-Fixtures bleiben davon getrennt.

Der Testknopf `offline_restore_test_confirmed=True` ist
**keine** technische Bestätigung eines realen Backups, und
`production_approved` ist in jeder Rückgabe `false`.
Das Modul wird niemals in den NAS-Deploypfad aufgenommen.

**Merge nach `main` bleibt blockiert**, bis die produktive
Implementierung und die genannten Tests tatsächlich bestanden sind.

## Controller-Regression 15.10.2026

Erster gemeinsamer Testlauf: `FAILED_SUITES=2`. Im übermittelten
Ausschnitt scheiterte die neue Prozess-Preflight-Suite an
`UNSAFE_TRUSTED_FILE`, während beide früheren Suiten für
Transfernachweis (19/19) und Empfängerprüfung (18/18) bestanden.

Die Preflight-Tests sind nun von den Dateimodi des per `git worktree`
ausgecheckten Source-Skripts unabhängig: Sie verwenden eine
lokale `0600`-Kopie des unveränderten Empfängerprüfers. Die echte
Sicherheitsprüfung bleibt streng und läuft jetzt **vor dem ersten
SSH-Aufruf**. Zwei weitere Tests verlangen fail-closed-Verhalten bei
`0664` und Symlinks. Das Repo-Skript darf für reale Ausführung
weiterhin nicht gruppenbeschreibbar sein; die Testkorrektur hebt
keine Berechtigung auf.

Ferner korrigiert ein ATTEMPTED-Test die erwartete öffentliche
Fehlerklasse `INVALID_HISTORICAL_RECEIPT`: Die Speicherung kapselt
den intern erkannten Statuswiderspruch absichtlich in diese
fail-closed-Meldung. Die zweite fehlgeschlagene Suite aus dem
Controller-Ausschnitt ist damit noch **nicht nachgewiesen**; alle
betroffenen und anschließend alle acht Suiten sind erneut zu prüfen.
