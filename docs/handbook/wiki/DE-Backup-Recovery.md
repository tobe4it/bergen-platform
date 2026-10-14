<!-- bergen-platform-handbook: managed -->
# Sicherung und Wiederherstellung

[Deutsch](DE-Start.md) | [English](EN-Backup-Recovery.md)

**Öffentliche Ausgabe 1.0, 14.10.2026.** Beispiele ersetzen keine private Standortkonfiguration.

## Backups: eine Wiederherstellung vorbereiten

Eine Sicherung ist erst dann für die Übergabe belastbar, wenn sie ohne den laufenden Ursprungsdienst erfolgreich wiederhergestellt wurde.

### Fünf häufige Verwechslungen
**Synchronisation** überträgt auch Fehler und Löschungen. **RAID** schützt vor bestimmten Plattenausfällen. **Snapshots** liegen oft auf demselben gefährdeten Speicher. **Git** bewahrt Baupläne. Ein **Backup** soll einen früheren nutzbaren Datenstand unabhängig zurückbringen.

Mehrere davon sind sinnvoll; keiner ersetzt allein eine vollständige Wiederherstellung. Ein erfolgreiches Backup-Protokoll beweist außerdem nicht, dass alle wichtigen Mountpoints oder Anwendungen enthalten sind.

### Vier Teile müssen zusammenpassen
- **System:** Betriebssystem, Dienstversionen und Konfiguration.
- **Daten:** Dateien, Postfächer, Datenbanken und wichtige Historien.
- **Standort:** privates Inventory, lokale Variablen, Netze und externe Anbieter.
- **Zugang:** Entschlüsselung, Passphrasen, Notfallkonten und MFA-Weg.

Das Repository benennt Backup & Recovery weiterhin als Roadmap-Ausbauschritt. Ein konkreter vollständiger Sicherungsplan, Ziel und getesteter Restore sind aus den verfügbaren Angaben nicht belegt. Dieses Kapitel ist daher ein vorgeschlagener Rahmen, keine Behauptung über laufende Jobs.

### Ziele für den Familienbetrieb festlegen
**RPO** beschreibt, wie viel neuere Arbeit verloren gehen dürfte. **RTO** beschreibt, wie lange der Ausfall dauern darf. Beispiel zur Erklärung: RPO 24 Stunden und RTO zwei Tage bedeuten höchstens einen Tag verlorene Änderungen und zwei Tage Zeit für die Rückkehr. Das ist kein bereits vereinbartes Bergen-Ziel.

Für Mail und wichtige Dokumente konkrete Ziele gemeinsam festlegen. Sicherungen mit mehreren Ständen, eine Kopie außerhalb des Hauptsystems und einen nachweisbar erreichbaren Entschlüsselungsweg vorsehen. Verlust von Haus, NAS oder Administratorgerät mitdenken.

### Datenbanken konsistent sichern
Eine laufende Datenbank beliebig Datei für Datei zu kopieren kann unbrauchbar sein. Die Betreuung wählt eine zum Dienst passende Methode, etwa einen unterstützten Export oder eine abgestimmte System-/Datenbanksicherung. Versionen, Zeitpunkt und Schreibpause werden dokumentiert.

**Abnahmefrage:** Kann eine zweite Person mit Sicherung und Notfallpaket eine wichtige Datei beziehungsweise Mail auf einem getrennten Ziel öffnen?

## Was genau gesichert werden muss

Die folgende Matrix beschreibt den erforderlichen Umfang. Sie ist keine Liste nachgewiesener vorhandener Sicherungen.

| System | Inhalt und zusätzliche Prüfpunkte |
| --- | --- |
| UniFi / Telefonie | Konfigurationsexporte, VLAN-/Portplan, DHCP, DNS, Firewall, WAN und Telefonieangaben; Wiederanmeldung prüfen. |
| Synology / LDAP | Freigaben samt Inhalt, DSM-/Paketkonfiguration, Verzeichnisdienst und DNS; Paket-spezifischen Restore prüfen. |
| Proxmox / Proxmox-Host | Host-/Netz-/Storage-Konfiguration und passende Gäste; Host selbst wird nicht durch jeden Gastbackup gesichert. |
| bp-controller | Ganze Arbeitskopie inklusive ignorierter Dateien; Vault, SSH, benötigte Abhängigkeiten und echter Ausführungsweg. |
| Aktive Maildienste | Alle tatsächlichen Postfachorte, Aliasse, Regeln und Gateway-Konfiguration; Bergen-Backend insbesondere /var/vmail. |
| Nextcloud | Daten, Datenbank, Konfiguration und Anpassungen; externe Speicher/Apps und gegebenenfalls Schlüssel ergänzen. |
| Paperless | Nach Einrichtung Dokumente, Datenbank, Konfiguration, Export und Versionsstände; Intake-Zugang getrennt sichern. |
| EVCC / MQTT | evcc.db und ggf. evcc.yaml; MQTT-Konfiguration, Benutzer/ACL und benötigte Persistenz. |
| KI / MQ / Protokolle | Zu erhaltende Inhalte bewusst auswählen; MQ-Persistenz/PKI, KI-Konfiguration/Chats, relevante Protokolle. |

