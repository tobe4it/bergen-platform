# Provider-neutral daytrading LXC

The former market-data integrations remain removed. This repository does not
fetch, process or redistribute market data and does not generate trading
signals.

The retained Ansible automation provisions the dedicated LXC and installs a
small notification helper with a single `mail-test` command.

## SMTP configuration

Keep host names and mail addresses in the Git-ignored local file:

```yaml
# ansible/group_vars/all/bergen-daytrade.yml
daytrading_smtp_host: mail.thebergens.net
daytrading_smtp_port: 587
daytrading_smtp_starttls: true
daytrading_smtp_username: daytrading@thebergens.net
daytrading_email_from: daytrading@thebergens.net
daytrading_email_to: YOUR_RECIPIENT
```

The password has exactly one Ansible source of truth and must not be placed in
that file:

```bash
ansible-vault edit ansible/group_vars/all/vault.yml
```

Add or replace the encrypted variable:

```yaml
vault_daytrading_smtp_password: "ROTATED_PASSWORD"
```

During deployment Ansible writes the credential to the dedicated target file
`/etc/bergen-daytrading-smtp-password` with mode `0400`. The JSON configuration
contains only the file path, never the password.

## Deploy

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/daytrading-collector.yml \
  --ask-vault-pass
```

The playbook also stops and removes obsolete collector service and timer units.
Existing result files below `/var/lib/bergen-daytrading` remain untouched.

## Test mail delivery

```bash
ansible -i ansible/inventory.local.yml market_collectors -b -m command -a \
  '/usr/bin/python3 /opt/bergen/daytrading-collector/collector.py --config /etc/bergen-daytrading.json mail-test'
```

The command exits successfully only after SMTP authentication and message
submission complete. It prints the recipient and the test payload, but never
the credential.

## Future data integration

Before adding another source, obtain terms that explicitly permit automated or
non-display processing, intraday data, derived signals, retention and any
required exchange entitlements. Credentials belong in Ansible Vault.
