# Paperless: lokaler Code-Review und Entwicklungs-Freeze (15.10.2026)

**Status:** Statische Prüfung eines lokalen Quellcode-Archivs; **kein Testlauf, kein Deployment, keine Freigabe zur Archivierung oder Löschung**. Dieses Dokument versioniert die Review-Ergebnisse, nicht die neun lokalen Quelldateien. Verbindlicher technischer Referenzstand: Branch `feat/paperless-ingest-bridge-20261014`, mit der jeweils ausdrücklich genannten Commit-SHA. Die stabile Plattform-Version bleibt `v0.9.2`.

## Herkunft und Abgrenzung

Auf `bp-controller` wurden am 14.10.2026 zehn unversionierte Dateien festgestellt, alle `ansible:ansible`, Modus `0600`. Neun Python-/Ansible-Dateien wurden unter `/tmp/bergen-paperless-code-review.tar.gz` verpackt (5.298 Bytes) und am 14.10.2026 an das verbundene Gmail-Postfach gesendet. Der Anhang wurde statisch eingesehen; keine der neun Dateien wurde durch diesen Review auf einem Host ausgeführt.

Die zehnte unversionierte Datei, `ansible/group_vars/all/bergen-proxy.yml`, **war nicht im Archiv** und ist daher **inhaltlich nicht geprüft**. Lokale `*.local.yml`-Dateien sind durch die allgemeine Git-Regel ausgeschlossen; `git ls-files -- '*.local.yml'` war leer. Das bedeutet nicht, dass jede andere YAML-Datei automatisch für Git geeignet ist.

Der E-Mail-Anhang ist ein **Review-Beleg außerhalb von Git**, kein dauerhaftes oder verifiziert wiederherstellbares Source-Release. Sein SHA-256-Wert und der SHA-256 jedes lokalen Quelltexts müssen vor einer späteren Codeaufnahme auf dem Controller erfasst werden. Die neun Dateien bleiben bis zur Härtung ausdrücklich **unversioniert**.

## Architektur und Datenschutzgrenzen

- Quelle: Synology-Scan-Eingänge; Transport mit technischem `paperless-sync`-Benutzer; eingeschränkter rsync-Empfang in `bergen-paperless`.
- Eingangsscoping: private Bereiche pro Person, `Eltern` und `Familie`. Die Trennung ist sicherheitskritisch und darf nicht allein aus einem erfolgreichen Dateitransfer oder Pfadmatch abgeleitet werden.
- Die lesende, versionierte Import-Lifecycle-Reconciliation weist **17 Live-Importe und 2 gesonderte, bestätigte Benutzerlöschungen** nach. Details und Grenzen: [Checkpoint](PAPERLESS-CHECKPOINT-2026-10-15.md) und [Scan-Lifecycle](PAPERLESS-SCAN-LIFECYCLE.md).
- Die neun lokal verbliebenen Skripte sind historische/standortspezifische Installations- und Konfigurationswerkzeuge. Ihre Existenz auf dem Controller beweist weder einen heutigen Produktionszustand noch einen wiederholbar sicheren Rollout.

## Einzelprüfung der neun lokalen Dateien

