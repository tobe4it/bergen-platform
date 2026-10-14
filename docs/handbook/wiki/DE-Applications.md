<!-- bergen-platform-handbook: managed -->
# Anwendungen im Alltag

[Deutsch](DE-Start.md) | [English](EN-Applications.md)

**Öffentliche Ausgabe 1.0, 14.10.2026.** Beispiele ersetzen keine private Standortkonfiguration.

## E-Mail: zwei Server und mehrere Wege

Bei selbst gehosteter E-Mail muss sowohl der Weg aus dem Internet als auch der Zugriff auf vorhandene Postfächer funktionieren.

### Die beteiligten Aufgaben
Der **öffentliche Gateway** nimmt E-Mails aus dem Internet an und versendet dorthin. Er betreut Internet-Richtlinien, Spamprüfung, DKIM und öffentliche Zustellung. Eine private Verbindung, unter anderem über **WireGuard**, verbindet ihn mit dem internen Backend.

**Postfix** nimmt Nachrichten an, prüft Weiterleitungen und hält eine Warteschlange. **Dovecot** ermöglicht den Postfachzugriff und die lokale Zustellung. **LDAP** liefert Identitäten und Rechte. Die Mailboxdaten des Bergen-Backends liegen laut Projekt unter `/var/vmail`.

### Die wichtigsten Protokolle
| Protokoll / Port | Zweck |
| --- | --- |
| SMTP / 25 | Übertragung zwischen Mailservern; im Backend nur für den vorgesehenen Gateway-Pfad |
| Submission / 587 | Angemeldetes Versenden vom Mailprogramm, meist mit STARTTLS |
| Submissions / 465 | Angemeldetes Versenden mit TLS ab Verbindungsbeginn |
| IMAPS / 993 | Lesen und Synchronisieren von Postfächern über TLS |

IMAP synchronisiert Ordner und Status mit dem Server. Ein Löschen kann daher auf allen Geräten wirksam werden. Das Mailprogramm auf dem Telefon ist nicht automatisch eine unabhängige Postfachsicherung.

### Adressen, Konten und Aliasse
Die tatsächlichen Maildomains sind standortspezifisch und werden privat erfasst. Ein **Alias** leitet eine zusätzliche Adresse an einen oder mehrere Empfänger weiter. Wer einen Alias empfangen darf, darf nicht automatisch unter ihm senden. **Send-as** bezeichnet eine gesonderte Versandberechtigung.

Die Gruppe Mailuser begrenzt die Postfachbereitstellung. Technische Sender dürfen laut Backend-Konzept SMTP nutzen, ohne ein normales IMAP-Postfach zu bekommen.

### Den aktiven Postfachort zuerst feststellen
Das neue Bergen-Backend ist eingerichtet. Die Projektunterlagen führen Postfachmigration, öffentliche Clientwege und vollständige Abnahme weiterhin als offene Arbeit. Im Nachlassfall deshalb sowohl bisherige Synology-Postfächer als auch `/var/vmail` sichern und zuerst ermitteln, welches System tatsächlich Nachrichten annimmt.

Eine erfolgreich reparierte Zertifikatserneuerung am Gateway beantwortet diese Frage nicht. MX-Eintrag, privater Zustellweg, Mailclient-Einstellungen und aktuelle neue Nachrichten gemeinsam vergleichen.

## E-Mail-Störungen erkennen

Senden, Empfangen und Anmelden sind getrennte Funktionen. Eine genaue Beschreibung verhindert, dass am falschen Server gearbeitet wird.

### Erst mit dem Mailprogramm eingrenzen
- Eine vorhandene Nachricht öffnen. Geht das nicht, Verbindung und Anmeldung zum Postfach prüfen.
- Eine Nachricht an ein eigenes unabhängiges externes Postfach senden und von dort antworten. Beide Uhrzeiten notieren. Diesen Test bewusst als kurze Testnachricht ausführen.
- Fehlermeldung vollständig erfassen. Eine ausbleibende Mail ohne Fehlermeldung kann noch in einer Warteschlange liegen.

| Beobachtung | Erste technische Prüfrichtung |
| --- | --- |
| Lesen geht, Senden nicht | Submission, Anmeldung, Send-as, Verbindung zum Gateway |
| Externe Mails kommen nicht | MX/Gateway, Warteschlange, privater Tunnel, aktives Backend |
| Nur ein Konto betroffen | Konto, Gruppen, Passwort, Alias oder Postfachgrenze |
| Mehrere Konten anmelden unmöglich | LDAP, DNS, TLS oder Postfachdienst |
| Zertifikatswarnung | Name, Uhrzeit, Laufzeit, Vertrauenskette und echte Erneuerung |

