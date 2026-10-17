# SSH into an isolated LXC through its Proxmox host

Use when an Ansible controller can SSH to a Proxmox node but a guest is
intentionally unreachable due to VLAN isolation. This **does not** open
cross-VLAN routes or weaken UniFi firewall rules.

Transport path:

    Ansible/SSH -> trusted PVE SSH -> pct exec VMID
                -> guest Python TCP relay to 127.0.0.1:22 -> guest sshd

The source of truth for guest identity is VMID plus strict SSH host-key checking.
The PVE SSH account is privileged enough to execute pct; limit it to trusted
automation. This transport **does not create additional network isolation**
between the Proxmox administrator and that guest; Proxmox already has control.

## Read-only preflight

From the repository root and with a git-ignored site-local vars file:

    ansible-playbook ansible/playbooks/preflight-pct-ssh.yml \
      -e @ansible/group_vars/all/bergen-proxy.yml \
      --check --ask-vault-pass

Preflight requires the guest to exist and be running; it reads its actual
hostname, bridge, unprivileged mode, Python 3, SSH service state, and ED25519
host-key fingerprint. It does not change configuration.

## Manual connection test

First, compare the ED25519 fingerprint displayed by preflight to the first
SSH host-key prompt below. Substitute **your own** reachable PVE SSH host,
guest VMID and currently discovered guest IP; the sample is documentation
only. Do not put real site addresses into this repository.

    ssh -o 'ProxyCommand=python3 ./ansible/scripts/pct_ssh_proxy.py --pve-host 192.0.2.10 --vmid 999' \
        -o HostKeyAlias=lxc-999 \
        -o StrictHostKeyChecking=ask \
        root@192.0.2.20 hostname

On first connection, accept the guest host key **only after comparing** the
fingerprint with the independently collected preflight value. Later SSH
connections should use StrictHostKeyChecking=yes. The PVE host's key must
already be trusted in the controller's SSH known_hosts file. No agent
forwarding is used; guest public-key authentication remains required.

This avoids placing a raw SSH tunnel listener on the PVE node or in any VLAN.
The guest must have its normal sshd and /usr/bin/python3. An IP is used as
the target name for host identity, but **no direct connection to that IP** is
made; the ProxyCommand supplies the byte stream from inside the LXC.

## Integrate with ignored Ansible inventory

Add an entry under the local group of isolated LXCs. All real IP addresses,
PVE hostnames and VMIDs are site-specific. Example (not deployable as-is):

    all:
      children:
        isolated_lxcs:
          hosts:
            example-guest:
              ansible_host: 192.0.2.20
              ansible_user: root
              ansible_python_interpreter: /usr/bin/python3
              ansible_ssh_common_args: >-
                -o ProxyCommand="python3 ./ansible/scripts/pct_ssh_proxy.py --pve-host 192.0.2.10 --vmid 999"
                -o HostKeyAlias=lxc-999
                -o StrictHostKeyChecking=yes

Use both the shared inventory and site-local inventory:

    ansible -i ansible/inventory.yml -i ansible/inventory.local.yml \
      example-guest -m ansible.builtin.ping

Run Ansible from the repository root (or use an absolute path for the proxy
script). Do **not** use the original discover-lxc.yml/bootstrap-lxc.yml
against these guests without refactoring their *direct TCP wait/ssh-keyscan*
steps; those steps cannot see the guest from the controller and may time out.
Apply baseline roles only after verifying the tunnel and reviewing the
target inventory.

## Limitations

- No TCP/IP interface is added to Proxmox's VLAN 3 bridge.
- No new software is installed: guest Python 3 is a prerequisite; its relay
  only connects to that guest's loopback SSH port.
- The SSH ProxyCommand runs a privileged, non-interactive pct exec through
  PVE and depends on working guest and host SSH key authentication.
- A failed guest SSH session cannot silently fall back to direct guest SSH.
- DHCP reservation, firewall policies, guest certificate management, and the
  separate Nginx deployment approval remain outstanding.
- Validate the streaming behavior with the manual SSH test before enabling
  Ansible configuration writes.