| Datei | Statische Feststellung | Offene Abnahme |
| --- | --- | --- |
| `ansible/files/paperless/configure_ingest_workflows.py` | Transaktionale Erstellung von fünf Workflows; bricht bei unbekannten oder abweichenden Workflows ab; synthetische Pfadmatch-Tests. Admin-Catch-all matcht auch private/Eltern-/Familienpfade. | **Hoch:** effektive Eigentümer-, Gruppen- und Benutzer-Sichtbarkeit *nach allen Workflow-Aktionen* prüfen; Reihenfolge/Überschneidungen gegen die tatsächlich installierte Paperless-Version testen. Private Bereiche ohne eigene Regel dürfen nicht unbemerkt für Admin sichtbar werden. |
| `ansible/playbooks/authorize-paperless-rsync-key.yml` | `authorized_keys` mit `from=`, `restrict` und erzwungenem `rrsync`; bestehende Datei löst absichtlich STOP aus. Öffentlicher Schlüssel und NAS-IP sind fest eingebettet. | Schlüssel und Quellnetz als lokale Parameter auslagern; `rrsync`-Pfad/-Flags auf Zielhost prüfen; idempotente, konfliktbewusste Verwaltung und SSH-Validierung **vor** dauerhafter Änderung/mit Rückfallpfad. |
| `ansible/playbooks/configure-paperless-family-permissions.yml` | Ergänzt Gruppen-Modellrechte; vergleicht vor/nachher `permitted_document_ids` für drei Nutzer. Erwartet Dokument-IDs 2, 3, 4. | **Hoch:** keine produktive Freigabe mit festen Dokument-IDs; dynamische positive/negative Tests über alle Familienrollen und Dokumentklassen, einschließlich Kinderkonten und privaten Bereichen. Änderung wirkt auf Gruppe, nicht nur Testnutzer. |
| `ansible/playbooks/configure-paperless-ingest-workflows.yml` | Kopiert Workflow-Python nach `/etc/bergen-paperless` und führt Django-Shell aus. `changed_when` basiert auf `CREATED=0`. | Workflow-Semantik und Fehlerpfade offline/isoliert testen; erst danach freigeben. |
| `ansible/playbooks/enable-paperless-recursive-consumer.yml` | Prüft Quadlet und auf reguläre Dateien leeren Consume-Pfad, schreibt Drop-in und startet Dienst bei Änderung neu. | **Hoch/Mittel:** Symlinks/Sonderdateien/unerwartete Einträge erfassen; wirksame Konfiguration vor und nach Restart prüfen; Neustart separat genehmigen, Backup/Rollback definieren. |
| `ansible/playbooks/prepare-paperless-consume.yml` | Prüft Owner/Modus des Consume-Roots und auf reguläre Dateien leeren Baum; erstellt Scopes mit Modus `0750`. | Symlinks, Sonderdateien und abweichende Verzeichnisstrukturen fail-closed behandeln; Eigentümer-UID/GID konfigurierbar machen. |
| `ansible/playbooks/prepare-paperless-rsync-receiver.yml` | Prüft Mount-Ziel, erstellt gesperrten technischen Account und restriktive Verzeichnisse. | Mount-Typ/Quell-Dataset sowie vorhandene Pfade/Symlinks prüfen; UID/GID und Rechte im Ist-Zustand auditieren; SSH-Forced-Command/Schreibgrenzen unabhängig testen. |
| `ansible/playbooks/set-synology-paperless-sync-password.yml` | Explizites Approval-Gate, UID-Check, Vault-Variable und `no_log`. Passwort wird dennoch als Argument von `synouser --setpw` übergeben. | **Hoch:** mögliche Offenlegung in Prozessargumenten/Remote-Audit prüfen und vermeiden; Rotation nur mit separater Autorisierung und getestetem Recovery-Verfahren. |
| `ansible/playbooks/test-paperless-synology-smb.yml` | Temporäre `0600`-Credentials in `/run`, Cleanup im `always`-Block, `smbclient -c ls`. | **Mittel:** `failed_when: false` lässt SMB-Fehler als Playbook-Erfolg erscheinen; Fehlerstatus nach Cleanup verbindlich propagieren. Keine Dateinamen/Geheimnisse in Ausgaben. |

**Geheimnisprüfung (statisch, neun Dateien):** Kein hartcodiertes Passwort, Token oder privater SSH-Schlüssel im geprüften Inhalt erkennbar. Der öffentliche SSH-Schlüssel, interne Adresse, Nutzernamen, UID/GID und Gruppennamen sind **standortspezifische Infrastrukturangaben** und sollten vor öffentlicher Wiederverwendung parametrisiert werden. Das nicht geprüfte `bergen-proxy.yml` ist ausdrücklich nicht von dieser Aussage erfasst.

## Identität und Passwort-Zuständigkeit

Für zentral verwaltete menschliche Konten ist der **Synology Directory Server (DS)** die maßgebliche Passwortinstanz. Paperless darf für diese Konten keine parallele, unabhängig zu pflegende Passwortquelle etablieren. LDAP-Anmeldung, Gruppen-Synchronisation, Anwendungsberechtigungen und mögliche SSO-/2FA-Komponenten sind **getrennte** Kontrollschichten; ein erfolgreiches LDAP-Login belegt noch keine korrekte Dokumentberechtigung.

**Offener technischer Sonderfall:** `paperless-sync` auf der Synology muss anhand der realen Kontoquelle klassifiziert werden: lokaler DSM-Benutzer oder Directory-Server-/LDAP-Benutzer. Das lokale Werkzeug `/usr/syno/sbin/synouser --setpw` adressiert DSM-Benutzerverwaltung und darf **nicht** als allgemeine LDAP-DS-Passwortrotation verstanden werden. Der feste UID-Test `1048` ist kein Nachweis der Authentifizierungsquelle. Das unversionierte Playbook `set-synology-paperless-sync-password.yml` bleibt bis zur Klärung gesperrt; keine Rotation ist Teil des Checkpoints. Geheimnisse bleiben außerhalb von Git in den dafür vorgesehenen geschützten Konfigurationen.

## Heute eingefrorener Funktionsumfang

