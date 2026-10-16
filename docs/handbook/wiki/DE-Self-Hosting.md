<!-- bergen-platform-handbook: managed -->
# Von null zur eigenen IT: Lern- und Aufbaupfad

[Deutsch](DE-Start.md) | [English](EN-Self-Hosting.md)

**Für wen?** Sie möchten Dienste selbst betreiben, haben aber noch keinen Server, kein Proxmox und keinen Ansible-Controller. Hier beginnt der Weg. Sie können die Etappen einzeln absolvieren; eine vollständige Bergen-Installation ist keine Voraussetzung zum Lernen.

**Erstes Ziel:** Ein eigener Linux-Testgast, auf den Sie zugreifen können, mit einer kleinen Anwendung und einem nachgewiesenen Wiederherstellungsweg. Erst danach übernehmen Sie wichtige Alltagsdaten. Für eine bereits laufende Umgebung gelten stattdessen [Soforthilfe](DE-Emergency.md) und [Betrieb](DE-Operations.md).

## 1. Verstehen, was Sie übernehmen

Selbst betrieben bedeutet: Sie bestimmen Speicherort und Konfiguration und übernehmen Updates, Konten, Datensicherung und Störungsbehebung. Eine Anwendung kann auf dem eigenen Rechner laufen und trotzdem externe Dienste benötigen, etwa für Nachrichtenversand oder Zertifikate.

| Begriff | Im ersten eigenen Aufbau |
| --- | --- |
| Server | Ein Rechner, der eine Funktion bereitstellt; ein vorhandener geeigneter Testrechner kann genügen |
| Client | Ihr Browser, Smartphone oder anderer Rechner, der diese Funktion nutzt |
| Host und Gast | Der Host stellt Ressourcen bereit; eine VM oder ein LXC ist ein abgegrenzter Gast darauf |
| Dienst und Daten | Das Programm kann ersetzt werden; Dokumente, Datenbank und Einstellungen müssen erhalten bleiben |
| Lokal und öffentlich | Im Heimnetz erreichbar heißt noch nicht aus dem Internet erreichbar |
| Betrieb | Regelmäßig prüfen, aktualisieren, sichern und die Wiederherstellung beherrschen |

**Übung:** Schreiben Sie einen konkreten Wunsch auf, etwa „Dokumente im Heimnetz wiederfinden“. Notieren Sie, wer ihn nutzt, welche Daten entstehen und wie lange ein Ausfall erträglich wäre. Beginnen Sie mit genau einem Dienst und Testdaten.

## 2. Einen kleinen Lernaufbau planen

Zum Üben reichen ein Verwaltungsrechner mit Browser und Terminal sowie eine getrennte Linux-Testumgebung. Das kann zunächst eine VM auf einem vorhandenen Rechner sein. Für den späteren Bergen-Aufbau kommt Proxmox als eigener Virtualisierungshost hinzu. Synology, UniFi, VLANs, LDAP, eine eigene Domain und alle Anwendungen gleichzeitig sind keine Voraussetzung für die erste Linux-Übung. Einzelne Bergen-Rollen können solche vorhandenen Dienste jedoch voraussetzen.

