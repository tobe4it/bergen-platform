<!-- bergen-platform-handbook: managed -->
# Git, Ansible and emergency access

[Deutsch](DE-Automation-Secrets.md) | [English](EN-Start.md)

**Public edition 1.0, 2026-10-14.** Examples do not replace a private deployment inventory.

## Git keeps the build description

A repository contains files and their history. A commit records a state; a branch is a development line; a tag can label a release. A pull request allows review before integration. The public repository is `tobe4it/bergen-platform`; its current deployment may use another branch or local modifications.

In the actual controller working directory, inspect rather than change:

```sh
git status --short
git branch --show-current
git log -1 --oneline
```

Empty short status means Git reports no tracked working changes. Record branch and commit separately. Fetching obtains repository information; `git pull --ff-only` can update the working copy and fails when history cannot advance directly. Applying an Ansible playbook is a separate step. Review local changes, release notes and recoverable backups first; never discard unknown changes with a reset.

`.gitignore` does not encrypt or back up a file. Private inventory, deployment variables, vault files and SSH material need protected backups outside the public repository. A fresh clone alone cannot restore a complete installation.

## Ansible's building blocks

Inventory identifies hosts and groups. Variables provide deployment-specific settings. Playbooks organize tasks; roles package reusable responsibilities; templates generate configuration; Vault encrypts sensitive stored values. Public and private inventories may need to be used together.

The connection route may be direct SSH or Proxmox-mediated execution. Keep the intended VLAN separation. A Python virtual environment isolates project dependencies; record the actual venv path rather than guessing from an old command or prompt.

| Result | Meaning |
| --- | --- |
| ok | Task completed without a reported change |
| changed | Task reported a change |
| failed | A task failed |
| unreachable | Ansible could not reach the target appropriately |
| skipped | Conditions caused the task to be skipped |

Idempotency means repeated runs aim to maintain the same desired state without unnecessary change. It is not a guarantee that every run is harmless: variables, versions and targets can change.

Syntax checking checks playbook syntax. Check mode attempts a preview but not every task fully supports it. Diff output can expose sensitive information unless the task protects it. Before an applying run, confirm scope, actual target, variables, version, expected impact and rollback. A clean recap does not prove an external mail round trip or a successful document import.

## Secrets needed for a takeover

Passwords sign in to accounts. Private SSH keys enable administration. Vault unlock information decrypts stored values. MFA devices, recovery codes and backup encryption keys can be necessary in addition. A secret cannot reliably be recovered from a vault encrypted with that same missing secret.

Vault protects stored content; necessary values become available during execution. It does not automatically sanitize every log or runtime file. Protect diagnostics and generated configuration too.

The private recovery package should cover local emergency administration, domain/DNS and provider access, the public mail gateway, controller/Git access, private deployment settings, the correct Vault unlock route, SSH passphrases, backup decryption and MFA recovery. Access must not depend solely on a broken LDAP service, the administrator's unavailable phone, or the platform's own email.

## Use the separate printout sparingly

The public wiki and ordinary handover record contain only references and storage locations. Print the blank emergency form and enter by hand only the necessary values unavailable from the protected vault/password manager. For existing managed secrets record a reference and test the recovery route instead of copying every password.

A password manager's name alone does not establish a usable emergency opening. A second person should demonstrate access through the intended process without the original administrator supplying missing information from memory.

Certificates are public descriptions of names and trust; their private keys are secrets. Show the public part when diagnosing TLS, never publish the private key.

Keep completed printouts offline under the agreed access policy. Do not upload them to the wiki, commits, issues, pull requests, scans or chat. No recovery credential is requested by this documentation.

---

[Contents](EN-Start.md) · [Sources](EN-Sources.md) · [Prepare private handover](EN-Handover.md)
