# Paperless: Abschluss früherer Entwicklungs-PRs #59, #60 und #68

Stand 17.10.2026. Abgleich gegen den nach [Release-PR #85](https://github.com/tobe4it/bergen-platform/pull/85) gemergten `main` (Paperless-Gruppenbetrieb v0.13.0). Der hier dokumentierte Abschluss bedeutet **ohne Merge der alten Entwicklungszweige**. Frühere PR-Diffs bleiben über GitHub als historischer Beleg zugänglich.

## #59 – Verworfenes SMB-Vorprüfungsdesign

[PR #59](https://github.com/tobe4it/bergen-platform/pull/59) enthielt einen **read-only TCP-Port-445-/Werkzeug-Preflight** im Paperless-LXC; er prüft weder SMB-Zugangsdaten noch Freigaben oder Dokumentinhalte. Die aktuelle Scanübertragung nutzt dagegen einen eingeschränkten **SSH/rsync-Push vom NAS** mit Senderquittungen und unabhängigem Paperless-Importnachweis. Ein SMB-Preflight aus dem LXC ist hierfür weder Bestandteil des Datenpfads noch ein Ersatz für diese Beweise.

**Entscheidung:** Als durch das heutige Transportdesign **obsolet schließen**, Playbook mit alter fest eingebauter NAS-IP nicht nach `main` übernehmen. Ein späterer separater SMB-Anwendungsfall benötigt eine neue, site-konfigurierbare Anforderung und einen eigenständigen PR; die frühere Datei bleibt im geschlossenen PR auffindbar.

## #60 – Historischer Synology-zu-Paperless-Import

[PR #60](https://github.com/tobe4it/bergen-platform/pull/60) liegt als älterer, direkter `main`-PR vor. Vergleich der Paperless-Dateien des Branch-HEADs mit `main` vom 17.10.: **101 bytegleich, 7 im heutigen `main` weiterentwickelt, 8 ältere Dokumentationsdateien nicht wortgleich übernommen.** Die aktuell vorhandenen v1-Bausteine decken Sender, Watcher, Import-Bridge, zwei explizite ältere Benutzer-Löschjournale, unabhängigen Lifecycle-Audit und automatische geschützte Gruppenarchivierung ab.

Die nicht übernommenen Dokumente waren `PAPERLESS-CHECKPOINT-2026-10-15.md`, `PAPERLESS-CODE-REVIEW-2026-10-15.md`, `PAPERLESS-PERMISSIONS.md`, `PAPERLESS-SCAN-LIFECYCLE.md`, `PAPERLESS-SYNOLOGY-INOTIFY.md`, `PAPERLESS-SYNOLOGY-PORTABLE.md`, `PAPERLESS-TAGS.md` und `PAPERLESS-USER-RIGHTS.md`. Deren weiterhin gültige **fachliche** Berechtigungs-, Tag- und Watcher-Regeln sind im [v1-Gruppen-Administrationshandbuch](PAPERLESS-GROUP-ADMINISTRATION.md) gesichert. Der aktualisierte Datenpfad, automatische Gruppe-Archivierung und Wiederanlauf sind im [v1-Betriebshandbuch](PAPERLESS-GROUP-OPERATIONS.md) beschrieben.

Die historischen Dokumente werden bewusst **nicht unverändert veröffentlicht**: Sie enthalten zwischenzeitlich veraltete „Archivierung nicht aktiviert“-/„Main nicht freigegeben“-Aussagen sowie teils standort-, konto- und dokumentbezogene Bestandsangaben. Die früheren PRs und Commits bleiben als Audit-Historie erhalten.

**Entscheidung:** #60 nach Veröffentlichung der bereinigten Dokumentation als **funktional von #85 ersetzt schließen**. Kein Merge älterer Sender-/Auditorversionen, keine Änderung an aktivem NAS-Sender oder Timer. Abgrenzung: Die allgemeine Erstinstallation des Paperless-Backends (PR #54), der Backup-Timer als IaC (PR #55) und die erweiterten API-Berechtigungstests (PR #62) bleiben eigenständige offene Arbeiten.

## #68 – Historischer lesender Archiv-Preflight

[PR #68](https://github.com/tobe4it/bergen-platform/pull/68) hatte ein kombiniertes **read-only**-Audit einschließlich zweier expliziter Benutzer-Löschjournale und des damaligen gesicherten LXC-Backups. Vier seiner fünf geänderten Dateipfade liegen bereits im heutigen `main`; dessen Archiv-Preflight ist zusätzlich um die Senderquittungshistorie ergänzt. Die fünfte Datei war ein historischer **Release-Gate-Text** mit der seinerzeit gültigen Einschränkung „Paperless darf nicht nach Main“ und genauen lokalen Sicherungsdaten.

Die heutige Produktivfreigabe umfasst **nur** den geschützten automatischen Gruppen-Original-Archiv-Move nach unabhängig verifiziertem Import. Das damals offene **Purge-/Quarantäne-/Quellen-Unlink** ist weiterhin nicht freigegeben. Deshalb dürfen die alten „nicht nach `main`“-Regeln weder auf den bereits veröffentlichten v1-Code übertragen noch als pauschale Löschfreigabe missverstanden werden.

**Entscheidung:** #68 als **durch die strengeren v1-Lifecycle-/Archiv-Audits abgelöst schließen**; historischen Read-only-Beleg im PR belassen, keine alte Freigabe-Dokumentation zurückmergen.

## Beibehaltene Nachfolgeaufgaben

- [PR #54](https://github.com/tobe4it/bergen-platform/pull/54): reproduzierbarer Backend-/Podman-/Quadlet-Erstinstallationspfad fehlt noch in `main`.
- [PR #55](https://github.com/tobe4it/bergen-platform/pull/55): geprüfter Proxmox-VZDump-Timer/Backup-Role als IaC fehlt noch in `main`.
- [PR #62](https://github.com/tobe4it/bergen-platform/pull/62): erweiterte DRF-API-Autorisierungstests getrennt überführen.
- [PR #80](https://github.com/tobe4it/bergen-platform/pull/80) und [#81](https://github.com/tobe4it/bergen-platform/pull/81): v2-Transport, Quarantäne, sichere Quellenentfernung und Restore bleiben **Draft**; kein automatischer Purge und keine v2-Live-Freigabe.

**Wirkung dieser Bereinigung:** Nur Dokumentation und Testabdeckung in Git. Keine neuen NAS-/Proxmox-Berechtigungen, keine Dienststarts, keine produktive Archivbewegung und keine Purge-Erlaubnis.
