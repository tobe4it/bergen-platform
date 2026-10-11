# Initial TLS provisioning for an isolated internal proxy

This workflow uses the **existing Mail TLS Certbot source**. It does not
reconfigure Certbot, request certificates, change DNS/firewall settings,
install Nginx, or reload services.

The controller script is **read-only by default**. Its separately approved
\`--apply\` mode performs a **first installation only** and refuses an
already installed Nginx binary or any existing target TLS certificate/key.
Renewal and rotation are deliberately not implemented.

## Local inputs

Keep the existing files git-ignored and mode 0600:

- \`ansible/vars/mail-tls.local.yml\`: the source SSH identity, Certbot
  fullchain/private-key locations, and wildcard SAN.
- \`ansible/group_vars/all/bergen-proxy.yml\`: the isolated LXC VMID,
  hostname, managed TLS destinations and configured proxy sites.
- \`ansible/inventory.local.yml\`: the single reviewed reverse_proxy_nodes
  host and strict PCT-mediated SSH ProxyCommand.
- \`ansible/inventory.yml\`: existing Proxmox management inventory.

The controller must already trust the source host, Proxmox and guest SSH
host keys. The source SSH identity needs noninteractive sudo read access to
the existing Certbot lineage.

## Read-only verification

From the repository root on the controller:

\`\`\`sh
python -m unittest discover -s tests -p 'test_proxy_tls_initial_install.py' -v
.venv/bin/python3 scripts/proxy_tls_initial_install.py \
  --source-vars ansible/vars/mail-tls.local.yml \
  --proxy-vars ansible/group_vars/all/bergen-proxy.yml
\`\`\`

Expected decision: \`FIRST_INSTALL\`, followed by
\`READ_ONLY: no TLS files transferred\`. Stop on any error and investigate.
The first run does not need a Vault password because it reads the existing
ignored site-local configurations.

## Separately approved first-time installation

The corresponding invocation with \`--apply\` is intentionally **not** part
of the initial testing procedure. Only execute it after reviewing the
read-only output and target state.

With that option, a protected stage is created inside the target LXC.
The controller links two verified SSH connections using an in-memory pipe:
there is no persistent private-key file on the controller. Certificate and
private key are staged at mode 0600 and checked against the source certificate
fingerprint, hostname scope, public-key correspondence, expiration, and CA
chain before placement. The TLS directory is root-owned and mode 0700.
Initial installation is rejected if Nginx is already installed.

Successful target paths are:
- \`/etc/nginx/tls/fullchain.pem\` (0644, under private directory).
- \`/etc/nginx/tls/privkey.pem\` (0600, under private directory).

This does not install or start Nginx.

## Operations and renewals

This script deliberately cannot rotate existing certificate files. Before
activating Nginx in regular use, implement and verify a **separate**
transactional rotation with backups, rollback, Nginx syntax validation,
controlled reload, real HTTPS listener checks, and expiration monitoring.
The existing Mail TLS source issuance and mail certificate distribution are
unchanged.

Do not deploy the Nginx role until real backend addressing, internal-only
ingress policy, DNS, certificate trust and firewall/WAN isolation have been
independently verified. A shared wildcard private key increases the number
of hosts whose compromise could expose it.
