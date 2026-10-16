# Changelog

All notable changes to the Bergen Platform are documented in this file.

The project follows **Semantic Versioning (SemVer)** and the changelog format is inspired by **Keep a Changelog**.

---

## [Unreleased]

### Changed

- Moved the IBM MQ evaluation lab, REST-administration prototype, topology,
  audit tooling, tests and operational documentation to the standalone
  [`tobe4it/bergen-mq-lab`](https://github.com/tobe4it/bergen-mq-lab)
  repository. Existing MQ guests and local secrets are not changed.

---

## [0.12.0] - 2026-10-16

Independent selfHOST DNS-01 wildcard certificate instances. This release
extends the existing mail-gateway ACME integration without migrating or
rewriting the legacy `example.net` certificate lineage.

### Added

- Optional, separately configured per-zone selfHOST instances using independent
  API credentials, authoritative nameservers, exactly two TXT slots and an
  isolated reservation state directory; default legacy paths stay unchanged.
- Guarded Ansible playbook for installation-only, opt-in staging and opt-in
  production wildcard issuance with ECDSA P-256 keys, separate Certbot names
  and SAN/algorithm validation.
- Strictly scoped per-instance recovery of abandoned DNS-01 reservations,
  with authoritative-idle verification, Certbot concurrency checks and a
  protected state backup before explicitly approved reconciliation.
- Git-ignored per-instance Ansible input and encrypted Vault examples, an
  operator runbook and offline state-isolation and recovery tests.

### Verified

- 47 relevant offline tests passed, and the isolated recovery playbook passed
  Ansible syntax validation.
- `example.org` staging and production issuance succeeded on the certificate
  source, covering both the zone apex and wildcard with ECDSA P-256.
- Independent `certbot renew --dry-run` tests passed for the existing
  `legacy-wildcard` and the new `selfhost-dns-secondary` lineages.
  Both local reservation stores and authoritative DNS TXT slots were confirmed
  clean after their respective tests.
- The source's enabled and active `certbot-renew.timer` runs the generic
  Certbot renewal service; provider credentials remain local to the source
  and do not require the Ansible controller during renewal.

### Operational follow-up

- No new `selfhost-dns-secondary` Nginx consumer or deploy-reload hook is
  installed by this release. Connect the prepared `cloud.example.org` vhost
  on the destination during the separate Nextcloud migration; verify Nginx
  configuration, reload behavior and served certificate before cutover.
- A simulated renewal does not prove a future scheduled production renewal;
  observe one and its downstream deploy hooks independently.

---

## [0.11.0] - 2026-10-15

Open WebUI OIDC integration with Synology SSO.

### Added

- Guarded OIDC deployment for the existing Podman Quadlet, using a protected
  environment file and additive drop-in with a restart and health check.
- Synology scopes and PKCE S256, local administrator recovery, pending accounts
  by default, and disabled automatic account merging and role/group mapping.
- English deployment, acceptance, secret-rotation and rollback documentation;
  configuration tests and Git ignore rules for local settings and Vault files.

### Verified

- Two configuration tests and Ansible syntax validation passed.
- Live deployment completed without failures; application health returned HTTP 200.
- Browser SSO created a separate pending account; the existing administrator
  remained present.

### Operational follow-up

- Client-secret rotation and a fresh login afterward remain operator tasks.
- User approval, a model request and existing-chat checks remain unconfirmed.
- One of the identity provider's two DNS addresses timed out from the AI guest;
  network/DNS remediation remains separate from this release.

---

## [0.10.0] - 2026-10-15

Internal reverse-proxy and Bergen-AI HTTPS access release.

### Added

- Reusable Nginx reverse-proxy role for an existing dedicated internal Debian
  LXC, with TLS-only virtual hosts, WebSocket forwarding, private client CIDR
  allowlists and a rejecting default TLS server.
- Read-only Proxmox/live-proxy preflights and a guarded, explicitly approved
  Bergen-AI first-install playbook.
- Separate non-root Bergen-AI SSH tunnel identity and hardened systemd unit,
  forwarding proxy loopback TCP 13000 to Open WebUI loopback TCP 3000.
- Rollback of only newly staged AI files and checksum protection for the
  existing Paperless vhost.
- Operational documentation and static safety-contract tests.

### Fixed

- SSH configuration validation now uses `runuser` on the minimal proxy LXC
  instead of assuming that `sudo` is installed.
- Activation validates the effective SSH user, identity file, dedicated
  known-hosts file, strict host-key checking, batch mode and identity isolation
  rather than merely parsing the SSH configuration.

### Verified

- Five Bergen-AI proxy contract tests passed and the activation playbook passed
  its Ansible syntax check on the controller.
- Read-only live preflight completed with `changed=0` and `failed=0`.
- Activation completed with `ok=24`, `changed=5`, `failed=0` and preserved
  the Paperless vhost checksum.
- Open WebUI returned HTTP 200 locally on the AI guest and through the dedicated
  SSH tunnel; certificate coverage, internal DNS agreement, `nginx -t` and
  Nginx reload passed.
- Access through an existing Synology proxy was confirmed.

### Follow-up

- Diagnose direct access from the iPad client path separately; verify WebSocket
  use and an actual application login.
- Prove automatic wildcard-certificate distribution and Nginx reload after a
  real renewal.

## [0.9.2] - 2026-10-11

Mail gateway TLS and Certbot maintenance release. The gateway certificate
lifecycle is distinct from the still-incomplete internal mail backend cutover.

### Added

- Scoped mail TLS/ACME playbooks for certificate audits, renewal diagnostics,
  HTTP-01/MTA-STS vhost adoption and selfHOST DNS-01 management.
- Read-only-by-default, site-local-variable-driven MTA-STS Nginx IPv6 and
  Certbot deploy-hook adoption with guarded root-only backup and explicit apply.
- Controller-driven selected mail certificate synchronization, example user
  systemd timer/service units and offline regression tests.
- Public mail-gateway TLS operations runbook in `docs/MAIL-TLS-OPERATIONS.md`:
  ownership, DNS-01/HTTP-01, IPv4/IPv6 MTA-STS, scoped reload hooks, timer
  checks, quarantine, rollback and operational acceptance criteria.

### Changed

- Scoped Postfix RSA/ECDSA and wildcard Nginx deploy hooks now distinguish
  authorized lineages and fail closed on reload/validation errors.
- Documented the retirement/quarantine of unused renewal configurations
  without deleting certificate material and the disabling of an obsolete
  monthly legacy renewal cron; no system-wide crypto-policy workaround.
- Linked the source-MX lifecycle to mail backend documentation, while
  preserving separate cutover and mailbox-migration acceptance requirements.
- Ignored site-local Ansible settings and inventory-editor backup files;
  sanitized test fixtures to avoid embedding real infrastructure identifiers.

### Verified

- 104 Mail-TLS/selfHOST-ACME Python tests passed; 15 associated Ansible
  syntax checks and Python script compilation passed on the release branch.
- Exact-name MTA-STS staging and production renewal succeeded; IPv4 and
  public IPv6 HTTPS delivered the reviewed policy and renewed certificate.
- MTA-STS lineage hook ignored unrelated names and reloaded Nginx for its
  selected test invocation; remote Ansible read-only preflight passed with
  `changed=0` and `failed=0`.
- Scheduled global Certbot scan on 2026-10-11 completed successfully with
  ten existing profiles not yet due. It did **not** exercise a real unattended
  renewal or full downstream certificate distribution.

### Follow-up

- Observe a real scheduled source-certificate renewal, deploy-hook execution,
  internal sync and served certificate verification. Complete monitoring and
  the separate mail-backend production cutover acceptance criteria.

---

## [0.9.1] - 2026-09-16

This patch release records fixes from the successful Rocky LXC / Podman MQ
evaluation rollout. Evaluation only, not productive approval; productive
licensing must be clarified with IBM.

### Added

- Optional `mq_lab_admin_cidrs` list for source-specific browser/admin HTTPS
  access to MQ evaluation port 9443; empty by default, no client-port opening

### Fixed

- Managed inventory now evaluates dynamic group/host keys instead of writing
  literal Jinja placeholders; guarded same-address legacy repair preserves
  unrelated entries/custom settings and backs up the inventory before changes
- Explicit evaluation-only mqweb Basic authentication and admin registry with
  `MQ_DEV=false`; preserve disabled DEV objects and use the secret-derived
  secure password reference rather than writing passwords into XML
- MQ REST readiness requests now include IBM's required CSRF header for HTTP
  Basic authentication, both locally and from the Ansible controller
- Rocky MQ evaluation deployment now prepares missing OpenSSH through Proxmox
  before SSH discovery, preserving existing host keys and SSH security policy
- Existing MQ evaluation LXC can resume deployment after a missing-SSH failure

### Verified

- User-run evaluation rollout completed with no failed/unreachable hosts
- Authenticated REST readiness and queue-manager identity verified locally
  and from bp-controller with CA/TLS verification enabled
- Browser login confirmed after the authorized Intern HTTPS source was added
- Real MQ `BERGENLAB` smoke test: check detected missing `BERGEN.LAB.SMOKE`
  with zero mutations; apply created/verified it; second apply reported
  `changed=0` and zero mutations
- 50 offline tests passed; 5 opt-in Ansible runtime tests skipped; inventory
  writer syntax checked
- Other object types/ALTER/deletion safeguards, CHLAUTH/OAM, reboot persistence,
  backup/restore and actual Syslog delivery remain outside this verification

---

## [0.9.0] - 2026-09-15

This release provides an IBM MQ example / evaluation, not approval for
productive operation. For productive operation, clarify licensing with IBM.
The Rocky LXC / Podman rollout and acceptance against real MQ remain pending.

### Added

- Parametrized Rocky 9 unprivileged LXC / Podman MQ evaluation example with
  digest-pinned developer image, persistent QMGR state, Vault-backed Podman
  secrets, lab CA/TLS verification, source-specific firewall rules and Syslog
- Explicit example/evaluation-only notices requiring productive licensing to
  be clarified with IBM; no default license acceptance or productive approval
- Bounded IBM MQ REST desired-state administration prototype for queues,
  channels, topics and namelists, with incremental updates, check/diff,
  deletion gates, TLS verification and post-change validation
- Offline reconciliation and real-Ansible HTTPS mock tests; documented IBM
  support/coverage limits and outstanding real-MQ acceptance

### Verified

- 41 automated tests passed; 5 real-Ansible integration tests skipped because
  the build environment does not permit Ansible's local RPC socket
- Deployment and bootstrap playbook syntax checked
- No completed LXC rollout, real-MQ acceptance or productive approval claimed

---

## [0.8.0] - 2026-09-15

This release adds a dedicated EVCC LXC and a guarded Ansible migration that
preserves configuration, UI settings and charging history while enforcing a
single active charging controller.

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

### Verified

- Production migration from EVCC `0.314.5` to `0.315.0` completed successfully
- Configuration and SQLite database checksums matched after transfer
- SQLite `quick_check`, EVCC configuration parsing and HTTP API validation
  completed successfully
- Automatic rollback restored the legacy service after an initial transient
  API-readiness failure
- API retry handling completed the subsequent cutover, leaving the target
  active and the legacy EVCC service stopped and disabled

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
