# Bergen Platform – Paperless checkpoint (15.10.2026)

**Status:** dokumentierter Entwicklungsstand auf `feat/paperless-ingest-bridge-20261014`, **kein produktiv freigegebenes Archivierungs- oder Löschverfahren**. Dieser Stand ist eine Dokumentations- und Reconciliation-Baseline, keine automatische Aktivierung neuer Funktionen und kein vollständiges Release der Plattform.

## Architektur und Verantwortungsgrenzen

- `bp-controller` (LXC 100): Ansible-Steuerung, Vault und Git-Arbeitskopie.
- `venombox`: Proxmox-Host; `bergen-paperless` (LXC 126) verarbeitet Dokumente.
- Synology: Scan-Eingänge `Privat/thomas`, `Privat/nadja`, `Eltern`, `Familie`; dedizierter `paperless-sync`-Sender.
- NAS → LXC: eingeschränkter, copy-only rsync-Transport. Der Sender dokumentiert `SENT`, der Import-Bridge-Nachweis `IMPORTED` nach Prüfung des lebenden Paperless-Dokuments und seiner Zugriffsrechte.
- `bergen-ai` (LXC 110) und `bergen-proxy` (LXC 125) laufen laut `pct list` am 14.10.2026. Daraus folgt **keine** bestätigte Ollama-API-, Modell-, Proxy- oder Paperless-KI-Integration.
- Alle LXC 100, 110, 120–126, 131 und 141–143 waren bei der zuletzt mitgeteilten `pct list`-Abfrage `running`; das ist ein Laufzeitstatus, kein Ende-zu-Ende-Funktionstest.

## Abgenommene Import-Reconciliation

Am 14.10.2026 wurde das **lesende** Playbook
`ansible/playbooks/audit-paperless-import-lifecycle-15-26.yml`
auf `venombox` ausgeführt: `ok=14 changed=0 unreachable=0 failed=0`.

Ergebnis:

| Scope | Live importiert | NAS-SENT bestätigt |
| --- | ---: | ---: |
| Privat/thomas | 5 | 5 |
| Privat/nadja | 0 | 0 |
| Eltern | 7 | 7 |
| Familie | 5 | 5 |
| **Summe** | **17** | **17** |

Zwei separat nachgewiesene bewusste Benutzerlöschungen: Dokument 15 (`Gebuehren.pdf`) und Dokument 26 (`Gebuehren 2.pdf`), jeweils in Paperless und am NAS abwesend. Beide Dateien hatten **denselben Inhaltshash**, jedoch **unterschiedliche Dokument- und Receipt-Identitäten**. Für beide wurden gesonderte, kanonisch SHA-256-geprüfte `DELETED_BY_USER`-v2-Journale unter `/var/lib/paperless-ingest/deletion-decisions/` veröffentlicht. Weder die historischen Sender- noch die Bridge-Receipts wurden dabei geändert.

Abschlussmarker: `DELETED_BY_USER 2`, `IMPORT_LIFECYCLE_RECONCILED`, `ARCHIVE_NOT_AUTHORIZED`, `NO_RECEIPTS_CHANGED`, `NO_FILES_CHANGED`.

**Achtung:** `audit-paperless-import-lifecycle.yml` ist die ältere Ein-Journal-Variante für Dokument 26 und bildet den aktuellen Zustand nicht vollständig ab. Für diesen Checkpoint das Playbook mit Suffix `-15-26` verwenden. Auch dessen erfolgreicher Lauf berechtigt nicht zur Archivierung.

## Backup- und Recovery-Stand

- Historischer Nachweis: erfolgreicher `vzdump`-Task für LXC 126 vom 14.10.2026, ca. 03:02:54 MESZ, vor der zweiten Journalveröffentlichung.
- **Neuer Nachweis aus dem Proxmox-Tasklog:** LXC 126 (`bergen-paperless`) wurde am **15.10.2026 um 03:00:12 MESZ** im Modus `stop` auf Storage `bergen-synology-backup` gesichert. `rootfs` (`/`) **und** `mp0` (`/srv/bergen-paperless`) wurden laut Log eingeschlossen.
- Gemeldeter Archivpfad: `/mnt/pve/bergen-synology-backup/dump/vzdump-lxc-126-2026_10_15-03_00_12.tar.zst`. Log: 4.597.626.880 Byte geschrieben (4,3 GiB), Archivgröße 1,39 GB; Wiederanlauf des Containers nach 183 Sekunden; Backupende **03:03:15 MESZ**, `Backup job finished successfully`, `TASK OK`.
- Der erfolgreiche Task liegt **nach** der Veröffentlichung beider `DELETED_BY_USER`-Journale am 14.10.2026 gegen 21:45 MESZ. Die frühere Lücke „kein zeitlich nachfolgender Backup-Task“ ist damit geschlossen. **Ob beide Journaldateien im Archiv enthalten, lesbar und wiederherstellbar sind, wurde noch nicht anhand des Archivinhalts oder eines Restore-Tests nachgewiesen.** Ein Tasklog allein bestätigt auch nicht die heutige Existenz der Archivdatei.
- Backup-Pruning laut Log: `keep-daily=7,keep-monthly=12,keep-weekly=4`; bei diesem Lauf `pruned 0 backup(s)`.
- Vor jeder zukünftigen Original-Löschung/Retention-Freigabe: Existenz und technische Lesbarkeit der konkreten Archivdatei, tatsächlichen Einschluss der Journale, ggf. Ausschlüsse/Binds und isolierte Wiederherstellbarkeit kontrollieren. Ein früherer isolierter Paperless-Restore ersetzt den Test mit dem aktuellen Backup nicht.

