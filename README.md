# Bergen Platform

> Infrastruktur als Code für die private Bergen Platform.

## Ziel

Die Bergen Platform ist eine vollständig reproduzierbare private Cloud-Plattform auf Basis von Proxmox VE.

Die gesamte Infrastruktur wird deklarativ mit Ansible beschrieben. Ein neuer Management-Controller oder Proxmox-Host soll jederzeit automatisiert neu aufgebaut werden können.

Grundprinzipien:

- Infrastructure as Code
- Git als Single Source of Truth
- reproduzierbare Installationen
- idempotente Playbooks
- möglichst keine manuellen Konfigurationsänderungen

---

# Projektstatus

## Aktueller Stand

### Management Controller

Der erste Management-Controller (`bp-controller`) kann vollständig automatisiert erzeugt werden.

Folgende Komponenten funktionieren bereits:

- Erstellung eines Debian-LXC auf Proxmox
- automatische Vergabe von CPU, RAM und Storage
- automatische Netzwerkkonfiguration
- DHCP-Unterstützung
- SSH Public Key Authentication
- Python Virtual Environment
- Ansible Controller
- Projektstruktur
- Vault-Unterstützung
- Rollenstruktur
- Validierung eines Proxmox Hosts

---

# Projektstruktur

```
bergen-platform/
│
├── ansible/
│   ├── group_vars/
│   │   └── all/
│   │       ├── proxmox.yml
│   │       └── vault.yml
│   │
│   ├── host_vars/
│   │
│   ├── inventory.yml
│   │
│   ├── playbooks/
│   │   ├── bootstrap-controller.yml
│   │   ├── create-controller.yml
│   │   ├── preflight-controller.yml
│   │   └── validate-proxmox.yml
│   │
│   ├── roles/
│   │   └── validation/
│   │       ├── tasks/
│   │       ├── defaults/
│   │       ├── handlers/
│   │       ├── meta/
│   │       ├── templates/
│   │       ├── files/
│   │       └── vars/
│   │
│   ├── templates/
│   └── reports/
│
├── ansible.cfg
└── README.md
```

---

# Playbooks

## create-controller.yml

Erstellt einen neuen Management-LXC auf einem Proxmox-Host.

Der Controller erhält:

- Debian LXC
- DHCP
- SSH Public Key
- Root Passwort
- Autostart
- Ressourcen gemäß group_vars

---

## bootstrap-controller.yml

Bereitet einen frisch installierten Controller für den Betrieb vor.

Aktuell:

- Python
- Python venv
- Ansible
- Community Collections
- Projektstruktur

Geplant:

- SSH Key Erzeugung
- known_hosts
- Git Clone
- automatische Initialisierung

---

## preflight-controller.yml

Prüft vor der Erstellung eines Controllers:

- VMID frei
- Template vorhanden
- Storage vorhanden
- Bridge vorhanden
- API erreichbar

---

## validate-proxmox.yml

Validiert einen Proxmox Host.

Aktuell werden geprüft:

- Verbindung
- FQDN
- Proxmox Version
- Proxmox Dienste
- ZFS Status
- Bridges

---

# Rollen

## validation

Erste produktive Rolle.

Sie enthält sämtliche Validierungen eines Proxmox Hosts.

Die Rolle dient gleichzeitig als Referenz für alle zukünftigen Rollen.

---

# Konfiguration

Alle projektspezifischen Einstellungen befinden sich ausschließlich unter

```
ansible/group_vars/all/
```

### proxmox.yml

Enthält sämtliche Infrastrukturparameter.

Beispiele:

- API Host
- Node
- VMID
- RAM
- CPU
- Netzwerk
- Bridge
- VLAN
- DHCP
- Storage

### vault.yml

Enthält ausschließlich verschlüsselte Informationen.

Beispiele:

- Root Passwort
- API Passwort
- LXC Passwort

---

# Sicherheitsprinzipien

Folgende Informationen werden niemals im Repository gespeichert:

- private SSH Schlüssel
- Passwörter
- API Tokens
- Zertifikate

Geheimnisse werden ausschließlich über Ansible Vault verwaltet.

---

# Entwicklungsprinzipien

Alle Änderungen erfolgen ausschließlich über:

