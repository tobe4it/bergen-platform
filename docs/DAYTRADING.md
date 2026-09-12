# Provider-neutral daytrading LXC

The former market-data collector and all provider-specific integrations have
been removed. This repository does not fetch, process or redistribute market
data and does not generate trading signals.

The retained Ansible automation can provision a dedicated LXC, discover its
effective IPv4 address and maintain the host below `market_collectors` in the
Git-ignored `ansible/inventory.local.yml`.

## Local configuration

Create the ignored configuration and set at least `lxc_vmid` and `lxc_bridge`:

```bash
cp ansible/group_vars/all/bergen-daytrade.yml.example \
  ansible/group_vars/all/bergen-daytrade.yml
```

## Provision or reconcile the LXC

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  ansible/playbooks/deploy-daytrading.yml \
  -e @ansible/group_vars/all/bergen-daytrade.yml \
  --ask-vault-pass
```

The included cleanup role stops and removes any previously deployed collector
service, timer, program and configuration. Existing result files below
`/var/lib/bergen-daytrading` are preserved so they can be reviewed or deleted
locally at a later time.

To apply only the cleanup to an existing host:

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/daytrading-collector.yml
```

## Future data integration

Before adding another source, obtain terms that explicitly permit the intended
use, including automated or non-display processing, intraday data, derived
signals, retention and any required exchange entitlements. Credentials belong
in local variables or Ansible Vault and must not be committed.
