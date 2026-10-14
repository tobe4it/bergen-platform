# Paperless scan inbox lifecycle: verified import, NAS quarantine, expiry

Status: **design approved, implementation NOT deployed** (2026-10-14). The active
Synology sender and Paperless ingest pipeline remain copy-only. In particular,
no script or timer may delete or rename an original scan based solely on SENT.

## Objective

Keep the source Paperless scan folders flat and empty after *verified* import,
without inventing a permanent folder hierarchy on Synology. Paperless is the
authoritative searchable archive. The NAS holds a short-lived, private
recovery copy after acknowledgement, not a second organised document library.

Current enabled scopes: Privat/thomas, Privat/nadja, Eltern, Familie. Do not
enable any additional private scopes until the Paperless account, workflow
and ACL checks exist.

## Backup baseline (verified separately)

Proxmox guest 126 `bergen-paperless`: 32 GiB rootfs plus 100 GiB `mp0`
document volume with `backup=1`. Backup destination
`bergen-synology-backup` on Synology NFS. `vzdump` stop mode + zstd.
A full recovery into isolated test guest 901 was completed on 2026-10-12,
including PostgreSQL, Redis, Paperless and an OCR test document; the test
guest was subsequently removed. Additional protected archive created
2026-10-13. The systemd units `bergen-paperless-vzdump.service` and
`.timer` run at 03:00 Europe/Berlin. The 2026-10-14 run completed successfully
at 03:02:54, with rootfs and mp0 included and an archive present on the NFS
target. The executed retention was keep-daily=7, keep-weekly=4,
keep-monthly=12. Purge still needs a fresh backup-health check at the time
of each deletion, not just this historical evidence. A successful historical restore is not
proof that the unattended job continues to work.

## Fail-closed workflow

1. Synology sender detects a stable PDF and copies it through the existing
   restricted rsync receiver. It records SHA-256, sender source filename,
   scope, destination and signature in its private SENT journal.
2. Paperless LXC stages and imports the document. Its reconciliation journal
   records IMPORTED only after a live document-ID, checksum, owner, group,
   direct-permissions and active-user visibility verification.
3. A trusted controller workflow via **existing** access
   `bp-controller -> venombox -> pct exec 126` re-verifies the live Paperless
   document and emits a narrow acknowledgement containing the receiver-side
   destination name, SHA-256, document ID and bridge receipt identity.
   No new inbound NAS, Paperless or SSH connection is necessary.
4. Through the existing NAS administrative connection, a *short-lived* NAS
   archiver validates that acknowledgement against its own SENT receipt and
   verifies the original source is the *same* file with the *same* digest
   and signature. The archiver has a lock and durable journal. If any
   comparison fails, it must leave the original source in place.
5. After validated live import proof, the archive step creates a durable,
   SHA-256-verified copy (not a cross-device rename) of the original PDF
   from the monitored input into a private,
   non-watched quarantine owned by the restricted sync account within
   `state_parent/paperless-archive/<scope>/YYYY-MM/`. Private and shared
   scopes remain separated; no new read grants are created.
   The restricted `paperless-sync` account is intended to have **read and
   delete** rights on PDFs inside its permitted scan input directories:
   traversing/listing, reading, and removing successfully processed originals
   are necessary; creating/editing PDF content, changing ACLs or ownership,
   and access to other home content are not. Synology ACL permissions for
   unlink/rename depend on directory-level delete/delete-child rights.
   The current broad input ACE permits more than this target and must not
   be blindly replaced while production ingest is running.
   The quarantine directory and its scope/month subdirectories are owned by
   the configured `paperless-sync` account (group `users`) and use mode `0700`.
   Its application parent and code/config remain root:root `0755` / root-owned.
   The same account is intended to copy verified originals into this
   quarantine and, only after durable journal acknowledgement, remove the
   unchanged original from the scan input; deletion of expired archive PDFs
   is a separate operation. Time-based deletion is
   enforced by the scheduled application logic, **not by the filesystem ACL**;
   thus compromise of the sync account can also cause early deletion. Run
   the expiry worker as `paperless-sync` with no elevation. Minimise its
   capabilities, keep durable audit receipts and verify periodic backups.
6. The NAS receipt remains durable, so the same scan cannot be resent merely
   because it has disappeared from the inbox. A crash between temporary copy,
   fsync, target publish, archive journal commit and source removal must be
   recoverable by checking the source signature, target digest and journal,
   never by blindly repeating a deletion.
7. Purge after >=30 full days in quarantine must be a **separate, disabled-by-
   default** operation. It must require a verified recent successful backup
   on the configured target (covering rootfs and mp0) and a healthy timer,
   must refuse ambiguous/missing evidence, and never touch inbox files.
   Once enabled, preview the exact purge candidates before the first deletion.

## Required sender-journal change for reused scanner filenames

