# pihole

Deploys Pi-hole as the DNS filtering service for a dedicated Bergen Platform
Debian LXC.

## Purpose

The UniFi gateway remains responsible for routing, VLAN isolation and firewall
policy. Pi-hole is responsible only for DNS resolution/filtering and query
visibility.

The initial resolver chain is:

```text
clients -> Pi-hole -> Synology DNS -> upstream
```

The Synology DNS server remains authoritative for internal zones.

## Installed software

The role itself does not install an OCI runtime. `bootstrap-pihole.yml` applies
the existing `podman` role first and then runs the official Pi-hole container
as a system Quadlet.

## Generated files

- `/etc/containers/systemd/pihole.container`
- `/etc/bergen-platform/pihole.env`
- `/srv/pihole/etc-pihole/` persistent Pi-hole data

The environment file is mode `0600` because it contains the web/API password.

## Network services

With host networking the LXC itself provides:

- TCP/UDP 53: DNS
- TCP 80: web administration
- TCP 443: HTTPS web administration

Pi-hole DHCP and NTP are disabled. UniFi remains DHCP/router infrastructure.

`dns.listeningMode=SINGLE` accepts routed client networks on `eth0`. This mode
must be paired with UniFi firewall policy; never expose the LXC as a public DNS
resolver.

## Configuration

Required secret:

```yaml
vault_pihole_web_password: CHANGE_ME
```

Store it in the existing encrypted/local Ansible Vault only.

The upstream DNS list is configured by `pihole_upstreams`. Do not create a
forwarding loop. In particular, if Pi-hole forwards to Synology DNS, Synology
must not forward back to Pi-hole or to a resolver whose upstream is Pi-hole.

## Validation

The role waits for DNS and HTTP listeners, verifies the systemd unit is active
and runs `pihole status` inside the container.

The role is intended to be idempotent. Re-running it reconciles the managed
environment and Quadlet and restarts Pi-hole only when those inputs changed.
