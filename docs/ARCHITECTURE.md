# Bergen Platform Architecture

## Overview

The Bergen Platform is a modular Infrastructure-as-Code (IaC) project based on
Ansible. It automates the deployment and lifecycle management of self-hosted
services running on Proxmox VE using Debian LXC containers.

The architecture separates infrastructure, automation, services and
documentation into reusable components.

## High-Level Architecture

GitHub
  |
  +-- Bergen Platform Repository
        |
        +-- bp-controller (Ansible Controller)
              |
              +-- Proxmox VE
                    |
                    +-- Debian LXCs
                          |
                          +-- bergen-ai
                          |     +-- Ollama
                          |     +-- Open WebUI
                          |     +-- OpenLDAP Authentication
                          |
                          +-- bergen-mail
                          |     +-- Postfix submission and local delivery
                          |     +-- Dovecot LMTP and IMAPS
                          |     +-- LDAP authentication
                          |
                          +-- monitoring

Public Infrastructure
  |
  +-- mail-gateway
        +-- Public SMTP edge policy
        +-- DKIM and internet delivery
        +-- Private relay to bergen-mail

Synology NAS
  |
  +-- OpenLDAP Directory
  +-- Storage
  +-- Backup

## Repository Structure

bergen-platform/
|
+-- ansible/
|   |
|   +-- playbooks/
|   +-- roles/
|   +-- templates/
|   +-- group_vars/
|   +-- host_vars/
|   +-- inventory.yml
|   +-- requirements.yml
|   +-- UPDATE.md
|
+-- docs/
|   |
|   +-- ARCHITECTURE.md
|   +-- ROADMAP.md
|   +-- TROUBLESHOOTING.md
|   +-- CHANGELOG.md
|   
+-- README.md
+-- LICENSE


## Design Principles

- Infrastructure as Code
- Reproducible deployments
- Modular Ansible roles
- Idempotent playbooks
- Documentation first
- Security by default

## Deployment Workflow

validate-proxmox.yml
        |
create-lxc.yml
        |
bootstrap-lxc.yml
        |
bootstrap-ai.yml
        |
Configured platform

## Current Components

Infrastructure
- Proxmox VE
- Debian 13
- LXC

Automation
- Ansible
- Roles
- Playbooks
- Templates
- Vault

Identity
- Synology Directory Server
- OpenLDAP

Mail
- Postfix/Dovecot backend LXC
- LDAP-backed SMTP authentication
- Mailuser-only mailbox provisioning
- Existing external edge gateway without user database

AI
- Ollama
- Open WebUI

Planned
- llama.cpp
- IBM MQ
- Monitoring
- Nextcloud
- Backup
- Security

## Version

Current architecture baseline: v0.6.0