The current NAS sender keys a receipt by `(scope, basename)` and refuses a
different signature at the same path with `MANUAL_REVIEW_SOURCE_CHANGED`.
Once quarantine empties an input directory, scanners may legitimately create
another file such as `Gescanntes Dokument.pdf`. **Do not deploy automatic
quarantine before changing this rule.** Introduce an append-only, per-version
receipt identity using an unambiguous, validated source fingerprint including
SHA-256; retain old SENT journal entries for backward compatibility. Refuse
ambiguous/prepared outcomes, never overwrite prior receipts, and add regression
tests for identical names across multiple successive imports, replay, modified
content and crash recovery.

Also verify the future archiver's month rollover provisioning and privacy
boundary: existing NAS scanner folders may have Synology-specific ACLs, while
the private sync-user-owned quarantine must not inherit an unintended shared ACL.
A new LDAP home requires per-home safe provision and explicit Paperless
workflow/ACL activation before its scope may be monitored.

## Threats/tests to cover before deployment

- Wrong owner/group or privacy ACL, missing active-user visibility, digest
  mismatch, missing or forged receipt, PREPARED/SUBMITTED/PENDING state.
- Replaced/edited source since SENT, symlinks, multiple hardlinks, invalid
  input path, directory traversal, unsafe file permissions, mount loss.
- Interrupted copy or rename, destination already exists, cross-device
  rename, repeated acknowledgement, partial receipt write.
- Unexpected Paperless downtime or failed daily backup: *do not purge*.
- New scans arriving while archiving: sender lock and journal invariants hold.
- Manual NAS recovery from quarantine remains possible for 30 days.

## Current status / deployment gate

On 2026-10-14 the live sender completed startup with `SYNC_END STARTUP rc=0`.
Nine Paperless documents (IDs 5-13) were imported; IDs 10-13 underwent a
fresh successful live ACL and SHA-256 audit. **No NAS archival or purge
mechanism is deployed yet.** Do not infer that this design document activates
it. Implement, test in dry-run and deploy the archive stage separately;
enable automatic expiry only after backup verification.

## Archivierungs-Preflight (nur lesend)

Vor der Archivverschiebung den Zustand des NAS, die Quellverzeichnisse und
die bisherigen Sender-Receipts untersuchen:

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-synology-archive.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Der Audit wird als eingeschränkter `paperless-sync`-Benutzer auf der Synology
ausgeführt und schreibt **nichts**. Er kontrolliert:

- Eigentümer und Modi der privaten Archiv-/Statusverzeichnisse
- identisches Dateisystem für eine atomare `rename`-Operation je Scope
- bisherige `PREPARED`-/`SENT`-Journale und ersetzte Scans mit gleichem Namen
- manuellen DSM-ACL-Prüfbedarf für `delete-child` und Umbenennung

**Absichtlich immer blockiert:** Die bisherigen Sender-Receipts verwenden
`SHA256(scope + NUL + basename)` und können wiederverwendete Scannamen
noch nicht sicher versionieren. Vor einem produktiven Archiver müssen
Sender-Journal, Importnachweis, Archivjournal und Crash-Recovery gemeinsam
umgesetzt und mit Regressionstests geprüft werden.

Auch bei positivem Preflight wird dadurch kein Archivdienst aktiviert.


## Staging 2026-10-14: versionierte Quittungen und alternative Archivorte

Der Synology-Sender bleibt **unverändert**. Die neue Hilfsdatei
`synology_receipt_versions.py` definiert ausschließlich eine zukünftige
`v2-<sha256>.json`-Identität, gebunden an Scope, Dateiname, SHA-256 und
NAS-Dateisignatur. Sie schreibt keine Quittungen und wird vom aktiven Sender
noch nicht importiert. Die vorhandenen v1-Quittungen bleiben unangetastet.
Die Tests prüfen Namenswiederholung, identischen Inhalt mit neuer Datei,
PREPARED-Sperre, Replay und ungültige Pfade. Solange ein belastbarer
ARCHIVED-Nachweis fehlt, blockiert die Policy eine neue Inkarnation unter
bereits verwendeten Dateinamen.

**Noch offen:** Der rsync-Zielname muss ebenfalls pro Datei-Inkarnation
eindeutig sein; allein eine neue Journal-ID verhindert keine Kollision mit
`--ignore-existing`. Identische Inhalte können von Paperless als Duplikat
abgelehnt werden und benötigen eine eigene bestätigte Entscheidung. Eine
Migration oder produktive Aktivierung der v2-Logik ist noch nicht erfolgt.

Die bisherige Quarantäne unter `state_parent/paperless-archive` liegt laut
Preflight auf einem anderen Dateisystem als alle vier Scan-Eingänge.
Als Alternative wird ein versteckter, nicht überwachter Unterordner
`.paperless-archive` **innerhalb jedes Scan-Eingangs** untersucht.
Der aktuelle inotify-Watcher überwacht nur die konfigurierten Eingangsordner,
nicht rekursiv; der Sender ignoriert Unterverzeichnisse. Eine gleichnamige
versteckte Archivablage wird damit nicht automatisch erneut importiert.
Die Zielverzeichnisse sind noch nicht angelegt.

