# MX1 Cloud retirement: read-only inventory

The goal is to identify **only** obsolete Nextcloud components on mx1.
The mail server remains in production. No files, Nginx configuration,
MariaDB databases, cron tasks, Certbot material or containers are removed.
No services are restarted.

## Existing evidence

- mx2 is serving cloud.tbergen.de and Collabora successfully.
- PR #112 installed an automatically scheduled NFS backup, containing
  Nextcloud files, configuration and MariaDB export, with a verified SHA-256.
- The old mx1 Cloud is stale relative to mx2.
- The **production migration/recovery onto mx2** was independently functionally
  verified. Do not conflate that completed migration with a separate optional
  disaster-recovery exercise restoring a later mx2 backup into CT701.
- Any cleanup requires a current mx1 scope/dependency review, retention review,
  explicit removal approval, and post-removal checks of mx2 and mx1 mail services.

## Execute from bp-controller

Use a detached worktree so PR #108 and main remain untouched:

    cd ~/bergen-platform
    git fetch origin audit/mx1-nextcloud-retirement-20261019
    git worktree add --detach ~/bergen-platform-mx1-audit \
      origin/audit/mx1-nextcloud-retirement-20261019
    cd ~/bergen-platform-mx1-audit

Create a site-local config (Git-ignored), using the real mx1 SSH target,
username and the exact FQDN returned by hostname -f ON MX1:

    umask 077
    cp ansible/vars/mx1-nextcloud-retirement.local.yml.example \
      ansible/vars/mx1-nextcloud-retirement.local.yml
    chmod 600 ansible/vars/mx1-nextcloud-retirement.local.yml
    vi ansible/vars/mx1-nextcloud-retirement.local.yml
    git check-ignore -q ansible/vars/mx1-nextcloud-retirement.local.yml

Run the read-only playbook. The existing inventory can include Vault data:

    BASE="$HOME/bergen-platform"
    ansible-playbook \
      -i "$BASE/ansible/inventory.yml" \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/audit-mx1-nextcloud-retirement-readonly.yml \
      -e @ansible/vars/mx1-nextcloud-retirement.local.yml \
      --vault-id infra@prompt

Expected: MX1_NEXTCLOUD_RETIREMENT_READ_ONLY_COMPLETE,
changed=0, failed=0. The script prints only bounded categories, not raw
config, credentials, database rows, emails or document contents.
If wrong hostname is detected, STOP; do not override the guard.

## Audit interpretation

- nextcloud_tree / nextcloud_data: identify old installation and data sizes.
- nextcloud_database: only schema presence, never export/drop in this audit.
- apache/root nextcloud cron entries: counts, not contents.
- nginx cloud/office references and vhost candidate count: deletion blockers
  until remaining certificate/vhost consumers are independently checked.
- Collabora candidate count: distinguish old standalone code containers.
- Mail services: must remain intact.

Unknown and inaccessible results are NOT proof of absence.

## Corrected project boundary: proven production migration, optional DR exercise

The Nextcloud migration/recovery onto `mx2` and its operational checks were
**already completed**. `mx2` now serves the live Cloud; `mx1` is a stale
post-cutover copy and must **not** be reintroduced as a writable fallback.
The fact that both installations were previously observed at version
31.0.14.1 does not make their databases and file trees interchangeable.

A **new** isolated exercise restoring the latest `mx2` backup in CT701
is useful disaster-recovery assurance, but **is not a newly imposed
prerequisite** to removing the old `mx1` installation. Keep the CT701
and CT790 workstreams separate from this retirement.

The following still require dedicated review before any delete action:
- Current verified `mx2` production health and the already recorded
  production cutover/recovery evidence; preserve usable `mx2` backup copies.
- Exact obsolete `mx1` application tree and its `data` subtree: ensure
  no unrelated service, nested mount, external storage, or host symlink
  would be affected. The old tree is not the live Cloud.
- MariaDB **schema `nextcloud` only**, with explicit proof it is not
  used by mail or any other application; preserve server, accounts and
  other schemas. No database drop is currently authorized.
- Nginx: identify all effective Cloud vhost references and other names
  sharing certificate lineages, proxies, include files or hooks.
  Do not remove a shared certificate, webserver or renewal hook.
- Cron and service/timer inventory: only verified Nextcloud-specific
  entries can later be proposed for removal. Preserve system-wide
  PHP-FPM, MariaDB, nginx, Postfix, Dovecot, WireGuard and mail delivery.
- Confirm independent historic backup retention needs and rollback plan
  for unintended effects, then request **a separate exact-scope removal
  approval**. No blanket removal or package purge.

### Recorded mx1 live read-only audit, 19 October 2026

The existing playbook
`ansible/playbooks/audit-mx1-nextcloud-retirement-readonly.yml`
was executed against the independently hostname-verified legacy mx1.
Operator receipt: `MX1_NEXTCLOUD_RETIREMENT_READ_ONLY_COMPLETE`,
`changed=0 failed=0`. The sanitized findings were:

| Item | Observed |
| --- | --- |
| Legacy Nextcloud `occ` and config | Present |
| Old installation tree | Approximately 9.5 GB |
| Old `data` subtree | Approximately 8.2 GB |
| MariaDB schema `nextcloud` | Present |
| Nextcloud `occ` | 31.0.14.1, maintenance enabled; no DB upgrade needed |
| Active Nextcloud cron entries | 0 in apache and root crontabs |
| Nginx | Active, effective config valid; two Cloud-vhost candidates, five Cloud references |
| PHP-FPM / MariaDB | Active; shared services must remain |
| Postfix / Dovecot | Active; must remain |
| Collabora container matches | 0 |

This report is an **inventory**, not a safe deletion manifest:
the two Nginx candidates, five references, ownership of shared
runtime services, unknown other vhosts/cert consumers and exact
obsolete schema ownership need a narrower review before a deletion
plan is executable. No live cleanup was performed.

### Separate disaster-recovery project

An additional offline restore of a completed `mx2` Synology snapshot,
with isolated filesystem and MariaDB, remains a distinct
`Nextcloud DR` test. It can improve recovery assurance and provide
a measured RTO, but it does not retroactively invalidate the
already verified successful production migration to `mx2`.

No commands in this document authorize deletion on `mx1`
or deployment changes on `mx2`.