- Playbooks
- Rollen
- Templates

Manuelle Änderungen auf Zielsystemen sind zu vermeiden.

---

# Roadmap

## Version 0.1

- [x] Projektstruktur
- [x] erster Management Controller
- [x] Vault
- [x] Validation Rolle

## Version 0.2

- [ ] vollständiger Bootstrap
- [ ] Git Integration
- [ ] automatische SSH Initialisierung
- [ ] Reports

## Version 0.3

- [ ] Proxmox Rolle
- [ ] Netzwerk Rolle
- [ ] Storage Rolle

## Version 0.4

- [ ] Mail Gateway
- [ ] Nextcloud
- [ ] Monitoring
- [ ] MQ

---

# Langfristiges Ziel

Ein vollständig automatisierter Aufbau der kompletten Bergen Platform.

Ein einzelner Befehl soll ausreichen, um eine komplette Infrastruktur inklusive Management Controller, Proxmox Hosts, Netzwerkdiensten und Anwendungen reproduzierbar bereitzustellen.

```
ansible-playbook site.yml
```
# Bergen Platform

Die Bergen Platform ist eine vollständig automatisierte, Ansible-basierte Private-Cloud-Plattform für Self-Hosting, KI, Monitoring und Infrastruktur.

## Projektziele

- Infrastruktur vollständig reproduzierbar
- Idempotente Ansible-Playbooks
- Dokumentierte Architektur
- Erweiterbar durch Rollen
- Git-Versionierung
- Lokale KI-Plattform mit Ollama und llama.cpp

---

# Aktueller Projektstatus

## Infrastruktur

### Proxmox Host

Status: ✅ Fertig

Enthält:

- validate-proxmox.yml
- SSH-Zugriff
- API-Anbindung
- Hostvalidierung
- ZFS-Prüfung
- Bridge-Validierung
- Dienstprüfung

---

### Management-LXC

Hostname

```
bp-controller
```

Status: ✅ Fertig

Enthält:

- Python Virtual Environment
- Ansible
- Projektstruktur
- Vault
- SSH-Schlüssel
- Inventory
- Rollen
- Playbooks

---

### Generisches LXC Deployment

Status: ✅ Fertig

Playbook

```
ansible/playbooks/create-lxc.yml
```

Unterstützt:

- Debian LXC
- DHCP
- IPv6
- vmbr2
- Startup-Reihenfolge
- SSH-Key
- Root-Passwort (Vault)
- Unprivileged Container

---

### Bootstrap Linux LXC

Status: ✅ Fertig

Playbook

```
ansible/playbooks/bootstrap-lxc.yml
```

Rolle

```
roles/lxc_base
```

Aktuell enthalten:

- Basispakete
- globale Bash-History-Suche
- erste Basiskonfiguration

Diese Rolle bildet zukünftig die Grundlage sämtlicher Linux-LXCs.

---

### KI-LXC

Hostname

```
bergen-ai
```

Status: ✅ Bereitgestellt

Enthält:

- Debian 13
- DHCP
- vmbr2
- Bootstrap erfolgreich

Noch offen:

- bootstrap-ai.yml
- Ollama
- llama.cpp
- Open WebUI

---

# Projektstruktur

```
bergen-platform/
├── ansible/
│   ├── inventory.yml
│   ├── group_vars/
│   ├── host_vars/
│   ├── playbooks/
│   ├── roles/
│   └── templates/
├── README.md
├── ARCHITECTURE.md
├── UPDATE.md
├── TROUBLESHOOTING.md
├── SECURITY.md
├── BACKUP.md
└── CHANGELOG.md
```

---

# Nächste Schritte

1. bootstrap-ai.yml
2. Ollama
3. llama.cpp
4. Open WebUI
5. erstes LLM
6. Observium
7. Mail Gateway
8. MQ
9. Nextcloud
10. GitHub Repository

---

# Langfristiges Ziel

Eine vollständig dokumentierte, reproduzierbare Private-Cloud-Plattform mit:

- Proxmox
- Ceph
- Ansible
- KI
- Monitoring
- Mail
- MQ
- Fileservices
- Automatisierung

Die komplette Plattform soll durch Ausführen weniger Playbooks auf neuer Hardware wiederhergestellt werden.
