# Paperless: freigegebener Gruppenbetrieb v1

Stand: 17. Oktober 2026. **Begrenzt freigegeben** für den bestehenden Synology-zu-Paperless-Gruppenscanpfad. Dieses Verzeichnis ist eine *Referenzimplementierung*, kein allgemeines Installationsprogramm für neue Anlagen. Private Pfade, Benutzer, Schlüssel und Hostnamen gehören ausschließlich in lokale, ignorierte Konfigurationen.

## Geltungsbereich und Architektur

- Synology-Scaneingänge der Gruppen `Familie` und `Eltern` -> `paperless-sync` (kein Administrator) -> über SSH/rsync zum Paperless-Ingest-Staging -> ingest-bridge/Reconciler -> Paperless-ngx im unprivilegierten Proxmox-LXC.
- NAS-Watcher überwacht neue Scans; regelmäßiger Vollscan deckt verpasste Ereignisse ab. Versand erst nach Schreibruhe und unter gesperrter Senderquittung.
- Ein unabhängiger Importabgleich muss Senderidentität, Empfangsquittung, SHA-256, Dokument-ID und nachweislich lebenden Paperless-Import samt Besitz-/Zugriffsberechtigungen bestätigen.
- Nur dann verschiebt ein separater Controller-OneShot das *NAS-Original* durch einen nicht überschreibenden, atomaren Rename auf demselben Synology-Dateisystem in das geschützte Originalarchiv: `.bergen-paperless-archive/<Scope>/<YYYY-MM>/<Receipt-ID>.pdf`. Ein `PREPARED`-/`ARCHIVED`-Journal sowie die unabhängige Archiv-PDF-Nachprüfung sind Pflicht.
- Historische Sender-`SENT`-Quittungen und Archivjournale werden **niemals überschrieben**. `mtime`-/`ctime`-Drift darf nur bei identischem Device/Inode/Größe, stabilem vollständigem SHA-256 und erneutem Importnachweis akzeptiert werden; beide Signaturen stehen dann im unveränderlichen Archivjournal.
- Gleichnamige **neue** Scans erhalten im Eingang automatisch einen eindeutigen `--scan-<nonce>`-Namen. Für jeden neuen Inode entsteht eine eigene Sendequittung; die Archivierung nutzt statt nummerierter Verzeichnisse eindeutige Receipt-Namen.
- Die Gruppenautomatik archiviert **höchstens eine** nachweislich importierte PDF je erfolgreichem Durchlauf. `OnUnitInactiveSec=5min` startet frühestens fünf Minuten *nach Ende* des Dienstes den nächsten.

## Produktivgrenzen

**Freigegeben:** Gruppenscan-Sender, selbstständige Auswahl verifizierter Gruppenimporte, geschützte Verschiebung der unveränderten NAS-Originale und unabhängige Journal-/Importprüfung.

**Nicht freigegeben:** Löschen/Purgen archivierter Originale, 30-Tage-Aufbewahrungslöschung, produktive v2-Quarantäne oder Restore-Automat, private Archivautomatik sowie automatische Wiederholung mehrdeutiger Crash-/Importzustände. Ein sichtbares Dateiverschwinden aus dem Eingangsordner infolge geschützter Same-Volume-Verschiebung ist **kein** Purge: Das archivierte Original muss nachweisbar erhalten bleiben.

Zwei historisch ausdrücklich vom Benutzer gelöschte Paperless-Dokumente sind in der bestehenden Installation separat dokumentiert und aus automatischen Archivkandidaten ausgeschlossen. Das System behandelt weitere Benutzerlöschungen nicht pauschal als freigegeben.

Ein widersprüchlicher Beweis kann weiterhin den *ganzen* v1-Durchlauf blockieren. Die pro-Dokument-Fehlerisolierung bleibt eine Entwicklungsaufgabe. Niemals Quittungen, Zeiten, Dateinamen oder PDFs manuell verändern, um einen Blocker zu umgehen.

## Betrieb (bestehende Installation)

Controller-Worktree: geprüftes und abgestimmtes Git-Checkout mit Ansible-Venv und ignorierten standortspezifischen Vault-/NAS-Werten. **Die laufende systemd-Service-Unit kann noch ein Entwicklungs-Worktree referenzieren**: Nach diesem Git-Main-Release ändert sich der produktive Codepfad *nicht automatisch*. Vor einem Wechsel zu einem Main-Checkout sind Dateiprüfsummen, Worktree-Pfad, Ansible-Inventar und systemd-ExecStart separat abzugleichen.

Status ohne sensitive Nutzdaten:

```bash
systemctl is-enabled bergen-paperless-group-auto-v1.timer
systemctl is-active bergen-paperless-group-auto-v1.timer
systemctl show bergen-paperless-group-auto-v1.service \
  -p ActiveState -p SubState -p Result -p ExecMainStatus
systemctl list-timers --all --no-pager --full \
  bergen-paperless-group-auto-v1.timer
```