### Lesende Prüfung durch die Betreuung
Im tatsächlichen Postfix/Dovecot-System, nicht pauschal im neuen Backend:
```text
systemctl status postfix dovecot --no-pager
mailq
journalctl -u postfix -n 40 --no-pager
journalctl -u dovecot -n 40 --no-pager
```
`mailq` zeigt auf diesem Server wartende Nachrichten. Eine leere Backend-Warteschlange sagt nichts über die Warteschlange des öffentlichen Gateways. Fehlermeldungen nach Zeit und betroffener Nachricht zuordnen.

### TLS und Domains weiterbetreuen
**TLS** verschlüsselt die Verbindung und prüft das Gegenüber anhand des Namens. **ACME/Certbot** kann Zertifikate erneuern. Danach muss der zuständige Dienst das neue Zertifikat tatsächlich verwenden. Bei einer Verteilung vom Gateway zum Backend gehört auch dieser Schritt zum Nachweis.

**MX** sagt anderen Servern, wohin Mail geht. **SPF, DKIM und DMARC** helfen bei der Prüfung der Absenderdomain. Diese DNS-Einträge nicht einzeln auf Verdacht ändern. Domainregistrierung, DNS-Verwaltung und Gateway-Vertrag müssen erhalten bleiben.

Keine Warteschlange löschen und keine alten Postfächer entfernen, um Platz zu gewinnen. Die Betreuung entscheidet erst nach Sicherung und einer überprüften Zustell-/Archivstrategie.

## Nextcloud: Dateien und Synchronisation

Nextcloud stellt Dateien, Freigaben und je nach Nutzung weitere Familieninhalte bereit. Die vorhandene Installation gehört zur Übergabe, auch wenn ihre Automation im Bergen-Projekt noch geplant ist.

### Was in einer Nextcloud steckt
Die **Dateien** sind ein Teil der Daten. Eine **Datenbank** enthält unter anderem Zuordnungen und Freigaben. **Konfiguration** beschreibt Datenbankzugang, Speicher und Anbindung; installierte Apps können zusätzliche Inhalte verwalten.

Installierte Version, Host und Installationsart vor Ort erfassen. Vor Wartung den aktuellen Supportstatus und die zur installierten Version gehörende Anleitung prüfen.

### Synchronisation ist keine Sicherung
Ein Synchronisationsprogramm gleicht lokale Ordner mit dem Server ab. Änderungen und Löschungen können übertragen werden. Nach einem Ausfall oder Restore die Synchronisation bewusst anhalten lassen, bis die Betreuung den maßgeblichen Datenstand festgelegt hat.

Eine lokale Kopie kann wichtige neuere Dateien enthalten. Deshalb im Fehlerfall nicht vorschnell Konto entfernen, Ordner neu anbinden oder alle lokalen Daten überschreiben. Zunächst betroffene Dateien getrennt erhalten.

### Was eine vollständige Sicherung braucht
Nextcloud nennt Konfigurationsverzeichnis, Datenverzeichnis, Datenbank und vorhandene Theme-Anpassungen als wesentliche Bestandteile. Bei zusätzlichen Apps und externen Speichern muss die Betreuung deren Sicherungsbedarf ergänzen. Zusammengehörige Stände und passende Versionen sind wichtig.

### Anmelden und Funktion prüfen
Im bekannten Browserzugang mit einem berechtigten Konto anmelden. Eine vorhandene Datei öffnen und herunterladen. Falls Kalender oder Kontakte genutzt werden, auch sie testen. Eine erfolgreiche Anmeldung allein beweist nicht, dass die Dateiinhalte lesbar sind.

### Nach einer Wiederherstellung
Dateien und Datenbank müssen gemeinsam zurückgebracht werden. Beim Wiederanschließen von Clients kann ein älteres Serverbackup mit neueren lokalen Dateien kollidieren; die offizielle Anleitung enthält dafür besondere Maßnahmen. Die Betreuung legt den Ablauf fest, bevor Clients wieder synchronisieren.

**Offen für die Übergabe:** Host/ID, URL, Datenpfad, Datenbanktyp, externe Speicher, App-Liste, Sicherungsziel, letzter Test und verschlüsselungsabhängige Schlüssel. Sind Inhalte serverseitig verschlüsselt, gehört ihr tatsächlicher Entschlüsselungsweg zwingend in das getrennte Notfallpaket.

## Paperless: Dokumente finden und bewahren

Paperless-ngx kann die zentrale Dokumentenablage übernehmen. Diese Ausgabe erklärt Grundlagen; tatsächliche Installation, Rechte und Intake werden vor Ort abgenommen.

