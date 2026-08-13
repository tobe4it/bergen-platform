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

Client applications and devices should use dedicated technical users rather than sharing credentials.

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

If a fresh checkout does not have the executable bit set, correct it once with:

```bash
chmod +x tools/mqtt-user
```

### Add a user

Full read/write access:

```bash
tools/mqtt-user add homey --rw '#'
```

Restrict a client to a namespace:

```bash
tools/mqtt-user add go-echarger --rw 'go-eCharger/#'
```

The tool prompts for the password without echoing it and passes it to Ansible only for that invocation.

### Change a password

```bash
tools/mqtt-user passwd homey
```

### Remove a user

```bash
tools/mqtt-user remove homey
```

ACLs are generated per user and combined into the Mosquitto ACL configuration by the Ansible role.

## Clients

### go-eCharger

The go-eCharger connects directly to the broker and publishes below its configured prefix, for example:

```text
go-eCharger/090580/
```

Use a dedicated `go-echarger` account and restrict its ACL to the required go-eCharger namespace where practical.

### Homey

The Homey MQTT Client connects directly to Mosquitto with its dedicated account. Typical settings are:

```text
Broker: <MQTT broker address>
Port: 1883
Username: homey
Client ID: homey
TLS: disabled on the trusted internal network
```

Grant only the topic permissions Homey actually requires. `--rw '#'` is useful during migration and testing but can later be narrowed.

LWT (Last Will and Testament) is optional. It allows the broker to publish a predefined status message if Homey loses its MQTT connection unexpectedly.

### evcc

evcc can connect to the central MQTT broker for its own MQTT integration. Its direct control of the go-eCharger is independent of MQTT when evcc uses the `go-e-v3` charger template and accesses the charger's IP directly.

Use a dedicated `evcc` MQTT account if MQTT is enabled for evcc.

## Verification

Check that Mosquitto is running:

```bash
systemctl status mosquitto
```

Follow broker connections and authentication events:

```bash
journalctl -u mosquitto -f
```

Subscribe to all topics for a short diagnostic test using an appropriately authorized account:

```bash
mosquitto_sub -h <broker> -p 1883 -u <user> -P '<password>' -t '#' -v
```

For a go-eCharger-specific test:

```bash
mosquitto_sub -h <broker> -p 1883 -u <user> -P '<password>' -t 'go-eCharger/#' -v
```

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

### Validate Mosquitto configuration

```bash
mosquitto -c /etc/mosquitto/mosquitto.conf -t
```

A configuration validation failure must be fixed before restarting the broker.

### Duplicate configuration directives

Mosquitto loads its main configuration and included files. A directive such as persistence settings must not be defined incompatibly in multiple loaded files. Bergen Platform's Ansible role owns the generated MQTT configuration; avoid parallel manual configuration of the same directives.

## Security model

The intended model is one technical MQTT user per application or device class, with least-privilege topic ACLs. Broad `#` read/write access should primarily be used during initial migration or where a client genuinely needs access to the complete topic tree.

MQTT on port 1883 is unencrypted. It is intended for the trusted internal network. If MQTT is exposed across untrusted networks, TLS and appropriate network-level access controls are required.
