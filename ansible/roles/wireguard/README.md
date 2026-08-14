# wireguard

Configures the WireGuard management tunnel for an external Bergen Platform node.

Security design:

- the private key is generated on the managed node
- the private key never needs to be stored in Git or Ansible Vault
- only the public key is shown by the playbook
- the role does not alter firewall state

For the STRATO test mail node the assigned tunnel address is
`192.168.5.4/32`.

A successful local role run is not sufficient for firewall lockdown.
SSH and Ansible access over WireGuard must first be independently validated
from `bp-controller`.
