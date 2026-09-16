# MQ evaluation: second queue manager and isolated client

Infrastructure extension for the existing `BERGENLAB` evaluation. It does not
replace the passed single-QMgr object audit and does not yet certify message
transport. Productive licensing must be clarified with IBM.

| Guest | QMgr | Purpose |
| --- | --- | --- |
| Existing `bergen-mq-lab` | `BERGENLAB` | Existing server and retained audit evidence |
| New `bergen-mq-lab-b` | `BERGENLABB` | Independent server, CA, secrets and persistence |
| New `bergen-mq-client` | None | Java compiler and MQ Java client, account `mqtest` |

The service/container name `bergen-mq-lab` remains local to each server LXC.
Always select the correct inventory host first. Both servers use their own
`/etc/bergen-mq-lab/storage.conf`; identical guest-local paths do not share data.
Controller CA and connection files are separate per server. The generated B
connection file references `vault_mq_lab_b_admin_password`, never A's password.

## Site configuration

Run from the repository on bp-controller:

```bash
mkdir -p ansible/vars/mq-topology
cp -n ansible/examples/mq-topology/qmgr-b.yml.example ansible/vars/mq-topology/qmgr-b.yml
cp -n ansible/examples/mq-topology/client.yml.example ansible/vars/mq-topology/client.yml
vim ansible/vars/mq-topology/qmgr-b.yml ansible/vars/mq-topology/client.yml
```

Fill free VMIDs, Rocky 9 template, storage, Proxmox node/inventory name, bridge
and syslog settings. No VMID or address is preallocated by these examples.
Select the IoT bridge for B and the Intern bridge for the client. If using DHCP,
reserve the discovered addresses before configuring TLS endpoints and firewall
source rules. Review the explicit evaluation/license gates in both files.
Use separate Vault secrets `vault_mq_lab_b_admin_password` and
`vault_mq_lab_b_app_password`, each at least 12 characters and different from
each other and A's secrets. Add them through `ansible-vault edit` to your existing
encrypted Vault. Existing controller/Proxmox and root credentials are reused.

Keep these site files under `ansible/vars/mq-topology/`, not `group_vars/all/`:
Ansible automatically loads every YAML file in the latter for every host.
Each invocation receives exactly one site file with `-e @...`.

## Deploy

First run the controller syntax checks using its installed Proxmox/Ansible
collections and populated site files:

```bash
ansible-playbook ansible/playbooks/deploy-mq-lab.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-topology/qmgr-b.yml --ask-vault-pass --syntax-check

ansible-playbook ansible/playbooks/deploy-mq-client.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-topology/client.yml --ask-vault-pass --syntax-check
```

```bash
ansible-playbook ansible/playbooks/deploy-mq-lab.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-topology/qmgr-b.yml --ask-vault-pass

ansible-playbook ansible/playbooks/deploy-mq-client.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-topology/client.yml --ask-vault-pass
```

VMID collisions with different guests/nodes fail before creation. The server
creation step explicitly uses `update: false`, preserving an existing guest's
network/MAC configuration across repeat runs regardless of collection defaults.
DHCP itself does not guarantee a permanent address; use local DHCP reservations
for stable TLS endpoints and firewall sources.
The server
deployment includes the existing explicit stop/start step for its selected LXC;
do not point B's site file at A. To reconfigure B without that step:

```bash
ansible-playbook ansible/playbooks/bootstrap-mq-lab.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-topology/qmgr-b.yml \
  -e bootstrap_mq_lab_target=bergen-mq-lab-b --ask-vault-pass
```

Never run a shared `mq_lab_nodes` bootstrap with B's extra variables against
both servers. Existing persistence identity checks refuse queue-manager renames.

The client deployment resolves the configured repository digest in local Podman
storage and compares its image ID with the source container's actual image ID.
It does not compare tag spelling in `ImageName` and never pulls a replacement.
An unknown digest or different image ID stops the deployment before copying.
It then
copies only the Java client JAR out of it, fetches it over SSH and checks SHA-256
after installation. A temporary source directory is removed in an `always`
block. The source service is not restarted. Client provenance is stored in
`/opt/bergen-mq-client/provenance.json`. Repeating client deployment does not
restart a running client LXC. Artifact staging can still report changes.

## Network and test rollout

Controller SSH to each new guest and HTTPS 9443 to B must work. B's host firewall
permits HTTPS only from the configured controller/admin sources. No new messaging
rule is enabled by default. The client exposes no application listener.

Later, authorize client IP → A/B TCP 1414 and A ↔ B TCP 1414, scoped to those
addresses, in both UniFi and the server host firewall. These rules alone do not
configure MQ listeners, TLS, SVRCONN, SDR/RCVR, CHLAUTH or OAM.

The next test implementation must configure dedicated test identities and trust,
then verify:

1. Client-mode PUT/GET, message identity/payload and commit/rollback on one QMgr.
2. Positive and negative TLS, authentication and authority cases.
3. A QREMOTE → A XMITQ → A SDR → B RCVR → B QLOCAL, plus a separate reverse pair.
4. Bounded channel interruption/recovery without losing or silently deleting data.

The current infrastructure deployment reports these as **NOT_TESTED**. No blanket
CHLAUTH disable, FORCE deletion, queue purge, or automatic audit PASS is used.
Live provisioning and second-run validation must be recorded on bp-controller;
offline syntax/unit tests do not establish live MQ compatibility.

## Development verification, 2026-09-16

- Python suite: 74 tests, 69 passed, 5 optional integration tests skipped.
- New role/examples YAML parsed; artifact collection playbook syntax check passed.
- Full deployment syntax check blocked in the development workspace by missing
  `community.proxmox` collection; collection installation did not complete.
- Neither new guest has been provisioned by these development checks.
