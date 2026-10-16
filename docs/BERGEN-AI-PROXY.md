# Bergen-AI through the existing Bergen Proxy

Status: **activated and technically verified on 2026-10-15**. This deployment
uses the existing `nginx_reverse_proxy` role and the existing dedicated proxy
LXC. It does not introduce another reverse proxy, modify the productive
Paperless vhost, copy the wildcard private key to Bergen-AI, or request a new
certificate.

## Verified baseline

- The existing `bergen-proxy` LXC runs Nginx on TCP 443 and has no TCP 80
  listener.
- `paperless.example.net` uses the existing
  `50-internal-paperless.example.net.conf` vhost and the loopback upstream
  `http://127.0.0.1:18000`.
- Paperless reaches its backend through a dedicated, non-root SSH local
  forward. Its identity is not reused for Bergen-AI.
- The proxy uses the existing certificate files
  `/etc/nginx/tls/fullchain.pem` and `/etc/nginx/tls/privkey.pem`.
- Open WebUI listens on loopback TCP 3000 in the Bergen-AI guest.
- Internal DNS resolves `ai.example.net` and
  `paperless.example.net` to the same proxy address.
- The existing certificate covers `ai.example.net`, and `nginx -t`
  succeeds.

The automatic wildcard-certificate distribution and the corresponding Nginx
reload after a real renewal remain to be proven separately.

## Architecture and scope

```text
https://ai.example.net
  -> existing Nginx in the dedicated proxy LXC
  -> http://127.0.0.1:13000 on the proxy
  -> dedicated SSH local forward
  -> 127.0.0.1:3000 in the Bergen-AI guest
```

The additional backend listener binds only to proxy loopback. The playbook does
not add WAN ingress, DNS records, routing changes, firewall rules, certificates,
SSH accounts, keys, or SSO configuration.

### Dedicated SSH transport

Before activation, the following site-local prerequisites must already exist:

- a dedicated non-root tunnel account on the proxy;
- a separate Ed25519 client key owned by that account;
- a restricted target account and `authorized_keys` rule permitting only the
  required loopback forward to TCP 3000;
- an independently verified and pinned Ed25519 server host key;
- a mode 0400 or 0600 SSH client configuration and a dedicated
  `known_hosts` file;
- a reviewed SSH alias resolving to the intended target account and address.

The activation playbook creates none of these prerequisites. It executes
`ssh -G` through `runuser` and validates the effective user, identity file,
dedicated known-hosts file, `IdentitiesOnly`, `BatchMode`, and strict
host-key checking.

The generated systemd service runs as the dedicated tunnel user and uses:

- `ssh -4 -b <proxy-source-address>`;
- `-N -T`;
- `-L 127.0.0.1:13000:127.0.0.1:3000`;
- public-key-only authentication;
- `StrictHostKeyChecking=yes`;
- `ExitOnForwardFailure=yes`;
- server-alive monitoring and restart on failure.

The unit also applies `NoNewPrivileges`, `ProtectSystem=strict`,
`ProtectHome=true`, `PrivateDevices=true`, restricted address families,
and an empty `CapabilityBoundingSet`.

### Nginx

The AI vhost uses the same
`ansible/roles/nginx_reverse_proxy/templates/internal-proxy-site.conf.j2`
template as other managed internal HTTPS sites. It includes WebSocket upgrade
support, forwarded headers, the existing private client CIDR allowlist, and the
existing TLS files.

The activation does not render, replace, or remove the Paperless vhost. Its
SHA-256 checksum is recorded before the change and compared afterwards.

Clients outside the configured CIDRs receive HTTP 403 only after reaching
Nginx. The allowlist is not a firewall substitute; VLAN policy and WAN
isolation remain separate controls.

### Certificate and DNS

The activation preflight verifies:

- exact certificate coverage for `ai.example.net`;
- at least 14 days of remaining certificate validity;
- identical internal IPv4 resolution for AI and Paperless;
- a valid existing Nginx configuration;
- an unused proxy loopback port 13000.

No certificate is copied or renewed, and no DNS entry is created. The proxy has
no HTTP listener, so this deployment does not provide an HTTP-to-HTTPS
redirect.

## Controller workflow

Run the read-only preflight first, using both inventories and the site-local
variable files:

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/preflight-bergen-ai-proxy.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml \
  -e @ansible/group_vars/all/bergen-proxy.yml
```

For an authorized first installation, perform the syntax check and then run the
activation playbook with the explicit approval variable:

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/activate-bergen-ai-proxy.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml \
  -e @ansible/group_vars/all/bergen-proxy.yml \
  -e ai_proxy_deployment_approved=true
```

This is intentionally a first-install playbook. It refuses existing AI vhost or
unit files rather than reconciling them. Do not rerun it against the activated
installation as a routine maintenance action.

## Activation and acceptance evidence

The authorized first-install run on 2026-10-15 completed with:

```text
ok=24  changed=5  unreachable=0  failed=0
```

The five changes were limited to staging and starting the AI tunnel, rendering
and enabling the AI vhost, and reloading Nginx. The Paperless vhost checksum
remained unchanged.

The following was verified:

- the dedicated `bergen-ai-backend-tunnel.service` runs as
  `bergen-ai-tunnel`;
- proxy loopback TCP 13000 is owned by the SSH tunnel;
- Open WebUI returns HTTP 200 on target loopback TCP 3000;
- Open WebUI returns HTTP 200 through proxy loopback TCP 13000;
- certificate name coverage and remaining lifetime checks pass;
- internal AI and Paperless DNS results agree;
- Nginx validation succeeds before and after the change;
- Nginx reload succeeds;
- access through the existing Synology proxy succeeds;
- five static Bergen-AI proxy contract tests pass;
- the activation playbook passes its Ansible syntax check.

The direct path from one iPad in the internal VLAN remains a separate
client/network diagnostic. If an attempted request creates no Nginx access-log
entry, investigate client DNS, encrypted DNS or Private Relay, WLAN client
isolation, and VLAN/firewall policy before changing the vhost. This does not
invalidate the verified proxy-to-backend path.

## Operational follow-up

- Verify an actual Open WebUI login and WebSocket operation.
- Verify access from every intended client network and denial from a network
  outside the allowlist.
- Confirm both SSH tunnel services and their loopback listeners after a reboot.
- Prove automatic wildcard-certificate delivery and Nginx reload after a real
  renewal.
- Keep the SSH keys, effective addresses, inventory, and certificate private key
  outside the repository.
- Never introduce an allow-all CIDR, disable SSH host-key checking, or reuse the
  Paperless private key for Bergen-AI.
