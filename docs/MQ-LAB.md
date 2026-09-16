# Rocky LXC + Podman MQ example / evaluation

> **EXAMPLE / EVALUATION ONLY. This setup is not approved for productive
> operation. Before any productive use, the license question must be clarified
> with IBM.**
>
> **Nur Beispiel / Evaluation, keine Freigabe für produktiven Betrieb.
> Für den produktiven Betrieb ist die Lizenzfrage mit IBM zu klären.**

Accepting developer-image terms for this evaluation does not grant a production
entitlement, establish commercial support or settle licensing for a future
deployment. View and review the applicable IBM terms before explicitly setting
`mq_lab_license_acceptance: accept`. Defaults do not accept the license.

## Purpose and boundary

Provides a real, disposable MQ test target for the [REST reconciler](MQ.md):
Rocky Linux 9 amd64 in an unprivileged Proxmox LXC, with a version/digest-pinned
IBM MQ Advanced for Developers image under Podman/Quadlet. Initial example
resources: two cores, 2 GiB RAM and 20 GiB disk; adjust for test workload.

IBM documents [developer secrets](https://github.com/ibm-messaging/mq-container/blob/master/docs/developer-config.md),
[persistence and TLS certificate mounting](https://github.com/ibm-messaging/mq-container/blob/master/docs/usage.md),
and [container UID 1001/GID 0 and capability removal](https://github.com/ibm-messaging/mq-container/blob/master/docs/security.md).
The example pins MQ 9.4 LTS `9.4.0.25-r3-amd64` to the public registry manifest
digest verified on 2026-09-15. The image has not yet been run on our Proxmox host;
registry availability is not a runtime or security certification. Review IBM
release/security guidance and match the intended production MQ version before
using evaluation results.

LXC shares the Proxmox host kernel: this is **not** an equivalent RHEL kernel,
SELinux, HA, storage/performance or vendor-support qualification. A Rocky/RHEL
VM is closer for operating-system/security testing. MQ object/API tests can
still run against the real containerized queue manager. Productive RHEL support
and licensing must be checked separately with IBM for the intended deployment.

The generic baseline and Podman roles are Debian-specific, so this role uses
DNF directly. Podman must be >=4.9 with its Quadlet generator and cgroup v2.
Dedicated VFS storage avoids nested overlay/FUSE assumptions. The LXC retains
AppArmor and unprivileged isolation: no unconfined profile, privileged fallback,
capability additions or permission bypass is implemented. If the runtime is
denied, stop and review or select a VM; do not disable protection blindly.

## Provisioning and local configuration

On the selected Proxmox node, find/download an available Rocky 9 template:

```bash
pveam update
pveam available | rg rockylinux-9
pveam download <template-storage> <selected-rockylinux-9-template>
```

On bp-controller, from `~/bergen-platform` with the Ansible venv active:

```bash
cp ansible/group_vars/all/bergen-mq-lab.yml.example \
  ansible/group_vars/all/bergen-mq-lab.yml
vim ansible/group_vars/all/bergen-mq-lab.yml
ansible-vault edit ansible/group_vars/all/vault.yml
```

Fill the free VMID, downloaded template volume ID, storage, bridge, Proxmox
inventory host/node and Syslog target. Set `mq_lab_controller_cidr` to the
controller's authorized source address (prefer `/32`), not the entire home
network. Add distinct >=12-character `vault_mq_lab_admin_password` and
`vault_mq_lab_app_password` to Vault. After reviewing terms and intended usage,
explicitly set `mq_lab_confirm_test_only: true` and
`mq_lab_license_acceptance: accept` for this evaluation only.

The role's `admin` is the dedicated **lab** administrator from the developer
image, not a production least-privilege recommendation. `MQ_DEV=false` avoids
creating the optional default DEV objects/channels; it does not certify the
remaining QMGR security policy as production-hardened. With `MQ_DEV=false`,
the image also selects its non-developer web configuration without the default
Basic-auth registry. Therefore this role explicitly mounts a read-only
`mqwebuser.xml` enabling `basicAuthenticationMQ-1.0` and binding only the lab
`admin` to REST/console `MQWebAdmin`. Its password references the image's
secret-derived `${env.MQ_ADMIN_PASSWORD_SECURE}`; no plaintext password is
rendered into XML. Web configuration changes recreate the container without
deleting QMGR persistence. This is not a production security recommendation.
MQ application secrets
are mounted via Podman secrets rather than deprecated password environment
variables. Protected root-only input files and Podman's local secret store
remain sensitive at rest; include them in backup/access policy.

Deploy:

```bash
ansible-playbook ansible/playbooks/deploy-mq-lab.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/group_vars/all/bergen-mq-lab.yml --ask-vault-pass
```

This validates license/evaluation gates, cluster-wide VMID identity and template
availability; creates the LXC, preserves unrelated runtime features while
enabling nesting/keyctl, restarts it, prepares OpenSSH through `pct exec`,
discovers DHCP/SSH, writes the ignored
`mq_lab_nodes` inventory entry and bootstraps Rocky/MQ. The **first-deployment**
workflow is not a dry run and includes an LXC restart. For subsequent runtime
reconciliation, use `bootstrap-mq-lab.yml` with the same inventories/vars instead
of repeating first deployment. For MQ object drift use `mq-objects.yml --check`.

If SSH host-key verification blocks bootstrap, independently verify the new
host's fingerprint and accept only that host through the usual controller
process. Do not disable host-key checking. Rocky must already provide Python 3
through its template. The deployment checks Rocky 9/amd64 and LXC identity,
installs `openssh-server` only if missing, generates only missing host keys,
validates SSH configuration and enables/starts `sshd` before SSH discovery.
Existing host keys, SSH login policy and Proxmox-installed authorized keys are
preserved; firewall/security restrictions are not bypassed. A failed deployment
at SSH discovery can be resumed by rerunning the deployment with the same VMID
and configuration; do not delete/recreate the existing LXC.
Reserve the discovered DHCP address afterward.

## Persistence, TLS, networking and logging

Authenticated REST readiness checks include the `ibm-mq-rest-csrf-token`
header, required even for GET requests using HTTP Basic authentication
([IBM authentication documentation](https://www.ibm.com/docs/en/ibm-mq/9.4.x?topic=security-using-http-basic-authentication-rest-api)).
Omitting it can produce HTTP 401 despite valid credentials. Do not work around
authentication failures by accepting 401 as readiness or disabling TLS checks.

- MQ state/messages live in `/var/lib/bergen-mq-lab/mqm`, bind-mounted to
  `/mnt/mqm` with IBM UID 1001/GID 0. Container recreation does not delete this
  directory. Existing unmarked data, QMGR renaming and image changes are refused.
- A private evaluation CA signs a **distinct** server certificate with host/IP
  SANs. Only the server key/chain is mounted into IBM's TLS importer; the CA
  private key stays in a protected LXC directory. Public CA is fetched over
  authenticated SSH to `ansible/reports/mq/bergen-mq-lab-ca.crt`; no global trust
  or insecure HTTPS certificate acceptance is used.
- Certificates are generated once. Address changes or imminent expiry fail
  validation rather than silently rotating keys. Reserve DHCP and review any
  renewal/address-change procedure explicitly; automated rotation is not included.
- MQ uses host networking **inside the LXC**. Web 9443 and MQ listener 1414 can
  bind there; host networking avoids Podman's nested DNAT path. Firewalld public
  zone rules allow HTTPS from the declared controller source. Client 1414 is
  allowed only when explicitly enabled for `mq_lab_client_cidr`.
- Previously role-managed firewall rules are revoked when their inputs change;
  unrelated rules are not deleted. Unexpected default zones or unrestricted MQ
  port openings block deployment. Existing interfaces/zones, other broad rules,
  Proxmox/UCG ACLs and IPv6 still need real-host review and external testing.
- Container stdout/stderr uses journald; Rocky rsyslog plus `remote_syslog`
  forwards host logs. Verify an actual MQ event arrives at the Syslog collector;
  the configuration/test emitter alone does not establish successful delivery.

The `bergen-mq-lab.service` is generated by Quadlet. Boot activation comes from
its `[Install]` section, not `systemctl enable` on a generated service, as
[Podman's Quadlet documentation](https://docs.podman.io/en/v4.9.3/markdown/podman-systemd.unit.5.html)
explains. Container runtime/cgroup restrictions and reboot persistence remain
part of real-host acceptance.

## Real MQ object acceptance

After verified local authenticated TLS/REST startup, bootstrap creates
`ansible/vars/mq-lab.local.yml` as an ignored connection example, without
overwriting existing user declarations and verifies controller-to-lab
authenticated HTTPS/REST. No smoke queue is silently created.
Inspect the connection file and run from the controller:

```bash
vim ansible/vars/mq-lab.local.yml
ansible-playbook ansible/playbooks/mq-objects.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-lab.local.yml --ask-vault-pass --check --diff
```

Review the proposed `BERGEN.LAB.SMOKE` creation. Apply the same command without
`--check`, then repeat; the unchanged declaration must report no changes. Change
one reviewed attribute and verify its incremental diff/update. Extend acceptance
to every supported object type, denied authorities and protected deletion per
[MQ.md](MQ.md). CHLAUTH/OAM are still separate pending features.

Useful diagnostics (Ansible/sudo, not unconditional root SSH):

```bash
ansible mq_lab_nodes -i ansible/inventory.yml -i ansible/inventory.local.yml \
  --ask-vault-pass -b -m command -a 'systemctl status bergen-mq-lab.service --no-pager'
ansible mq_lab_nodes -i ansible/inventory.yml -i ansible/inventory.local.yml \
  --ask-vault-pass -b -m command -a 'journalctl -u bergen-mq-lab.service -n 80 --no-pager'
```

Do not remove MQ data/CA material or downgrade the image as an error recovery
shortcut. Stop the generated service for a consistent lab backup and preserve
persistence, identity marker, pinned image reference and protected configuration.
Backup/restore and upgrades are not automated here.

## Verification status

Prepared and checked locally: YAML/Ansible syntax, rendered Quadlet/connection
contracts, license gates, secret/TLS settings, and actual OpenSSL certificate
generation/chain/SAN checks against temporary test paths.

**Not yet verified:** LXC creation, Rocky package/runtime behavior, actual image
startup, cgroup/AppArmor/firewalld behavior, remote REST/MQ reconciliation,
reboot persistence or Syslog delivery. We cannot reach the home Proxmox network
from this workspace. Full Ansible execution here is also blocked by denied local
RPC/IPC; opt-in integration tests must run on bp-controller. This is a prepared
evaluation example, not a completed rollout or a productive approval.
