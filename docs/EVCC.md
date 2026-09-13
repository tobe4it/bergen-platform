# EVCC Charging Control

## Purpose

`bergen-evcc` provides EVCC charging control in a dedicated Debian 13 LXC. It
replaces the existing EVCC host without discarding configuration, UI settings,
credentials or charging history.

The migration preserves both EVCC persistence layers:

- `/etc/evcc.yaml` when file-based configuration is used
- `/var/lib/evcc/evcc.db` for UI configuration, settings and history

Neither file is stored in Git because both may contain credentials or other
private installation data.

## Platform design

- LXC: Debian 13, unprivileged
- VMID, storage and Proxmox node: local parameters
- Hostname: `bergen-evcc`
- CPU: 1 vCPU
- RAM: 1024 MiB
- Root filesystem: 8 GiB
- Runtime: native EVCC systemd service
- EVCC release: pinned and checksum-verified in `bergen-evcc.yml`
- Network bridge/VLAN: local parameter
- Initial addressing: DHCP for discovery and parallel staging
- Existing EVCC source: local inventory parameter
- Central logging: optional queued TCP/UDP Syslog forwarding

The dedicated LXC already provides an isolation boundary. A native package
keeps multicast, local device discovery and possible future serial-device
access simpler than a second container layer.

## Safety model

Only one EVCC instance may control the charger. The first deployment therefore
installs EVCC but leaves `evcc.service` stopped and disabled. The migration
playbook starts the new instance and disables the old one as one guarded
cutover.

The cutover playbook:

1. verifies source, target and explicit operator confirmation;
2. requires the target service to be inactive;
3. records the source EVCC service state;
4. preserves any existing target data;
5. stops the old EVCC service;
6. creates a permanent source-side SQLite backup;
7. transfers the database and optional YAML through a protected temporary
   controller directory;
8. verifies SHA-256 checksums, SQLite integrity and YAML syntax;
9. starts and validates the new EVCC HTTP endpoint;
10. disables the old service only after all target checks pass.

If a migration task fails, Ansible stops the target and restores the old
service's previous enablement and runtime state. The source database and the
new source-side backup are never modified during target validation.

## First deployment

Create the ignored local configuration from the public template and replace all
`CHANGE_ME` values:

```bash
cp ansible/group_vars/all/bergen-evcc.yml.example \
  ansible/group_vars/all/bergen-evcc.yml
```

Run from the Ansible controller:

```bash
cd /opt/bergen-platform
git pull --ff-only

ansible-playbook ansible/playbooks/deploy-evcc.yml \
  -e @ansible/group_vars/all/bergen-evcc.yml \
  --ask-vault-pass
```

The playbook rejects the configured VMID if it belongs to a different guest.
On success it reports the DHCP address and leaves EVCC stopped.

Reserve the reported address/MAC in UniFi before migration. Add the stable
target and the existing source to the ignored `ansible/inventory.local.yml`:

```yaml
all:
  children:
    evcc_nodes:
      hosts:
        bergen-evcc:
          ansible_host: NEW_EVCC_IP
          ansible_user: root
          ansible_python_interpreter: /usr/bin/python3

    evcc_legacy_nodes:
      hosts:
        evcc-old:
          ansible_host: OLD_EVCC_IP
          ansible_user: root
          ansible_python_interpreter: /usr/bin/python3
```

Verify SSH reachability from `bp-controller` before cutover:

```bash
ansible evcc_nodes:evcc_legacy_nodes \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  -m ping
```

## Migration and cutover

The default source paths match a native Debian EVCC installation. Check them on
the old host before running the cutover:

```bash
ssh root@OLD_EVCC_IP
systemctl status evcc --no-pager
evcc --version
ls -lh /etc/evcc.yaml /var/lib/evcc/evcc.db
```

It is valid for `/etc/evcc.yaml` to be absent when the installation is managed
entirely through the web UI. The database is mandatory.

Choose a quiet moment with no active charging session and run:

```bash
ansible-playbook ansible/playbooks/migrate-evcc.yml \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  -e evcc_migration_confirm=true
```

The explicit confirmation prevents an accidental stop of the production
service. No Vault password is required unless the local inventory itself uses
vaulted connection variables.

For a non-standard native source layout, override either path explicitly:

```bash
ansible-playbook ansible/playbooks/migrate-evcc.yml \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  -e evcc_migration_confirm=true \
  -e evcc_migration_source_config_path=/custom/evcc.yaml \
  -e evcc_migration_source_database_path=/custom/evcc.db
```

The automated cutover currently expects the old installation to use a native
`evcc.service`. A Docker, Podman or Home Assistant source must be stopped and
exported according to that runtime before adapting the source paths.

## Post-migration checks

Open the target web interface:

```text
http://NEW_EVCC_IP:7070
```

Confirm before retiring the old LXC:

- previous charging sessions and energy history are visible;
- site, meter, charger and vehicle status are plausible;
- a harmless charger-state read succeeds;
- EVCC publishes below `evcc/#` to the configured MQTT broker;
- Homey still receives the EVCC topics;
- EVCC logs arrive at the configured Syslog server;
- no active charging plan or vehicle assignment was lost.

Keep the old LXC powered off but undeleted until at least one real charging
cycle has completed successfully. Its migration backup remains below
`/var/backups/evcc/migration-<timestamp>`.

## Reusing the old address

Migration should first succeed on the new LXC's temporary reserved address. If
clients or bookmarks must continue using `OLD_EVCC_IP`, transfer that DHCP
reservation to the new LXC MAC only after the old service is stopped and
the new instance is validated. Then renew the new LXC lease and update
`inventory.local.yml`.

Never allow both machines to claim `OLD_EVCC_IP` at the same time.

## Rollback

If post-migration functional checks fail:

```bash
systemctl disable --now evcc   # on bergen-evcc
systemctl enable --now evcc    # on the old EVCC host
```

If the old address was transferred, restore its previous UniFi reservation
before starting the old host. The migration does not alter the old EVCC files,
and a second backup is retained on that host.

## Normal reconciliation

After migration, the regular service playbook enforces the operational
started/enabled state from `bergen-evcc.yml`:

```bash
ansible-playbook ansible/playbooks/bootstrap-evcc.yml \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  -e @ansible/group_vars/all/bergen-evcc.yml \
  --ask-vault-pass
```

Before changing `evcc_version`, review every intervening EVCC release for
breaking changes, update the matching SHA-256 checksums and retain a current
database backup.
