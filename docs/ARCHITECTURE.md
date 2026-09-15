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
                          +-- bergen-pihole
                          |     +-- Pi-hole DNS filtering
                          |     +-- Podman / Quadlet
                          |
                          +-- bergen-evcc
                          |     +-- Native EVCC service
                          |     +-- MQTT integration
                          |
                          +-- daytrade
                          |     +-- Provider-neutral collector
                          |     +-- Alpaca / IBKR / replay adapters
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

DNS Filtering
- Pi-hole v6 in a dedicated Debian 13 LXC
- Synology DNS as the initial upstream resolver

Charging Control
- Native EVCC service in a dedicated Debian 13 LXC
- Persistent configuration and SQLite charging history
- Guarded single-controller migration from the legacy EVCC host
- MQTT publishing to the central Mosquitto service

Market Data
- Provider-neutral daytrading collector
- Site-local provider selection and Vault-backed credentials
- Direct SMTP notification pending a future MQTT/MQ boundary

Logging
- Central Syslog collection
- Queued remote forwarding for managed services

MQ administration prototype (evaluation only)
- Controller-local, authenticated HTTPS JSON MQSC desired-state reconciliation
- Bounded queues/channels/topics/namelists; check/diff and guarded deletion
- Existing MQ required by reconciler; separate Rocky LXC/Podman evaluation target
- Evaluation only; productive license question must be clarified with IBM
- No daytrading message bridge or productive deployment approval
- Real MQ acceptance, CHLAUTH/OAM and full cross-platform coverage pending
- See [MQ administration](MQ.md)

Planned
- llama.cpp
- IBM MQ deployment and complete security/object lifecycle management
- Monitoring
- Nextcloud
- Backup
- Security

## Version

Current architecture baseline: v0.8.0
