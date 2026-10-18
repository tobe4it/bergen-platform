# Nextcloud and Collabora on the mail host: production baseline

This is a **read-only adoption/drift audit**, not a deployment or disaster
recovery role. The production stack was migrated and tested separately, with
successful WOPI, DOCX edit/save/reopen, and the shared wildcard certificate.

## Baseline captured in the repository

- Approved target hostname and system crypto policy FUTURE.
- Active Nginx, crond, PHP-FPM, rootful Quadlet-managed Collabora.
- PHP 8.3 with ldap, sodium, igbinary, msgpack, imagick, smbclient in CLI and
  FPM; php-smbclient provides the RPM alias php-libsmbclient.
- One Apache five-minute cron.php job, backgroundjobs_mode=cron, lastcron set.
- Richdocuments WOPI restricted to one fixed container IP.
- Fixed Podman bridge IP, gateway host mapping for Nextcloud, loopback-only
  Collabora 9980, pinned digest, CA-chain mount, and reviewed CODE settings.
- Identical wildcard Certbot lineage for Cloud and Office Nginx; Office
  client_max_body_size 100M and the existing scoped reload hook from PR #84.
- Collabora can reach the Cloud status endpoint without TLS exceptions.
- The old dedicated Office certificate lineage was removed. Never blindly
  restore older VHost backups which reference its deleted certificate paths.

Quadlet templates are **reviewed, exact-match baseline fixtures**. The audit
does not push these templates to the host, change crypto policy, install RPMs,
alter cron, run Certbot, restart Podman or reload Nginx. A difference is a
failure requiring investigation, not authorization to overwrite production.

## Controller setup

Supply the existing ignored mail-tls.local.yml (reviewed SSH source identity).
Populate another ignored YAML from the actual production Quadlets and Nginx
configuration; do not copy placeholder values unchanged. Preserve backslashes
in the effective CODE aliasgroup1 environment value literally.

```sh
cp ansible/vars/mail-nextcloud-stack.local.yml.example \
  ansible/vars/mail-nextcloud-stack.local.yml
chmod 600 ansible/vars/mail-nextcloud-stack.local.yml
$EDITOR ansible/vars/mail-nextcloud-stack.local.yml

python3 -m pytest -q tests/test_mail_source_nextcloud_stack_audit.py
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/mail-source-nextcloud-stack-audit.yml \
  -e @ansible/vars/mail-tls.local.yml \
  -e @ansible/vars/mail-nextcloud-stack.local.yml --syntax-check

ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/mail-source-nextcloud-stack-audit.yml \
  -e @ansible/vars/mail-tls.local.yml \
  -e @ansible/vars/mail-nextcloud-stack.local.yml
```

Successful execution reports ADOPTED_READ_ONLY. There is no apply mode.

## Operational acceptance and follow-up

After any maintenance check both live SNI certificate fingerprints, Office
discovery with TLS validation, a DOCX edit/save/reopen, successful WOPI from
the fixed container IP, and the next Apache cron completion. Redact WOPI
tokens from logs before sharing.

The production adoption audit does not yet reproduce a new installation.
A separate approved reconciliation/deployment implementation must consider
existing Nginx VHost content, Remi dependencies under FUTURE, SELinux,
Certbot renewal lifecycle, Nextcloud storage/database/secrets, pre-existing
crontabs, and retention of the stopped old Collabora container. Do not delete
rollback data or old servers as part of this audit. PR #84 already manages the
scoped Cloud Certbot renewal hook.
