# MQTT role

Deploys Eclipse Mosquitto as the Bergen Platform MQTT broker.

## Design

- dedicated Debian LXC
- MQTT listener on TCP/1883 by default
- anonymous access disabled by default
- password authentication and ACL support
- Mosquitto persistence enabled for retained messages and persistent sessions
- broker logs go to syslog and can be forwarded to the central Bergen syslog node

MQTT remains a messaging layer, not the platform's historical telemetry archive.
Applications that require historical MQTT data should persist selected topics in
a dedicated datastore or analysis pipeline.

## Credentials

Define `mqtt_users` in an encrypted variable source, preferably Ansible Vault.
Do not commit MQTT passwords to the repository.

Example:

```yaml
mqtt_users:
  - username: homey
    password: "{{ vault_mqtt_homey_password }}"
  - username: evcc
    password: "{{ vault_mqtt_evcc_password }}"
```

## Deployment

Provision the LXC with the standard Bergen Platform workflow:

```bash
ansible-playbook ansible/playbooks/deploy-lxc.yml \
  -e @ansible/group_vars/all/bergen-mqtt.yml \
  --ask-vault-pass
```

After discovery/inventory registration, configure the broker:

```bash
ansible-playbook ansible/playbooks/bootstrap-mqtt.yml \
  --ask-vault-pass
```
