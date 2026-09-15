# Bergen Platform Roadmap

This document describes the planned evolution of the Bergen Platform.

The roadmap reflects current priorities and may change as the project evolves.

---

# Vision

Provide a reproducible, fully documented and modular Infrastructure-as-Code
platform for self-hosted services running on Proxmox VE.

The platform should allow a complete environment to be rebuilt from scratch
using Ansible.

---

# Released milestones

## v0.5.1

Documentation and Open WebUI stabilization.

Delivered:

- Documentation cleanup
- Open WebUI improvements
- LDAP refinements
- Validation improvements
- Operational stability

---

## v0.6.0 - Mail Backend Foundation

Released 2026-08-29:

- Debian 13 `bergen-mail` LXC deployment
- Postfix/Dovecot with LDAP-backed identities
- Mailuser-only create-only mailbox provisioning
- authenticated submission, LMTP and IMAPS
- equivalent identity domains, aliases and Send-as ownership
- private smart-host integration with IPv4 preference
- verified internal deployment checkpoint and production-readiness checklist

The production cutover remains governed by the open Mail Platform work below.

---

## v0.7.0 - Platform Services and Daytrading

Released 2026-09-13:

- Provider-neutral daytrading collector with Alpaca, IBKR and replay adapters
- Automated daytrading LXC deployment and site-local inventory maintenance
- Vault-backed provider and SMTP credentials
- Built-in provider, session and mail validation commands
- Dedicated Pi-hole LXC with Podman/Quadlet deployment
- Reusable queued remote Syslog forwarding for platform services
- Postfix LDAP lookup correction through `proxymap`

The future MQTT/MQ event boundary for decoupled notifications remains planned
and is not part of this release.

---

## v0.8.0 - EVCC Charging Control

Released 2026-09-15; production cutover verified 2026-09-13:

- Dedicated Debian 13 EVCC LXC with a native, version-pinned package
- Site-local infrastructure, inventory and central Syslog parameters
- Migration of file configuration, UI settings and charging history
- Source-side SQLite backup plus end-to-end SHA-256 and integrity validation
- Single-controller cutover with automatic restoration of the legacy service
- API-readiness retry validated during the production migration
- Successful production upgrade from EVCC `0.314.5` to `0.315.0`

---

# v0.9.0

## AI Platform

Planned:

- Model management
- Automated model provisioning
- llama.cpp integration
- GPU support improvements
- AI validation
- Resource monitoring

---

# v0.10.0

## Monitoring

Planned:

- Observium deployment
- Automated monitoring configuration
- Host monitoring
- LXC monitoring
- Service monitoring
- Alerting preparation

---

# v0.11.0

## Backup & Recovery

Planned:

- Automated LXC backups
- Configuration backups
- Restore procedures
- Backup validation
- Scheduled backups
- Disaster recovery documentation

---

# v0.12.0

## Security

Planned:

- Security hardening
- SSH hardening
- Firewall validation
- Secrets management
- Central logging
- Audit support
- Patch management

---

# v1.0.0

## First Stable Release

Goals:

- Stable deployment process
- Fully documented platform
- Open WebUI
- Ollama
- LDAP authentication
- Monitoring
- Backup
- Security baseline
- Reliable update procedures

---

# Beyond v1.0

## Mail Platform

Implemented foundation:

- Internal Postfix submission and delivery backend
- Dovecot LDAP authentication, LMTP and IMAPS
- Mailuser-only create-only mailbox provisioning
- Declarative aliases and Send-as ownership
- Relay integration with an existing public gateway

Planned:

- publicly trusted TLS certificate issuance and renewal
- firewall and private gateway-path enforcement
- end-to-end gateway queueing and delivery acceptance tests
- SMTP AUTH, IMAP, mailbox and alias authorization test matrix
- mail migration with bulk and final incremental synchronization
- mailbox backup and isolated restore validation
- RFC 5322 From-header ownership policy/Milter
- external client access design and Fail2ban/rate limiting
- queue, authentication, disk, certificate and timer monitoring
- Webmail evaluation

The existing public gateway remains responsible for Rspamd/spam policy, DKIM,
DMARC-related delivery policy, public reputation, MTA-STS and TLS reporting.
These functions are not duplicated in the internal backend unless the gateway
architecture changes.

---

## Additional Services

Future candidates:

- Nextcloud
- Matrix
- Asterisk
- High Availability
- Multi-node deployments
- CI/CD
- Automated testing
