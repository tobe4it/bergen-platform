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

v0.5.1

See **docs/CHANGELOG.md** for release history.

---

## License

See LICENSE.

