# EVCC role

## Purpose

The `evcc` role installs a pinned EVCC release as a native Debian package and
manages its systemd service on a dedicated LXC.

A native installation is intentional: the LXC already provides the service
boundary, while direct networking keeps local device discovery, multicast and
future serial-device access uncomplicated.

## Managed state

- EVCC Debian package downloaded from the upstream GitHub release
- SHA-256 verification before installation
- `/var/lib/evcc` persistent database directory
- `/var/backups/evcc` protected local backup directory
- `evcc.service` enablement and runtime state
- configuration syntax, service state and HTTP listener validation

The role does not generate `/etc/evcc.yaml`. EVCC configuration often contains
device, vehicle, MQTT and sponsor credentials. Existing configuration is
transferred by the dedicated migration playbook and remains outside Git.

## Important variables

```yaml
evcc_version: "0.315.0"
evcc_service_enabled: true
evcc_service_state: started
evcc_config_path: /etc/evcc.yaml
evcc_database_path: /var/lib/evcc/evcc.db
```

The first LXC deployment explicitly overrides the service to
`stopped`/`disabled`. This prevents the old and new EVCC instances from
controlling the same charger at the same time.

## Validation

When running, the role verifies the systemd service, TCP port `7070` and the
local `/api/state` endpoint. If an `evcc.yaml` exists, `evcc checkconfig` parses
it with `--ignore-db` before the service result is accepted.
