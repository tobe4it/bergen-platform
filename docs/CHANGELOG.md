# Changelog

All notable changes to the Bergen Platform are documented in this file.

The project follows **Semantic Versioning (SemVer)** and the changelog format is inspired by **Keep a Changelog**.

---

## [Unreleased]

### Added

#### EVCC

- Dedicated Debian 13 `bergen-evcc` LXC definition and staged first-deploy
  workflow
- Native, version-pinned EVCC role with upstream SHA-256 verification
- Protected persistence paths for configuration, SQLite history and backups
- Guarded old-to-new migration with source-side SQLite backup, end-to-end
  checksums, configuration/database validation and automatic source-service
  recovery on failed cutover
- Site-local source/target inventory examples and full deployment, migration,
  address-transfer and rollback documentation

### Fixed

- First EVCC deployment now forces the migration staging state even when
  higher-precedence site-local extra vars request normal service startup
- EVCC API validation now retries while the web listener is available but the
  application routes are still initializing

---

## [0.7.0] - 2026-09-13

This release adds deployable DNS filtering and provider-neutral daytrading
market-data collection, extends central logging, and makes discovered LXC
addresses maintainable in the site-local inventory. It also tightens mail and
secret handling without publishing provider credentials.

### Added

#### Daytrading

- Dedicated Debian 13 daytrading LXC deployment and reusable collector role
- Provider-neutral adapters for Alpaca, IBKR Client Portal and local replay
- Local replay fixture for deterministic end-to-end validation
- Provider health checks, session execution and a built-in mail-test command
- Optional systemd service and timer for scheduled collection
- Git-ignored site-local provider configuration and Vault-backed secrets
- Opening-range breakout evaluation with relative-volume filtering

#### DNS Filtering

- Dedicated `bergen-pihole` Debian 13 LXC definition and first-deploy workflow
- Pi-hole v6 Podman/Quadlet role with persistent state, vaulted administration
  credential, explicit upstream DNS and runtime validation
- Staged DNS-cutover documentation that preserves UniFi routing and policies

#### Central Logging

- Reusable remote Syslog forwarder role with queued TCP/UDP delivery,
  configuration validation and optional deployment test events
- Remote Syslog integration for the mail backend and Pi-hole

### Changed

#### Inventory

- Extended LXC discovery to market collectors
- Added automatic maintenance of effective host addresses in the Git-ignored
  `inventory.local.yml`

#### Security

- Restricted the daytrading SMTP password to Ansible Vault
- Removed direct integrations that were not suitable for redistribution and
  kept provider selection explicit and local

### Fixed

#### Mail Platform

- Routed chrooted Postfix LDAP mailbox and domain-alias lookups through the
  existing unchrooted `proxymap` service

### Verified

- Provider-neutral replay session completed end to end with an ORB signal,
  15 opening-range bars and RVOL 3.9
- Python template syntax and repository YAML parsing completed successfully
- No GitHub status checks are configured for this repository

---

## [0.6.0] - 2026-08-29

This release expands the Bergen Platform beyond its original AI baseline with
central Syslog collection, an authenticated MQTT platform and the first
deployable mail-backend foundation. It also records verified operational paths
and the remaining production-cutover work with explicit acceptance criteria.

### Added

#### Mail Platform

- Dedicated Debian 13 `bergen-mail` LXC example and deployment workflow
- Postfix trusted inbound and authenticated submission services
- Dovecot LDAP authentication, LMTP and IMAPS
- LDAP `Mailuser`-restricted mailbox authorization
- Daily create-only mailbox provisioning timer
- Equivalent identity domains, recipient aliases and explicit Send-as owners
- Site-local, Git-ignored mail inventory for the effective LXC address
- Anonymous or authenticated LDAP directory searches for the mail backend
- Migration, backup and security-boundary documentation
- Verified initial Debian 13 LXC deployment checkpoint
- Dovecot 2.4 configuration and storage version declarations
- IPv4 preference for delivery to the single outbound smart host
- Runtime validation for non-loopback SMTP, submission and IMAPS listeners
- Operational validation, troubleshooting and production-readiness checklist

#### Central Logging

- Dedicated central Syslog collector role and LXC configuration
- UDP and TCP Syslog reception with sender-specific log files
- Remote-log rotation and retention management
- Ad-hoc remote Syslog enablement playbook
- Scheduled Syslog operations analyzer with SQLite-backed state

#### MQTT Platform

- Dedicated Mosquitto MQTT LXC and bootstrap workflow
- Per-client authentication and least-privilege topic ACLs
- `tools/mqtt-user` account, password and ACL management
- Secure temporary transport of typed topic-filter lists to Ansible
- Production ACL documentation for evcc, go-eCharger and Homey
- Verified go-eCharger/evcc to Mosquitto to Homey message flow

### Changed

#### Documentation

- Refined the repository overview and service-specific operating guides.
- Added verified deployment state and troubleshooting boundaries instead of
  treating successful configuration generation as end-to-end proof.

### Fixed

#### Central Logging

- Serialized Syslog analyzer database access to prevent concurrent SQLite
  writes.

#### MQTT Platform

- Preserved MQTT topic lists as typed Ansible data, including `#` and `+`
  wildcard filters.
- Corrected MQTT ACL parsing and user-management argument handling.

#### Mail Platform

- Postfix configuration changes now validate and restart as one handler event,
  ensuring `inet_interfaces` changes activate non-loopback listeners.
- Dovecot validation and restart now run as one ordered handler event.
- Mail listener validation no longer accepts loopback-only services.

---

## [0.5.1] - 2026-07-20

### Changed

- Reorganized project documentation.
- Refined the README and initial roadmap after the v0.5.0 release.

---

## [0.5.0] - 2026-07-20

### Added

#### AI Platform

- Automated AI LXC deployment
- Open WebUI deployment
- Ollama integration

#### LDAP

- OpenLDAP integration for Open WebUI
- LDAP connectivity validation
- Anonymous LDAP bind support
- Application bind support
- Configurable LDAP search filter
- Automatic generation of the Open WebUI LDAP environment

#### Documentation

- Semantic Versioning introduced
- First official project release

### Changed

- Open WebUI configuration is now fully managed through Ansible.
- LDAP configuration has been moved into a dedicated reusable role.
- Project documentation reorganized.

### Verified

- Successful deployment from Ansible.
- Open WebUI reachable after deployment.
- LDAP authentication against Synology Directory Server successful.
- LDAP users are automatically created in Open WebUI.
- Open WebUI LDAP configuration fully managed by Ansible.

### Notes

- Newly created LDAP users currently require administrator approval inside Open WebUI before first use.
