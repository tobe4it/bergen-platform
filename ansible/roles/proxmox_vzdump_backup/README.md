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

## Reuse of an already running timer (17.10.2026)

**No blind replacement.** If service/timer unit files already exist on the Proxmox host, they must both be root-owned regular 0644 files and byte-identical to the rendered, locally reviewed unit templates. The playbook only audits them when identical; it does not rewrite existing units. A differing pair fails with `BACKUP_UNIT_DRIFT`, or an incomplete pair with `BACKUP_UNIT_PARTIAL_OR_UNTRUSTED`. Review a separate migration; do not overwrite the existing backup schedule to silence these checks.

If the existing enablement state differs from the reviewed desired state, it is rejected unless the **independent** local `paperless_backup_existing_timer_state_change_approved=true` gate is set. The baseline defaults both approvals to false. The playbook never executes `vzdump` directly, but enabling a timer may schedule a future backup and its retention policy: do not enable on a production host without observing the active schedule and checking for duplicate cluster jobs.

The old document describing a disabled timer represented the PR state, not the already-running system observed in October 2026. A successful code merge neither installs nor restarts its service. For a live site, first run a read-only audit and record the unit checksums, backup logs and independent restore evidence. Exact NFS storage/volume checks and the reviewed daily 03:00/7-4-12 policy remain mandatory. Existing VZDump archives are **not** immutable or independently encrypted.
