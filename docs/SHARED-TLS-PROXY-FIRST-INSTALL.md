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

## Not yet implemented

- Certificate transfer and live first installation
- Nginx installation/configuration and private ingress
- Nginx cert/key rotation, reload, endpoint TLS health checks and rollback
- Automatic proxy enrollment in the existing mail timer

The prior standalone proxy TLS installer remains superseded. Do not run it.
