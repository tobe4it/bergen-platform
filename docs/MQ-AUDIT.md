# Single-QMgr-Prüfung (Beispiel / Evaluation)

Für produktiven Betrieb ist die Lizenzfrage mit IBM zu klären. Dies ist ein
funktionales Prüfprotokoll, keine unabhängige Audit- oder Compliancefreigabe.

## Automatisierter Umfang

`ansible/playbooks/mq-audit.yml` führt den vorhandenen Reconciler über HTTPS mit
CA-Prüfung und Vault-Zugang aus. Zufällige, kollisionsfrei geprüfte `BGA.*`-Namen
isolieren die Prüfungen von bestehenden Objekten. Keine Channels werden gestartet.

| Bereich | Prüfungen |
|---|---|
| QLOCAL, QREMOTE, QALIAS, QMODEL, TOPIC, NAMELIST | Check-Erstellung, DEFINE, Idempotenz, Check-ALTER, inkrementelles ALTER, Attributerhalt, Check-DELETE, DELETE, Abwesenheitsprüfung |
| SDR, RCVR, SVRCONN, CLNTCONN, CLUSSDR, CLUSRCVR | Definitions-Lifecycle; keine Kommunikations- oder Clusterfreigabe |
| Schutzmechanismen | Typkonflikte, unveränderlicher TOPICSTR, Löschfreigabe, SYSTEM-Namen, Wildcards, unbekannte Attribute, ungültige Enums, doppelte Identitäten |
| Nachweise | UTC-Zeit, Git-Revision, Erwartungen/Resultate, strukturierte Befehle und Codes, Bereinigung, SHA-256-Manifest |

Cluster-Definitionen können an vom Reconciler nicht unterstützten Pflichtattributen
scheitern. Das ist ein dokumentierter FAIL, kein unterdrückter Fehler.

## Ausführung auf bp-controller

Vorher neuen Code bereitstellen und `git status --short` prüfen; lokale Änderungen
im Prüfkontext dokumentieren. Die Suite ist kein Ansible-Check-Mode-Playbook.

```bash
python -m unittest discover -s tests -v
ansible-playbook ansible/playbooks/mq-audit.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-lab.local.yml \
  -e mq_audit_confirm_test_mutations=true \
  --ask-vault-pass
```

Die Zustimmung erlaubt gezielte Testobjekt-Erstellung, ALTER und DELETE ausschließlich
auf BERGENLAB. Ergebnisdateien unter `ansible/reports/mq-audit/BGA.*/` sind ignoriert
und restriktiv berechtigt: `evidence.json`, `Pruefbericht.md`, `SHA256SUMS`.
Bei FAIL wird erst gespeichert, dann das Playbook abgebrochen. Bei Verbindungsabbruch,
SIGKILL oder unklarer Bereinigung Präfix prüfen; nicht blind wiederholen oder FORCE
verwenden. Keine Zugangsdaten in Berichte oder Git aufnehmen.

Channel-Löschungen werden anhand des zuvor per DISPLAY ermittelten `CHLTYPE` mit
der richtigen `CHLTABLE` (`CLNTCONN` oder `QMGR`) qualifiziert. Ein fehlender oder
unbekannter Typ führt vor DELETE zum sicheren Abbruch, damit gleichnamige
Channel-Namensräume eindeutig adressiert bleiben.

Diagnosehinweis: Der Live-Lauf mit Commit `424cbaf` hat die Channel-Löschung
weiterhin mit HTTP 400 abgelehnt. Die CHLTABLE-Änderung ist damit **nicht live
bestätigt**; erfolgreiche Offline-Tests ersetzen diese Bestätigung nicht.
HTTP-400-Diagnosen geben nun ausschließlich erkannte IBM-`msgId`-Kennungen und
gefilterte `message`-Felder aus begrenzten JSON-Antworten aus. Bekannte Zugangsdaten
werden entfernt, sensibel erscheinende Meldungen unterdrückt; Header, Rohantwort,
`explanation` und `action` werden nicht ausgegeben. Meldungen können weiterhin
betriebliche Objektnamen enthalten. HTTP 401/403 bleibt ohne Antwortinhalt.
Keine automatische Wiederholung oder zusätzliche MQ-Mutation wird dafür ausgeführt.

## Noch nötige Single-QMgr-Prüfungen

### Optionaler Mailversand

Zusätzlich `-e mq_audit_mail_to=empfaenger@example.org` angeben. Ohne Parameter
erfolgt kein Versand. Die drei Ergebnisdateien werden auch bei FAIL vor der
abschließenden Assertion versendet. Voraussetzung: ein auf bp-controller bereits
konfigurierter lokaler MTA mit `/usr/sbin/sendmail`. Das Playbook installiert oder
konfiguriert keinen Mailserver und übernimmt keine SMTP-Zugangsdaten.
Absender und Sendmail-Pfad sind mit `mq_audit_mail_from` beziehungsweise
`mq_audit_sendmail_path` überschreibbar; Standardabsender ist `ansible@bp-controller`.
Für externen Versand gegebenenfalls einen vom Relay zugelassenen Absender verwenden.
Eine erfolgreiche Übergabe an den MTA ist kein Nachweis der Zustellung im Postfach.
Ein Versandfehler lässt die Ergebnisdateien bestehen und führt zum Playbook-Fehler.
Preflight-Abbrüche ohne Ergebnisdateien erzeugen keine Mail. Die Anhänge können
betriebliche Metadaten enthalten; ausschließlich autorisierte Empfänger verwenden.

Dieser erste automatisierte Lauf testet die implementierte Objektverwaltung, nicht
alles, was IBM MQ auf einem einzelnen QMgr grundsätzlich kann. Separat offen:

- PUT/GET/Browse, Persistenz, Commit/Rollback und nicht-leere Queue-Löschsperre.
- Authentifizierung mit falschem Passwort, TLS-Negativfälle, CHLAUTH/OAM und Rollen.
- Lokales Publish/Subscribe und dynamische Queues (nicht implementierte Funktionen).
- Dienst-/Container-Wiederanlauf, Host-Neustart, Backup/Restore und tatsächliche
  Syslog-Zustellung; dafür muss ein abgestimmtes Unterbrechungsfenster bestehen.
- Attribut-Grenzwerte und vollständige Matrix der erlaubten Attribute.

Nicht geprüfte Punkte bleiben NOT TESTED. Zwei-QMgr-Routing, HA und aktive Cluster
sind mit dieser Topologie nicht nachweisbar. Offline-Tests sind ausdrücklich keine
realen IBM-MQ-Kompatibilitätsnachweise. Ein endgültiger Prüfbericht benötigt die
tatsächlichen Ergebnisdateien und die organisatorische Prüferfreigabe.
