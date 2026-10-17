# Paperless v1 – Scan-Eingänge, Tags und Berechtigungen

Stand: 17.10.2026. Ergänzung zum [freigegebenen Gruppen-Betriebshandbuch](PAPERLESS-GROUP-OPERATIONS.md). Bewahrt die weiterhin gültigen fachlichen Regeln der älteren PR #60, **nicht** deren historisch veraltete Rollout- und Löschfreigaben. Diese Dokumentation verändert keine Paperless-Daten.

## Scan-Eingang und Synology-Watcher

- Die derzeit freigegebene automatische **Archivierung** betrifft ausschließlich die Gruppenbereiche `Familie` und `Eltern`. Separate private Eingänge haben eigene Benutzer-/ACL-Grenzen und werden **nicht** über den Gruppen-Archivtimer verarbeitet.
- Ein NAS-Watcher verwendet `IN_CLOSE_WRITE` und `IN_MOVED_TO` als unmittelbare Auslöser, startet den Sender erst nach einer Ruhezeit und führt einen periodischen vollständigen Nachlauf durch (historischer Konfigurationswert: 900 Sekunden). Bei Watch-Verlust wird der Worker neu gestartet; ein unprivilegierter Supervisor hält den Prozess unter Kontrolle.
- Die effektiven Werte für Ruhezeit, Nachlauf, Maximalgröße und Sendeintervall kommen aus der **root-kontrollierten lokalen Konfiguration**; Dokumentationswerte sind keine Freigabe, eine bestehende Anlage stillschweigend zu verändern. Die PDF-Prüfung im Sender verlangt stabile Metadaten, vollständigen Inhalt/Hash und gültige Sendequittung.
- Scanprogramme sollten eine unfertige Datei außerhalb des endgültigen Namens schreiben und sie nach abgeschlossenem Schreiben atomar in den Eingang umbenennen. Auch eine reine Zeit-/Größenruhe **beweist nicht**, dass kein Prozess mehr schreibt.
- Bei gleichnamigen neuen Scans wird ein neuer Quell-Inode in einen eindeutigen Dateinamen überführt; bereits importierte identische Inodes werden auch nach reiner `mtime`-/`ctime`-Änderung nicht erneut übertragen. Unklare Zustände bleiben gesperrt.
- Das NAS-Sender-Gate bleibt getrennt von der Archiv-Freigabe. Bei Ausfall weder Quittungen rückdatieren noch Quelle/Archiv manuell umbenennen. Diagnose und kontrollierter Wiederanlauf stehen im [Betriebshandbuch](PAPERLESS-GROUP-OPERATIONS.md).

Implementierung: `ansible/files/paperless/synology_inotify_watch.py`, `synology_watcher_supervisor.py`, `synology_scan_sync.py` und `synology_config.py`. Site-Konfiguration und Zugangsdaten bleiben außerhalb von Git.

## Dokumentberechtigungen und neue Benutzer

Paperless unterscheidet **Modellrechte**, Objektberechtigungen und genau einen Dokument-`owner`. Aus einer LDAP-/OIDC-Gruppenzugehörigkeit folgt **keine automatische Erlaubnis**, private Dokumente anderer Konten zu lesen.

- Private Dokumente: regulärer Eigentümer und administrative Sonderzugriffe; keine pauschale Freigabe an Familie oder Eltern.
- Gemeinsam freigegebene Dokumente: technische Eigentümerschaft plus ausdrücklich geprüfte Objekt-/Gruppenrechte. Für reguläre Benutzer **keine** allgemeine `delete_document`-Erlaubnis auf Gruppenunterlagen.
- Kinder erhalten nicht allein durch einen vorhandenen Home-/Scan-Pfad einen Paperless-Account oder eigene Scan-Verarbeitung. Erforderlich sind einzeln verifizierte Identität, Gruppe, Workflow, Besitzrechte und negative API-Sichtbarkeitstests.
- Ein Django-/DRF-In-Process-ACL-Test ersetzt weder einen echten OIDC-Login noch einen End-to-End-Test durch Proxy, KI-Tool oder Download-URL. Der erweiterte 36/36-DRF-Test aus [PR #62](https://github.com/tobe4it/bergen-platform/pull/62) bleibt als **separat noch zu übernehmende** Testverbesserung offen.

Das vorhandene `audit-paperless-permissions.yml` in `main` ist standardmäßig lesend; sein Ergebnis darf nicht als uneingeschränkte Prüfung aller HTTP-Endpunkte oder aktueller Benutzerkonfiguration interpretiert werden.

## Administrativer Tag-Katalog (18 Tags)

Der über `prepare-paperless-inbox-tag.yml` implementierte Katalog enthält 15 thematische Tags:

**Steuer, Haus, Finanzen, Versicherung, Mobilität, Gesundheit, Bildung, Beruf, Reise, IT, Ehrenamt, Behörden, Haustiere, Energie, Gewährleistung.**

Diese Tags können anhand bestätigter Beispiele das automatische Lernen nutzen. Die drei *nicht als Themen trainierten* Funktionstags sind:

- `Posteingang`: Import-Eingangskennzeichnung.
- `Aktion offen`: manueller Bearbeitungszustand.
- `Frist prüfen`: manueller Bearbeitungszustand.

Der Katalog ist flach. Neue oder bestehende verwaltete Tags müssen den erwarteten administrativen Eigentümer und erlaubte Einstellungen besitzen; Abweichungen führen zu STOP, nicht zu stillschweigender Übernahme. Normale Benutzer erhalten für verwaltete Tags ausschließlich die nachweislich benötigten Leserechte. **Das Anlegen des Katalogs allein bestätigt keine Lernqualität.**

Die persönliche UI-Option `document_editing.remove_inbox_tags` soll nur initialisiert werden, wenn sie noch nicht vom jeweiligen Nutzer gesetzt wurde.

## Eigene Tags löschen: explizit begrenzte Rechte

`prepare-paperless-user-rights.yml` auditiert standardmäßig nur. `documents.delete_tag` ist ein **globales Modellrecht**, das für eine Freigabe der eigenen Tag-Löschung allein nicht ausreicht; die objektbezogene Eigentümerschaft/Permission muss ebenfalls passen.

Vor einem ausdrücklich autorisierten Apply müssen insbesondere ausgeschlossen sein: Tags ohne Eigentümer, unerwartete Lösch-Objektrechte für andere Benutzer/Gruppen sowie fremde/admin-eigene Tags, die reguläre Benutzer löschen könnten. Eine Tag-Löschung entfernt Zuordnungen, nicht die Dokumente; dennoch darf sie nicht automatisch erfolgen. Dokumentlöschrechte, Mitarbeiter-/Superuserrollen und Workflows werden dadurch **nicht** erweitert.

## Optionales Vorgehen für den vorhandenen Controller

Alle folgenden Playbooks sind im bestehenden v1-Code verfügbar; **ohne** Apply-Flag sind sie nur für Review und Audit vorgesehen. Vor Ausführung sind die aktuelle Inventarbindung, die Vault-Datei und die effektive Berechtigung zu prüfen. Keine Namen, Secrets oder Papierdokumente in öffentliche Logs kopieren.

```bash
cd /home/ansible/bergen-platform
ansible-playbook -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-inbox-tag.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml

ansible-playbook -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-user-rights.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml
```

**Keine** automatische Rechte-/Tag-Mutation aus diesem Dokument. Eine bislang nur im Entwicklungsbranch vorhandene Bootstrapping-/Ansible-Role wird durch diese v1-Dokumentation nicht nachträglich als veröffentlicht erklärt.
