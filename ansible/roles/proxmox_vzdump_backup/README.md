# Proxmox VZDump backup (Bergen Paperless)

Dedicated, explicitly approved **Proxmox-host-side** systemd timer for LXC backup.
Does not deploy Paperless, change the Proxmox global `/etc/vzdump.conf`, or
create native `/cluster/backup` jobs.

## Why a dedicated timer?

The verified first NFS backup of the **unprivileged** Paperless LXC failed because
`tar` could not open its temporary tree on NFS. The successful full backup used
`vzdump ... --mode stop --compress zstd --tmpdir /var/tmp`. A per-service
`--tmpdir` avoids changing VZDump defaults for unrelated guests.

The systemd calendar is exactly `03:00 Europe/Berlin`. On boot, missed runs
are **not** replayed (`Persistent=false`). The guest is stopped during the
backup for PostgreSQL file consistency. Backups may take longer as documents grow.

## Scope and safety

- Requires explicit, site-local target host, LXC VMID and hostname, storage ID
  and exact NFS export path.
- Requires `paperless_backup_schedule_approved=true` at each execution.
- Verifies actual Proxmox hostname, unprivileged LXC, local-ZFS root and
  `mp0` with `backup=1`, active NFS storage and exact mount source.
- Refuses remote or non-sticky `/var/tmp`.
- Creates a single dedicated systemd service and timer only; **does not
  execute a backup during deployment**.
- Pruning applies to the target LXC backup set using
  `keep-daily=7,keep-weekly=4,keep-monthly=12`.
- Does not configure independent encrypted exports, immutable backups, or
  notifications beyond the existing Proxmox VZDump notification target.

Only one scheduler should manage this LXC's backups. Review
`pvesh get /cluster/backup` and `systemctl list-timers --all` before enabling.
The job is visible under **systemd timers**, not Proxmox Datacenter → Backup.

## Deploy from bp-controller

Copy `docs/examples/paperless-backup.local.yml.example` into ignored
`ansible/vars/paperless-backup.local.yml`, then review actual host, volume
and NFS export. Confirm the temporary restore VMID 901 has been destroyed,
and the known-good manual archive remains on the Synology.

```bash
ansible-playbook -i ansible/inventory.local.yml \
  ansible/playbooks/configure-paperless-backup.yml \
  -e @ansible/vars/paperless-backup.local.yml \
  -e paperless_backup_schedule_approved=true --check

ansible-playbook -i ansible/inventory.local.yml \
  ansible/playbooks/configure-paperless-backup.yml \
  -e @ansible/vars/paperless-backup.local.yml \
  -e paperless_backup_schedule_approved=true
```

Inspect next execution, service status and logs:

```bash
ssh root@YOUR_PROXMOX_ADDRESS 'systemctl list-timers --all bergen-paperless-vzdump.timer'
ssh root@YOUR_PROXMOX_ADDRESS 'systemctl status bergen-paperless-vzdump.timer --no-pager'
ssh root@YOUR_PROXMOX_ADDRESS 'journalctl -u bergen-paperless-vzdump.service -n 100 --no-pager'
```

Check the Proxmox VZDump notification target and a real scheduled execution.
Repeat an isolated full restore periodically and maintain a separate,
preferably encrypted, document/database export backup. The NFS archive itself
is **not** encrypted or immutable.