## Offene Punkte – bewusst zurückgestellt

1. **Archivierung/Purge (blockiert):** Synology-ACLs und sichere Quarantäne, Cross-Btrfs-Subvolume-Copy statt `rename` (`EXDEV`), Hash/fsync, atomare Journale, Replay-/Crash-Recovery, getrennt autorisierte Originaldatei-Entfernung und zeitgesteuerte Löschung.
2. **Sender-Versionierung (blockiert):** v1-Receipt-Schlüssel basieren auf Scope und Dateiname; Wiederverwendung eines Scannamens und `rsync --ignore-existing` erfordern eine vollständige v2-Inkarnations-/Zielnamenstrategie. Keine stillschweigende Receipt-Migration.
3. **Backup nach Journalpublikation:** erfolgreicher LXC-126-Backup-Task am 15.10.2026, 03:00–03:03 MESZ, **belegt**. Existenz/Lesbarkeit des konkreten Archivs, Journal-Einschluss und isolierte Restore-Evidenz weiterhin offen.
4. **Audit-Konsolidierung:** älteren Ein-Journal-Audit nicht als aktuellen Gesundheitscheck ausgeben; Migration/Deprecation erst mit Tests und expliziter Freigabe.
5. **Lokale, noch nicht versionierte Dateien:** Nach der allgemeinen `.gitignore`-Regel `*.local.yml` sind auf `bp-controller` zehn untracked Dateien übrig: neun Paperless-Python-/Ansible-Dateien und `ansible/group_vars/all/bergen-proxy.yml`. Die neun Paperless-Dateien wurden am 14./15.10.2026 als TAR.GZ aus einer E-Mail **statisch** geprüft, aber **nicht ausgeführt oder versioniert**. Das Proxy-YAML wurde nicht eingesehen und ist vor jeder Git-Aufnahme separat auf Geheimnisse und Standortdaten zu prüfen. Kritische Befunde und der Arbeitsplan stehen im [lokalen Code-Review](PAPERLESS-CODE-REVIEW-2026-10-15.md).
6. **KI/SSO/Berechtigungen:** keine bestätigte produktive, identitätsgebundene Paperless-KI-Suche; getrennten Designzweig `feat/paperless-ai-identity-bound-design-20261015` nicht ungeprüft in diesen Branch integrieren. Mandantentrennung, Benutzerkontext und Zugriffskontrolle vor Aktivierung testen.
7. **Ollama-Status:** die bislang gezeigte Terminalausgabe enthielt keine eindeutig auswertbare `ollama list`-/API-Antwort. Modelle, Version, Systemd-Konfiguration und Netzwerkgrenzen separat lesend prüfen.
8. **Dokumentation für Nachlass und Einsteiger:** Betriebs-, Wiederanlauf- und Geheimnis-Notfallblatt weiter vervollständigen; keine Kennwörter, Tokens oder privaten Schlüssel in Git/Wiki.

## Reproduzierbare read-only Kontrolle

Auf `bp-controller` nach Aktualisierung des Branches:

```bash
cd ~/bergen-platform
python3 -m unittest discover -s tests -p 'test_paperless_import_lifecycle_15_26.py' -v
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-import-lifecycle-15-26.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Der Ansible-Lauf muss `changed=0` ergeben; jeder unbekannte oder nicht belegte Löschfall muss **fail-closed** bleiben. Die Unit-Test-Ergebnisse sind erst nach tatsächlicher Ausführung als bestätigt zu dokumentieren.

## Versions- und Freigabepolitik

Aktuelle stabile Plattform-Version laut README/Changelog: **v0.9.2**. Dieser Paperless-Stand wird als **unreleased development checkpoint** geführt. Ein mögliches späteres Pre-Release-Tag (z. B. `v0.10.0-paperless.1`) ist **nicht erstellt**. Ein Release-Tag darf erst nach Review und Härtung der noch unversionierten Dateien, Prüfung auf Secrets, Testnachweisen, vollständigem Commit-Stand und bewusster Festlegung des Release-Scopes gesetzt werden. Der Dokumentations-Checkpoint ist über die jeweilige Git-Commit-SHA referenzierbar, nicht über ein Release-Tag.

Weitere Details und historische Freigaben: [Paperless Scan Lifecycle](PAPERLESS-SCAN-LIFECYCLE.md).
