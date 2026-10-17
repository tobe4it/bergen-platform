# Bootstrap an isolated Proxmox LXC

Use this generic playbook only after verifying the exact LXC and its SSH host
key by the documented PCT-mediated SSH transport (see PROXMOX-PCT-SSH.md).

Unlike the existing bootstrap-lxc.yml, bootstrap-isolated-lxc.yml uses
wait_for_connection through the configured SSH ProxyCommand. It never tries
to connect directly from the Ansible controller into the isolated guest VLAN
or replaces trusted host keys.

## Configuration

Provide the correct lxc_hostname, lxc_vmid, and lxc_inventory_group in your
git-ignored local variables file. The site-local inventory must configure the
PCT SSH ProxyCommand, HostKeyAlias=lxc-<VMID>, and
StrictHostKeyChecking=yes. Do not commit real addresses, names or secrets.

## Dry run

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/bootstrap-isolated-lxc.yml \
      -e @ansible/group_vars/all/your-local-vars.yml \
      --check --diff --ask-vault-pass

Verify that exactly the intended guest is listed, that the host identity
assertions pass, and that the proposed baseline changes are expected.

## Explicitly approved live bootstrap

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/bootstrap-isolated-lxc.yml \
      -e @ansible/group_vars/all/your-local-vars.yml \
      -e isolated_lxc_bootstrap_approved=true \
      --ask-vault-pass

This applies the existing lxc_base role, then verifies Ansible communication
and tmux. It does **not** invoke the Nginx role or alter VLANs, network rules,
DNS or TLS distribution. Nginx deployment remains separately gated.
