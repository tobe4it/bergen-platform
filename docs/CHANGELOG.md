# Changelog

All notable changes to the Bergen Platform are documented in this file.

The project follows **Semantic Versioning (SemVer)** and the changelog format is inspired by **Keep a Changelog**.

---

## [Unreleased]

### Added

#### Central Logging

- Added a reusable remote Syslog forwarder role with queued TCP/UDP delivery,
  configuration validation and an optional deployment test event.
- Integrated central Syslog forwarding into the mail-backend bootstrap.
- Integrated the same queued remote Syslog forwarding into the Pi-hole
  bootstrap while keeping DNS query logging local to Pi-hole.

#### DNS Filtering

- Added a dedicated `bergen-pihole` Debian 13 LXC definition and first-deploy
  workflow.
- Added a Pi-hole v6 Podman/Quadlet role with persistent state, vaulted
  administration credential, explicit upstream DNS and runtime validation.
- Added staged DNS-cutover documentation that preserves UniFi routing/policies
  and keeps Synology DNS as the initial internal/upstream resolver.

### Fixed

#### Mail Platform

- Routed chrooted Postfix LDAP mailbox and domain-alias lookups through the
  existing unchrooted `proxymap` service.

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
