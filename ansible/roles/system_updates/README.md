# system_updates

Inspect or apply OS security updates on one explicitly selected inventory host.
Uses distribution security origins with exact APT version pins, or DNF security
metadata. Refreshing package metadata is a write even in AUDIT mode. Requires
python3-apt on Debian/Ubuntu; does not bootstrap packages during an audit.

No reboot, crypto-policy change, repository change, application major-version
upgrade, container image update, or automatic rollback. Package maintainer scripts
may restart services during installation. Configured consumers are explicitly
restarted after changed transactions. Health URLs must return HTTP 200 with valid
TLS before and after updates. List all affected long-running consumers, including
PHP workers and services using updated shared libraries.

Run via scripts/system_updates.py. Results are private controller JSON files.
Failed or unreachable hosts stop subsequent writes, while remaining hosts are
still inspected. See docs/SYSTEM-UPDATES.md for deployment and limitations.
