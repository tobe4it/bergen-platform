# Internal reverse proxy (design and read-only preflight)

The dedicated reverse proxy is a future shared HTTPS entry point for **internal**
web applications in separate Proxmox LXCs. It must not reuse the public-facing
mail gateway. A generic `nginx_reverse_proxy` role and provisioning are **not**
implemented yet. This first change provides preflight checks only.

## Boundaries

- LXC: unprivileged, Proxmox firewall enabled, dedicated VMID.
- TLS: terminate HTTPS at the internal reverse proxy. Certificate/key are
  delivered through a separately reviewed, secret-safe process; never commit
  either file to the repository. Existing Synology certificates may be used.
- DNS: internal application FQDNs resolve to the internal proxy address.
  External DNS records, NAT forwarding and public ingress are out of scope.
- Network security: restrict proxy port 443 to explicitly permitted VLANs,
  restrict application backends to the proxy, and prohibit WAN forwarding.
  DNS and the Proxmox firewall flag alone do not enforce isolation.
- Identity: Paperless can use an independent OIDC identity provider. The proxy
  does not replace application-level authorization.
- Other workloads: neither a mail server nor non-HTTP protocols (MQ, MQTT,
  LDAP) are reverse-proxied by this Nginx service.

## Preflight: no host changes

1. Copy `ansible/group_vars/all/bergen-proxy.yml.example` to
   `ansible/group_vars/all/bergen-proxy.yml` and edit the local values.
2. Choose an unused VMID and an existing Proxmox bridge, storage, and template.
   The sample VMID **999 is a placeholder, not a reservation**.
3. Run on the configured Ansible controller:

```bash
ansible-playbook ansible/playbooks/preflight-reverse-proxy.yml \
  -e @ansible/group_vars/all/bergen-proxy.yml --check
```

The playbook queries the Proxmox cluster inventory, verifies that the proposed
VMID is free or belongs to a matching LXC on the designated node, and checks
rootfs storage, template availability and bridge existence. It checks hostname
uniqueness and basic backend URL syntax. All remote commands are read-only,
and the preflight is safe to run with `--check`.

Successful preflight **does not** authorize deploying a container or modifying
existing Nginx, DNS, routing, firewall, certificate or SSO configurations.
Before provisioning, independently verify the internal addressing plan, actual
DNS resolution, firewall/WAN isolation, certificate chain and key distribution,
and backend reachability. A DHCP address should be reserved before DNS cutover.

## Next implementation stage

Following an approved preflight, implement the reusable Nginx role, per-site
configuration, safe TLS source distribution/reload, and Proxmox LXC deployment.
Test with a temporary backend first. Only then add Paperless and migrate other
existing application entry points without disrupting their current URLs.
