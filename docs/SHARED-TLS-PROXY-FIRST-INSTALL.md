# Shared Mail/Proxy TLS – initial-install readiness

This stage prepares a future one-time TLS installation to the reviewed isolated
Nginx proxy LXC. It does **not** copy certificates, change permissions, install
Nginx, reload services, alter firewall rules or modify either TLS service.

## Unchanged current Mail TLS operation

The existing `mail-tls-sync.timer` invokes `mail_tls_sync.py --config ... --apply`
without proxy flags. Its source and mail destination SSH, public certificate
validation, mail activation and live listener checks are unchanged.

## Explicit additional read-only first-install readiness check

From the controller on the reviewed shared TLS branch:

```bash
cd ~/bergen-platform
python -m unittest discover -s tests -p 'test_shared_tls_proxy_audit.py' -v
python -m pytest -q tests/test_mail_tls_sync.py

.venv/bin/python3 scripts/mail_tls_sync.py \
  --config ansible/vars/mail-tls.local.yml \
  --proxy-vars ansible/group_vars/all/bergen-proxy.yml \
  --proxy-first-install-plan
```

Expected additional messages for a fresh isolated LXC:

```text
PROXY TLS: MISSING_EXPECTED_FIRST_INSTALL
PROXY TLS: AUDIT_ONLY; no files transferred or services changed
PROXY TLS: FIRST_INSTALL_PREFLIGHT_PASS
PROXY TLS: PLAN_ONLY; no certificate transfer, file writes or Nginx change
```

The prerequisite proxy audit verifies the intended Proxmox node, LXC VMID,
dedicated inventory group, pinned guest SSH host key, TLS destination paths,
root-owned protective directory if it already exists, both destination files'
presence, and wildcard site scope.

The additional readiness check refuses an installed Nginx binary, active Nginx
service, or either existing TLS destination path (including dangling symlinks).

For safety, this is **not** authorization to perform a certificate installation:
`--apply` combined with `--proxy-vars` is rejected before accessing the
source. A separate reviewed and approved activation stage must re-check target
state immediately before writing and provide rollback; later automated Nginx
rotation must be a distinct operation.


## New isolated first-install candidate (unapproved)

The `feat/paperless-proxy-tls-first-install-20261013` branch
contains a **separate** `scripts/proxy_tls_first_install.py`
candidate. This does not alter the existing mail distributor, mail timer or
read-only `--proxy-vars` mode of `mail_tls_sync.py`.
The new routine **has not been authorized for production use**. Complete
its offline safety tests and code review before permitting any write.

The default mode is a read-only confirmation of the exact already reviewed
LXC inventory, certificate source and missing proxy TLS files:

```bash
python3 -m unittest discover -s tests \
  -p 'test_proxy_tls_first_install.py' -v

python3 scripts/proxy_tls_first_install.py \
  --config ~/bergen-platform/ansible/vars/mail-tls.local.yml \
  --proxy-vars ~/bergen-platform/ansible/group_vars/all/bergen-proxy.yml \
  --proxy-local-inventory ~/bergen-platform/ansible/inventory.local.yml \
  --proxy-pve-inventory ~/bergen-platform/ansible/inventory.yml
```

Expected dry-run result includes `PROXY_TLS_FIRST_INSTALL_PLAN_ONLY`.
The routine uses pinned SSH to validate the certificate source and isolated
proxy and deliberately requires a distinct explicit approval before writing.
An approved, future first install would stream the certificate and private
key from the existing source to a protected root-only directory **without
writing either to controller disk**. It then checks source fingerprint,
expiration, hostname match, and cert/key pairing. Refuse existing TLS
destinations, existing Nginx, unexpectedly broad site lists, or any failed
validation. There is no Nginx installation, DNS update, external ingress,
firewall modification, or mail service activation.

No commands that enable writes are documented here pending review and
observed offline test results. Afterwards, independently review wildcard
key exposure to the proxy, renewal synchronization, its DHCP reservation,
private ingress CIDRs, the backend tunnel/allowlist and the Paperless HTTPS
route before activating Nginx or an OIDC login.

## Not yet implemented

- Production-approved certificate transfer and live first installation (candidate only)
- Nginx installation/configuration and private ingress
- Nginx cert/key rotation, reload, endpoint TLS health checks and rollback
- Automatic proxy enrollment in the existing mail timer

The prior standalone proxy TLS installer remains superseded. Do not run it.
