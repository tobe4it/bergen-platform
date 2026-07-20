# Bergen Platform

> Build your complete self-hosted infrastructure from scratch using Ansible.

The Bergen Platform is an Infrastructure-as-Code (IaC) project that automates the deployment and lifecycle management of a modern self-hosted environment.

Starting with an empty Proxmox VE host, the platform provisions Debian LXC containers, deploys services, configures networking, integrates authentication, and keeps everything reproducible through Ansible.

The long-term vision is a modular platform capable of deploying AI services, mail infrastructure, monitoring, messaging, collaboration tools and enterprise middleware from a single code base.

---

# Project Goals

The Bergen Platform follows four primary goals.

- Infrastructure as Code
- Fully automated deployments
- Reproducible environments
- Modular architecture

Every service should be deployable from an empty Proxmox VE installation using Ansible only.

---

# Current Status

Current release

```
v0.5.0
```

Implemented components

| Component | Status |
|-----------|--------|
| Proxmox validation | ✅ |
| LXC deployment | ✅ |
| Debian bootstrap | ✅ |
| AI LXC | ✅ |
| Ollama | ✅ |
| Open WebUI | ✅ |
| OpenLDAP authentication | ✅ |
| Documentation | ✅ |
| Semantic Versioning | ✅ |

---

# Architecture

```
                         GitHub

                            │

                     Bergen Platform

                            │

                   bp-controller (Ansible)

                            │

          ┌─────────────────┴─────────────────┐

      Proxmox VE                     Synology NAS

          │                               │

          │                        OpenLDAP Server

          │

      Debian LXCs

          │

 ┌────────┴─────────┬──────────────┐

 bergen-ai     mail-gateway    monitoring

          │

     Open WebUI

          │

       Ollama

          │

   Large Language Models
```

---

# Repository Layout

```
bergen-platform/

├── ansible/
│   ├── inventory.yml
│   ├── playbooks/
│   ├── roles/
│   ├── group_vars/
│   ├── host_vars/
│   └── requirements.yml
│
├── docs/
│
├── ARCHITECTURE.md
├── CHANGELOG.md
├── ROADMAP.md
├── TROUBLESHOOTING.md
├── UPDATE.md
├── README.md
└── LICENSE
```

---

# Deployment Workflow

Typical deployment flow

```
validate-proxmox.yml

        ↓

create-lxc.yml

        ↓

bootstrap-lxc.yml

        ↓

bootstrap-ai.yml

        ↓

Ready
```

---

# Components

## Infrastructure

- Proxmox VE
- Debian 13
- Linux Containers (LXC)
- VLAN capable bridges

## Automation

- Ansible
- Playbooks
- Roles
- Inventory
- Vault
- Templates

## Artificial Intelligence

- Ollama
- Open WebUI
- OpenLDAP authentication
- llama.cpp (planned)

## Identity

- Synology Directory Server
- OpenLDAP

## Future Components

- IBM MQ
- Mail Gateway
- Nextcloud
- Monitoring
- Backup
- Security
- Observium

---

# Documentation

| Document | Description |
|----------|-------------|
| README.md | Project overview |
| ARCHITECTURE.md | System architecture |
| CHANGELOG.md | Release history |
| ROADMAP.md | Planned features |
| UPDATE.md | Upgrade instructions |
| TROUBLESHOOTING.md | Common issues |

---

# Requirements

Minimum

- Proxmox VE 9
- Debian 13
- Python 3
- Ansible
- SSH access

Recommended

- Synology Directory Server
- GitHub
- VLAN capable network

---

# Installation

Clone the repository

```bash
git clone git@github.com:tobe4it/bergen-platform.git
```

Create a Python virtual environment

```bash
python3 -m venv .venv
```

Activate it

```bash
source .venv/bin/activate
```

Install Ansible dependencies

```bash
pip install -r requirements.txt
```

---

# Example Deployments

Validate the Proxmox host

```bash
ansible-playbook ansible/playbooks/validate-proxmox.yml
```

Create a Debian LXC

```bash
ansible-playbook ansible/playbooks/create-lxc.yml
```

Bootstrap the container

```bash
ansible-playbook ansible/playbooks/bootstrap-lxc.yml
```

Deploy the AI platform

```bash
ansible-playbook ansible/playbooks/bootstrap-ai.yml
```

---

# Roadmap

## v0.5.1

- Automatic LDAP user activation
- Open WebUI administration improvements

## v0.6.0

- Model management
- llama.cpp integration
- GPU improvements

## v0.7.0

- Mail Gateway
- Postfix
- Dovecot
- Rspamd

## v0.8.0

- IBM MQ
- MQ Client automation
- MQ Administration

## v0.9.0

- Monitoring
- Observium
- Backup
- Security

## v1.0.0

First stable Bergen Platform release

---

# Contributing

Issues, feature requests and pull requests are welcome.

---

# License

This project is licensed under the MIT License.

---

# Author

Thomas Bergen

---

> Infrastructure as Code.
>
> Fully reproducible.
>
> Self-hosted by design.

