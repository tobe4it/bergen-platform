<!-- bergen-platform-handbook: managed -->
# Bergen Platform for beginners

[Deutsch](DE-Start.md) | [English](EN-Start.md)

You do not need to be a Linux expert to use the platform or prepare a handover. This handbook explains each system's role, its dependencies and the point at which a trained caretaker should take over.

## Four reading paths

- **No deployment yet?** [Build your own self-hosted IT from scratch](EN-Self-Hosting.md): understand prerequisites, practise in a lab, verify a first installation and expand gradually.
- **Outage or estate handover:** Start with emergency help, find the private contact and recovery route, and preserve existing data.
- **Everyday use:** Read the application sections, use authorized personal accounts, and describe failures accurately.
- **New caretaker:** Study fundamentals, automation and recovery; inventory the actual deployment and prove isolated restoration.

## Contents

**Starting from zero:** [Self-hosting learning and setup path](EN-Self-Hosting.md).

1. [Emergency](EN-Emergency.md)

2. [Architecture](EN-Architecture.md)

3. [Networks and identities](EN-Network-Identity.md)

4. [Linux and containers](EN-Linux-Containers.md)

5. [Automation and secrets](EN-Automation-Secrets.md)

6. [Applications](EN-Applications.md)

7. [Backup and recovery](EN-Backup-Recovery.md)

8. [Operation and takeover](EN-Operations.md)

9. [Private handover and printout](EN-Handover.md)

10. [Glossary](EN-Glossary.md)

11. [Sources](EN-Sources.md)

## Public guide and private operating record

This edition describes available architecture and verifiable procedures. It contains no real deployment addresses, private domain names or credentials. Documentation examples use `example.test` and `192.0.2.0/24`.

An implemented role, a successful Ansible recap and an accepted user function are different evidence. Distinguish planned, prepared and productive components. Prove a backup through an actual successful restore.

The separate blank printout is for the small number of necessary secrets unavailable from vaults or a password manager. Print it, enter those values by hand offline and store it securely. Reference secrets already managed elsewhere rather than duplicating them.

Edition 1.0, 2026-10-14. [Sources and maintenance](EN-Sources.md).
