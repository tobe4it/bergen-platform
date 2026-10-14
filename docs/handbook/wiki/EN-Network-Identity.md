<!-- bergen-platform-handbook: managed -->
# Networks, DNS and identities

[Deutsch](DE-Network-Identity.md) | [English](EN-Start.md)

**Public edition 1.0, 2026-10-14.** Examples do not replace a private deployment inventory.

## Routers, switches, Wi-Fi and VLANs

A router connects networks. A switch distributes wired links. An access point supplies Wi-Fi. Power over Ethernet (PoE) powers compatible devices over their network cable. UniFi can manage routing, DHCP, firewall rules and DNS assignments. A separate FRITZ!Box may provide telephony; preserve its actual configuration too.

An IP address is a device's network address. DHCP distributes addresses and related settings, including DNS. A reservation keeps an address stable for a particular device. A subnet defines an address range; /23 covers more addresses than /24. The suffix is not a software version.

A VLAN creates a logical separation even when devices share switches. The VLAN number is not automatically a digit in the IP address. Switch port profiles and Wi-Fi assignments determine which network a device joins. Routing and firewall rules then control permitted connections between networks. Guest internet access can work while access to an internal file server is intentionally denied.

Addresses in `192.0.2.0/24` and names under `example.test` are documentation examples, not deployment settings. Record real VLANs, subnet prefixes, reservations, ports and rules privately.

## Narrow down a network failure

Try a second device on the same network, then a known wired connection. Mobile internet supplies an independent comparison. In UniFi, inspect devices, connection status and assigned addresses before changing settings. Preserve a configuration export and a rollback path before an authorized change. An unrestricted rule between all VLANs is not an appropriate general repair.

The reference Pi-hole design leaves routing and DHCP on UniFi. Pi-hole DHCP and NTP are disabled. Whether a particular installation already uses that design must be checked locally.

## DNS and Pi-hole

A client asks a DNS resolver for a name's address. The resolver answers local names or forwards the query. Pi-hole filters unwanted destinations. Synology DNS is the initial upstream and internal authority in the reference design: client network → Pi-hole → Synology DNS → external resolver path.

Not every deployment or VLAN necessarily uses Pi-hole yet. Determine the actual resolver configured on the client. Pi-hole and its upstream must not forward the same query back to one another indefinitely.

On a computer with `nslookup`, these read-only examples query the configured resolver and an explicitly named example resolver:

```text
nslookup ldap.example.test
nslookup ldap.example.test 192.0.2.53
```

Replace documentation examples with independently verified local values. Record which resolver answers, the returned address and any timeout. A successful DNS answer does not prove the service port is reachable or the login is authorized.

Split DNS lets the same service name resolve differently inside and outside the local network. Keep the intended service name when testing TLS; switching to a numeric IP can make the certificate name wrong. A DNS outage, a filtered destination and a firewall block are separate causes.

DNS servers need stable addresses. Confirm the reservation, device identity and private inventory before changing an address. Substituting a public resolver can break internal names and bypass intended filtering.

## Synology, storage and directory services

A NAS is a storage computer with additional services. DSM is Synology's management interface. A share exposes a folder to other devices, commonly using SMB or NFS. Permissions determine which users can read or change it. Externally mounted NAS content may lie outside an LXC backup.

RAID handles certain disk failures; it is not a complete backup. It does not reliably undo deletion, ransomware or loss of the entire appliance. Preserve warnings and the backup state before replacing disks or changing storage.

LDAP is a directory of accounts and groups. Authentication asks who a user is; authorization asks what that user may do. LDAPS protects the directory connection using TLS, commonly on port 636. The actual service name must match its certificate; changing the access hostname does not imply renaming the internal directory tree.

An application bind account allows directory queries. The Mailuser group determines mailbox eligibility in the backend design; a technical sender can have different permissions. Synology LDAP Server and an AD-based Directory Server have different schemas and operating procedures. Record the installed package rather than treating their names as interchangeable.

## When several logins fail together

Check directory name resolution, reachability, system time, certificate validity and service status. Try one known authorized account. Do not recreate users or groups until the cause is understood: a new account with the same visible name may have a different identity.

Critical systems need tested local emergency administration that is not dependent solely on the failing directory. Store its recovery route in the protected handover record, not in this wiki.

---

[Contents](EN-Start.md) · [Sources](EN-Sources.md) · [Prepare private handover](EN-Handover.md)