### Was Paperless-ngx macht
Paperless übernimmt Dateien, erkennt Text per OCR und macht ihn durchsuchbar. Titel, Dokumentdatum, Korrespondent, Dokumenttyp und Tags unterstützen das Wiederfinden. OCR kann Fehler machen; wichtige Angaben am Original prüfen. Alte und neue Dokumente können gemischt importiert werden; das erkannte Datum bei Bedarf korrigieren.

Die installierte Version, LXC-ID, Bridge, Adresse und persistenten Pfade sind standortspezifisch. Eine Roadmap oder ein Feature-Branch ist kein Nachweis einer abgenommenen Installation. Den tatsächlich freigegebenen Installations- und Ingest-Runbook verwenden.

### Anwendung, Datenbank und Hintergrundaufgaben
Ein Aufbau mit Podman/Quadlet kann Paperless, PostgreSQL und Valkey/Redis trennen. PostgreSQL hält strukturierte Metadaten; Valkey/Redis vermittelt Hintergrundarbeit. Dokumente und Datenbank müssen außerhalb austauschbarer Images erhalten bleiben. Eine erreichbare Seite beweist noch keinen erfolgreichen Import.

### Privater Bereich, Eltern und Familie
Benutzer, Gruppen und Dokumentrechte bestimmen die Sichtbarkeit. Tags sind Suchmerkmale, keine Zugriffssperre. Persönliche Abrechnungen gehören in einen passend berechtigten privaten Bereich. Allgemeines Wissen kann bewusst der Familie freigegeben werden. Die Berechtigung mit einem tatsächlichen Kinder-/anderen Benutzerkonto prüfen, einschließlich Suche, Download, Vorschau und API.

Scan-Eingänge können in Benutzer-Homes liegen; ein technischer Sync-Benutzer erhält nur die benötigten Leserechte, keine allgemeinen Administratorrechte. Eigentümer und Zielberechtigungen müssen aus der überprüften Quelle übernommen werden. Fehlende oder unklare Zuordnung darf keinen Import in einen allgemeinen Bereich auslösen.

### Dateien und E-Mail übernehmen
Synchronisation erst nach abgeschlossenem Schreiben beziehungsweise mit geprüfter Stabilitäts-/Wartebedingung auslösen. Ein verzögerter Trigger allein beweist noch keine abgeschlossene Datei. Dubletten, Wiederholungen, Fehler und Neustarts gehören zur Abnahme. Quelldateien erst nach belegtem Import gemäß Aufbewahrungsregel entfernen.

Ein eigener IMAP-Eingangsordner kann E-Mails oder Anhänge importieren. Verschieben, Markieren und Löschen hängen von der Regel ab. Eine beliebige Ordnerbewegung ist noch kein Archivierungsnachweis.

### KI und Zugriff
Eine angeschlossene KI darf nur die Dokumente abrufen, die der anfragende Benutzer lesen darf. Gemeinsame Administrator-Tokens, geteilte Suchindizes oder Antwort-Caches können diese Grenze unterlaufen. Netzwerk-/RADIUS-Anmeldung ist kein automatischer Nachweis einer Web-SSO-Sitzung. Vor Freigabe Identitätszuordnung und positive wie negative Zugriffstests prüfen.

### Export und Wiederherstellung
Der Document Exporter sichert Dokumente, Vorschaubilder, Metadaten und Datenbankinhalte. Laut aktueller Projektanleitung benötigt der Import denselben Paperless-Versionsstand; API-Tokens müssen neu erzeugt werden. Standortkonfiguration und Zugangsmaterial gesondert sichern. Ein isolierter Restore-Test gehört vor die produktive Ablage wichtiger Originale.


## EVCC: Laden mit einer Steuerinstanz

EVCC koordiniert das Laden mit Fahrzeug, Wallbox und Energiedaten. Für die Übernahme zählt sowohl die Ladbarkeit als auch der Erhalt der Einstellungen und Historie.

### Die beteiligten Systeme
Die **Wallbox** liefert Strom an das Auto. **EVCC** entscheidet anhand von Modus und Messwerten, wann beziehungsweise wie geladen wird. **Zähler** liefern Bezugs-, Erzeugungs- oder Speicherwerte. Das Fahrzeug kann eigene Zeitpläne und Begrenzungen haben.

In Bergen ist ein go-eCharger angebunden. EVCC steuert ihn laut Projektdokumentation direkt über dessen Netzwerkzugang. MQTT liefert zusätzliche Daten für Homey; ein MQTT-Ausfall muss deshalb nicht automatisch die direkte EVCC-Wallbox-Steuerung verhindern.

### Nur ein aktiver Controller
Das Projekt dokumentiert eine erfolgreiche EVCC-Migration. Die aktive Instanz und deren ID müssen im privaten Inventar erfasst werden. Der alte Dienst bleibt gestoppt und deaktiviert. Den alten Dienst nicht parallel starten: Zwei Instanzen könnten widersprüchliche Steuerbefehle auslösen.

