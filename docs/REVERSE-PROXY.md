# Internal reverse proxy

The dedicated Nginx reverse proxy is the shared **internal-only** HTTPS entry
point for selected web applications in separate Proxmox LXCs. It is deployed in
an existing unprivileged Debian LXC and must not reuse the public mail gateway.

Status: implemented and in use for Paperless and Bergen-AI. Bergen-AI was added
and technically accepted on 2026-10-15 without changing the existing Paperless
vhost.

## Architecture and boundaries

- TLS terminates on the internal proxy on TCP 443; no HTTP listener is required.
- Internal application names resolve to the proxy address.
- Backend services are reached through dedicated, non-root SSH local forwards
  bound to loopback on the proxy.
- Each backend has a separate SSH account, key and pinned host-key file.
- Nginx permits only explicitly configured private client CIDRs and returns 403
  after TLS for other sources.
- DNS, the Nginx allowlist and the Proxmox firewall flag are not substitutes for
  VLAN policy. WAN forwarding remains prohibited and is not managed here.
- Certificates and private keys are delivered through a separately reviewed
  process and are never committed to Git.
- Application authentication remains the responsibility of the application or
  its identity provider; Nginx is not an authorization service.
- Mail, MQ, MQTT and LDAP are not reverse-proxied by this service.

## Managed components

The repository contains:

- the reusable `nginx_reverse_proxy` role;
- read-only Proxmox and live-proxy preflights;
- the guarded Bergen-AI first-install playbook;
- common TLS/WebSocket and per-site Nginx templates;
- the hardened SSH backend-tunnel unit template;
- offline safety-contract tests.

Site-local inventory, addresses, client CIDRs, SSH identities and TLS material
remain outside Git.

## Bergen-AI activation

The Bergen-AI path is:

```text
https://ai.thebergens.net
  -> existing Nginx proxy on TCP 443
  -> http://127.0.0.1:13000
  -> dedicated SSH local forward
  -> Open WebUI on target loopback TCP 3000
```

The activation playbook requires explicit
`ai_proxy_deployment_approved=true`, refuses an existing AI installation,
checks the certificate and DNS, validates the resolved dedicated SSH identity,
requires an unused local port, checks Nginx before changes and rolls back only
the newly staged AI files if activation fails. It verifies that the Paperless
vhost checksum is unchanged.

See [BERGEN-AI-PROXY.md](BERGEN-AI-PROXY.md) for prerequisites, commands,
acceptance evidence and remaining operational follow-up.

## Verified state on 2026-10-15

- The read-only preflight completed with `changed=0` and `failed=0`.
- Activation completed with `ok=24`, `changed=5`, `failed=0`.
- The dedicated AI SSH tunnel listens only on proxy loopback TCP 13000.
- Open WebUI returned HTTP 200 locally on the AI guest and through the tunnel.
- The AI certificate name, DNS mapping, combined Nginx configuration and reload
  passed.
- The Paperless vhost checksum remained unchanged.
- Access through an existing Synology proxy was confirmed.

Direct access from one iPad in the internal VLAN remains a client/network-path
diagnostic, not a proxy-to-backend failure. Use Nginx access/error logs to
distinguish requests that reach the allowlist from DNS, WLAN isolation or
firewall failures before Nginx.

## Operations and follow-up

- Verify all intended client networks and also verify denial from a disallowed
  network.
- Confirm WebSocket operation and an actual Open WebUI login.
- Prove certificate renewal distribution and the required Nginx reload.
- Monitor both tunnel units and local listeners after reboot.
- Never add `0.0.0.0/0`, disable SSH host-key checks or reuse another
  backend's private key.
