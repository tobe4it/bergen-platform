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
- A complete isolated recovery test from Synology has NOT yet been proved.
- MX1 cleanup must wait for restore proof, snapshot/retention review and
  separately approved scope.

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

## Isolated recovery prerequisite on venombox (separate implementation)

Create a new, network-isolated disposable test guest, not connected to live
mx1/mx2 SQL databases, DNS identities or public services. In this guest:
1. Verify the Synology COMPLETE, SHA256SUMS and archive.
2. Extract nextcloud.tar.gz into a distinct test filesystem with GNU tar ACL,
   owner and xattr support. Never extract into production.
3. Import nextcloud.sql.gz into a new, empty, isolated MariaDB database.
4. Preserve and review config.php secrets but replace test-only trusted
   domains, connection settings and external side effects. No mail notifications
   or sync with production users. Keep restored cron disabled.
5. Confirm the copied Nextcloud version starts, schema is valid, and representative
   files and public share metadata are present. Run app/ACL checks appropriate
   to the test guest and document recovery time and blockers.
6. Record results before approving ANY deletion from mx1.

After restore success and separate operator approval, develop a guarded cleanup
PR, preserving Postfix, Dovecot, certificates with remaining consumers,
WireGuard, mail data, and the historical archives for the retention period.