1. **Versioniert:** Bridge-/Sender-Reconciliation, zwei separate `DELETED_BY_USER`-v2-Journale, lesender Audit `audit-paperless-import-lifecycle-15-26.yml`, dazu Tests und Dokumentation im Feature-Branch.
2. **Belegt:** letzter übermittelter Live-Audit `ok=14 changed=0 unreachable=0 failed=0`, 17/17 Importe/SENT-Nachweise und zwei bestätigte Benutzerlöschungen. Die Dokumente 15 und 26 haben denselben Inhalts-SHA, aber verschiedene IDs/Receipts.
3. **Nicht belegt:** ein erfolgreiches Backup **nach** Veröffentlichung beider Journale, Wiederherstellbarkeit der neuesten Journale, neuer lokaler Unit-Testlauf, vollständiger End-to-End-Test der neun lokalen Playbooks.
4. **Nicht freigegeben:** NAS-Archivkopie, Originaldatei-Entfernung, Retention/Purge, Receipt-Migration, Reimport/Restore, Passwortrotation, SSH-Autorisierungsänderung, Consumer-Neustart.

## Morgen: Archivierung als getrennte Arbeitsphase

**Phase A – ausschließlich lesend:**
- Nach-21:45-MESZ-Backup für LXC 126 anhand Taskstatus, tatsächlich vorhandenem Backup-Archiv, rootfs/mp0-Einschluss und Journalpfad prüfen. Ein erfolgreicher Task allein belegt keine Wiederherstellbarkeit.
- NAS-Scope-/Archivpfade und DSM-ACLs einschließlich `delete-child`/Rename/Quarantäne isoliert prüfen; `st_dev` je Pfad erfassen. Die bekannten Gerätekennungen unterscheiden sich zwischen Scan-Scopes und Archiv (47, 1048641, 40); ein atomarer `rename` über diese Grenze ist ausgeschlossen (`EXDEV`).
- Sender v1/v2-Receipt-Inkarnationen, Wiederverwendung gleicher Dateinamen, `rsync --ignore-existing`, Duplikatverhalten und eindeutige Receiver-Zielnamen als Gesamtkette spezifizieren.
- Entscheidung für crash-sicheren Cross-Subvolume-Transport entwerfen: Kopie in privaten Staging-Bereich, Hashvergleich, `fsync` von Datei und Verzeichnis, atomare Veröffentlichung des Archivnachweises, idempotenter Replay und definierte Quarantäne bei Teilfehlern.
- Negative Tests definieren: fehlender Live-Import, veränderte Quelle, gelöschtes Dokument, nicht bestätigtes Journal, ACL-Verstoß, Crash zwischen Kopie/Journal/Entfernung, Dateinamenskollision und abgelaufenes/fehlendes Backup.

**Phase B – erst nach gesonderter Zustimmung:** mögliche Schreibtests in isolierter Testumgebung; weder automatische produktive Archivierung noch NAS-Quelllöschung. Eine weitere, eigene Freigabe wäre für produktive Aktivierung und nochmals separat für Löschung/Retention erforderlich.

## Reproduzierbare, nicht mutierende Prüfungen

Auf `bp-controller`:

```bash
cd ~/bergen-platform
git fetch origin
git merge --ff-only origin/feat/paperless-ingest-bridge-20261014
git status --short
git ls-files -- '*.local.yml'
git check-ignore -v ansible/vars/paperless.local.yml
sha256sum /tmp/bergen-paperless-code-review.tar.gz
python3 -m unittest discover -s tests -p 'test_paperless_import_lifecycle_15_26.py' -v
```

Der letzte Testbefehl wurde in diesem Review **nicht** ausgeführt. Der lesende Live-Audit wird mit beiden Inventory-Dateien, `--vault-id paperless@prompt` und den vorhandenen Vault-/NAS-Variablendateien ausgeführt; siehe [Checkpoint](PAPERLESS-CHECKPOINT-2026-10-15.md). Ein Ansible-`--check` ist **kein** Ersatz für einen nachweislich read-only Playbook-Pfad.

## Versionierung und Wiederaufnahme

Dieser Dokumentations-Freeze ist ein **Unreleased-Checkpoint**, kein `v0.10.0`, kein Tag, kein Merge nach `main` und keine produktive Abnahme. Nach dem Commit ist dessen vollständige SHA der referenzierbare Stand; nicht die Uhrzeit oder eine hypothetische Versionsnummer.

Die neun lokalen Dateien und `bergen-proxy.yml` bleiben zunächst unverändert auf dem Controller. Vor einer späteren Aufnahme: Quellhashes sichern, Secrets/Standortdaten prüfen, Hochprioritätsbefunde beheben, Tests durchführen und jeden Commit gezielt auswählen (niemals `git add -A`). Die Dateien dürfen weder durch einen Git-Fetch überschrieben noch aufgrund dieses Dokuments gelöscht werden.

**Wiederaufnahme morgen:** zuerst Backup-Nachweis, dann read-only ACL-/Dateisystemprüfung und Architekturentscheidung für die Archivierung. Keine implizite Freigabe aus einem bestandenen Audit.
