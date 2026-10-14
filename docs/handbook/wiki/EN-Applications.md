<!-- bergen-platform-handbook: managed -->
# Applications in everyday use

[Deutsch](DE-Applications.md) | [English](EN-Start.md)

**Public edition 1.0, 2026-10-14.** Examples do not replace a private deployment inventory.

## Mail: understand the complete path

The public gateway receives internet mail and sends to external destinations. It owns public delivery policy, spam handling, DKIM and reputation. A private route, which may use WireGuard, connects it to the internal mailbox backend.

Postfix accepts and routes messages and maintains a queue. Dovecot supplies mailbox access and local delivery. LDAP supplies identities and rights. The reference backend stores mail under `/var/vmail`; the actual active mailbox source must be recorded separately.

| Protocol / port | Purpose |
| --- | --- |
| SMTP / 25 | Server-to-server mail; backend access restricted to the intended gateway route |
| Submission / 587 | Authenticated client sending, usually with STARTTLS |
| Submissions / 465 | Authenticated client sending with TLS from connection start |
| IMAPS / 993 | TLS-protected mailbox access and synchronization |

IMAP synchronizes folders and message state. Deletion may propagate to all clients. A phone's mail application is not automatically an independent mailbox backup.

Aliases route additional addresses to recipients. Receiving an alias does not automatically authorize sending as it. Send-as is a separate permission. The backend's Mailuser group controls mailbox eligibility; technical senders can authenticate for SMTP without having an ordinary mailbox.

A new backend and functioning gateway TLS do not establish a completed mailbox migration. Determine current MX records, private transport, client settings and where new messages actually arrive. Preserve both legacy and target mail data until acceptance and a defined rollback period are complete.

## Narrow down mail problems

First open an existing message. If that fails, investigate mailbox connectivity and authentication. For a deliberate round-trip test, send a short message to your own independent external mailbox and reply; record both times. A missing message can still be queued rather than lost.

| Observation | First technical direction |
| --- | --- |
| Reading works, sending fails | Submission, authentication, Send-as or gateway route |
| External messages do not arrive | MX, gateway queue, private tunnel and active backend |
| One account fails | Account, group, password, alias or quota |
| Several logins fail | LDAP, DNS, TLS or mailbox service |
| Certificate warning | Name, time, validity, trust chain and actual renewal |

In the actual Postfix/Dovecot system, the caretaker can read:

```sh
systemctl status postfix dovecot --no-pager
mailq
journalctl -u postfix -n 40 --no-pager
journalctl -u dovecot -n 40 --no-pager
```

An empty backend queue says nothing about the gateway queue. Correlate messages by time and message identity. Never delete queues or old mailboxes just to make the warning disappear.

TLS protects the connection and checks the intended name. ACME/Certbot can renew certificates; the consuming service must then use the new certificate. Where material is synchronized to a backend, include that transfer and reload in the verification. MX routes mail; SPF, DKIM and DMARC support sender-domain checks. Do not change those DNS records independently without understanding the delivery design. Domain, DNS and gateway contracts remain part of the operating environment.

## Nextcloud files and synchronization

Nextcloud holds files and, through its database and apps, relationships, shares and possibly calendars or contacts. It may already exist outside the current automation scope. Record actual host, URL, version, install type, database, storage, apps and update support status.

Synchronization is not a backup: it can propagate changes and deletions. During an incident or restore, pause client synchronization until the caretaker chooses the authoritative data state. Preserve newer local files separately instead of removing accounts or overwriting folders blindly.

A complete backup needs the data, configuration, database and existing theme/customization content. Add external storage, app-specific content and encryption keys where relevant. Capture a coherent state using the appropriate maintenance and database procedure.

Test login, opening and downloading a real file; test calendars or contacts if used. A login alone proves neither file readability nor complete recovery. After restoring an older server snapshot, client copies may contain newer data. Follow the version-appropriate recovery procedure before reconnecting clients, including any required data-fingerprint handling. Database and data directory must both be available.

## Paperless document management

Paperless imports files, uses OCR to recognize text and makes content searchable. Titles, document date, correspondent, type and tags help organization. OCR and inferred dates can be wrong; verify important details against the original. Import order does not need to match document date order.

