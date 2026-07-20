# Update Guide

This document describes the recommended procedure for updating an existing Bergen Platform installation.

The goal is to perform reproducible, low-risk updates while preserving configuration, inventory and secrets.

---

# Supported Upgrade Paths

The Bergen Platform follows Semantic Versioning.

Examples:

- v0.5.0 → v0.5.1
- v0.5.x → v0.6.0
- v0.x → v1.0.0

Major releases may require manual intervention.

Always read the CHANGELOG before upgrading.

---

# Before Updating

Before updating, verify the current installation.

Recommended checks:

- Existing deployment is operational
- All playbooks complete successfully
- Git working tree is clean
- Inventory is committed
- Vault password is available
- Backups exist

Verify repository status:

```bash
git status
```

Verify current version:

```bash
git describe --tags
```

---

# Update Repository

Retrieve the newest changes.

```bash
git fetch --all --tags
```

Update to the newest release:

```bash
git checkout main
git pull
```

Or checkout a specific release:

```bash
git checkout v0.6.0
```

---

# Update Python Environment

Activate the virtual environment.

```bash
source .venv/bin/activate
```

Upgrade Python packages.

```bash
pip install -r requirements.txt
```

---

# Update Ansible Collections

Install or update required collections.

```bash
ansible-galaxy collection install \
-r ansible/requirements.yml \
--force
```

---

# Review Configuration

Before applying changes, review:

- inventory.yml
- group_vars
- host_vars
- Vault secrets

Check whether new variables were introduced in the release notes.

---

# Validate Infrastructure

Always validate the infrastructure before applying updates.

```bash
ansible-playbook \
ansible/playbooks/validate-proxmox.yml
```

Expected result:

- Proxmox reachable
- API available
- Storage available
- Network available

---

# Apply Updates

Infrastructure updates should always be executed using Ansible.

Example:

```bash
ansible-playbook \
ansible/playbooks/bootstrap-lxc.yml \
--ask-vault-pass
```

For AI services:

```bash
ansible-playbook \
ansible/playbooks/bootstrap-ai.yml \
--ask-vault-pass
```

Only run playbooks required for the updated component.

---

# Verify Installation

After the update verify:

## Proxmox

- Containers running
- Network connectivity
- Storage available

## AI

Verify:

- Ollama
- Open WebUI
- LDAP authentication

Example:

```bash
curl http://<ai-host>:11434/api/tags
```

Open WebUI should be reachable via browser.

---

# Verify LDAP

Confirm authentication.

Check:

- User login
- Automatic user creation
- Search filter
- Group membership (future)

---

# Rollback

If required:

Checkout the previous release.

Example:

```bash
git checkout v0.5.0
```

Re-run the corresponding playbook.

If infrastructure changes cannot be reverted automatically, restore from backup.

---

# Recommended Backup Strategy

Before every update:

- Backup Proxmox configuration
- Backup LXC containers
- Backup inventory
- Backup Vault
- Backup LDAP configuration

Never perform upgrades without backups.

---

# Troubleshooting

## Playbook fails

Run:

```bash
ansible-playbook ... -vvv
```

Review:

- SSH connectivity
- Inventory
- Vault password
- Variables

---

## LDAP login fails

Verify:

- LDAP server reachable
- Search Base
- Search Filter
- Bind DN
- Bind password

---

## Open WebUI unavailable

Verify:

```bash
podman ps
```

Inspect logs:

```bash
podman logs open-webui
```

---

## Rollback required

Return to the previous Git tag.

Re-run the deployment playbook.

---

# Best Practices

- Always read the CHANGELOG.
- Test upgrades in a non-production environment first.
- Keep inventory under version control.
- Never edit generated files manually.
- Let Ansible remain the single source of truth.
- Tag every stable release.
- Commit documentation together with infrastructure changes.

---

# Future Improvements

Planned enhancements:

- Dedicated upgrade playbooks
- Automatic version detection
- Pre-upgrade validation
- Automatic backups
- Database migration support
- Zero-downtime upgrades
- Rollback automation

