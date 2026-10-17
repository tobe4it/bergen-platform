# Paperless v1 Gruppenbetrieb — Release-Schnitt 2026-10-17

Gegenstand: dokumentierter, vom Betreiber in der vorhandenen Infrastruktur verifizierter v1-Gruppenbetrieb. Codebasis ist aus dem laufenden Paperless-Entwicklungszweig gezielt herausgelöst, ohne dessen unfertige v2-Quarantäne-/Source-Unlink-Implementierung und ohne Änderungen an IBM-MQ, Mail oder ACME aus gestapelten Entwicklungszweigen.

## Enthalten

- Synology Sender/Watcher, eindeutige Verarbeitung gleichnamiger Gruppenscans, nur nach Schreibruhe.
- Paperless-Ingest-Bridge und Reconciler mit getrennten Quittungen/gesicherten Identitäten.
- Abgleich mit lebendem Paperless-Import und ACL/Owner-Pflicht.
- Atomare geschützte Same-Volume-Originalarchivierung, append-only Journal, unabhängig überprüfbarer PDF-Inode/SHA, unveränderte historische Senderbelege.
- 5-Minuten-Systemd-Gruppentimer mit höchstens einem verifizierten Original je Lauf, ausschließlich `Familie`/`Eltern`.
- Nur lesende Diagnosen, freigabegesperrte Bereitstellungsplaybooks und Tests.

## Explizite Einschränkungen

Kein automatischer Purge, keine produktive Quarantäne-/Source-Unlink-Freigabe, kein automatisierter Restore aus Langzeitaufbewahrung, keine private Gruppenarchivierung, noch keine robuste per-Dokument-Fehlerisolierung. Fehlende/unklare Nachweise führen zum Stopp.

**Betriebsfreigabe != Quellcode-Merge-Prüfung:** Der laufende Controller-Dienst kann weiterhin explizit das bisherige Entwicklungs-Worktree verwenden. Die Übernahme in `main` ändert nicht automatisch einen bestehenden systemd-ExecStart. Vor Umstellung muss ein kontrollierter Checkout-/Pfad- und Auditvergleich stattfinden.

Siehe [Betriebshandbuch](PAPERLESS-GROUP-OPERATIONS.md).
