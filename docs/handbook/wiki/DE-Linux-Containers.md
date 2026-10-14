<!-- bergen-platform-handbook: managed -->
# Linux, SSH und Container

[Deutsch](DE-Start.md) | [English](EN-Linux-Containers.md)

**Öffentliche Ausgabe 1.0, 14.10.2026.** Beispiele ersetzen keine private Standortkonfiguration.

## Proxmox und LXC: mehrere Rechner in einem

Proxmox verwaltet den physischen Server und seine Gäste. Ein LXC ist eine getrennte Linux-Umgebung mit eigener Kennnummer, Netzwerk- und Speicherzuordnung.

### Die Ebenen auseinanderhalten
**Node/Host:** Proxmox-Host, der eigentliche Server. **LXC/CT:** ein Linux-Container auf diesem Host. **VM:** eine virtuelle Maschine mit eigenem Betriebssystemkern. In einem LXC kann zusätzlich Podman einzelne Anwendungen betreiben.

Eine **VMID** bezeichnet auch LXC-Gäste. Die Beispiel-ID 900 ist daher eine Verwaltungsnummer; sie hat nichts mit einer IP-Adresse zu tun. Name und ID müssen vor einem Eingriff zusammenpassen.

### Die Oberfläche als erster Zugang
Die übliche Proxmox-Oberfläche verwendet HTTPS-Port 8006. Mit einer reinen Beispieladresse ergibt sich `https://192.0.2.10:8006`. Erreichbarkeit und vertrauenswürdigen Zugang beim betreuten Erstzugang prüfen; keine unbekannte Zertifikatswarnung pauschal wegklicken.

Nach Anmeldung sieht die Betreuung links Datacenter, Node und Gäste. Beim ausgewählten Gast zeigen **Summary/Übersicht** Zustand und Ressourcen, **Resources/Ressourcen** die Zuordnung und **Console/Konsole** einen direkten Zugang. Menünamen können je nach Sprache und Version abweichen.

### Speicher und Mountpoints
Das **Root-Dateisystem** enthält Linux und Programme. Ein zusätzlicher **Mountpoint** stellt weiteren Speicher im Gast bereit. Ein zusätzlicher Paperless-Datenspeicher kann beispielsweise unter `/srv/bergen-paperless` eingebunden sein; den tatsächlichen Pfad privat erfassen.

**ZFS** ist das eingesetzte Speichersystem für bestimmte Datenträger. Ein **Snapshot** hält einen früheren Zustand im selben Speicher fest. Er ersetzt keine unabhängige Sicherung. Bei Bind-Mounts oder externem Speicher ist die Einbeziehung in Backups besonders zu prüfen.

### Was Angehörige ansehen können
Läuft der richtige Gast? Zeigt der Node eine Speicherwarnung? Ist die Platte voll? Der Status „running“ bestätigt den LXC, noch nicht die Gesundheit der Anwendung.

Start, Neustart und Wiederherstellung übernimmt die Betreuung mit Blick auf Abhängigkeiten und Sicherungen. „Stop“ entspricht keinem sauberen normalen Herunterfahren aller Programme. „Remove“ löscht den Gast; diese Funktion ist kein Reparaturversuch.

**Lernprobe:** Pi-hole-LXC läuft, aber DNS antwortet nicht. Welche nächste Ebene prüfen? Den Pi-hole-Anwendungscontainer und den Netzwerkpfad.

## Linux-Grundlagen ohne Vorwissen

Linux ist das Betriebssystem in den meisten Bergen-Gästen. Eine Konsole nimmt Textbefehle entgegen und zeigt Ergebnisse sowie Fehlermeldungen.

### Benutzer, Rechte und Pfade
**root** ist das Administratorkonto mit weitreichenden Rechten. **sudo** führt einen einzelnen Befehl mit zusätzlichen Rechten aus, sofern erlaubt. Ein normaler Benutzer ist für alltägliche Arbeit vorzuziehen.

`/` ist die oberste Ebene der Verzeichnisse. `/etc` enthält oft Konfiguration, `/var/lib` dauerhafte Programmdaten, `/var/log` Protokolle und `/home` Benutzerverzeichnisse. `~` meint das Zuhause des angemeldeten Benutzers. Groß- und Kleinschreibung kann unterschiedliche Dateien bezeichnen.

### Lesen und orientieren
Die folgenden Befehle verändern keine Konfiguration. Auf dem jeweils betroffenen Linux-System ausführen, nicht wahllos auf dem Proxmox-Host:
```text
hostname
whoami
pwd
ls -lh
df -h
free -h
```
`hostname` zeigt das Zielsystem, `whoami` den Benutzer, `pwd` das aktuelle Verzeichnis und `ls` dessen Inhalt. `df` zeigt freien Plattenplatz; `free` die Speichernutzung. Linux nutzt RAM auch als Cache, deshalb ist wenig „free“ allein kein Fehler.

