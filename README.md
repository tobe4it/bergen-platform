# Bergen Platform

Infrastructure as Code for reproducible self-hosted services on Proxmox VE.

The Bergen Platform is an opinionated automation framework built around Ansible
and Debian LXC containers. It provides a reproducible way to deploy, configure
and maintain infrastructure and AI services for private and homelab
environments.

The project focuses on repeatability, documentation and modular automation.

---

## Features

Current capabilities include:

- Proxmox VE automation
- Debian LXC deployment
- Generic LXC bootstrap
- Ansible role-based architecture
- Open WebUI deployment
- Internal Nginx HTTPS proxy with isolated SSH backend tunnels
- Ollama deployment
- OpenLDAP authentication
- Mosquitto MQTT deployment and per-client access management
- Postfix/Dovecot mail backend with LDAP identities and explicit aliases
- Scoped public-gateway Certbot renewal, MTA-STS IPv4/IPv6 and TLS operations runbook
- Pi-hole DNS filtering in a dedicated LXC
- EVCC charging control with guarded configuration/history migration
- Centralized remote Syslog forwarding
- Provider-neutral daytrading market-data collection
- Centralized configuration
- Paperless-ngx Synology group scan transfer, verified import and protected original archival ([runbook](docs/PAPERLESS-GROUP-OPERATIONS.md))
- Semantic Versioning
- Documented headless Proxmox/Synology Wake-on-LAN recovery fallback (no G3 guarantee)
- Complete project documentation

---

## Project Goals

- Infrastructure as Code
- Reproducible deployments
- Idempotent playbooks
- Modular architecture
- Documentation first
- Security by default
- Easy maintenance
- Version controlled infrastructure

---

## Repository Structure

```text
bergen-platform/
|
+-- ansible/
|   |
|   +-- group_vars/
|   +-- host_vars/
|   +-- inventory.yml
|   +-- playbooks/
|   +-- reports/
|   +-- roles/
|   +-- templates/
|
+-- docs/
|   |
|   +-- ARCHITECTURE.md
|   +-- CHANGELOG.md
|   +-- DAYTRADING.md
|   +-- MQTT.md
|   +-- PIHOLE.md
|   +-- ROADMAP.md
|   +-- UPDATE.md
- PROXMOX-POWER-RECOVERY.md
- PROXMOX-SYNOLOGY-WOL.md
|
+-- ENGINEERING.md
+-- README.md
+-- ansible.cfg
```

---

## Documentation

Project documentation can be found in the **docs/** directory.

User handbook for beginners and deployment handover:

- [Deutsch](docs/handbook/wiki/DE-Start.md)
- [English](docs/handbook/wiki/EN-Start.md)
- [Blank recovery printouts and wiki publishing](docs/handbook/README.md)

The handbook source is reviewed with this repository and can be published to
the GitHub Wiki. Only blank recovery templates are public; completed sheets and
private deployment inventories remain outside Git.

- ARCHITECTURE.md
- CHANGELOG.md
- DAYTRADING.md
- MAIL.md
- MAIL-TLS-OPERATIONS.md
- MQTT.md
- PIHOLE.md
- EVCC.md
- REVERSE-PROXY.md
- BERGEN-AI-PROXY.md
- ROADMAP.md
- UPDATE.md

Engineering guidelines are documented in:

- ENGINEERING.md

---

## Deployment Workflow

```text
Validate Infrastructure
        |
Create LXC
        |
Bootstrap LXC
        |
Deploy Services
        |
Validate Platform
```

---

## Current Platform

Infrastructure

- Proxmox VE
- Debian 13
- LXC Containers

Automation

- Ansible
- Roles
- Templates
- Vault
- Playbooks

AI

- Ollama
- Open WebUI

Identity

- OpenLDAP
- Synology Directory Server

Messaging / IoT

- Mosquitto MQTT broker
- Per-client authentication and topic ACLs
- `tools/mqtt-user` technical-user management

See **docs/MQTT.md** for deployment, client configuration, user management and troubleshooting.

Mail

- Internal Postfix/Dovecot backend behind an existing public gateway
- LDAP authentication for human and technical submission identities
- Mailbox provisioning restricted to the LDAP `Mailuser` group
- Declarative aliases and Send-as ownership

See **docs/MAIL.md** for architecture, deployment boundaries and migration.
See **[docs/MAIL-TLS-OPERATIONS.md](docs/MAIL-TLS-OPERATIONS.md)** for the
public gateway's Certbot certificate inventory, DNS-01/HTTP-01 procedures,
lineage-scoped reloads, IPv6 MTA-STS, quarantine/rollback and validation.
Gateway TLS health is not proof of completed backend migration.

DNS Filtering

- Dedicated Pi-hole LXC behind the UniFi gateway
- Podman/Quadlet deployment with persistent Pi-hole state
- Synology DNS retained as the initial upstream/internal DNS authority
- Pi-hole DHCP and NTP disabled so routing/DHCP remain on UniFi

See **docs/PIHOLE.md** for deployment, stable addressing, validation and the
later UniFi DNS cutover.

Charging Control

- Dedicated Debian 13 `bergen-evcc` LXC with a native, pinned EVCC package
- Migration-safe staging with the new service initially stopped
- Guarded transfer of `evcc.yaml` and `evcc.db` with checksums, SQLite
  validation and automatic source-service rollback on failure

See **docs/EVCC.md** for deployment, migration and cutover.

Market Data

- Dedicated Debian 13 daytrading LXC deployment
- Provider-neutral adapters for Alpaca, IBKR Client Portal and local replay
- Vault-backed credentials and Git-ignored site-local provider configuration
- Provider, session and mail test commands plus an optional systemd timer

See **docs/DAYTRADING.md** for deployment, local provider selection and
validation.

---

## Roadmap

Current development priorities:

- AI Platform improvements
- Monitoring (Observium)
- Backup & Recovery
- Security hardening
- Mail Platform automation

See **docs/ROADMAP.md** for the complete roadmap.

---

## Releases

The Bergen Platform follows Semantic Versioning.

Current release:

v0.15.0 — Bergen-AI family OIDC and four private chat profiles (2026-10-20)

See **[docs/CHANGELOG.md](docs/CHANGELOG.md)** for release history and
**[the Bergen-AI family chat operations runbook](docs/BERGEN-AI-CHAT-PROFILES-LIVE-OIDC.md)**
for reproducible Ansible commands, exact model/group ACLs, idempotent second
apply and outstanding child-access and revocation tests. The v0.15.0
documentation records a live functional deployment; it does **not** claim
complete child/login revocation E2E assurance or a verified backup restore.
Source-merge and Git tag/release publishing are separate steps.

---

## License

See LICENSE.
