# Wildcard TLS: MX2 to bergen-mail

## Scope and established topology

Source and renewal owner: MX2, SSH address mx.thebergens.net.

Certbot lineage renewed in September 2026:
- /etc/letsencrypt/live/thebergens.net-wildcard/fullchain.pem
- /etc/letsencrypt/live/thebergens.net-wildcard/privkey.pem

First target: the bergen-mail LXC serving mail.thebergens.net.

The existing mail Ansible role expects:
- /etc/ssl/certs/mail-backend-fullchain.pem
- /etc/ssl/private/mail-backend-key.pem

Postfix and Dovecot must continue referring to those target files.

Renewal via Certbot DNS-01 is a separate process. Manual DNS challenge
authorization, if still needed, remains separate from distribution.

## Read-only preflight on bp-controller

Run syntax-check and then collect the real evidence:

    cd ~/bergen-platform
    ansible-playbook \
      -i ansible/inventory.yml \
      -i ansible/inventory.local.yml \
      ansible/playbooks/mail-wildcard-tls-readonly-preflight.yml \
      --syntax-check

    ansible-playbook \
      -i ansible/inventory.yml \
      -i ansible/inventory.local.yml \
      ansible/playbooks/mail-wildcard-tls-readonly-preflight.yml \
      --ask-vault-pass

If Vault protection is required even for parsing the inventory, add
--ask-vault-pass to the syntax-check command.

The source is added to the in-memory inventory only as
mx2-certificate-source with ansible_host=mx.thebergens.net.
SSH defaults to the user's configured Ansible identity. If necessary
supply -e mail_tls_source_ssh_user=YOUR_AUTHORIZED_SSH_USER
using an existing authorized account. Do not commit credentials.

Checks:
1. Source Certbot certificate and key exist at the expected paths.
2. The certificate contains the exact DNS:*.thebergens.net SAN.
3. The certificate remains valid for at least 30 days.
4. The locally derived PUBLIC keys of certificate and private key match.
5. Effective Postfix and Dovecot certificate paths on bergen-mail match
   the approved destination files, and Postfix hostname is mail.thebergens.net.

Neither certificate nor key is transferred. The private key is not
printed or saved on the controller. Expect changed=0.

PASS means source and target configuration was observed in a safe
read-only check, NOT that bergen-mail already presents the wildcard
certificate and NOT permission for a later deployment.

## Troubleshooting a failed preflight

If MX2 reports "Host key verification failed", do NOT disable SSH
host-key checking or remove the existing known_hosts record blindly.
On bp-controller, inspect the exact SSH target and its current trust entry:

    ssh -G mx.thebergens.net | grep -E '^(hostname|user|port|hostkeyalias) '
    ssh-keygen -F mx.thebergens.net

Confirm that the DNS result and SSH host key match the intended MX2
system, using a previously verified fingerprint or a separate trusted
administrator channel. If MX2 is already reachable through a trusted
local SSH alias, override the source address for this preflight:

    -e mail_tls_source_address=YOUR_VERIFIED_MX2_SSH_ALIAS

This does not change DNS, SSH trust, or any host configuration.

If the target reports an unexpected Dovecot certificate path, inspect
the effective non-secret FILE NAME with the existing Ansible inventory:

    ansible -i ansible/inventory.yml -i ansible/inventory.local.yml \
      bergen-mail -b -m ansible.builtin.command \
      -a 'doveconf -h ssl_server_cert_file' --ask-vault-pass

This reads only the path. Do not add -x or -P, dump private key contents,
or work around the mismatch by forcing the certificate copy. Check
the actual installed Dovecot 2.4 configuration before adjusting the
preflight's expected path or the mail role.

The target preflight refuses to proceed if MX2 has not produced
verified source evidence. This avoids misleading partial validations.

## Deployment boundary (not implemented)

A separate, reviewed distribution playbook will need:
- End-to-end secret-safe transport without persistent plaintext staging
  of the private key on the controller or leaking into Ansible logs.
- Restrictive ownership and mode for staged and active private keys.
- Verification on the target of certificate hostname, chain validity,
  expiry and key pairing before activation.
- Atomic activation / recoverable rollback for certificate and key.
- Validated Postfix and Dovecot configuration, controlled reload, and
  verification with IMAPS 993, SMTP STARTTLS 587, and if enabled TLS 465.
- Rotation after each MX2 Certbot renewal and alerting on failure/expiry.

Copying a wildcard private key expands the impact of a compromise of
any recipient. A dedicated certificate for mail.thebergens.net reduces
that blast radius and remains a worthwhile alternative.

DO NOT copy a private key with ad hoc shell/scp commands or expose it
in support output. No live mail service change is authorized here.
