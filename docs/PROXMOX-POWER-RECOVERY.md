# venombox: unattended restart after a power outage

## Separation of concerns

1. **Physical host AC recovery:** motherboard BIOS/UEFI or BMC must provide `Power On` / `Always On` after power is restored. Linux/systemd cannot turn itself on while the hardware is without power.
2. **Proxmox guests:** after host startup, individual VM/LXC `onboot` and start order/delay determine when services return. Guest boot settings cannot replace host firmware AC recovery.
3. **UPS:** optional controlled shutdown and restore policy are a separate change; do not treat a UPS software shutdown as equivalent to an AC power outage. A UPS that continues supplying AC might not trigger a firmware AC-loss event.

## Read-only remote discovery

From the existing `bp-controller` checkout:

```bash
ansible-playbook -i ansible/inventory.yml \
  ansible/playbooks/audit-proxmox-power-recovery-readonly.yml \
  -e power_recovery_target=venombox
```

No inventory IP, credentials, BMC endpoints, passwords, or hardware serial numbers should be added to tracked documentation.

The playbook refuses an unselected host or an actual host whose short hostname is not `venombox`. It reads DMI hardware IDs and checks existing interfaces via `fwupdmgr`, local IPMI and firmware sysfs. It is safe to repeat, including in Ansible check mode; all expected tasks report unchanged.

## Decision after audit

- **fwupd supports an AC-recovery key:** establish the precise setting name and firmware-accepted `Power On` value; introduce a separately approved idempotent setter.
- **Local IPMI reports a supported power restore policy:** consider a separately approved `ipmitool chassis policy always-on` implementation, with pre-/post-read and host identity gates.
- **Only vendor tooling supports it:** design a board-specific adapter and verify vendor documentation.
- **No writable remote interface:** document that configuration needs out-of-band KVM/BIOS access, rather than claiming that Ansible can set it.

Do not execute a setter or reboot until the board and firmware interface are identified and reviewed. If no power management interface exists, Ansible can still document policy expectations and verify Proxmox guest autostart but cannot enforce the physical host AC recovery configuration.

## Next checks after enabling hardware recovery

Review required guests' `onboot` and their start order/delays, especially identity, DNS, databases and dependent applications. Verify resulting startup during an independently planned maintenance window. Do not test by cutting power to a live host.