Ein `Type=oneshot` kann während einer laufenden Archivprüfung `ActiveState=activating` melden und anschließend mit `inactive` / `Result=success` beenden. Ein erfolgreicher OneShot **allein** beweist keine zusätzliche Archiv-PDF, weil die Warteschlange leer sein kann. Prüfe das Abschlussjournal, die Gesamtzähler im rein lesenden Lifecycle-Audit und die aktuelle Archivbelegung unabhängig.

Zum beschränkten Journalblick **keine rohen Ansible-`no_log`-Werte oder vertrauliche PDF-Dateinamen ausgeben**:

```bash
sudo journalctl -u bergen-paperless-group-auto-v1.service \
  -n 200 --no-pager -o cat |
  grep -E 'VERIFIED_GROUP_IMPORT_READY|NO_GROUP_IMPORT_READY|ONE_GROUP_PDF_ARCHIVE_COMPLETED|POST_MOVE_LIFECYCLE_RECONCILED|ALL_RELEASE_GATES_ABSENT|PLAY RECAP|changed=|failed='
```

Vollständige, nur lesende Gegenprobe:

```bash
cd /home/ansible/bergen-platform-pr81
ansible-playbook \
  -i ansible/inventory.yml \
  -i /home/ansible/bergen-platform/ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-import-lifecycle-15-26.yml \
  --vault-id paperless@prompt \
  -e @/home/ansible/bergen-platform/ansible/vars/paperless.vault.yml \
  -e @/home/ansible/bergen-platform/ansible/vars/paperless-synology.local.yml \
  -e '{"paperless_lifecycle_quiet":true}'
```

Das Audit muss die unveränderten historischen Sender-/Archivquittungen, alle geschützten archivierten Inodes/PDF-SHAs, aktuelle Live-Importe und die zwei einzeln bestätigten alten Benutzerlöschungen vollständig reconciliieren. **Kein Audit autorisiert automatisch eine Löschung.**

## Fehlerfälle und Wiederanlauf

1. `SOURCE_RECEIPT_MISMATCH`, SHA-Abweichung oder neue Inode ohne verifiziertes Vorgängerarchiv: **nicht manuell umbenennen oder Quittungen reparieren**. Timer bei anhaltendem Fehler anhalten, rein lesenden Diagnosepfad ausführen, ursprüngliche Daten sichern.
2. `PREPARED` ohne `ARCHIVED`, zeitlich unklarer Crash oder Rest-Gate: keine automatische Wiederholung; ausschließlich isolierter Recovery-Audit und Nachweis des tatsächlichen Quell-/Ziel-Inodes. Keine manuelle Ersatzarchivierung im Normalbetrieb.
3. Archiv-ACLs, DSM-Btrfs-Schutz oder SHA-Nachweis unzureichend: fail closed; nicht durch pauschale Berechtigungen, Root-Sender oder gelockerten Hashvergleich umgehen.
4. `No group import ready`: normaler Leerlauf. Nicht mit fehlgeschlagener Übertragung verwechseln; getrennte Sender-/Bridge-Proofs prüfen.
5. Neu bereitgestellte Version: vorher geprüfte Tests, aktives Archivtimer-Deployment ggf. deaktivieren, Code atomar mit SHA-/Owner-Kontrollen stagen, einen automatischen OneShot samt POST-Audit abnehmen; erst dann periodischen Timer freigeben.

## Backup, Datenschutz und Restore

Aufbewahrungsorte: Paperless-App-Daten/DB und geschützte NAS-Originale sind **zwei verschiedene Sicherungsobjekte**. Sender- und Archivjournale müssen gesichert und mit gesichertem Datenstand konsistent wiederherstellbar sein. Regelmäßige Backups und getrennte Restore-Tests sind erforderlich; eine erfolgreiche aktuelle NAS-Archivprüfung ist kein Beweis für ein vollständiges Disaster-Recovery-Szenario.

Private Papierdokumente bleiben durch gesonderte Paperless-Berechtigungen und private Eingangsverzeichnisse geschützt. Gruppenfreigabe darf nie die privaten Dokumente einer fremden Paperless-Identität einsehbar machen. Alle Credentials, NAS-Zielpfade und betriebsbezogenen Identitäten verbleiben außerhalb der öffentlichen Git-Quellen.

## Freigabeprotokoll

Am 17.10.2026 vom Betreiber gemeldete Abnahmen: 840 Offline-Tests im Entwicklungsbranch `OK`; Installation der aktualisierten vier NAS-Komponenten `ok=25 changed=4 failed=0`; Read-only-Lifecycle-Audit `ok=18 changed=0 failed=0`; systemd-OneShot `Result=success ExecMainStatus=0`; Timer `enabled`/`active`; mindestens **ein automatisch archiviertes** weiteres Gruppenoriginal vom Betreiber bestätigt. Dies ist eine **begrenzte Freigabe**, kein Beleg, dass jeder künftige Timer-Lauf erfolgreich sein wird.

Die v2-Lösch-/Quarantäne-Arbeit verbleibt in der Entwicklungs-PR. Der Merge dieses v1-Referenzreleases autorisiert weder Löschungen noch die Freigabe des v2-Zweigs.
