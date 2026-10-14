<!-- bergen-platform-handbook: managed -->
# Private handover and recovery sheet

[Deutsch](DE-Handover.md) | [English](EN-Handover.md)

## Keep three records separate

1. **Public handbook:** Fundamentals and generalized procedures.
2. **Private operating record:** Hosts/IDs, URLs, persistent paths, contacts, contracts, network plan and backup/restore evidence.
3. **Recovery sheet:** Only necessary unlock/recovery values unavailable from a vault or password manager. The completed sheet stays offline.

## Blank printout

[English recovery sheet: download PDF](https://github.com/tobe4it/bergen-platform/raw/refs/heads/main/docs/handbook/print/Emergency-Secrets-EN.pdf)

[German printout](https://github.com/tobe4it/bergen-platform/raw/refs/heads/main/docs/handbook/print/Emergency-Secrets-DE.pdf)

Two A4 pages cover the access route, vault unlock and any necessary local emergency login, then decryption, MFA recovery and justified additional exceptions. Not every field needs a secret; cross out fields that are not needed.

## Fill only what is necessary

Reference entries already in a vault/password manager. Do not copy an entire vault or private keys onto the sheet. An encrypted vault cannot be the sole reachable source of its own unlock secret.

A second person should test the intended access without missing values supplied from the original administrator's memory, then prove isolated recovery of important content. Login, backup success and restore success are separate recorded outcomes.

Do not photograph, scan or upload completed sheets to the wiki, Git, issues, pull requests or chat. Privately record storage, authorized people, a protected spare copy and test date. Replace outdated copies after changes according to the agreed policy.

## Minimum private operating record

| Topic | Record |
| --- | --- |
| Service | Role, productive/prepared/lab state, host/ID, URL and version |
| Network | Bridge/VLAN, subnet, DNS, reservation and permitted administration route |
| Data | Document/mailbox path, database and external mounts |
| Backup | Job, target, scope, schedule, retention and decryption reference |
| Restore | Isolated target, version, date, samples, duration and result |
| Responsibility | Caretaker, substitute and independent contact route |
| Contracts | Provider, role, deadline and private record location |

[Contents](EN-Start.md) · [Backup and recovery](EN-Backup-Recovery.md)
