# Generic wildcard certificate source-to-target preflight

This public document deliberately contains no real infrastructure names,
DNS zones, SSH users, IP addresses, or certificate lineage names.

## Site-local configuration

Copy the tracked placeholder example to the Git-ignored local file:

    cp ansible/vars/mail-tls.local.yml.example ansible/vars/mail-tls.local.yml
    chmod 600 ansible/vars/mail-tls.local.yml

Edit that file locally (for example with vim). Supply the real existing target
inventory alias, source SSH DNS name or verified SSH alias, SSH user, Certbot
fullchain and private-key paths, required wildcard SAN, expected target FQDN,
and target Postfix/Dovecot certificate/key paths.

The populated file MUST stay untracked. Confirm the ignore rule:

    git check-ignore -v ansible/vars/mail-tls.local.yml

The two service paths must reflect the actual effective Postfix and Dovecot
configuration. Use standard internal inventory and Vault files for SSH
credentials and other secrets, never the committed example file.

## Read-only audit

On the Ansible controller:

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/mail-wildcard-tls-readonly-preflight.yml \
      -e @ansible/vars/mail-tls.local.yml --syntax-check --ask-vault-pass

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/mail-wildcard-tls-readonly-preflight.yml \
      -e @ansible/vars/mail-tls.local.yml --ask-vault-pass

The source is registered as an ephemeral, generic in-memory host alias.
A known-good SSH host key must already be trusted. Never bypass host-key
verification, and independently verify an unknown key before adoption.

The preflight validates:
- source certificate/key files exist;
- wildcard DNS SAN equals the configured expected SAN;
- certificate expiry is at least 30 days away;
- public keys derived locally from certificate and private key match;
- effective Postfix and Dovecot TLS file paths match the local settings;
- configured mail hostname matches the real Postfix hostname.

Expected result is verification PASS with changed=0. The result is NOT an
authorization to change files or reload services. This playbook never copies
private keys, certificate files or service configuration.

If Dovecot 2.4 returns a blank path for a legacy setting, query the
named SSL server context instead:

    doveconf -h ssl_server/cert_file
    doveconf -h ssl_server/key_file

Do not print or send the private key. Do not adjust the effective service
paths merely to make an audit pass.

## Read-only rotation decision

Before any file transfer, compare the current target certificate and key
pair with the verified source certificate:

    python3 -m pytest -q tests/test_mail_wildcard_tls_readonly_preflight.py \
      tests/test_mail_tls_rotation_readonly_plan.py

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/mail-tls-rotation-readonly-plan.yml \
      -e @ansible/vars/mail-tls.local.yml --syntax-check --ask-vault-pass

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/mail-tls-rotation-readonly-plan.yml \
      -e @ansible/vars/mail-tls.local.yml --ask-vault-pass

The planner imports the verified source/target preflight first. It then
obtains SHA-256 fingerprints of the source leaf certificate and installed
target leaf certificate, checks the target certificate and private key are
readable regular files, and compares their locally derived public keys.
Neither the source nor the target private key is transferred or printed.

Its proposed_action is one of:
- NO_CHANGE_REQUIRED: the same leaf certificate is installed and the
  target private key matches it.
- CANDIDATE_FOR_ROTATION: the target has a valid certificate/key pair but
  its leaf certificate differs from the source.
- MANUAL_REMEDIATION_MISSING_TARGET_FILES: a required target file is absent.
- MANUAL_REMEDIATION_INVALID_TARGET_PAIR: target certificate or key cannot
  be parsed, or their public keys differ.

The planner does not establish CA-chain trust or live TLS correctness;
those require separate checks. No proposed_action authorizes deployment.
The production installation remains a separately reviewed operation.

## Deployment remains a separate change

A future implementation requires a least-privilege secret transport,
restricted target file modes, end-to-end certificate/key validation,
transactional activation with rollback, controlled Postfix and Dovecot
reload, service-port TLS checks, and certificate renewal monitoring.

Distributing a wildcard private key enlarges the set of systems from which
it may be compromised. A per-service certificate reduces this blast radius.

## Previous Git history

Git history and previously published tags are immutable references unless
intentionally rewritten. Removing site-specific values from the latest
revision does NOT erase their appearance in older commits. If eliminating
that history is required, review a coordinated repository-wide history
rewrite and new credentials or keys only where actual secrets were exposed.
Never force-push a rewritten history as part of this routine refactor.

## Automation

For guarded distribution, optional daily systemd timer and rollback handling,
see [MAIL-TLS-AUTOSYNC.md](MAIL-TLS-AUTOSYNC.md).
