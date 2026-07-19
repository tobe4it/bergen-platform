# Changelog

Alle wesentlichen Änderungen an der Bergen Platform werden in dieser Datei dokumentiert.

Das Format orientiert sich an "Keep a Changelog".

---

## [Unreleased]

### Hinzugefügt

#### Projektstruktur

- Ansible-Projektstruktur aufgebaut
- README.md erstellt
- ARCHITECTURE.md erstellt
- UPDATE.md erstellt
- TROUBLESHOOTING.md erstellt
- CHANGELOG.md angelegt

#### Proxmox

- Playbook `validate-proxmox.yml`
- Validierung der Proxmox-API
- Prüfung der Host-Erreichbarkeit
- Prüfung der Proxmox-Dienste
- Prüfung der Netzwerk-Bridges
- Prüfung der ZFS-Pools
- Prüfung des FQDN

#### Management

- Management-LXC `bp-controller`
- Python Virtual Environment
- Ansible installiert
- Vault eingerichtet
- SSH-Schlüssel eingerichtet
- Ansible-Konfiguration erstellt

#### LXC

- Generisches Playbook `create-lxc.yml`
- Unterstützung für beliebige Debian-LXCs
- DHCP für IPv4/IPv6
- vmbr2-Unterstützung
- Startup-Reihenfolge
- Unprivileged Container
- SSH Public Key
- Root-Passwort aus Ansible Vault

#### Rollen

Neue Rolle:

- `lxc_base`

Erste Funktionen:

- Installation von Basispaketen
- globale History-Suche über Pfeiltasten

#### KI

Neuer LXC:

- `bergen-ai`

Status:

- Debian 13 installiert
- Erstellung vollständig automatisiert
- Bootstrap erfolgreich abgeschlossen

#### Infrastruktur

Automatisierter Ablauf erfolgreich umgesetzt:

```
validate-proxmox
        ↓
create-lxc
        ↓
bootstrap-lxc
```

Erster vollständig automatisierter End-to-End-Deployment-Prozess erfolgreich abgeschlossen.

---

### Geändert

#### Netzwerk

- Umstellung aller generischen LXCs auf `vmbr2`
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

### Behoben

#### Proxmox

- Fehlerhafte `cmode`-Konfiguration
- Timeout beim Start neuer LXCs
- Netzwerkkonfiguration für VLAN 2
- API-Parameterformat für `net0`
- SSH-Key-Übernahme auf `bp-controller`

#### Ansible

- Rollenpfad korrigiert
- `meta/main.yml` validiert
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