Read-only-Mount-/Berechtigungsprüfung:

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-synology-same-volume.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Der Audit meldet Gerätekennung, Eigentümer, Modus und Zugriff des
`paperless-sync` auf den Eingangsordner sowie Existenz und Gerätekennung
einer eventuellen versteckten Quarantäne. Eine **fehlende** Quarantäne
ist keine Bestätigung gleicher Gerätekennung; erst nach kontrollierter
Bereitstellung kann dies geprüft werden. `os.access` ersetzt keine
DSM-ACL-Prüfung von Delete-Child/Rename. Das Audit verändert nichts.

**Freigabegates:** privates Archiv ohne ungewollte ACL-Vererbung,
gleiche Dateisystemkennung, gültige Live-Importnachweise,
durables Archivjournal und Crash-Recovery, v2-Sender und
rsync-Zielversionierung sowie sichere Backup-gesteuerte Aufbewahrung.

## Live evidence reconciliation and archive planning (2026-10-14)

The read-only `audit-paperless-archive-imports.yml` successfully matched **19
of 19** NAS `SENT` source PDFs to live Paperless `IMPORTED` document evidence:
7 Privat/thomas, 0 Privat/nadja, 7 Eltern, 5 Familie. The previously repaired
document 23 is included. The exporter rechecks live document SHA-256, owner,
group, direct grants and active-user effective visibility.

NAS `st_dev` values differ across Btrfs subvolumes despite the shared
`/volume1` mount: private scan inputs 47, shared scan inputs 1048641,
private quarantine 40. **No atomic cross-device rename is permitted.**
The existing private quarantine is
`/volume1/.bergen-platform-state/paperless-archive`; do not create
inheriting hidden archives inside scanner folders.

The evidence matcher now prints `PREVIEW_ARCHIVE_COPY` for each verified
sender receipt, using a deterministic `<scope>/<current UTC preview month>/<64-character
sender receipt ID>.pdf` target. The actual archive month and the start of
30-day retention must be persisted at successful archival, never derived from
`sent_at` or `reconciled_at`. This is **only a logical plan**: it does not
check live destination ACLs or write a file, and
`ARCHIVE_COPY_NOT_IMPLEMENTED` is always printed. Production archival
remains blocked until native DSM archive ACL verification, crash-safe
cross-subvolume copy journal, replay recovery, versioned sender receipts and
collision-safe receiver filenames are implemented and tested. Expiry additionally
requires fresh backup health evidence. Do not run the old
`prepare-paperless-synology-archives.yml` as a fix for cross-device rename.

The 2026-10-14 preview run initially failed on a missing optional `sent_at`
field after 14 matches. No NAS or Paperless files were changed. The evidence
format was reverted to the original timestamp-independent schema. Sender
receipts repaired via live proof may use `reconciled_at` instead of `sent_at`;
neither field is needed for a logical archive target preview.

## Bewusst in Paperless gelöschte Importe (Dry-Run, 2026-10-14)

Dokument-ID 26 (`Privat/thomas`) wurde nach erfolgreichem Import bewusst
aus Paperless gelöscht. Das unveränderte Bridge-Journal zeigt weiterhin
`IMPORTED`, während die Live-Datenbankprüfung sowohl ID 26 als auch den
ursprünglichen Importdateinamen als nicht vorhanden meldet. Diese Situation
ist **kein** positiver Importnachweis und darf **keine** Archivierung oder
NAS-Quelllöschung freigeben.

`preview-paperless-deleted-import.yml` prüft ausschließlich lesend:

1. Das ursprüngliche Bridge-Receipt gehört zur ausdrücklich bestätigten
   Dokument-ID und enthält `IMPORTED`.
2. Die Live-Paperless-Datenbank enthält weder diese ID noch den ursprünglichen
   Importdateinamen. Eine fehlgeschlagene ACL-/Checksum-Prüfung wird nicht
   als Löschbeweis akzeptiert.
3. Die ursprüngliche NAS-Datei und ihr `SENT`-Receipt werden unter dem
   bestehenden Sender-Lock anhand Signatur und SHA-256 erneut geprüft.
4. Eine reine Policy-Funktion verbindet beide Belege und gibt ausschließlich
   `PREVIEW_DELETED_IN_PAPERLESS`, `EXCLUDED_FROM_ARCHIVE_MATCH_READY`
   und `NO_FILES_CHANGED` aus.

Die Entscheidung `DELETED_IN_PAPERLESS` ist **noch nicht im Journal
persistiert**; die aktive Sender-/Receiver-Logik wird nicht verändert.
Der vorhandene Sender-Receipt blockiert weiterhin das erneute Senden
derselben unveränderten Dateiversion. Die bisherige reguläre
`audit-paperless-archive-imports.yml`-Prüfung bleibt bei gelöschtem
Dokument absichtlich fehlgeschlagen. Eine künftige dauerhaft dokumentierte
Löschentscheidung muss versioniert und unveränderlich an
Sender-Receipt, Bridge-Receipt, SHA-256 und Dokument-ID gebunden sein,
bevor die Archivpipeline sie berücksichtigen darf. Sie darf weder
Reimport noch Archivierung oder Löschung des NAS-Originals auslösen.

