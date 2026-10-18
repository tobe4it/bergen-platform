# mx2 Nextcloud: daily consistent NFS backup

This is a **new** service, separate from the existing mail-host root cron and
/backup/mx*.tgz archives. It never modifies /usr/local/bin/backup.sh or those
archives. The only intended application mutation is the brief Nextcloud
maintenance-mode window needed for a consistent file/database cut.

## Confirmed starting conditions (18 Oct 2026)

- New mail host: mx.thebergens.net; Nextcloud root:
  /usr/share/nginx/de.tbergen.cloud/html; data/ is inside this filesystem.
- MariaDB database: nextcloud; all tables InnoDB; root can dump over local socket.
- Existing Nextcloud encryption is disabled.
- Synology MountainCloud export:
  192.168.6.11:/volume1/nextcloud-backup mounted on mx2 at
  /mnt/nextcloud-backup, NFSv4.1, sec=sys, rw. Exact export, hostname and
  permissions are checked before any application modification.
- Dedicated root-owned backup folder /mnt/nextcloud-backup/mx2-nextcloud,
  and export root both mode 0700.
- Traffic is WireGuard-encrypted **only to the UCG**; UCG-to-Synology
  NFS sec=sys is NOT encrypted. Backup archive is unencrypted on Synology
  by explicit recovery requirement. DSM share/export/firewall ACLs and
  Synology-admin-controlled snapshots are mandatory compensating controls.

## How it works

One root-owned systemd oneshot executes daily at 04:30 in the server's
timezone, independently of the existing 00:00 mail backup. A lock rejects
overlap. The first successful installation *runs the backup immediately*;
this is not a separate operator-run manual database dump.

1. Fail closed if wrong host, NFS export unmounted/mismatched, backup dirs
   not root-owned mode 0700, unexpected nested Nextcloud mounts, incorrect
   database engine, already active maintenance mode, or insufficient free
   local disk space.
2. Live rsync to /var/lib/bergen-nextcloud-backup/stage/html (local disk).
3. Enable Nextcloud maintenance mode, drain running apache cron.php,
   wait briefly for admitted requests, final rsync including deletions;
   dump nextcloud with mariadb-dump --single-transaction; compress SQL.
4. ALWAYS attempt to disable maintenance mode in the error cleanup path.
   If that fails, report CRITICAL_NEXTCLOUD_MAINTENANCE_DISABLE_FAILED
   and require immediate administrator intervention.
5. With Nextcloud online, archive local staged html/ plus SQL and manifest
   as an ordinary GNU tar.gz (including ACL/xattr/SELinux metadata).
   Verify decompression with tar -tzf.
6. Transfer into unique hidden temporary NFS folder; SHA-256 compare local
   and remote archive; publish SHA256SUMS and COMPLETE. Atomically rename
   the directory only on success. A complete backup appears as
   mx2-nextcloud/backup-YYYYMMDDTHHMMSSZ-PID/.
7. Keep the 30 newest completed sets. Ignore/delete NO mail backups or other
   NAS paths. A failed job leaves any .incoming directory for diagnosis,
   not a successful backup marker.

The local stage persists between runs for rsync efficiency; the temporary
compressed archive is removed after transfer. Old independently made
/root/bergen-nextcloud-stage.* folders are untouched.

**Recovery note:** the archive captures config.php in maintenance mode.
During isolated restore, bring the restored instance out of maintenance mode
only *after* importing the matching nextcloud.sql.gz and reviewing config,
secrets, ownership, domain and environment. A standby old mx1 database is
not a current restore point after mx2 starts accepting edits.

## Deploy from bp-controller

Use a **separate Git worktree**, never overwrite untracked Paperless files
or conflict with PR #108. Keep the reviewed local SSH and Nextcloud stack
vars from the existing audit in the original main checkout.

    BASE="$HOME/bergen-platform"
    cd "$BASE"
    git fetch origin feat/nextcloud-consistent-nfs-backup-20261018
    git worktree add --detach "$HOME/bergen-platform-nextcloud-backup" \
      origin/feat/nextcloud-consistent-nfs-backup-20261018
    cd "$HOME/bergen-platform-nextcloud-backup"

Create a Git-ignored NFS config *in this separate worktree*:

    umask 077
    cat > ansible/vars/nextcloud-backup.local.yml <<'EOF'
    ---
    nextcloud_backup_nfs_source: 192.168.6.11:/volume1/nextcloud-backup
    nextcloud_backup_mount: /mnt/nextcloud-backup
    EOF
    chmod 600 ansible/vars/nextcloud-backup.local.yml
    git check-ignore -q ansible/vars/nextcloud-backup.local.yml

The following **single deployment** executes the actual first full backup
and verifies the committed remote snapshot before enabling the timer:

    ansible-playbook \
      -i "$BASE/ansible/inventory.yml" \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/deploy-nextcloud-consistent-backup.yml \
      -e @"$BASE/ansible/vars/mail-tls.local.yml" \
      -e @"$BASE/ansible/vars/mail-nextcloud-stack.local.yml" \
      -e @ansible/vars/nextcloud-backup.local.yml

Expect NEXTCLOUD_BACKUP_REMOTE_COMMITTED=YES, timer
ENABLED_04_30_LOCAL and NEXTCLOUD_ONLINE=YES. If a first run fails,
the timer is NOT enabled by this playbook. Inspect the oneshot logs
without exposing paths or secrets to third parties.

Read-only checks after completion on mx2:

    systemctl is-enabled bergen-nextcloud-backup.timer
    systemctl is-active bergen-nextcloud-backup.timer
    systemctl show bergen-nextcloud-backup.service -p Result -p ExecMainStatus
    journalctl -u bergen-nextcloud-backup.service -n 40 --no-pager
    cat /var/lib/bergen-nextcloud-backup/last-success.txt

The success file is root-readable and contains timestamp, published remote
directory and SHA-256 digest. The first implementation validates archive
readability and checksum; a full DB + file restore test onto a *separate*
server remains a further acceptance gate. Do not retire the old Nextcloud
until recovery has been tested and Synology snapshots/retention are reviewed.

## Isolated restore outline

Choose a completed snapshot directory on Synology, verify its SHA256SUMS,
then extract the nextcloud.tar.gz using GNU tar with ACL/xattr/SELinux
support onto an isolated replacement host. Restore the SQL dump into an
isolated MariaDB instance (avoid running its database CREATE/USE commands
on production). Verify configs/secrets and ownership before switching
hostnames or disabling maintenance mode. Check users, shares, Contacts,
Calendar, documents and Collabora separately. Never test restore on the
live mx2 database or the NFS backup directory itself.

## Operational limitations

- No application-specific coordination for third-party writers outside
  Nextcloud's maintenance mode; inspect integrations before relying on
  application quiescence for zero-write windows.
- If cron.php cannot drain within 120 seconds, the run fails closed and
  attempts to bring Nextcloud back online.
- NFS sec=sys has no Kerberos identity protection or link encryption inside
  the DMZ. Root on compromised mx2 can delete any mutable backup snapshots.
  Protect completed sets with Synology snapshots/immutability administered
  independently, not with chmod alone.
- Backups are readable by Synology administrators. Keep DSM accounts/export
  allowlist and snapshot permissions restricted.
- 30 complete daily archives may use several hundred gigabytes; size and
  free space require ongoing monitoring and alerting.
