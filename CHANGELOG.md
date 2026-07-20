# Changelog

Alle wesentlichen Änderungen an der Bergen Platform werden in dieser Datei dokumentiert.

Das Format orientiert sich an **Keep a Changelog** und das Projekt folgt **Semantic Versioning (SemVer)**.

---

## [0.5.0] - 2026-07-20

### Added

#### LDAP
- OpenLDAP-Integration für Open WebUI
- LDAP-Authentifizierung gegen Synology Directory Server
- Unterstützung für Anonymous Bind
- Unterstützung für Application Bind
- LDAP Search Filter konfigurierbar
- Automatische Generierung der Open-WebUI-LDAP-Konfiguration per Ansible

#### Open WebUI
- LDAP-Konfiguration vollständig über Umgebungsvariablen
- Unterstützung für automatische Benutzeranlage bei erfolgreicher LDAP-Anmeldung

### Changed

- Open WebUI wird vollständig über Ansible konfiguriert.
- LDAP-Konfiguration in eigene Ansible-Rolle ausgelagert.
- LDAP-Konfiguration vollständig templatisiert.

### Verified

- Verbindung zum Synology Directory Server erfolgreich.
- LDAP-Suche erfolgreich getestet.
- Anmeldung mit LDAP-Benutzern erfolgreich.
- LDAP Search Filter wird korrekt an Open WebUI übergeben.
- Benutzer werden automatisch in Open WebUI angelegt.

### Known Issues

- Neue LDAP-Benutzer müssen derzeit einmalig durch einen Administrator aktiviert werden.
- Open WebUI informiert Administratoren derzeit nicht automatisch über wartende Benutzer.
- Nach der Aktivierung funktioniert die LDAP-Anmeldung dauerhaft.

---

## [Unreleased]

### Added

#### Projektstruktur

- Ansible-Projektstruktur aufgebaut
- README.md erstellt
- ARCHITECTURE.md erstellt
- UPDATE.md erstellt
- TROUBLESHOOTING.md erstellt
- CHANGELOG.md angelegt

#### Proxmox

- Playbook 
- Validierung der Proxmox-API
- Prüfung der Host-Erreichbarkeit
- Prüfung der Proxmox-Dienste
- Prüfung der Netzwerk-Bridges
- Prüfung der ZFS-Pools
- Prüfung des FQDN

#### Management

- Management-LXC 
- Python Virtual Environment
- Ansible installiert
- Vault eingerichtet
- SSH-Schlüssel eingerichtet
- Ansible-Konfiguration erstellt

#### LXC

- Generisches Playbook 
- Unterstützung für beliebige Debian-LXCs
- DHCP für IPv4/IPv6
- vmbr2-Unterstützung
- Startup-Reihenfolge
- Unprivileged Container
- SSH Public Key
- Root-Passwort aus Ansible Vault

#### Rollen

Neue Rolle:

- 

Erste Funktionen:

- Installation von Basispaketen
- globale History-Suche über Pfeiltasten

#### KI

Neuer LXC:

- 

Status:

- Debian 13 installiert
- Erstellung vollständig automatisiert
- Bootstrap erfolgreich abgeschlossen

#### Infrastruktur

Automatisierter Ablauf erfolgreich umgesetzt:



Erster vollständig automatisierter End-to-End-Deployment-Prozess erfolgreich abgeschlossen.

---

### Changed

#### Netzwerk

- Umstellung aller generischen LXCs auf 
- Wegfall der VLAN-Tags innerhalb der LXC-Konfiguration
- Nutzung VLAN-fähiger Bridges

#### Architektur

- Trennung zwischen
  - Playbooks
  - Rollen
  - Variablen
  - Inventory
- Einführung generischer LXC-Deployment-Playbooks

---

### Fixed

#### Proxmox

- Fehlerhafte -Konfiguration
- Timeout beim Start neuer LXCs
- Netzwerkkonfiguration für VLAN 2
- API-Parameterformat für 
- SSH-Key-Übernahme auf 

#### Ansible

- Rollenpfad korrigiert
-  validiert
- Inventory-Struktur verbessert
- Bootstrap erfolgreich auf neuem Controller getestet

---

## Roadmap

- bootstrap-ai.yml
- Ollama
- llama.cpp
- Open WebUI
- Observium
- Mail Gateway
- Nextcloud
- IBM MQ
- GitHub Repository