Read-only-Aufruf (Vault und lokale NAS-Variablen erforderlich):

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/preview-paperless-deleted-import.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

### Separates Löschentscheidungsjournal – Implementierungsvorbereitung

`ansible/files/paperless/deleted_import_decision_journal.py` stellt eine
**offline-only** Bibliothek bereit. Es gibt bewusst **keinen CLI-Einstieg,
keinen produktiven Journalpfad und keine Ansible-Einbindung**. Das
Journalformat Version 1 bindet `DELETED_IN_PAPERLESS` an Dokument-ID,
Bridge-Receipt-ID, Sender-Receipt-ID, Quell-Scope, NAS-Dateiname,
Receiver-Quelle und SHA-256. Hinzu kommen explizite Bestätigung
(`confirmed_by`), UTC-Bestätigungszeit (`confirmed_at`) und der Grund
`explicit_user_deletion`.

Der deterministische `event_id` wird aus Dokument-ID, Bridge-Receipt-ID,
Sender-Receipt-ID und SHA-256 gebildet. Eine abweichende zweite Bestätigung
mit derselben Identität wird nicht überschrieben, sondern als Konflikt
abgewiesen. Die Publikation verwendet eine 0600-Temporärdatei,
`fsync` auf deren Inhalt, einen atomaren Hardlink ohne Überschreiben und
`fsync` des 0700-Journalverzeichnisses. Ein bereits vorhandener
byteidentischer Eintrag ist idempotent. Nach einem Absturz kann eine
`.decision-*.tmp`-Datei übrig bleiben; sie erfordert kontrollierte
Bereinigung, ohne bestehende Journaldateien zu verändern.

**Wichtig:** Dies ist nur ein vorbereiteter append-only Mechanismus,
keine unveränderliche/WORM-Speicherung. Ein privilegierter Administrator
könnte Journaldateien weiterhin ändern. Eine spätere Produktivintegration
muss unmittelbar vor der Journalerstellung die Herkunft und Aktualität
der NAS-/Paperless-Nachweise erneut prüfen, die Entscheidung
autorisieren, den Journalpfad mit Backup- und Zugriffsschutz festlegen
und eine Revisions-/Recoverystrategie definieren. Der Status ist noch
nicht persistiert; der reguläre Archivabgleich bleibt absichtlich
fail-closed und die NAS-Originaldatei bleibt erhalten.

Offline-Regressionstests:

```bash
python3 -m unittest discover \
  -s tests \
  -p 'test_paperless_deleted_import_decision_journal.py' -v
```

### Bewusste Löschung auf beiden Seiten: `DELETED_BY_USER` (nur Vorschau)

Bei Dokument 26 (`Privat/thomas/Gebuehren 2.pdf`) hat der Nutzer die
Löschung in Paperless **und** auf der Synology ausdrücklich bestätigt.
Die vorherige Vorschau `preview-paperless-deleted-import.yml` verlangt
noch eine vorhandene NAS-Quelldatei und ist dafür ungeeignet.

`preview-paperless-deleted-by-user.yml` prüft rein lesend:

1. Paperless: historischer Bridge-Receipt `IMPORTED`, zugehörige
   Dokument-ID und ursprünglicher Importdateiname aktuell nicht vorhanden.
2. Synology: unter dem Sender-Lock existiert das Original **nicht**;
   das reguläre `SENT`-Receipt existiert unverändert, ist restriktiv
   geschützt und enthält die historische Prüfsumme, Quelldatei und
   Empfängerkennung. Der Receipt-Schlüssel wird nach
   `SHA256(scope + NUL + filename)` gegengeprüft.
3. Lokal: beide Nachweise müssen in Scope, Empfängerkennung, SHA-256
   und den ausdrücklich bestätigten IDs übereinstimmen.

Die Ausgabe `PREVIEW_DELETED_BY_USER` ist **kein persistierter
Journalstatus**, kein Nachweis, *wer* die Dateien technisch gelöscht
hat, und keine Archivierungsfreigabe. Abwesenheit wird nur zum
Prüfzeitpunkt festgestellt. Sender- und Bridge-Receipt werden nicht
verändert. Wiederimport, Wiederherstellung, Archivkopie und
Quelllöschung sind nicht Bestandteil dieser Vorschau.

