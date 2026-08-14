# rocky_base

Baseline configuration for Rocky Linux mail nodes.

The role:

- validates Rocky Linux 9
- sets the hostname
- installs common administration packages
- creates the Bergen Platform administrative user
- installs its SSH public key
- configures passwordless sudo
- verifies SELinux remains enforcing
- enables rsyslog

The role deliberately does **not** install, enable or configure firewalld.
Firewall lockdown is performed only after WireGuard has been independently
validated.
