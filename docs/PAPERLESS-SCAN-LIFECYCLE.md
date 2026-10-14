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