Die bekannten dauerhaften Daten sind `/etc/evcc.yaml`, sofern Dateikonfiguration genutzt wird, und `/var/lib/evcc/evcc.db` für UI-Einstellungen und Historie. Beide können private Angaben enthalten und gehören nicht ins öffentliche Git.

### Wenn das Auto nicht lädt
- Ladekabel und Steckverbindung normal prüfen; keine elektrischen Gehäuse öffnen.
- Wallboxstatus, EVCC-Modus, Ziel-Ladestand und Fahrzeugzeitplan ansehen.
- Plausibilität der Messwerte prüfen: Wird ein Gerät als offline angezeigt? Stimmen Leistungswerte ungefähr?
- Mit der Betreuung einen erlaubten manuellen Ladeweg über die Herstellerbedienung prüfen und dokumentieren. Die konkrete Bedienung ist hier noch nicht bekannt.

Ein PV-Modus kann bei zu wenig Überschuss absichtlich nicht laden. Eine falsche Uhrzeit, ein nicht erreichbarer Zähler oder ein eigener Fahrzeugplan können ein anderes Verhalten verursachen.

### Nach Eingriffen prüfen
Die bekannte EVCC-Oberfläche nutzt üblicherweise Port 7070; die aktuelle URL im privaten Übergabebogen ergänzen. Historie, Fahrzeugzuordnung und Messwerte prüfen. Die betreute Abnahme umfasst anschließend einen realen kontrollierten Ladevorgang.

Ein Restore-Test läuft ohne Zugriff auf die Wallbox. Erst nach isolierter Prüfung darf genau eine Instanz wieder steuern.

## MQTT und Homey: Nachrichten zwischen Geräten

MQTT ist eine leichte Nachrichtenvermittlung für das Smart Home. Der zentrale Mosquitto-Broker verteilt veröffentlichte Werte an interessierte Geräte und Anwendungen.

### Eine Verteilung nach Themen
Ein **Publisher** veröffentlicht eine Nachricht. Ein **Subscriber** abonniert passende **Topics**. Der **Broker** ist die Verteilstation. Ein Topic sieht wie ein Pfad aus, ist aber keine Datei: zum Beispiel ein Messwert unter `evcc/…`.

Homey empfängt damit Werte von EVCC und go-eCharger. Laut Projekt veröffentlicht go-eCharger unter `go-eCharger/#`, EVCC unter `evcc/#`. Homey liest beide und darf unter `homey/#` schreiben.

### Konten und Rechte
Jede Anwendung beziehungsweise Geräteklasse hat einen eigenen technischen Benutzer. **ACLs** legen fest, welche Topics gelesen oder geschrieben werden dürfen. Ein richtiges Passwort reicht nicht, wenn das Topic nicht zur Berechtigung passt.

`#` steht für mehrere Topic-Ebenen, `+` für eine einzelne. Groß-/Kleinschreibung und Schreibweise zählen. `go-eCharger` und `go-echarger` können daher unterschiedliche Bedeutung haben; Kontoname und Topic sind zusätzlich voneinander unabhängig.

### Der bekannte Betrieb
Mosquitto kann im dedizierten MQTT-LXC laufen. Adresse und ID im privaten Inventar erfassen; der dokumentierte Listener verwendet Port 1883. Dieser Port ist im dokumentierten Betrieb unverschlüsselt und bleibt auf den vorgesehenen internen Netzen. Keine spontane öffentliche Freigabe einrichten.

Technische Benutzer werden vom Controller mit `tools/mqtt-user` verwaltet. Eine Passwortänderung muss auch in den betroffenen Clients ankommen. Die konkrete Änderung übernimmt die Betreuung; keine gemeinsamen Ersatzpasswörter verteilen.

### Bei fehlenden Smart-Home-Werten
Die Betreuung prüft im Broker-LXC:
```text
systemctl status mosquitto --no-pager
journalctl -u mosquitto -n 40 --no-pager
```
„not authorised“ weist auf Anmeldung oder ACL hin. Eine erfolgreiche Netzwerkverbindung beweist noch keine MQTT-Berechtigung. Gespeicherte **retained**-Nachrichten können älter sein; Zeit und aktueller Gerätestatus sind mitzuprüfen.

MQTT-Nachrichten sind kein vollständiges Familienarchiv. Dauerhafte Gerätekonfiguration, Benutzerrechte und gegebenenfalls Broker-Persistenz müssen gezielt gesichert werden.

---

[Inhalt](DE-Start.md) · [Quellen](DE-Sources.md) · [Private Übergabe vorbereiten](DE-Handover.md)
