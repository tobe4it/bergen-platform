<!-- bergen-platform-handbook: managed -->
# Netzwerk, DNS und Identität

[Deutsch](DE-Start.md) | [English](EN-Network-Identity.md)

**Öffentliche Ausgabe 1.0, 14.10.2026.** Beispiele ersetzen keine private Standortkonfiguration.

## Netzwerk verstehen: UniFi und VLANs

Ein Netzwerk liefert die Wege zwischen den Geräten. Eine IP-Adresse ist die Anschrift; eine Firewall entscheidet, welche Verbindungen diese Anschrift erreichen dürfen.

### Router, Switch, WLAN und VLAN
Ein Router verbindet Netze; Switches verteilen Kabelverbindungen; Access Points liefern WLAN. PoE versorgt bestimmte Geräte über das Netzwerkkabel mit Strom. UniFi kann Routing, DHCP, DNS-Zuweisung und Firewallregeln zentral verwalten. Eine vorhandene FRITZ!Box kann gesondert für Telefonie zuständig sein.

Eine IP-Adresse ist die Anschrift eines Geräts. DHCP verteilt Adressen und DNS-Einstellungen. Reservierungen halten die Adresse eines bestimmten Geräts stabil. DNS übersetzt Dienstnamen in IP-Adressen. Ein Subnetz beschreibt einen Adressbereich; /23 umfasst mehr Adressen als /24.

Ein VLAN trennt Geräte logisch. Die Nummer eines VLANs ist nicht automatisch Teil seiner IP-Adresse. Ein Switch-Portprofil und eine WLAN-Zuordnung bestimmen, welchem Netz ein Gerät angehört. Routing und Firewall legen anschließend die erlaubten Verbindungen zwischen den Netzen fest. Ein Gast kann absichtlich keinen internen Server erreichen.

### Öffentliches Beispiel, privater Netzplan
Adressen unter `192.0.2.0/24` und Namen unter `example.test` sind nur Dokumentationsbeispiele. Sie werden nicht als reale Standortkonfiguration übernommen. Die tatsächlichen VLANs, Subnetze, Reservierungen, Portprofile und Regeln stehen in einem privaten Netzplan.

In der referenzierten Bergen-Konfiguration übernimmt UniFi DHCP; Pi-hole-DHCP und -NTP bleiben deaktiviert. Der DNS-Pfad ist gesondert abzugleichen. Ob diese Einstellungen schon im eigenen Netz gelten, muss die Betreuung feststellen.

### Ausfall eingrenzen
Zuerst ein zweites Gerät im selben Netz, dann eine bekannte Kabelverbindung testen. Mobilfunk liefert einen unabhängigen Internetvergleich. In UniFi zunächst Geräteübersicht, Verbindungszustand und IP ansehen. Vor Änderungen Konfigurationsexport und Rückkehrweg prüfen. Keine allgemeine Freigabe zwischen allen VLANs als Reparatur einsetzen.


## DNS und Pi-hole: Namen finden

Wenn ein Dienstname nicht mehr aufgelöst wird, wirkt die Anwendung unerreichbar. Der Dienst selbst kann dabei weiterhin laufen.

### So funktioniert eine Namensabfrage
Ein Gerät fragt einen DNS-Resolver nach der Adresse eines Namens. Der Resolver beantwortet lokale Namen oder fragt weiter. **Pi-hole** kann unerwünschte Ziele filtern. **Synology DNS** ist laut Projekt zunächst der nachgelagerte Resolver und die interne Namensquelle.

Der dokumentierte Pfad lautet: Client über UniFi-Netz → Pi-hole → Synology DNS → externe Auflösung. Ob alle VLANs bereits Pi-hole verwenden, ist vor Ort zu prüfen. UniFi stellt DHCP bereit; Pi-hole-DHCP ist im Projekt ausgeschaltet.

### DNS ist nicht die Firewall
Eine erfolgreiche Namensauflösung beweist nur, dass eine Adresse gefunden wurde. Der Port kann trotzdem blockiert sein. Eine Blockliste kann umgekehrt einzelne Seiten betreffen, während der restliche Internetzugang funktioniert.

**Split-DNS** bedeutet: Derselbe Name kann intern auf eine private Adresse und außerhalb des Hauses auf eine öffentliche Adresse zeigen. Bei Mail und TLS den bisherigen Dienstnamen verwenden; ein Wechsel auf die nackte IP kann einen Zertifikatsfehler auslösen.