Prüfen Sie vorhandene Hardware anhand der [Proxmox-Anforderungen](https://www.proxmox.com/en/products/proxmox-virtual-environment/requirements) und der geplanten Gäste. Die Mindestanforderungen des Hosts sind kein Ressourcenplan für alle Anwendungen. Berücksichtigen Sie RAM, Speicherplatz, Strombedarf und ein getrenntes Sicherungsziel. KI-Modelle sind ein späterer Ausbau und kein Maßstab für den ersten Lernserver.

Notieren Sie privat: Gerätename, Aufgabe, Verwaltungsadresse, Betriebssystem, Datenort und Sicherungsziel. Planen Sie Namen, Adressen und freien Speicher selbst; die Beispiele im Wiki sind keine gültige Standortkonfiguration. Ein VLAN ist ein logisch getrenntes Netz, eine Bridge ein virtueller Switch. Beides vertiefen Sie unter [Netzwerk und Identität](DE-Network-Identity.md).

**Weiter, wenn:** Sie den Testrechner eindeutig benennen können und keine produktiven Daten für die Übung benötigen.

## 3. Linux lernen, bevor Automation übernimmt

Installieren Sie in der Testumgebung ein zur geplanten Nutzung passendes, unterstütztes Linux. Für die Proxmox-Variante: offizielle [Installationsanleitung](https://pve.proxmox.com/pve-docs/chapter-pve-installation.html) lesen, Installationsmedium vorbereiten, Zielplatten bewusst auswählen und die Management-Netzwerkkonfiguration festlegen. **Der Proxmox-Installer löscht vorhandene Daten auf den ausgewählten Laufwerken.** Verwenden Sie hierfür ein dafür vorgesehenes Gerät oder leere Testlaufwerke.

Prüfen Sie anschließend die lokale Verwaltungsoberfläche, Uhrzeit und Netzwerkzugang. Eine Zertifikatswarnung bei der ersten Einrichtung verlangt eine unabhängige Prüfung der Serveridentität; TLS-Prüfungen nicht dauerhaft abschalten. Erstellen Sie danach über Proxmox einen Linux-Testgast mit dokumentiertem Speicher und Netzwerk. Eine VM hat einen eigenen Kernel; LXC teilt den Kernel des Hosts. Wählen Sie für spätere Anwendungscontainer die vom jeweiligen Runbook unterstützte Variante.

Lernen Sie im Gast: anmelden, Dateien finden, Benutzerrechte verstehen, Paketverwaltung verwenden, Dienststatus und Protokolle lesen. Die Befehle in [Linux und Container](DE-Linux-Containers.md) werden auf dem jeweils genannten Rechner ausgeführt. Die Proxmox-Konsole ist der Rückweg, wenn SSH zum Gast noch nicht funktioniert.

**Übung:** Legen Sie im eigenen Home-Verzeichnis eine Textdatei an, lesen Sie sie und finden Sie sie nach einer erneuten Anmeldung wieder. Prüfen Sie dann Hostname, freien Speicher und die Uhrzeit. Richten Sie SSH mit einem eigenen Schlüssel ein und prüfen Sie den Host-Fingerabdruck über die Konsole.

**Weiter, wenn:** Sie wissen, ob Sie gerade auf dem Host, einem Gast oder Ihrem Verwaltungsrechner arbeiten, und den Gast auch ohne funktionierendes SSH erreichen.

## 4. Eine erste Anwendung verstehen

Wählen Sie eine kleine Anwendung mit eigener offizieller Installationsanleitung, lokalem Testkonto und Testdaten. Installieren Sie sie ausschließlich im Testgast. Notieren Sie Version, Start-/Stoppweg, Port, Konfigurationsdatei und dauerhafte Datenpfade. Öffnen Sie nur den für den Test notwendigen Zugriff im lokalen Netz.

Testen Sie aus Sicht eines Nutzers: öffnen, anmelden, etwas speichern, abmelden, erneut anmelden und das Gespeicherte wiederfinden. Starten Sie den Gast kontrolliert neu und wiederholen Sie den Test. Ein laufender Prozess allein ist noch keine funktionierende Anwendung.

Für Bergen ist der [Pi-hole-Leitfaden](https://github.com/tobe4it/bergen-platform/blob/main/docs/PIHOLE.md) ein möglicher späterer Anwendungsweg: zunächst nur von einem Testclient gezielt abfragen. Den DNS-Server für den gesamten Haushalt erst nach erfolgreichen Tests umstellen. Mailserver, zentrale Anmeldung und die Migration des Familienarchivs folgen später, weil daran mehr Abhängigkeiten hängen.

**Weiter, wenn:** Sie erklären können, wo die Daten liegen und was nach einem Neustart startet.

## 5. Sichern und tatsächlich zurückholen

Lesen Sie [Backup und Restore](DE-Backup-Recovery.md), bevor die Anwendung wichtige Daten erhält. Sichern Sie Anwendungseinstellungen und Daten zusammen; bei einer Datenbank gehört ein konsistenter Sicherungsweg dazu. Ein Snapshot auf demselben Gerät ersetzt keine getrennte Sicherung.

Stellen Sie den Testgast oder die Anwendungsdaten an einem getrennten Ziel wieder her. Vermeiden Sie dabei doppelte IP-Adressen und unbeabsichtigte Verbindungen zu echten Konten oder Geräten. Öffnen Sie die wiederhergestellte Anwendung und prüfen Sie die Testdatei. Dokumentieren Sie Datum, Schritte, Ergebnis und benötigte Schlüssel. Die erste Übung gilt erst nach diesem Test als abgeschlossen.

**Weiter, wenn:** Sie wichtige Testdaten ohne den ursprünglichen Gast wiederfinden und erklären können, wie der Zugriff auf die Sicherung im Notfall möglich bleibt.

## 6. Bergen und Ansible schrittweise kennenlernen

Git speichert den Entwicklungsstand der Konfiguration. Ansible führt beschriebene Aufgaben auf ausgewählten Rechnern aus. Der **Controller** ist der Rechner, auf dem Ansible läuft; das **Inventar** benennt die Ziele. Die Grundlagen stehen unter [Automation und Geheimnisse](DE-Automation-Secrets.md).

Auf einem Verwaltungsrechner mit Git können Sie zunächst nur den öffentlichen Code ansehen:

```sh
git clone https://github.com/tobe4it/bergen-platform.git
cd bergen-platform
git status
git log -1 --oneline
```

Das installiert noch keine Plattform. Lesen Sie README, ENGINEERING und die Dokumentation des gewünschten Dienstes. Ein Klon bringt weder Ihre Geheimnisse noch eine passende private Standortkonfiguration mit.

**Der erste Controller ist ein eigener Einrichtungsschritt.** Beginnen Sie bei Bedarf mit einem manuell eingerichteten Linux-Rechner beziehungsweise einer VM und der [offiziellen Ansible-Einführung](https://docs.ansible.com/projects/ansible/latest/getting_started/index.html). Ansible muss bereits irgendwo laufen, bevor es einen weiteren Controller einrichten kann. Üben Sie zuerst nur gegen Ihren Testgast mit einem eigenen Lerninventar.

Die vorhandenen Playbooks `create-controller.yml` und `bootstrap-controller.yml` sind keine universellen Erstinstallationsbefehle. Der geprüfte Stand erwartet unter anderem lokale Proxmox-/Vault-Variablen beziehungsweise einen vorhandenen SSH-Schlüssel am ausführenden Rechner. Das Bootstrap-Playbook richtet außerdem weitreichendes passwortloses sudo ein. Proxmox-API-Aufrufe in den geprüften Controller-Playbooks deaktivieren die Zertifikatsprüfung; das ist keine empfohlene neue Vertrauenseinrichtung. Vor Einsatz müssen Verantwortliche diese Vorgaben, Rechte und TLS-Vertrauen passend zum eigenen Aufbau prüfen und anpassen. Siehe [geprüften Controller-Code](https://github.com/tobe4it/bergen-platform/blob/e9078b80c9bb3fed7b02a6b1749b6187b241350d/ansible/playbooks/bootstrap-controller.yml) und [Erzeugung des Controllers](https://github.com/tobe4it/bergen-platform/blob/e9078b80c9bb3fed7b02a6b1749b6187b241350d/ansible/playbooks/create-controller.yml).

Vor jedem echten Lauf: Ziele und Variablen prüfen, Syntax prüfen, betroffene Hosts auflisten und das Playbook lesen. `--check` ist nur eine zusätzliche Hilfe; Module und Playbooks unterstützen diesen Modus unterschiedlich. Nachher Nutzerfunktion und erneuten Lauf auf unerwartete Änderungen prüfen.

**Weiter, wenn:** Sie genau wissen, welcher Rechner verändert wird, wo Geheimnisse liegen und wie Sie den vorherigen Datenstand wiederherstellen.

## 7. Aus dem Labor einen kleinen Betrieb machen

Erweitern Sie in dieser Reihenfolge: stabile lokale Namen und Adressen; erste gesicherte Anwendung; wiederholbare Einrichtung; Protokolle und Wartung; weitere Benutzer und passende Rechte; erst dann zentrale Identität oder Zugriff von außen, falls benötigt. Jede Erweiterung erhält einen Funktionstest und einen Rückweg. Router-Portfreigaben sind kein notwendiger Teil des Einstiegs.

Behalten Sie den vorhandenen DNS-, Mail- oder Dateiweg, bis der Ersatz geprüft ist. Synology/UniFi beschreiben Teile der Referenzumgebung; andere Geräte benötigen passende eigene Konfiguration. Nehmen Sie keine identischen Gruppennamen, Netzwerke oder Pfade an.

**Fertig für den Alltag:** Ein anderer berechtigter Mensch kann sich anmelden, eine typische Aufgabe erledigen und anhand Ihrer Notizen Hilfe organisieren. Eine benannte Person prüft Updates und Sicherungen. Nutzen Sie dafür [Betrieb](DE-Operations.md) und [private Übergabe](DE-Handover.md).

---

[Inhalt](DE-Start.md) · [Architektur verstehen](DE-Architecture.md) · [Quellen](DE-Sources.md)
