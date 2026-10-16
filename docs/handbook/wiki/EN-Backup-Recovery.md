<!-- bergen-platform-handbook: managed -->
# Backup and recovery

[Deutsch](DE-Backup-Recovery.md) | [English](EN-Start.md)

**Public edition 1.0, 2026-10-14.** Examples do not replace a private deployment inventory.

## Know what protection actually provides

Synchronization can copy deletion and corruption. RAID addresses some disk failures. Snapshots often remain on the same endangered storage. Git preserves a build description. A backup should independently recover a usable earlier data state. Combine appropriate protections, but do not treat them as interchangeable.

A successful job does not prove the inclusion of every mountpoint or a usable restore. The repository still lists comprehensive Backup & Recovery as development work. This chapter is a proposed operating framework, not a claim that all installations have working scheduled backups.

## Four parts of a recoverable installation

- System: operating environment, versions and configuration.
- Content: files, mailboxes, databases and important history.
- Deployment: ignored inventory, local variables, network and provider settings.
- Access: usable decryption, keys, passphrases, emergency accounts and MFA recovery.

RPO describes how much recent work can be lost; RTO how long an outage can last. For explanation only, an RPO of 24 hours and RTO of two days would allow one day's changes to be lost and two days to recover. Agree actual targets for important services and record them privately.

Keep suitable history, a copy outside the primary system and a tested decryption route. Include loss of the appliance, building or original administrator's device. Use service-appropriate database exports or coherent system/database backups; arbitrary live file copies may not be recoverable.

## Required backup scope

| Component | Content to preserve and verify |
| --- | --- |
| Network / telephony | Configuration exports, VLAN/port plan, DHCP, DNS, firewall, WAN and phone settings |
| Synology / directory | Shares and content, package/configuration backups, LDAP/AD and DNS recovery |
| Proxmox | Host/network/storage configuration and guests, not only guest archives |
| Controller | Complete checkout including ignored files, Vault, SSH and reproducible dependencies |
| Mail | Actual source and target mailboxes, rules, aliases, gateway and backend `/var/vmail` where used |
| Nextcloud | Data, database, configuration, customization, apps, external storage and relevant keys |
| Paperless | Documents, database, configuration, exports, exact versions and intake recovery |
| EVCC / MQTT | EVCC database/configuration; broker users, ACLs, configuration and necessary persistence |
| AI / logs | Deliberately selected history/settings and relevant retained logs |

Additional managed LXC volumes need explicit backup inclusion. Bind/device mounts are not included as ordinary managed guest data and need another method. `backup=1` is a configuration indication, not evidence of a completed or readable backup. Check logs and actual recovered content.

For each service record target, scope, schedule, retention, encryption route, last success, last restore, owner and unresolved omissions. Do not mark an untested field complete.

## Restore to an isolated destination first

1. Preserve the source and backups; define the required recovery point.
2. Check backup age, version, completeness and decryption; preserve newer local files separately.
3. Select a free guest ID and separate destination storage. Do not duplicate productive addresses, MACs or names.
4. Isolate before the first start. Restored services can send mail, fetch intake folders, synchronize clients or control charging immediately.
5. Follow version-appropriate vendor and local instructions; restore databases and files as a coherent state.
6. Test actual content and relevant permissions, not just the login screen.
7. Record time, target, restored version, samples, failures and reviewer.

| Service | Meaningful sample |
| --- | --- |
| Mail | Older/newer message, attachment, folder and flags; sending only after safe cutover |
| Nextcloud | Open/download files and inspect used shares, calendars or contacts |
| Paperless | Original file, search and metadata for older and newer content |
| EVCC | Settings/history without charger access, then one authorized real charging controller |
| LDAP / DNS | Expected accounts, groups and selected internal names |

Proxmox provides GUI restoration and `pct restore` for LXC. Do not assemble a concrete applying restore command before the archive, new ID, storage and isolation are known. A wrong target can overwrite content.

## Returning to production

Choose the authoritative data state and reconcile changes since the backup. Keep the original through an agreed rollback period. Coordinate Nextcloud clients and Paperless intake before reconnecting them. A second person must be able to recover important content without the running original application or missing information from memory.

---

[Contents](EN-Start.md) · [Sources](EN-Sources.md) · [Prepare private handover](EN-Handover.md)