### Einfache Diagnose auf einem Rechner mit nslookup
```text
nslookup ldap.example.test
nslookup ldap.example.test 192.0.2.53
```
Der erste Befehl fragt den eingestellten Resolver; der zweite den Beispiel-Pi-hole. Die zweite Adresse muss noch zum aktuellen Bestand passen. Notieren: Welcher Server antwortet? Welche Adresse liefert er? Gibt es Zeitüberschreitungen?

Falls Pi-hole antwortet, interne Namen aber fehlen, prüft die Betreuung Synology DNS und Weiterleitungen. Pi-hole und Synology dürfen nicht gegenseitig dieselbe Abfrage endlos weiterreichen. Wenn nur bestimmte Inhalte fehlen, zuerst Filter- und SafeSearch-Regeln ansehen.

### Wichtige Betriebsregel
DNS-Server brauchen eine verlässliche Adresse. Eine neue Reservierung nicht ohne Abgleich von MAC-Adresse, bisheriger Nutzung und Inventory setzen. Externe DNS-Adressen als spontaner Ersatz können interne Namen und Familienfilter umgehen.

**Lernprobe:** „IP erreichbar, Name nicht“ weist zuerst auf DNS. „Name löst auf, Anmeldung scheitert“ weist eher auf Dienst, LDAP oder Rechte.

## Synology und LDAP: Speicher und Konten

Die Synology stellt zentrale Aufgaben bereit. Eine Anmeldung kann von ihrem Verzeichnisdienst abhängen, auch wenn die betroffene Anwendung auf Proxmox-Host läuft.

### NAS, RAID und Dateien
Ein **NAS** ist ein Rechner mit Speicherfreigaben und zusätzlichen Diensten. **DSM** ist die Synology-Verwaltungsoberfläche. Dort sieht die Betreuung Speicherzustand, Freigaben, Benutzer und installierte Pakete.

Ein **RAID** kann den Ausfall einzelner Platten abfangen. Es schützt nicht zuverlässig vor Löschen, Schadsoftware oder Verlust des gesamten Geräts. Bei einer Plattenwarnung zuerst den Zustand und vorhandene Sicherungen dokumentieren. Keine Platte auf Verdacht herausziehen.

Eine **Freigabe** stellt einen Ordner anderen Geräten zur Verfügung. SMB und NFS sind gängige Zugriffsprotokolle. Rechte begrenzen den Zugriff; eine erreichbare Freigabe bedeutet nicht, dass jeder Benutzer alle Dateien lesen darf. Auch eingebundene NAS-Ordner können außerhalb eines LXC-Backups liegen.

### Was LDAP macht
LDAP ist ein Verzeichnis für Konten und Gruppen. **Authentifizierung** beantwortet „Wer bist du?“. **Autorisierung** beantwortet „Was darfst du?“. Ein Konto kann sich anmelden dürfen, ohne ein Postfach oder Zugriff auf alle Dateien zu besitzen.

**LDAPS** schützt die Verbindung durch TLS. Ein reiner Beispielname lautet `ldap.example.test`, der übliche LDAPS-Port 636. Andere unpassende Dienstnamen können für Zertifikatsprüfungen unpassend sein. Interne Verzeichnisnamen müssen dadurch nicht umbenannt werden.

### Gruppen und technische Identitäten
Die Gruppe **Mailuser** wird im Mail-Backend zur Postfachberechtigung genutzt. Technische Konten für Geräte können andere Rechte haben. Ein **Bind-Konto** erlaubt einer Anwendung die Verzeichnissuche; seine Zugangsinformation liegt getrennt geschützt vor.

Synology LDAP Server und ein AD-basierter Directory Server haben unterschiedliche Eigenschaften. Welches Paket tatsächlich die Konten führt, muss im Übergabebogen festgehalten werden. Beide nicht als austauschbare Namen behandeln.

### Wenn mehrere Anmeldungen gleichzeitig ausfallen
- Prüfen, ob DNS den LDAP-Namen auflöst und die Synology erreichbar ist.
- Uhrzeit, Zertifikatsgültigkeit und Status des tatsächlichen Verzeichnisdienstes prüfen lassen.
- Mit einem bekannten, berechtigten Konto genau einen Anmeldeversuch testen.
- Konten und Gruppen nicht neu erzeugen, bevor die Ursache bekannt ist. Neue gleichnamige Konten müssen nicht dieselbe interne Identität besitzen.

Für Notfälle braucht die Betreuung erreichbare lokale Administrationszugänge für die Grundsysteme, die nicht allein vom ausgefallenen LDAP abhängen. Ihre Existenz und der getrennte Aufbewahrungsort werden im privaten Übergabebogen dokumentiert.

---

[Inhalt](DE-Start.md) · [Quellen](DE-Sources.md) · [Private Übergabe vorbereiten](DE-Handover.md)
