# Bergen Platform Architecture

## Überblick

Die Bergen Platform ist eine vollständig automatisierte Private-Cloud-Plattform auf Basis von

- Proxmox VE
- Debian Linux
- Ansible
- Git
- ZFS

Alle Systeme werden reproduzierbar durch Ansible bereitgestellt.

---

# Architektur

```
                    Benutzer
                        │
                        ▼
                Git Repository
                        │
                        ▼
                 bp-controller
                (Ansible Control)
                        │
        ┌───────────────┼────────────────┐
        │               │                │
        ▼               ▼                ▼
   Proxmox Host    Linux-LXCs       Infrastruktur
        │               │                │
        ▼               ▼                ▼
  vmbr0 / vmbr2     Anwendungen     Monitoring
```

---

# Schichtenmodell

```
Layer 5  Anwendungen
──────────────────────────────────────

Open WebUI
Ollama
llama.cpp
Observium
Mailman
MQ
Nextcloud

──────────────────────────────────────

Layer 4  Bootstrap

bootstrap-ai.yml

bootstrap-lxc.yml

──────────────────────────────────────

Layer 3  Bereitstellung

create-lxc.yml

──────────────────────────────────────

Layer 2  Infrastruktur

validate-proxmox.yml

──────────────────────────────────────

Layer 1  Hardware

Proxmox VE
ZFS
Netzwerk
```

---

# Projektstruktur

```
bergen-platform/

README.md
ARCHITECTURE.md
CHANGELOG.md
UPDATE.md
SECURITY.md
BACKUP.md
TROUBLESHOOTING.md

ansible/

    inventory.yml

    group_vars/
    host_vars/

    playbooks/

        validate-proxmox.yml

        create-lxc.yml

        bootstrap-lxc.yml

        bootstrap-ai.yml

    roles/

        validation/

        lxc_base/

        ai/

        observium/

        mq/

        mail/

        nextcloud/
```

---

# Deployment-Reihenfolge

```
1

Proxmox installieren

        │

2

validate-proxmox.yml

        │

3

create-lxc.yml

        │

4

bootstrap-lxc.yml

        │

5

bootstrap-<rolle>.yml

        │

6

Produktivbetrieb
```

---

# Netzwerk

```
Management

192.168.20.0/24

vmbr2

│

├── bp-controller

├── bergen-ai

├── observium

├── mailman

├── mq

└── weitere Linux-LXCs
```

---

# Rollen

Jede Rolle besitzt dieselbe Struktur.

```
roles/

role/

    README.md

    defaults/

    files/

    handlers/

    meta/

    tasks/

    templates/

    vars/
```

Dadurch bleibt die Plattform konsistent.

---

# Designprinzipien

- Infrastructure as Code
- Idempotenz
- Wiederholbare Installationen
- Kleine, unabhängige Rollen
- Dokumentation vor Implementierung
- Versionsverwaltung mit Git
- Trennung von Infrastruktur und Anwendungen

---

# Aktuelle Architektur

Status

✅ Proxmox validierbar

✅ Management-LXC

✅ Generische LXC-Erstellung

✅ Linux-Bootstrap

✅ KI-LXC erstellt

🚧 bootstrap-ai.yml

📋 Ollama

📋 llama.cpp

📋 Open WebUI

📋 Observium

📋 MQ

📋 Mail Gateway

📋 Nextcloud

---

# Langfristiges Ziel

Die Bergen Platform soll auf neuer Hardware durch folgende Schritte vollständig reproduzierbar aufgebaut werden:

```
Proxmox installieren

↓

Git klonen

↓

Ansible Vault bereitstellen

↓

validate-proxmox.yml

↓

create-lxc.yml

↓

bootstrap-lxc.yml

↓

Anwendungsrollen

↓

Fertig
```

Es sollen keine manuellen Konfigurationsschritte erforderlich sein.
