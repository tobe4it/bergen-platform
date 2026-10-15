<!-- bergen-platform-handbook: managed -->
# Beobachtung, Wartung und Übernahme

[Deutsch](DE-Start.md) | [English](EN-Operations.md)

**Öffentliche Ausgabe 1.0, 14.10.2026.** Beispiele ersetzen keine private Standortkonfiguration.

## Syslog, Zeit und Beobachtung

Protokolle helfen, eine Störung zeitlich zu verstehen. Sie sind keine Datensicherung und lösen ohne eingerichtete Auswertung keinen Alarm aus.

### Zwei Orte für Meldungen
Das Linux-**Journal** enthält lokale systemd- und Dienstmeldungen. **Syslog** kann Meldungen an einen zentralen Sammler schicken. In Bergen speichert der Syslog-Dienst laut Role entfernte Meldungen nach Quell-IP unter `/var/log/remote/<sender-ip>.log`.

Die Basisrolle nennt TCP/UDP-Port 514 und eine konfigurierbare Aufbewahrung. Der aktuelle Wert und die tatsächlich angebundenen Geräte müssen vor Ort festgestellt werden. Ein im Projekt vorhandener Standardwert beweist noch keine wirksame Aufbewahrung im Betrieb.

### Uhrzeit ist eine Grundlage
**NTP** gleicht Uhren ab. Ohne passende Zeit sind Ereignisse schwer zuzuordnen; auch Zertifikate und Anmeldungen können scheitern. Zeitzone und UTC sind zu unterscheiden. Für eine Störung lokale Uhrzeit und Zeitzone notieren.

### So entsteht eine brauchbare Fehlerbeschreibung
- Was war erwartet, was ist tatsächlich passiert?
- Seit wann, mit welcher Uhrzeit und Zeitzone?
- Welche Geräte, Konten oder Netze sind betroffen?
- Was wurde zuletzt geändert?
- Was zeigen genau die Meldungen in diesem Zeitraum?

Die Betreuung kann eine eng begrenzte Journalabfrage verwenden:
```text
journalctl -u evcc -n 40 --no-pager
```
Das Beispiel liest den nativen EVCC-Dienst auf dessen Host. Für andere Dienste zuerst den richtigen Unit-Namen bestimmen. Große Komplettauszüge erschweren die Fehlersuche und können private Inhalte verraten.

### Weiterleitung nachweisen
Ein eingerichteter Syslog-Sender allein beweist keine Ankunft. Die Betreuung erzeugt bei Einrichtung eine harmlose Testmeldung, prüft sie am Empfänger und dokumentiert Zeit sowie Quelladresse. Queuing kann vorübergehende Ausfälle abfangen, garantiert aber keine unbegrenzte Historie.

### Monitoring ist eine zusätzliche Aufgabe
**Monitoring** prüft Zustände wie freien Speicher, Diensterreichbarkeit oder Zertifikatsablauf und meldet Abweichungen. Observium und weitere Auswertung sind im Projekt als Ausbau vorgesehen. Bis eine wirksame Alarmierung nachgewiesen ist, müssen regelmäßige Kontrollen bewusst organisiert werden.

## KI und Zusatzdienste

Diese Systeme haben für die schnelle Familienübernahme zunächst geringere Priorität. Ihre Daten und Abhängigkeiten müssen dennoch verstanden werden, bevor sie stillgelegt werden.

### Ollama und Open WebUI
Ollama betreibt lokale Sprachmodelle; Open WebUI ist die Browseroberfläche. Modell-Dateien, Einstellungen, Konten und Chatverläufe haben unterschiedliche Sicherungsbedarfe. Anmeldung und eine kurze Modellanfrage getrennt testen. KI-Ausgaben ersetzen keine technische Bestätigung einer Diagnose.

### Weitere Komponenten
Der dokumentierte Daytrading-Collector sammelt Daten und erzeugt Signale, er platziert keine Orders. Providerzugänge, Timer, Abonnements und tatsächliche Nutzung erfassen. Proxy-Regeln und optionale Monitoring-, Kafka- oder Analysekomponenten nach dem realen Deployment dokumentieren; Projektideen sind keine laufenden Dienste.


## Wartung mit wenig Überraschungen

Regelmäßige kleine Kontrollen sind leichter zu übernehmen als unvorbereitete große Änderungen. Zuständigkeit und Termin müssen klar sein.

### Ein vorgeschlagener Rhythmus
| Zeitpunkt | Kontrolle durch die benannte Betreuung |
| --- | --- |
| Wöchentlich | Backup-Ergebnisse und fehlende Jobs, freier Speicher, Gerätewarnungen, wichtige Dienste und Mailwarteschlangen |
| Monatlich | Zertifikatsablauf, Domain-/Gateway-Verträge, Updatehinweise, Warnungen und aktuelle Zuständigkeit |
| Nach Änderungen | Funktionstest, Backup und Rückkehrplan; Inventar und dieses Handbuch aktualisieren |
| Regelmäßig geplant | Wiederherstellung einer Stichprobe auf getrenntem Ziel; Umfang nach Wichtigkeit festlegen |