### Ein Befehl besteht aus Teilen
In `ls -lh /var/log` ist `ls` das Programm, `-lh` sind Optionen und `/var/log` das Ziel. Leerzeichen trennen Teile; Anführungszeichen können Text zusammenhalten. Ein vorangestelltes `$` oder `#` in einem Beispiel ist meist die Eingabeaufforderung und wird nicht mitkopiert.

### Fehler lesen
„Permission denied“ deutet auf Rechte. „No such file“ auf einen fehlenden Pfad. „Command not found“ auf fehlende Software oder eine falsche Umgebung. Die genaue Zeile aufschreiben; danach nicht einfach stärkere Rechte hinzufügen.

**Ctrl+C** beendet viele laufende Vordergrundbefehle. In einer paginierten Ausgabe beendet **q** den Betrachter. Bei Passworteingaben sind oft keine Zeichen sichtbar; das ist beabsichtigt.

**Lernprobe:** Vor jeder technischen Arbeit `hostname` prüfen. Derselbe Befehl auf dem falschen System kann eine andere Bedeutung haben.

## SSH und sicherer Konsolenzugang

SSH ermöglicht eine verschlüsselte Konsole auf einem anderen Rechner. Sie müssen dabei wissen, wer sich auf welchem System anmeldet.

### SSH-Schlüssel verstehen
Ein Schlüsselpaar besteht aus einem **öffentlichen Schlüssel**, den ein Server kennen darf, und einem **privaten Schlüssel**, der geschützt bleiben muss. Eine Passphrase schützt die private Datei zusätzlich. Sie ist nicht automatisch das Passwort des Linux-Kontos.

Der **Hostschlüssel** gehört zum Server. Seine Prüfsumme hilft, das richtige Gegenüber zu erkennen. Bei einer neuen oder geänderten Hostschlüsselwarnung nicht blind zustimmen. Die Betreuung prüft den Fingerabdruck über einen unabhängigen bekannten Zugang.

### Die Bergen-Verwaltung
`bp-controller` ist die Verwaltungsstation. Ein mögliches interaktives Konto heißt `ansible`; Projektpfad und Benutzer werden für jedes Deployment privat erfasst. Das öffentliche Inventory kann für Automationszugriffe andere Benutzer nennen. Interaktive Anmeldung und Automationskonto daher getrennt erfassen.

Bei getrennten Netzen können Proxmox-vermittelte Zugriffe über `pct exec` Teil der Verwaltung sein. Damit wird innerhalb eines LXC ein Befehl ausgeführt, ohne jedem VLAN direkte SSH-Wege zu öffnen. Die Netztrennung bleibt bestehen.

### Beispiel: nur lesen
Die Nummer 900 ist ein reines Beispiel; vor den folgenden Befehlen die tatsächliche Gast-ID ermitteln.

Erst mit dem hinterlegten, freigegebenen Zugang auf Proxmox-Host anmelden. Danach dort ausführen:
```text
hostname
pct list
pct status 900
```
Erwartung: `hostname` passt zu Proxmox-Host. `pct list` zeigt IDs, Namen und Zustände; die gewählte ID muss zum beabsichtigten Gast gehören. 900 ist nur ein Beispiel und wird vor der Ausführung durch die bestätigte lokale ID ersetzt. Der Status ist nur der LXC-Status.

Für die Betreuung, nach Abgleich der ID:
```text
pct exec 900 -- hostname
pct exec 900 -- systemctl --failed --no-pager
```
Der erste Befehl identifiziert den Gast. Der zweite listet fehlgeschlagene systemd-Einheiten darin. Ein LXC ohne eingerichtete Paperless-Anwendung kann keine Paperless-Dienste anzeigen; das ist kein Anlass, spontan welche anzulegen.

### Ausgabe weitergeben
Nur die benötigten Ausschnitte weitergeben. Logs können Adressen, Benutzernamen oder Dokumenttitel enthalten. Private Schlüssel, Vault-Inhalte und komplette Konfigurationsdateien nicht in Chat oder Tickets kopieren.

## systemd: Programme starten zuverlässig

systemd organisiert Linux-Dienste. Es kennt ihren Zustand, Abhängigkeiten und gegebenenfalls regelmäßige Zeitpläne.

### Was ist eine Unit?
Eine **service-Unit** betreibt ein Programm. Eine **timer-Unit** löst regelmäßig eine Aufgabe aus. „active“ bedeutet aktuell aktiv; „enabled“ beschreibt bei gewöhnlichen Units die Startfreigabe. Ein Timer kann aktiv sein, während sein kurzlebiger Dienst gerade inaktiv ist.

„inactive“ bedeutet deshalb nicht immer „kaputt“. Neu vorbereitete Dienste können absichtlich deaktiviert sein. Die erwartete Rolle des Dienstes muss bekannt sein.

