# Nginx reverse proxy (dedicated internal guest)

Reusable HTTPS reverse proxy role for **existing**, dedicated Debian-family
hosts. The role intentionally does not create guests, expose WAN ports, change
UniFi rules, or request or copy certificates.

## Deployment prerequisites

- Run `preflight-reverse-proxy.yml` and confirm a collision-free Proxmox VMID.
- Provision a private-network LXC separately after reviewing interface/VLAN
  transport, management availability, and DHCP in the designated VLAN.
- Add the proxy guest to a site-local inventory group
  `reverse_proxy_nodes`. Do **not** run on the public mail gateway.
- Import a trusted fullchain and matching private key using an independently
  reviewed secure transfer process. The key must be owned by root and mode
  `0400` or `0600`. **Do not store keys in Git or Ansible output.**
- Configure upstream backends, allowlisted client CIDRs and public-key
  compatible certificate names. Before enabling the service, verify LAN-only
  DNS, VLAN routing and WAN isolation separately.
- Existing Nginx sites other than the package default are not removed by this
  role; use on a **dedicated** guest only.

## Site-neutral variables

The example under `ansible/group_vars/all/bergen-proxy.yml.example` shows
`reverse_proxy_sites`, TLS paths, and placeholder topology.

In ignored local vars set:

```yaml
reverse_proxy_deployment_approved: false  # true ONLY after reviewed preflight
reverse_proxy_internal_only: true
reverse_proxy_allow_cidrs:
  - 192.0.2.0/24                  # example only; replace with client LANs
reverse_proxy_sites:
  - hostname: service.example.net
    backend_url: http://192.0.2.10:8000
reverse_proxy_tls_cert_path: /etc/nginx/tls/fullchain.pem
reverse_proxy_tls_key_path: /etc/nginx/tls/privkey.pem
```

These settings are not a firewall substitute. Clients not in the allowlist
receive HTTP 403 *after TLS*, but perimeter/network protections still must
block unauthorized access to the proxy and its backends.

## Staged workflow

1. Run cluster/bridge/storage checks using
   `ansible/playbooks/preflight-reverse-proxy.yml`.
2. Separately provision and bootstrap a dedicated Debian LXC.
3. Validate VLAN DHCP/DNS and implement allowlists/firewall policy.
4. Securely deliver valid matching TLS files to the LXC.
5. Change `reverse_proxy_deployment_approved` from false to true in the ignored
   local configuration **only when ready**.
6. Run `ansible-playbook ansible/playbooks/bootstrap-reverse-proxy.yml
   -e @ansible/group_vars/all/bergen-proxy.yml --ask-vault-pass`.
7. Verify that each HTTPS site reaches its intended backend from permitted
   networks and is blocked from disallowed ones.

## Behavior

- Expects a valid TLS certificate for **every** declared site, with a minimum
  of 14 days remaining. Rejects mismatched certificate and key.
- Installs Nginx from Debian repositories, disables its default HTTP site, sets
  a TLS handshake-rejecting default vhost and creates managed TLS virtual hosts.
- Allows only explicitly named client CIDRs. Validates `nginx -t` before
  service activation and before reload. This is not a firewall.
- Does **not** clean up obsolete managed vhosts from earlier runs. To remove
  a virtual host, review and delete its site file/link explicitly; a future
  reconciler should do this with an allowlist and controlled removals.
- TLS renewal distribution and reload integration are separate operations.
  Subsequent changes to certificate files alone do not trigger this role's
  reload handler. Verify renewal mechanics prior to production use.
- Paperless login/authorization continues in Paperless/OIDC, never in Nginx.

Keep real hostnames, internal addresses, certificates and secrets out of the
generic role and public repository.
