# Paperless-ngx private backend – staged deployment

This is a separate, opt-in Paperless backend workstream. It does not change
the existing Mail TLS distributor or the Nginx TLS draft.

## Architecture

A dedicated **unprivileged, firewalled Debian LXC** is proposed for Paperless.
The deployment role installs rootful Podman **inside that unprivileged LXC**,
with a private Podman bridge and three Quadlets:

- Paperless-ngx application with `127.0.0.1:8000:8000` published **only on
  the Paperless LXC loopback**, as a safe staging mode.
- PostgreSQL 17.x for persistent application metadata, not published.
- Redis for broker/queues, not published.

Dedicated bind-mounts under `/srv/bergen-paperless` persist database,
Redis, data, media, consumption, and export volumes. Root-only `0600`
configuration files contain database and app secrets; their source of truth
is the separate, Ansible-Vault-encrypted local file. Applications are NOT
started until separately approved.

**Important:** 127.0.0.1 is local to the Paperless LXC. The Nginx proxy in a
different LXC cannot use it directly. Before connecting the two LXCs,
implement and review a restricted inter-LXC backend connection (host
interface bind restricted to the proxy and explicit firewall policy, or
another authenticated internal transport). Do not expose port 8000 to guest
or WAN networks during initial staging.

The existing Paperless HTTPS hostname/route in the proxy config remains
a placeholder until a real reachable backend address is validated.

## Next safe step: propose VMID, storage, network and memory

Choose a free VMID across Proxmox cluster, e.g. a *candidate* VMID 126,
subject to the read-only cluster preflight. Assign an appropriate host,
Debian template, storage pool, bridge, CPU and memory. Review data capacity
and backup storage explicitly; the 16 GiB rootfs gate is a minimum, not a
recommendation for document archive capacity.

Use the checked-in example under `docs/examples/paperless.local.example.yml`
for non-secret infrastructure variables in the Git-ignored mode-0600
`ansible/vars/paperless.local.yml`. **No credentials belong in that file.**

Create the separate encrypted file with Ansible Vault (the existing
`ansible/group_vars/all/vault.yml` and existing service secrets stay untouched):

```bash
cd ~/bergen-platform
umask 077
ansible-vault create ansible/vars/paperless.vault.yml
```

Enter the three keys shown in
`docs/examples/paperless.vault.example.yml` with independently generated,
high-entropy values. Use `ansible-vault edit` for later changes; never
temporarily decrypt the file on disk. Verify its header is
`$ANSIBLE_VAULT;...` and protect it with mode 0600.

The read-only Proxmox preflight needs **only**
`paperless.local.yml` as an explicit extra-vars file and does not load the
new Paperless Vault file. However, Ansible automatically loads the existing
encrypted `ansible/group_vars/all/vault.yml` from the standard inventory;
therefore, even this read-only preflight needs `--ask-vault-pass` using
the existing platform Vault password.

Later explicitly approved deployment must load both variable sources:

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/deploy-paperless.yml \
  -e @ansible/vars/paperless.local.yml \
  -e @ansible/vars/paperless.vault.yml \
  --ask-vault-pass
```

The command above is a **future** deployment step, not authorized by
this draft. The current deployment flags remain false. Before live deployment,
add exactly one `paperless_nodes` host to
`ansible/inventory.local.yml` with verified, pinned PCT-mediated SSH
transport similar to `bergen-proxy`. Do not reuse VMID 125.

Read-only Proxmox preflight:

```bash
cd ~/bergen-platform
python -m unittest discover -s tests -p 'test_paperless_private_backend.py' -v

ansible-playbook -i ansible/inventory.yml \
  ansible/playbooks/preflight-paperless.yml \
  -e @ansible/vars/paperless.local.yml \
  --ask-vault-pass
```

The expected summary is `PREFLIGHT_PASS` and `deployment: not_performed`.
This will refuse an occupied VMID, missing template, storage, bridge or
undersized VM resources.

## Separate Podman runtime stage after LXC baseline

After provisioning the dedicated LXC (VMID 126), verifying the pinned
Proxmox-mediated SSH transport, mounting the dedicated ZFS volume, and
enabling FUSE, first verify the runtime without deploying the applications:

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-runtime.yml \
  -e @ansible/vars/paperless.local.yml \
  --check --diff --ask-vault-pass
```

Once the check shows only the expected apt changes, explicitly approve
the one-time runtime installation:

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-runtime.yml \
  -e @ansible/vars/paperless.local.yml \
  -e paperless_runtime_approved=true \
  --ask-vault-pass
```

This stage only installs `podman`, `uidmap`, `fuse-overlayfs`, and
`slirp4netns` in the approved guest, then tests `podman info`. It
does not pull images, create Quadlets, start databases, or change network
rules. `paperless_deployment_approved` and `paperless_start_approved`
remain false; the Paperless Vault is not needed at this stage.

## Requirements before any live deployment

1. Confirm Proxmox VMID, address reservation, guest network bridge and
   storage/backup placement. Proxmox **nesting, keyctl, and FUSE** must be
   reviewed for rootful Podman inside an unprivileged LXC.
2. Validate real tagged versions of Paperless, PostgreSQL 17.x and Redis
   against upstream release notes and selected image architecture.
3. Generate secrets only inside the **encrypted Vault file** and keep
   infrastructure in the separate ignored local file; never print secrets
   in task outputs, CI logs or terminal transcripts.
4. Review LXC creation, secure transport and Ubuntu/Debian packages before
   granting `paperless_deployment_approved: true`.
5. Review the generated Quadlets and systemd services with
   `paperless_start_approved: false`; approve start in a separate change.
6. Test local HTTP, database migrations, login, OCR/consumption,
   import/export, and backup/restore before involving the reverse proxy.
7. Only after TLS and inter-LXC networking verification, update the
   Nginx backend to a **real** Paperless endpoint and confirm internal-only
   access. No public forwarding is authorized.

This role is an initial staging proposal, not a tested production deployment.
