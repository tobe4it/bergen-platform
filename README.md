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
- Ollama deployment
- OpenLDAP authentication
- Mosquitto MQTT deployment and per-client access management
- Postfix/Dovecot mail backend with LDAP identities and explicit aliases
- Pi-hole DNS filtering in a dedicated LXC
- Centralized configuration
- Semantic Versioning
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
|   +-- MQTT.md
|   +-- PIHOLE.md
|   +-- ROADMAP.md
|   +-- UPDATE.md
|
+-- ENGINEERING.md
+-- README.md
+-- ansible.cfg
```

---

## Documentation

Project documentation can be found in the **docs/** directory.

- ARCHITECTURE.md
- CHANGELOG.md
- MAIL.md
- MQTT.md
- PIHOLE.md
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

DNS Filtering

- Dedicated Pi-hole LXC behind the UniFi gateway
- Podman/Quadlet deployment with persistent Pi-hole state
- Synology DNS retained as the initial upstream/internal DNS authority
- Pi-hole DHCP and NTP disabled so routing/DHCP remain on UniFi

See **docs/PIHOLE.md** for deployment, stable addressing, validation and the
later UniFi DNS cutover.

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

v0.6.0

See **docs/CHANGELOG.md** for release history.

---

## License

See LICENSE.
