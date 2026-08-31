# Pi-hole DNS Filtering

## Purpose

`bergen-pihole` provides DNS filtering for networks routed by the UniFi gateway.
It exists because DNS filters on an upstream router cannot reliably apply
per-client policy to clients hidden behind a downstream routed/NAT boundary.

Routing and security policy stay on UniFi. Pi-hole is not a router or firewall.

```text
UniFi VLAN clients
        |
        | DNS TCP/UDP 53
        v
 bergen-pihole
        |
        | upstream DNS
        v
 Synology DNS
        |
        v
 Internet resolver path
```

## Platform design

- LXC: Debian 13, unprivileged
- Default VMID: `123`
- CPU: 1 vCPU
- RAM: 1024 MiB
- Root filesystem: 8 GiB
- Runtime: Podman inside the LXC
- Pi-hole image: pinned in `bergen-pihole.yml`
- Network: `vmbr6` / DMZ VLAN 6
- Initial addressing: DHCP for first deployment/discovery
- Stable address: `192.168.6.218` by UniFi DHCP reservation
- Pi-hole DHCP: disabled
- Pi-hole NTP: disabled
- DNS listening mode: `SINGLE` on `eth0`
- Central logging: queued TCP Syslog forwarding to `bergen-syslog`

The first deployment intentionally leaves UniFi DHCP/DNS settings unchanged.

## Preconditions

Add the Pi-hole web/API password to the existing local Ansible Vault:

```yaml
vault_pihole_web_password: "use-a-long-random-password"
```

Before later changing any UniFi network to use Pi-hole, verify the DNS forwarding
chain cannot loop. With the default configuration Pi-hole forwards to
`192.168.6.11` (Synology DNS). Synology DNS must therefore not forward back to
Pi-hole or to a resolver that ultimately sends the same query back to Pi-hole.

VMID `123` follows the current Bergen Platform allocation. If it is already in
use on Proxmox, change `lxc_vmid` before deployment.

## First deployment

Run from the Bergen Platform controller:

```bash
ansible-playbook ansible/playbooks/deploy-pihole.yml \
  -e @ansible/group_vars/all/bergen-pihole.yml \
  --ask-vault-pass
```

The workflow:

```text
create LXC
  -> start/restart
  -> discover DHCP address
  -> Linux baseline
  -> enable nested Podman runtime support
  -> configure remote Syslog forwarding
  -> install Podman
  -> deploy Pi-hole
  -> validate DNS/web listeners and application status
```

No client DNS setting is changed by this playbook.

## Make the DNS address stable

A DNS server must not depend on a changing client address. After the first
deployment, create a UniFi DHCP reservation for `bergen-pihole` using the
address/MAC learned during deployment.

Only after that reservation is in place should clients or UniFi DHCP scopes
refer to the Pi-hole address.

Record the stable address in the ignored site-local inventory. The repository
contains an example `pihole_nodes` group:

```yaml
pihole_nodes:
  hosts:
    bergen-pihole:
      ansible_host: 192.168.6.218
      ansible_user: root
      ansible_python_interpreter: /usr/bin/python3
```

For later service reconciliation use both inventories:

```bash
ansible-playbook ansible/playbooks/bootstrap-pihole.yml \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  -e @ansible/group_vars/all/bergen-pihole.yml \
  --ask-vault-pass
```

## Initial validation

Before changing DHCP DNS for any VLAN:

```bash
nslookup example.org 192.168.6.218
nslookup bergen.intern 192.168.6.218
```

Open:

```text
http://192.168.6.218/admin/
```

Confirm that queries appear in Pi-hole and that internal Synology-hosted names
still resolve.

The bootstrap also emits a `BERGEN-SYSLOG-TEST` event through the reusable
`remote_syslog` role. Verify central receipt on `bergen-syslog` using the
Pi-hole LXC source address.

This forwarding is for host/service operational logs. Pi-hole query logging
remains in Pi-hole itself and is not deliberately duplicated into central
Syslog.

## UniFi cutover

Cut over one network at a time. Configure that network's DHCP DNS server to the
stable Pi-hole address, renew one test client's lease and verify browsing,
internal DNS and Pi-hole query logging.

For enforced child-network filtering, the firewall phase should:

- permit client TCP/UDP 53 to Pi-hole,
- redirect hard-coded IPv4 DNS TCP/UDP 53 to Pi-hole,
- permit Pi-hole TCP/UDP 53 to its configured upstream resolver,
- handle encrypted DNS bypass separately (DoT/DoQ/DoH/VPN policy),
- restrict the Pi-hole web interface to administration networks.

## Network-wide SafeSearch

SafeSearch is currently applied to all clients using Pi-hole. The managed
`pihole_dnsmasq_lines` map:

- `www.google.com` and `www.google.de` to the Google SafeSearch VIP,
- `www.bing.com` and the Edge sidebar search endpoint to Bing Strict,
- the documented YouTube endpoints to YouTube Moderate Restricted Mode.

The configuration uses provider SafeSearch VIP addresses instead of external
CNAME targets because Pi-hole's embedded dnsmasq requires CNAME targets to be
locally known/authoritative. A future children-only resolver may use YouTube
Strict while the general resolver stays Moderate.

Pi-hole also blocks Apple's Private Relay discovery domains through its built-in
`dns.specialDomains.iCloudPrivateRelay` behavior so managed DNS policy is not
silently bypassed by Private Relay.

## Blocklists and family policy

Blocklists and Pi-hole client/group policy are managed separately from the base
resolver path so that filtering changes remain independently testable and
reversible.

## Upgrade policy

The official Pi-hole container image is pinned to an explicit date-based release
instead of `latest`. Upgrade by changing `pihole_image` in Git, reconciling the
service and validating DNS before committing the new version as operationally
verified.