```bash
python3 -m unittest discover \
  -s tests \
  -p 'test_paperless_deleted_by_user_policy.py' -v

ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/preview-paperless-deleted-by-user.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Das bestehende offline-only Journalmodul kennt weiterhin nur
`DELETED_IN_PAPERLESS`. `DELETED_BY_USER` darf nicht durch bloßes
Umbenennen des bestehenden Ereignistyps gespeichert werden: Zunächst
sind ein separates Schema, Nachweisbindung, Tests und die Freigabe
einer produktiven Integration erforderlich. Der bisherige
Archivabgleich bleibt fail-closed.

### Journalentwurf für `DELETED_BY_USER` – ausschließlich Dry-Run

`ansible/files/paperless/deleted_by_user_decision_journal.py` definiert
ein **separates Schema v2** für den ausdrücklich bestätigten beidseitigen
Löschfall von Dokument 26. Das frühere v1-Journal für
`DELETED_IN_PAPERLESS` bleibt unverändert. Der neue Entwurf enthält
die historischen Sender-/Bridge-IDs, den SHA-256, Quell- und
Empfängerkennung, die zwei geprüften Abwesenheitszustände und die
explizite Nutzerbestätigung vom 14.10.2026. Ein domänenseparierter
`event_id` wird aus der historischen Dokumentidentität abgeleitet.

Der bestehende Live-Dry-Run
`ansible/playbooks/preview-paperless-deleted-by-user.yml` führt
zusätzlich eine **rein lesende Journalvorschau** aus. Sie gibt den
vorgeschlagenen Dateinamen, SHA-256 des kanonischen JSON-Inhalts
und den vollständigen JSON-Entwurf aus. Die Ausgabe
`NO_JOURNAL_WRITTEN` bestätigt, dass der Entwurf nicht persistiert
wird. Es gibt **keinen** produktiven Writer, kein automatisch
erzeugtes Journalverzeichnis, keinen neuen Sender-/Receiver-Code und
keine Freigabe für Wiederimport oder Archivierung.

Regressionstests:

```bash
python3 -m unittest discover \
  -s tests \
  -p 'test_paperless_deleted_by_user_decision_journal.py' -v
```

Eine spätere echte Persistierung benötigt eine ausdrücklich
freigegebene sichere Speicherposition, erneute Live-Nachweise,
separat geprüfte atomare Schreiblogik und den versionierten
Sender-/Empfänger-Lebenszyklus. Ein erneuter Scan mit demselben
Dateinamen wird durch diese Vorschau **nicht** automatisch
freigegeben; der bestehende Sender blockiert abweichende Signaturen
weiterhin fail-closed.

### Persistenzbaustein v2: atomarer Writer (noch nicht aktiviert)

Der separate Offline-Baustein
`ansible/files/paperless/deleted_by_user_decision_store.py`
stellt `publish_once(directory, record)` bereit. Er hat **keinen
CLI-Einstiegspunkt, keine produktiven Pfadvorgaben und keinen Aufruf
durch Ansible**. Er schreibt nur in ein bereits vorhandenes absolutes
Verzeichnis, das dem ausführenden Benutzer gehört und Modus `0700`
besitzt; es werden keine Verzeichnisse angelegt. Das kanonische
v2-JSON wird in einer privaten `0600`-Temporärdatei geschrieben,
`fsync`-gesichert, durch atomaren Hardlink **ohne Überschreiben**
veröffentlicht und anschließend per Verzeichnis-`fsync` gesichert.
Nur die selbst angelegte Temporärdatei wird entfernt.

Ein erneuter Aufruf mit identischem Inhalt ist idempotent; ein
abweichender, unsicherer oder symbolisch verlinkter Eintrag wird
abgewiesen. Bei einem simulierten Absturz vor Veröffentlichung darf
kein publizierter Eintrag entstehen; bei einem Fehler nach der
Veröffentlichung muss der Retry den vorhandenen Eintrag unverändert
akzeptieren. Fremde verwaiste Temporärdateien werden nicht automatisch
entfernt.

```bash
python3 -m unittest discover \
  -s tests \
  -p 'test_paperless_deleted_by_user_decision_store.py' -v
```

**Speicherort noch offen:** bevorzugt ein gesondertes privates
persistentes Verzeichnis auf dem Paperless-LXC-Dateisystem, dessen
Einbindung in die Proxmox-Sicherung und Restore-Praxis vorher
nachgewiesen wird. Nicht stillschweigend das Synology-Verzeichnis
`/volume1/.bergen-platform-state` verwenden: DSM-Unterstützung,
Subvolume-/ACL-Grenzen und Sicherung sind dafür nicht abschließend
geprüft. Der Writer benötigt vor produktivem Einsatz eine gesonderte
Freigabe, einen verifizierten Dienstbenutzer, frische Live-Beweise,
die explizite Nutzerentscheidung und eine Freigabe für den
tatsächlichen Schreibvorgang. Kein automatisches Archivieren,
Wiederimportieren, Wiederherstellen oder Entsperren wiederverwendeter
Dateinamen.

### Geplante Journalverzeichnis-Anlage (getrennte Freigabe)

Der read-only Audit vom 14.10.2026 hat bestätigt:
LXC 126 `bergen-paperless`, ZFS-Rootfs
`rpool/data/subvol-126-disk-0`,
`/var/lib/paperless-ingest` als `root:988` mit `0750`,
`paperless-ingest` als UID 997/GID 988. Das vorgesehene
Unterverzeichnis `deletion-decisions` war nicht vorhanden.
Das erfolgreiche `vzdump` vom 14.10.2026 um 03:00
enthielt `rootfs` und `mp0` und ging nach
`bergen-synology-backup`. Ein Restore des späteren Journals
ist damit noch nicht nachgewiesen.

Zwei separate Ansible-Playbooks verwenden denselben eng
begrenzten, über stdin ausgeführten Python-Helfer:
`plan-paperless-deletion-journal-directory.yml` ist
**rein lesend** und prüft Identität, Mount und
Verzeichnisrechte. Das zweite
`create-paperless-deletion-journal-directory.yml` benötigt
eine **zusätzliche explizite Freigabevariable** und darf erst
nach separater Benutzerzustimmung ausgeführt werden. Es legt
ausschließlich `/var/lib/paperless-ingest/deletion-decisions`
als UID 997/GID 988, Modus `0700` an. Bestehende
abweichende Verzeichnisse werden nicht repariert oder
überschrieben. Ein Journal wird dadurch **nicht** angelegt.

Offline-Test:
```bash
python3 -m unittest discover -s tests -p 'test_paperless_deletion_journal_directory.py' -v
```

Read-only Preflight:
```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/plan-paperless-deletion-journal-directory.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Die Schreiboperation ist bewusst **nicht** Bestandteil des
Preflight-Kommandos. Die notwendige Freigabe für die
Verzeichnisanlage ist unabhängig von einer späteren
Freigabe zur Speicherung des Löschentscheids.