### Zusätzliche LXC-Speicher prüfen
Proxmox sichert zusätzliche Volume-Mountpoints nicht automatisch alle mit. Bei verwalteten Volumes kann die Backup-Option sie einbeziehen. Inhalte von Bind- und Device-Mounts werden nicht als normale Gastdaten mitgesichert und benötigen eine andere Sicherung.

Die Option `backup=1` für ein verwaltetes zusätzliches Volume ist ein Konfigurationshinweis, kein Nachweis eines durchgeführten Jobs. Im Backup-Log und einem Testrestore prüfen, ob alle erwarteten Dokumente und Datenbanken enthalten sind.

Für jede Matrixzeile privater Übergabebogen ausfüllen: **Ziel, Umfang, Zeitplan, Aufbewahrung, Verschlüsselung, letzter Erfolg, letzter Restore und Verantwortlicher**. Einen leeren oder nicht überprüften Punkt als offen behandeln. [R2, R5, N1, L1]

## Restore: zuerst auf einem getrennten Ziel

Ein Wiederherstellungstest soll zeigen, dass die Daten nutzbar sind. Er darf nicht gleichzeitig in den laufenden Familienbetrieb eingreifen.

### Vorgeschlagener Ablauf für die Betreuung
- **1. Bestand erhalten:** Laufendes System und vorhandene Sicherungen unverändert bewahren. Den gewünschten Datenstand und die Ursache des Ausfalls notieren.
- **2. Backup wählen:** Datum, Dienstversion, Vollständigkeit, Verschlüsselung und Lesbarkeit prüfen. Neuere lokale Dateien gesondert sichern.
- **3. Getrenntes Ziel planen:** Neue freie ID und getrennten Speicher wählen. Produktive IP, DNS-Namen, MAC-Adressen und Steuerzugänge nicht doppelt verwenden.
- **4. Netz vor Start isolieren:** Automatisches Senden, Mailabholung, Dokumentimport, Synchronisation und Wallboxsteuerung wirksam verhindern. Schon der erste Start kann solche Tätigkeiten auslösen.
- **5. Wiederherstellen:** Zur vorhandenen Version passende offizielle und standortspezifische Anleitung verwenden. Datenbanken und Dateien als zusammengehörigen Stand zurückbringen.
- **6. Inhalte prüfen:** Anmeldung, Stichproben und die spezifischen Funktionen prüfen. Erst danach eine geplante Umschaltung vorbereiten.
- **7. Ergebnis dokumentieren:** Zeitbedarf, fehlende Schritte, Datenstand und Prüfergebnis im privaten Übergabebogen festhalten.

### Funktionsprüfungen je Dienst
| Dienst | Beispiel für eine ausreichende Stichprobe |
| --- | --- |
| Mail | Alte und neue Nachricht, Anhang, Ordner und Lesestatus; kontrollierter Versand erst nach sicherer Umschaltung |
| Nextcloud | Datei öffnen und herunterladen; Freigaben sowie tatsächlich genutzte Kalender/Kontakte |
| Paperless | Original öffnen, Suche und Metadaten prüfen; eine neuere und eine ältere Datei |
| EVCC | Konfiguration und Historie ohne Steuerzugriff; echter Ladevorgang erst mit genau einer produktiven Instanz |
| LDAP / DNS | Erforderliche Konten, Gruppen und ausgewählte interne Namen korrekt wiederfinden |

### Produktiv zurückkehren
Die Betreuung legt fest, welcher Stand künftig führend ist und wie seit dem Backup hinzugekommene Daten übernommen werden. Originalsystem erst nach erfolgreicher Abnahme und vereinbartem Rückkehrfenster stilllegen.

Proxmox ermöglicht die Wiederherstellung über Oberfläche und für LXC über `pct restore`. Einen konkreten ausführbaren Restore-Befehl erst erstellen, wenn Backup, neue ID, Storage und Isolation bekannt sind. Ein falsches Ziel kann Daten überschreiben.

---

[Inhalt](DE-Start.md) · [Quellen](DE-Sources.md) · [Private Übergabe vorbereiten](DE-Handover.md)
