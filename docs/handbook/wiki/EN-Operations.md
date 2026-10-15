<!-- bergen-platform-handbook: managed -->
# Observation, maintenance and takeover

[Deutsch](DE-Operations.md) | [English](EN-Start.md)

**Public edition 1.0, 2026-10-14.** Examples do not replace a private deployment inventory.

## Logs and system time

The Linux journal holds local unit/service events. Syslog forwards messages to a central receiver. The reference collector stores remote events by sender address under `/var/log/remote/<sender-ip>.log`. TCP/UDP 514 and retention are configurable; actual senders and retention must be verified locally.

NTP aligns clocks. Wrong time can confuse incident correlation and break certificates or authentication. Record the time zone as well as the local timestamp. A useful incident states expected and actual behavior, affected devices/accounts/networks, onset, last change and the messages around that time.

On the correct EVCC host, a bounded example is:

```sh
journalctl -u evcc -n 40 --no-pager
```

Identify the proper unit for other applications. Broad log dumps are hard to review and can expose private content. Configuring forwarding does not prove arrival: send a harmless test event and find it at the collector. Queuing does not guarantee unlimited retention.

Monitoring additionally checks disk space, availability and certificate expiry and sends actionable alerts. A planned Observium, Loki/Grafana or AI integration is not an active alerting system. Until tested alerts exist, arrange explicit recurring checks.

## Optional AI and market-data services

Ollama runs local models; Open WebUI supplies the interface. Test login and inference separately. Preserve settings/accounts/chat data intentionally; large downloadable model files may have a different recovery priority. AI output is not proof of a diagnosis.

The daytrading collector reads data and produces signals; it does not place orders according to the project. Record provider sessions, timers, data rights and subscriptions. Optional proxies, analytics and Kafka plans must be distinguished from real deployed dependencies.

## A proposed maintenance rhythm

| When | Designated caretaker checks |
| --- | --- |
| Weekly | Backup successes/missing jobs, space, device warnings, important services and mail queues |
| Monthly | Certificate expiry, provider/domain contracts, updates, warnings and responsibility |
| After changes | Functions, recovery path, backups and updated private inventory |
| Planned regularly | Isolated recovery samples with recorded scope and results |

This is a proposed schedule, not a statement that existing jobs already run. Agree frequency and an independent notification route.

An update has seven steps: establish current functions; record versions/local changes; read release guidance; ensure a recoverable backup; change one bounded component; verify login and real operation; document outcome and version. Reflect managed manual changes in their source so later Ansible runs do not overwrite them.

Rolling Git back is not a database rollback. Schema migrations and new content may require a matching data restore. Observe version compatibility especially for Nextcloud and Paperless.

Vim is an available editing approach, not a requirement for relatives. Practice first: i enters text, Esc returns to command mode, `:q!` discards and exits, `:wq` saves and exits. Record before/after behavior and evidence.

## Incident directions

| Symptom | First safe direction |
| --- | --- |
| Everything offline | Power/network/WAN; no factory reset |
| Internet works, local names fail | Configured DNS and Pi-hole/Synology path |
| Several logins fail | Directory, DNS, time and TLS; preserve accounts |
| Web page works, data missing | Pause sync, retain originals, inspect database/storage/backups |
| One service fails | Correct host/unit/logs and recent change |
| Low space or disk warning | Inspect backups and limit writes as appropriate, not speculative deletion |
| Certificate warning | Record name/time; caretaker checks actual chain and renewal |

## Take over or replace services gradually

In the first week, identify a caretaker, test recovery access and inventory devices, contracts and content. Confirm the active mailbox source and backup destinations. Keep functioning services stable.

Next prove isolated restoration, then have users check normal use. Complete administration transfer and larger migrations only after this evidence. If replacing a component, inventory its content and clients, export, open samples at the new destination and test users before retiring the old service.

Do not abandon a mail domain before moving dependent account-recovery addresses. Keep DNS and LDAP while applications still require them. Charging needs a tested fallback when EVCC is retired. Completion means ordinary users can work, a named caretaker can troubleshoot, and another person can recover important data.

---

[Contents](EN-Start.md) · [Sources](EN-Sources.md) · [Prepare private handover](EN-Handover.md)