Installation version, guest ID, bridge, address and persistent paths are deployment-specific. A roadmap or feature branch is not proof of accepted operation. Use the runbook for the actual installed ingestion system.

Podman/Quadlet may separate Paperless, PostgreSQL and Valkey/Redis. PostgreSQL holds structured metadata; Valkey/Redis supports background work. Preserve documents and database outside replaceable images. An available web page does not prove successful processing.

### Private, parent and shared-family documents

Users, groups and document permissions determine access. Tags are organizational labels, not access restrictions. Personal salary statements belong in an appropriately protected private area; general reading material can be intentionally shared. Test search, download, preview and API access using a real account that should be denied, as well as one that should be allowed.

User-home scan folders can grant a dedicated sync identity only the required access rather than administrative rights. Verified source identity must determine document ownership and destination permissions. Missing or ambiguous mapping must stop ingestion rather than defaulting to public/shared access.

### Intake and AI

Trigger synchronization after writing completes, or use a tested file-stability condition. A delay alone does not prove the writer has finished. Test retries, duplicates, partial files, restarts and errors. Remove source documents only after confirmed import according to the retention policy.

An IMAP intake rule can import messages or attachments. Marking, moving and deletion depend on the configured rule; an ordinary folder move is not a confirmed archive operation.

A connected AI must retrieve only documents authorized for the requesting user. Shared administrator tokens, embeddings/search indexes and answer caches can defeat that boundary. A network/RADIUS login is not automatically an authenticated web SSO session. Verify the identity mapping and both allowed and denied searches before exposing the integration.

The official document exporter includes documents, thumbnails, metadata and database content. The corresponding importer requires the same Paperless version according to the referenced administration documentation. API tokens must be regenerated. Preserve deployment configuration separately and prove an isolated restore before relying on the system for important originals.

## EVCC charging control

The wallbox supplies electricity; EVCC coordinates charging using mode and meter values. A vehicle can also impose its own limits and schedule. In the reference go-eCharger integration, EVCC controls the charger directly over its network interface. MQTT supplies additional telemetry to Homey; an MQTT outage does not necessarily break direct charging control.

Only one EVCC instance may control the charger. The project documents a guarded migration, but the actual active guest and ID belong in the private inventory. Leave the legacy controller stopped and disabled.

Preserve `/var/lib/evcc/evcc.db` for settings/history and `/etc/evcc.yaml` when file configuration is used. These can contain credentials and must not be committed publicly.

If charging fails, inspect ordinary cable connection, wallbox status, EVCC mode, target state of charge, vehicle schedule and plausible meter readings. A PV mode may intentionally wait for sufficient surplus. Record an approved manual charging fallback based on the manufacturer's controls; do not open electrical housings.

The web interface commonly uses port 7070. Following an authorized change, check history, assignments and measurements, then carry out a controlled real charging cycle. A restore test must have no access to the charger; authorize exactly one productive instance only after isolation checks.

## MQTT and Homey

Mosquitto is the broker that distributes topic messages. Publishers send; subscribers receive matching topics. A topic looks like a path but is not a file. In the reference ACLs, EVCC publishes under `evcc/#`, go-eCharger under `go-eCharger/#`; Homey reads both and writes under `homey/#`.

Each application or device class uses a dedicated technical account. ACLs constrain reading and writing. `#` matches multiple levels; `+` one level. Case matters, and usernames and topics are separate identifiers. A valid password does not grant all topics.

Record the actual broker address privately. The reference listener on port 1883 is unencrypted and restricted to intended internal networks. Do not publish it to the internet as a troubleshooting step. Manage users through the controller's `tools/mqtt-user`; password changes must also reach the affected clients.

On the broker host inspect:

```sh
systemctl status mosquitto --no-pager
journalctl -u mosquitto -n 40 --no-pager
```

“Not authorised” can indicate credentials or ACLs. A TCP connection is not proof of MQTT authorization. Retained messages may be old; check timestamps and actual device status. Preserve configuration, user/ACL state and any required broker persistence. Topic traffic is not a complete archive of family content.

---

[Contents](EN-Start.md) · [Sources](EN-Sources.md) · [Prepare private handover](EN-Handover.md)