### Löschjournal v2 – produktionsnaher Dry-Run ohne Schreiben

Nach gesonderter Freigabe wurde das private Verzeichnis
`/var/lib/paperless-ingest/deletion-decisions` in LXC 126
als UID 997/GID 988, Modus `0700`, erstellt und vom
Ansible-Playbook verifiziert (`CREATED_AND_VERIFIED`,
`NO_JOURNAL_WRITTEN`, `NO_RECEIPTS_CHANGED`).
Die Verzeichnisfreigabe **umfasst nicht** die Freigabe zur
Speicherung eines Löschentscheids.

`plan-paperless-deleted-by-user-journal.yml` ist ein
rein lesender Ende-zu-Ende-Preflight für genau Dokument 26.
Es prüft erneut das Fehlen des Paperless-Dokuments,
den historischen NAS-`SENT`-Receipt unter Sender-Lock
und das Fehlen der NAS-Quelldatei. Die Policy und
v2-Journalschema werden auf dem Controller validiert.
Der anschließende Gast-Preflight läuft **als**
`paperless-ingest` (nicht root) und kontrolliert die
private Verzeichnisablage und den konkreten
Zielnamen. Erwartet:
`READY_TO_PUBLISH` (oder bei exakt identischem
Bestand `ALREADY_IDENTICAL`),
`JOURNAL_DIRECTORY_PRIVATE_VERIFIED`,
`NO_JOURNAL_WRITTEN`, `NO_RECEIPTS_CHANGED`,
`NO_FILES_CHANGED`; Ansible `changed=0`.

