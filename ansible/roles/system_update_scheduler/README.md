# system_update_scheduler

Installs systemd service/timer for a dedicated clean repository checkout and a
private configuration. Runs as the existing controller user. Does not create SSH
keys, store secrets, change sudo policy or start an immediate package transaction.

Prerequisites: committed checkout, configured inventory, known SSH host keys,
noninteractive become/Vault access, private SMTP password file, successful first
manual run. Variables are listed in defaults/main.yml. Install watchdog mode on
an independent host at 09:00 Europe/Berlin, with SSH read access to the controller
heartbeat. Service exit 1 means update/watchdog failure, exit 2 mail failure.
