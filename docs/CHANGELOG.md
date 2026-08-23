# Changelog

All notable changes to the Bergen Platform are documented in this file.

The project follows **Semantic Versioning (SemVer)** and the changelog format is inspired by **Keep a Changelog**.

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

---

## [Unreleased]

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

#### Project Structure

- Initial Ansible project layout
- README.md
- ARCHITECTURE.md
- UPDATE.md
- TROUBLESHOOTING.md
- CHANGELOG.md

#### Proxmox

- `validate-proxmox.yml`
- Proxmox API validation
- Host validation
- Service validation
- Network bridge validation
- ZFS validation
- FQDN validation

#### Management

- `bp-controller`
- Python virtual environment
- Ansible installation
- Ansible Vault
- SSH key deployment

#### LXC

- Generic `create-lxc.yml`
- Debian LXC deployment
- DHCP support
- vmbr2 support
- Startup ordering
- Unprivileged containers
- SSH public key deployment
- Root password from Ansible Vault

#### Roles

New role:

- `lxc_base`

Features:

- Base package installation
- Improved shell history

#### AI

New container:

- `bergen-ai`

Status:

- Debian 13
- Fully automated deployment
- Automated bootstrap

#### Infrastructure

Successful end-to-end deployment workflow

validate-proxmox
↓
create-lxc
↓
bootstrap-lxc
↓
bootstrap-ai

---

### Changed

#### Network

- Generic LXCs migrated to `vmbr2`
- Simplified VLAN handling
- VLAN-aware bridge configuration

#### Architecture

- Separation of
  - playbooks
  - roles
  - inventory
  - variables
- Generic deployment architecture introduced

---

### Fixed

#### Proxmox

- Container mode configuration
- Startup timeout
- VLAN configuration
- API parameter handling
- SSH key deployment

#### Ansible

- Role path handling
- Role metadata
- Inventory structure
- Bootstrap execution