```bash
python3 -m unittest discover -s tests -p 'test_paperless_deleted_by_user_journal_target.py' -v
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/plan-paperless-deleted-by-user-journal.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Der Dry-Run schreibt weder Journal noch Receipt, verändert
keine Originale und autorisiert keine Archivierung.
Die tatsächliche atomare Veröffentlichung ist **nicht**
mit diesem Playbook verbunden und benötigt ein gesondertes
Approval mit erneuter frischer Beweiserhebung.

### Gesondert freizugebende Veröffentlichung des DELETED_BY_USER-Journals

Nach erfolgreichem Live-Dry-Run am 14.10.2026
(`READY_TO_PUBLISH`, `JOURNAL_DIRECTORY_PRIVATE_VERIFIED`,
`NO_FILES_CHANGED`, Ansible `changed=0`) ist die
separat gegatete Veröffentlichung vorbereitet.
**Die Ausführung ist noch nicht freigegeben.**

Das neue `publish-paperless-deleted-by-user-journal.yml`
verlangt die eigens dafür reservierte Ansible-Variable
`paperless_user_deletion_journal_apply_approved=true`.
Ohne sie bricht es vor jedem Schreibzugriff ab.
Das Verzeichnis-Approval ist nicht ausreichend.
Es prüft erneut Paperless-Dokument-ID 26, den historischen
NAS-`SENT`-Receipt unter Lock und die Abwesenheit
der NAS-Quelle, vergleicht beide frischen Proofs
mit dem Preflight und validiert die unabhängige
Deletion-Policy. Erst danach läuft der Publisher im
LXC **als `paperless-ingest`**, nicht root.

Der Publisher verwendet die geprüfte v2-Schemafunktion
und den offline crashgetesteten atomaren
`publish_once`-Store. Erwarteter fixer Event-ID:
`f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26`.
Erwarteter SHA-256 des kanonischen JSON:
`5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a`.
Die Journaldatei erhält Modus `0600`, wird
atomar ohne Überschreiben veröffentlicht und anschließend
byteweise überprüft. Bei identischem Bestand
ist der Vorgang idempotent. Historische Receipts,
Paperless-Dokumente und NAS-Originale werden nicht verändert.
Der Eintrag erteilt **keine** Archivierungsfreigabe und
keine Erlaubnis zum Reimport.

Offline-Tests für das Apply-Gate, **ohne Ausführung**:
```bash
python3 -m unittest discover -s tests -p 'test_paperless_deleted_by_user_journal_publication.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_deleted_by_user_decision_store.py' -v
```

Zur erneuten **rein lesenden** Live-Prüfung weiterhin:
`ansible/playbooks/plan-paperless-deleted-by-user-journal.yml`.

Der produktive Apply-Aufruf wird erst nach separater,
auf Dokument 26 bezogener Freigabe kommuniziert.

### Read-only Import-Lifecycle-Audit mit DELETED_BY_USER (14.10.2026)

Die vom Benutzer gesondert freigegebene atomare Veröffentlichung
für Dokument 26 wurde produktiv ausgeführt:
`JOURNAL_CREATED_AND_VERIFIED`,
`NO_RECEIPTS_CHANGED`,
`NO_REIMPORT_OR_RESTORE`,
`NO_ARCHIVE_AUTHORIZATION`;
Ansible `ok=22 changed=1 failed=0`.
Die private v2-Datei liegt unter
`/var/lib/paperless-ingest/deletion-decisions/`,
Event-ID
`f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26`,
kanonischer SHA-256
`5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a`.

**Neu, noch nicht live getestet:** Das unabhängige,
rein lesende Playbook
`ansible/playbooks/audit-paperless-import-lifecycle.yml`.
Es liest die gespeicherte v2-Entscheidung als
`paperless-ingest` und prüft Eigentümer, private
Berechtigungen, Linkzahl und die fixierte SHA-256.
Es überprüft erneut das Fehlen von Dokument 26 in
Paperless und des NAS-Originals unter Sender-Lock.
Die NAS-Inventur prüft weiterhin alle vorhandenen
Originale gegen `SENT`-Receipts und SHA-256.
Ein eigener Gast-Exporter validiert alle anderen
`IMPORTED`-Receipts weiterhin mit der vollständigen
live-Dokument-, Owner-, Gruppen- und effektiven ACL-Prüfung;
für genau Dokument 26 akzeptiert er den Zustand
`DELETED_BY_USER` **nur** bei passender Journal-Identität
und erneutem Live-Abwesenheitsnachweis (Dokument-ID
und Originaldateiname). Jeder andere fehlende oder
abweichende Import bleibt ein Fehler.

Der abschließende reine Matcher verlangt eine vollständige
1:1-Zuordnung aller noch vorhandenen NAS-Originale zu
live-verifizierten Imports und genau einen
journalbestätigten Löschfall. Erwartete Marker:
`DELETED_BY_USER_CONFIRMED 26`,
`IMPORT_LIFECYCLE_RECONCILED`,
`ARCHIVE_NOT_AUTHORIZED`,
`NO_RECEIPTS_CHANGED`,
`NO_FILES_CHANGED`.
Er erteilt **keine** Freigabe für Quarantäne,
Archivierung, Receipt-Statusänderung, Wiederimport oder
Dateinamen-Recycling.

```bash
python3 -m unittest discover -s tests -p 'test_paperless_import_lifecycle.py' -v
ansible-playbook --syntax-check \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-import-lifecycle.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-import-lifecycle.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Das bisherige strengere
`audit-paperless-archive-imports.yml` bleibt
**unverändert**: Ein fehlendes live-Dokument blockiert
dort weiterhin die Archiveignung. Der neue Audit ist
eine eigenständige Reconciliation-Sicht, kein
Ersatz für spätere Archive-Sicherheitsgates.

### Live-Audit 14.10.2026: zweiter ungeklärter Import

Die 18 Offline-Tests des Import-Lifecycle-Audits sind bestanden.
Die erste produktive read-only Ausführung ist mit
`LIVE_IMPORT_VERIFICATION_FAILED 7a92b91deb7b2e8e35f9f710.json`
abgebrochen (`changed=0`). Die Prüfung der gespeicherten
Benutzerlöschung 26, des privaten Journals und der NAS-Inventur
war bis dahin erfolgreich. Für den zweiten Receipt wurde
**keine** weitere Benutzerlöschung unterstellt.

Das neue rein lesende
`ansible/playbooks/diagnose-paperless-import-7a92.yml`
liest genau diesen historischen IMPORTED-Receipt über den
bestehenden Reconciler, überprüft die ursprüngliche
Dokument-ID und vergleicht bei vorhandenen Dokumenten
Originaldateiname, Prüfsumme, Eigentümer und Seitenzahl.
Bei umbenanntem Dateinamen wird die vollständige effektive
ACL-Verifikation erneut mit dem tatsächlichen Dateinamen
versucht. Ergebnis ist ausschließlich eine Diagnose, keine
Receipt- oder Dokumentänderung.