Dieser Rhythmus ist noch kein belegter laufender Kalender. Den passenden Turnus mit der Betreuung vereinbaren; regelmäßige erfolgreiche Prüfung und Alarmwege müssen nachvollziehbar sein.

### Ein Update in sieben Schritten
**1.** Aktuellen Zustand und Nutzerfunktion testen. **2.** Versionen und lokale Änderungen dokumentieren. **3.** Releasehinweise und Versionssprünge prüfen. **4.** Passendes, wiederherstellbares Backup bereithalten. **5.** Genau einen überschaubaren Dienst im Wartungsfenster ändern. **6.** Nachher Anmeldung und Funktion testen. **7.** Ergebnis und neue Version eintragen.

Ansible und Git bilden den nachvollziehbaren Weg für verwaltete Konfiguration. Manuelle Änderungen müssen in die zuständige Quelle zurückgeführt werden, sonst kann der nächste Lauf sie überschreiben.

### Rückkehr ist mehr als ein Git-Wechsel
Ein älterer Code-Commit setzt weder Datenbankmigrationen noch bereits geschriebene neue Daten zuverlässig zurück. Ein Rollback muss Konfiguration, Software und passende Daten gemeinsam berücksichtigen. Besonders bei Nextcloud und Paperless Versionskompatibilität prüfen.

### Editor und Kontrolle
Für betreute Änderungen ist bisher **vim** bevorzugt. Die Bedienung ist keine Voraussetzung für Angehörige. Wer ihn nutzt, sollte vor einer wichtigen Änderung an einer Testdatei üben: `i` für Eingabe, Esc für Befehlsmodus, `:q!` zum Verwerfen und `:wq` zum Speichern und Schließen.

Nach jeder Änderung „vorher/nachher“, Testergebnis und Datum dokumentieren. Für eine Übernahme zählt der verifizierte Zustand, nicht nur die Liste ausgeführter Befehle.

## Störungen und geordnete Übernahme

Die Familie darf sich entscheiden, die Umgebung weiterzubetreiben, betreuen zu lassen oder einzelne Funktionen schrittweise zu ersetzen.

| Symptom | Sichere erste Aktion / technische Richtung |
| --- | --- |
| Alles im Haus offline | Strom und Netzwerk ansehen; Router-/WAN-Störung eingrenzen, keine Werkseinstellungen |
| Internet geht, interne Namen nicht | Eingestellten DNS und Synology/Pi-hole prüfen |
| Mehrere Anmeldungen scheitern | LDAP, DNS, Zeit und TLS prüfen; Konten unverändert lassen |
| Seite erreichbar, Daten fehlen | Sync anhalten lassen, Originale bewahren, Datenbank/Storage und Backup prüfen |
| Nur ein Dienst gestört | Richtigen Host, Unit, Logs und letzten Eingriff ansehen |
| Platz knapp / Plattenwarnung | Schreiben begrenzen lassen, Sicherungslage prüfen; keine Datenbereinigung auf Verdacht |
| Zertifikatswarnung | Namen und Uhrzeit notieren, Betreuung prüft Vertrauenskette und Erneuerung |

### Erste Woche: Überblick und Zugriff
Betreuung bestimmen, Notfallzugänge testen, Geräte/Verträge erfassen und wichtige Inhalte lokalisieren. Tatsächlichen Mail-Postfachort und alle Sicherungsziele klären. Bereits laufende Dienste vorerst stabil halten.

### Danach: nachweisbar übernehmen
Die Betreuung stellt wichtige Daten isoliert wieder her und dokumentiert die Schritte. Familienmitglieder testen ihre normale Nutzung. Erst anschließend größere Updates, Migrationen oder die Übernahme der Administrationsrechte abschließen.

### Wenn ein Dienst ersetzt werden soll
Zuerst benötigte Inhalte, Konten, Freigaben, Geräte und externe Verträge erfassen. Daten exportieren, an einem neuen Ort öffnen und mit Stichproben vergleichen. Den neuen Weg mit den Beteiligten testen, bevor der alte Dienst entfällt.

Domains und Mailadressen erst aufgeben, wenn davon abhängige Kontowiederherstellungen umgestellt sind. DNS und LDAP nicht entfernen, solange aktive Dienste sie benötigen. Eine stillgelegte Ladesteuerung braucht einen verifizierten Ersatzweg zum Laden.

**Abschlusskriterium:** Die Familie kann die benötigten Funktionen nutzen, eine benannte Person kann Störungen bearbeiten und eine zweite Person kann wichtige Daten wiederherstellen. Dann wird aus einer persönlichen Bastelumgebung ein übergebbarer Betrieb.

---

[Inhalt](DE-Start.md) · [Quellen](DE-Sources.md) · [Private Übergabe vorbereiten](DE-Handover.md)