### Lesen statt verändern
Diese Beispiele passen zum nativen EVCC-Dienst und werden im aktuellen EVCC-LXC ausgeführt:
```text
systemctl status evcc --no-pager
systemctl is-active evcc
journalctl -u evcc -n 40 --no-pager
systemctl list-timers --all --no-pager
```
`status` zeigt Zustand und letzte Meldungen. `is-active` liefert eine kurze Antwort. `journalctl` liest das Journal, hier maximal 40 Einträge. Die Timerliste hilft bei planbaren Aufgaben wie Sicherungen und Zertifikaten.

### Neustart ist ein Eingriff
Ein Neustart unterbricht Arbeit und Verbindungen. Vorher richtigen Host, Dienst, erwarteten Zustand und aktuelle Fehlerausgabe prüfen. Bei Datenbanken und Ladesteuerung auch laufende Vorgänge berücksichtigen. Für einen bekannten einzelnen Dienst kann die Betreuung einen Neustart einplanen und anschließend dessen Funktion testen.

Ein kompletter Serverneustart betrifft viele Anwendungen gleichzeitig. Wiederholtes Neustarten ohne Diagnose kann Spuren verwischen und die Ursache verdecken.

### Zertifikats-Timer richtig bewerten
Ein erfolgreicher Timerlauf kann melden, dass noch kein Zertifikat erneuert werden musste. Dann ist nur der Ablauf dieses Aufrufs geprüft. Eine wirkliche automatische Erneuerung mit anschließender Verteilung und Dienstübernahme muss gesondert beobachtet werden.

**Lernprobe:** Ein Exportdienst ist inaktiv, sein Timer aktiv und der letzte Lauf erfolgreich. Muss das ein Fehler sein? Nein, regelmäßige Einmalaufgaben laufen zwischen zwei Terminen nicht dauerhaft.

## Podman und Quadlet: Programme in Paketen

Ein LXC ist die äußere Linux-Umgebung. Podman kann darin weitere Anwendungscontainer aus Images starten, etwa Pi-hole oder das MQ-Labor.

### Drei Teile eines Anwendungscontainers
Ein **Image** ist das ausgelieferte Programmpaket. Ein **Container** ist eine gestartete Instanz dieses Pakets. **Persistente Daten** liegen in eigens eingebundenen Verzeichnissen oder Volumes, damit sie einen Austausch des Containers überstehen.

Bei einem Update wird häufig das Image gewechselt, während Daten erhalten bleiben sollen. Ein neues Image allein enthält keine Familienunterlagen. „Alles neu starten“ und „Daten löschen“ sind deshalb sehr unterschiedliche Vorgänge.

### Quadlet verbindet Podman und systemd
Quadlet-Dateien beschreiben, wie der Container betrieben wird. Root-betriebene Konfiguration liegt üblicherweise in `/etc/containers/systemd/`. Aus beispielsweise `name.container` erzeugt systemd eine `name.service`.

Die erzeugte Service-Datei ist nicht die ursprüngliche Konfiguration. Änderungen gehören in die zuständige Vorlage beziehungsweise Quadlet-Datei. Der Autostart wird bei Quadlet über den Install-Abschnitt der Definition geregelt; ein normales `systemctl enable` ist für diese generierten Units nicht der richtige Weg.

### Die betreute Statusprüfung
Im richtigen LXC und mit dem Benutzer der betreffenden Podman-Instanz:
```text
podman ps
podman ps -a
systemctl --failed --no-pager
```
Der erste Aufruf zeigt laufende Container, der zweite auch gestoppte. Root und ein normaler Benutzer können unterschiedliche Podman-Container sehen. Ein leerer Befund allein beweist deshalb nicht, dass die Anwendung fehlt.

### Dauerhafte Daten erkennen
Die Betreuung dokumentiert für jeden Container Image-Version, eingebundene Pfade und Backup-Zuordnung. Bei Pi-hole müssen Einstellungen erhalten bleiben; bei MQ die Managerdaten. Paperless soll Dokumente und Datenbank dauerhaft getrennt vom austauschbaren Image ablegen.

Ein **Reverse Proxy** nimmt Webanfragen entgegen und leitet sie an eine interne Anwendung weiter. Er kann HTTPS/TLS betreuen, während die Anwendung auf einem anderen Port läuft. Bei einem Proxy-Dienst sind deshalb öffentliche Namen, TLS-Zuständigkeit und interne Ziele gemeinsam zu erfassen.

Keine Bereinigung von Volumes, kein automatisches „prune“ und kein Entfernen von Datenverzeichnissen als Fehlersuche. Zuerst feststellen, welche Daten zu welchem Dienst gehören und welche Sicherung existiert.

**Lernprobe:** Ein laufender LXC und eine leere Podman-Liste können zusammen auftreten: Der Dienst kann nativ laufen oder Podman unter einem anderen Benutzer betrieben werden.

---

[Inhalt](DE-Start.md) · [Quellen](DE-Sources.md) · [Private Übergabe vorbereiten](DE-Handover.md)