```bash
python3 -m unittest discover -s tests -p 'test_paperless_import_7a92_diagnostic.py' -v
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/diagnose-paperless-import-7a92.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Die Import-Lifecycle-Reconciliation bleibt bis zur
Klärung dieses zweiten Receipts fail-closed.

### Zweite explizite Benutzerlöschung: Dokument 15 (read-only Preflight)

Der Benutzer hat am 14.10.2026 bestätigt, dass auch
Dokument 15 bewusst aus Paperless und die entsprechende
Quelldatei von der Synology gelöscht wurden. Der Bridge-Receipt
`7a92b91deb7b2e8e35f9f710.json` bleibt historisch
`IMPORTED`; die Live-Diagnose zeigte `DOCUMENT_EXISTS False`
und `EXPECTED_FILENAME_EXISTS False`.
Diese Erklärung ist **keine Freigabe zum Schreiben eines zweiten Journals**.

Das neue rein lesende Playbook
`ansible/playbooks/preview-paperless-deleted-import-15.yml`
prüft die Abwesenheit in Paperless über die bestehende
Exporter-Logik und sucht unter exklusivem Sender-Lock den
historischen NAS-Sender-Receipt **anhand von Zielpfad und
SHA-256**, ohne den möglicherweise normalisierten Scan-Dateinamen
zu erraten. Es prüft dessen Identität, `SENT`-Status,
Signatur, Quelle, Pfadschlüssel und Abwesenheit des Originals.
Ein unabhängiger Matcher bestätigt die Übereinstimmung beider
Seiten. Alle Schritte sind read-only; weder Journal noch
Receipts, NAS-Originale oder Dokumente werden geändert.
Ein Journal-Schema oder produktiver Writer für Dokument 15
ist noch nicht eingerichtet. Bis zur vollständigen gesonderten
Journalisierung bleibt die Lifecycle-Reconciliation
fail-closed.

```bash
python3 -m unittest discover -s tests -p 'test_paperless_deleted_import_15.py' -v
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/preview-paperless-deleted-import-15.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

#### Live-Ergebnis für Dokument 15

Am 14.10.2026 wurde der rein lesende NAS-/Paperless-Preflight
erfolgreich ausgeführt: `ok=8 changed=0 failed=0`.
Ermittelte historische NAS-Quelldatei:
`Privat/thomas/Gebuehren.pdf`,
Sender-Receipt:
`adbbbd6b2ca9b6189da559a5e4d303e03eed2cb2403efaf14d343d02fd042b53.json`,
SHA-256:
`bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c`.
Sowohl NAS-Original als auch Paperless-Dokument 15 und dessen
ursprünglicher Dateiname sind aktuell nicht vorhanden.
Die Prüfsumme ist identisch zu Dokument 26 (`Gebuehren 2.pdf`);
die getrennten Sender- und Bridge-Receipts bleiben jedoch
unabhängige historische Identitäten.

Der erste Lauf der 13 Offline-Tests ergab 12 Erfolge und einen
Testfehler wegen einer uneinheitlichen Fehlermeldung bei fehlendem
NAS-`NO_FILES_CHANGED`-Marker. Der Matcher verweigerte den
fehlenden Marker bereits korrekt; die Meldung wurde auf
`NAS_READ_ONLY_MARKER_MISSING` vereinheitlicht. Erneuter
Testlauf ist noch ausstehend.

Es existiert weiterhin **kein zweiter Journaleintrag für
Dokument 15**. Keine Reimport-, Wiederherstellungs-, Lösch-
oder Archivierungsfreigabe.

### Dry-run für zweiten DELETED_BY_USER-v2-Eintrag (Dokument 15)

Für die zweite bestätigte Benutzerlöschung wurde ein **eigenständiges,
noch nicht live getestetes read-only Journal-Planungsplaybook**
`ansible/playbooks/plan-paperless-deleted-by-user-15-journal.yml`
ergänzt. Es wiederholt die aktuellen Abwesenheitsnachweise
in Paperless und auf der Synology, verifiziert den historischen
SENT-Receipt und gleicht beide Beweise unabhängig ab.
Ein separates v2-Schema für Dokument 15 fixiert Dokument-ID,
Sender- und Bridge-Receipt, Scan-Dateinamen, Prüfsumme,
Bestätigungsdatum und Löschgrund. Der Plan prüft das private
Journal-Verzeichnis als `paperless-ingest` (UID 997, GID 988)
und verlangt, dass der neue Zieldateiname **noch nicht existiert**.
Der bisherige Journaleintrag für Dokument 26 wird unabhängig
rein lesend erneut geprüft.

Vorgesehener neuer Event:
`2a6d73664436c1a3e0432d7a07911feab86ba2a617a185b81bc30580fdd67e90`,
vorgesehener kanonischer JSON-SHA-256:
`7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b`.
Der gemeinsame Inhalts-SHA-256 von Dokument 15 und 26
ändert **nicht** deren getrennte Event-Identitäten.

```bash
python3 -m unittest discover -s tests -p 'test_paperless_deleted_by_user_15_journal_plan.py' -v
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/plan-paperless-deleted-by-user-15-journal.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Die Dry-run-Ausgabe enthält `READY_TO_PUBLISH`,
`JOURNAL_DIRECTORY_PRIVATE_VERIFIED`,
`DOCUMENT_26_JOURNAL_INTACT` und `NO_JOURNAL_WRITTEN`.
Es gibt weiterhin **keine** produktive Schreibintegration,
keine Freigabe für die zweite Journal-Publikation und
keine Archivierungs- oder Reimportfreigabe.
