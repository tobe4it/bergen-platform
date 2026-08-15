# MQTT

Bergen Platform provides a centrally managed Mosquitto MQTT broker deployed and configured with Ansible.

## Architecture

The MQTT service runs on the Bergen Platform MQTT LXC container.

- Broker: Mosquitto
- MQTT port: `1883`
- Anonymous access: disabled
- Authentication: per-client username and password
- Authorization: per-user topic ACLs
- Configuration management: Ansible
- Secrets: Ansible Vault / interactive password input

Client applications and devices use dedicated technical users rather than sharing credentials.

## Deployment

Deploy or reconcile the MQTT node from `bp-controller`:

```bash
ansible-playbook ansible/playbooks/bootstrap-mqtt.yml --ask-vault-pass
```

The MQTT role installs Mosquitto, creates the persistence and authentication files, configures the listener and ACL, validates the Mosquitto configuration, and starts the service.

## Configuration

The role is located at:

```text
ansible/roles/mqtt/
```

Platform-specific MQTT variables are maintained under:

```text
ansible/group_vars/all/bergen-mqtt.yml
```

Do not store plaintext client passwords in Git.

## MQTT user management

Technical users are managed from `bp-controller` with:

```bash
tools/mqtt-user
```

If a fresh checkout does not have the executable bit set, it can also be invoked explicitly with Bash:

```bash
bash tools/mqtt-user ...
```

The tool accepts repeated `--read`, `--write`, and `--rw` options. Topic filters are passed to Ansible as native lists, including MQTT wildcards such as `#` and `+`.

### Current production ACLs

The current clients follow least privilege:

```text
user evcc
  write evcc/#

user go-echarger
  write go-eCharger/#

user homey
  read  go-eCharger/#
  read  evcc/#
  write homey/#
```

This allows evcc and the go-eCharger to publish their own data. Homey can consume both namespaces and publish its own MQTT messages below `homey/#`.

### Add or reconcile a user

For example, the current Homey permissions are configured with:

```bash
bash tools/mqtt-user add homey \
  --read 'go-eCharger/#' \
  --read 'evcc/#' \
  --write 'homey/#'
```

The go-eCharger and evcc publisher accounts can be configured with:

```bash
bash tools/mqtt-user add go-echarger --write 'go-eCharger/#'
bash tools/mqtt-user add evcc --write 'evcc/#'
```

The tool prompts for the MQTT password without echoing it. For add/remove operations it uses a mode-0600 temporary JSON vars file so ACL topic filters reach Ansible as correctly typed lists; the temporary file is removed after the run.

### Change a password

```bash
bash tools/mqtt-user passwd homey
```

Password changes preserve the existing ACL fragment.

### Remove a user

```bash
bash tools/mqtt-user remove homey
```

ACL fragments are stored per user under `/etc/mosquitto/acl.d/` and combined into `/etc/mosquitto/acl` by the user-management playbook.

The resulting production ACL can be inspected on the broker with:

```bash
cat /etc/mosquitto/acl
```

## Clients

### go-eCharger

The go-eCharger connects directly to the broker and publishes below its configured prefix, currently:

```text
go-eCharger/090580/
```

It authenticates with the dedicated `go-echarger` account and has write access to `go-eCharger/#`.

### Homey

The Homey MQTT Client connects directly to Mosquitto with its dedicated account. Current settings are:

```text
Broker: 192.168.20.138
Port: 1883
Username: homey
Client ID: homey
TLS: disabled on the trusted internal network
```

Homey reads `go-eCharger/#` and `evcc/#` and may publish under `homey/#`.

LWT (Last Will and Testament) is optional. It allows the broker to publish a predefined status message if Homey loses its MQTT connection unexpectedly.

### evcc

evcc connects to the central MQTT broker and publishes below `evcc/#` using its dedicated `evcc` account.

Its direct control of the go-eCharger is independent of MQTT: evcc uses the `go-e-v3` charger template and accesses the charger's IP directly. The go-eCharger separately publishes its telemetry to Mosquitto.

## Verification

Check that Mosquitto is running:

```bash
systemctl status mosquitto
```

Follow broker connections and authentication events:

```bash
journalctl -u mosquitto -f
```

Subscribe with an appropriately authorized account. For the current Homey ACL, a useful broker-side test is:

```bash
mosquitto_sub -h 127.0.0.1 -p 1883 \
  -u homey -P '<password>' \
  -t 'go-eCharger/#' \
  -t 'evcc/#' \
  -v
```

The end-to-end path has been verified in production: messages published by the go-eCharger and evcc reach Mosquitto and are received by the Homey MQTT Client.

For retained-message diagnostics, `--retained-only` can be used with `mosquitto_sub`. Without it, a subscription remains active and also displays newly published messages.

## Troubleshooting

### `not authorised`

Check:

1. username and password on the client,
2. that the user exists in the Mosquitto password file,
3. the user's ACL,
4. the topic prefix used by the client.

Broker-side diagnosis:

```bash
journalctl -u mosquitto -f
```

Remember that a successful TCP connection to port 1883 does not prove that MQTT authentication or ACL authorization succeeded.

### Validate Mosquitto configuration

```bash
mosquitto -c /etc/mosquitto/mosquitto.conf -t
```

A configuration validation failure must be fixed before restarting the broker.

### Duplicate configuration directives

Mosquitto loads its main configuration and included files. A directive such as persistence settings must not be defined incompatibly in multiple loaded files. Bergen Platform's Ansible role owns the generated MQTT configuration; avoid parallel manual configuration of the same directives.

## Security model

The intended model is one technical MQTT user per application or device class, with least-privilege topic ACLs. Broad `#` read/write access should primarily be used during initial diagnostics or where a client genuinely needs access to the complete topic tree.

MQTT on port 1883 is unencrypted. It is intended for the trusted internal network. If MQTT is exposed across untrusted networks, TLS and appropriate network-level access controls are required.
