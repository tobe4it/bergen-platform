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

## Baseline observed 2026-10-19 (read-only, venombox)

The first audited node returned:
- Proxmox `9.2.20`, running Linux kernel `7.0.14-19-pve`.
- SMBIOS system: `Micro Computer (HK) Tech Limited / AI Series`.
- SMBIOS mainboard: `Shenzhen Meigao Electronic Equipment Co.,Ltd / F8BSC`.
- `/sys/class/firmware-attributes` **absent**.
- Neither `fwupdmgr` nor `ipmitool` installed; the skipped queries do **not** prove that an actual BMC is absent.
- Successful Ansible run: `ok=12 changed=0 failed=0 skipped=4`.

**Vendor references, not an exact hardware confirmation:** The `F8BSC` board identifier occurs in Minisforum documentation for AI-family mini PCs. Minisforum describes `Restore on AC Power Loss` for the AI X1 Pro-370:
- https://www.minisforum.com/de/pages/product-info
- https://www.minisforum.com/de/blogs/press/hardware-requirements-for-enterprise-video-conferencing-rooms

Thus firmware may expose `Restore on AC Power Loss` in its own setup menus even when Linux lacks a writable BIOS interface. The board ID alone does not distinguish every Minisforum AI X1 / X1 Pro variant or firmware revision. The expanded audit collects **BIOS vendor, version and release date**, plus UEFI and local IPMI kernel presence, before choosing an access method.

For some *other* Minisforum AMD systems users report BIOS menu `Advanced → AMD CBS → FCH Common Options → AC Power Loss Options → Ac Loss Control → Always On`. This route is **unverified on F8BSC** and must be confirmed from the actual firmware menus; do not launch the setup menu remotely unless independent KVM/video access is available.

**Do not install `fwupd` merely to try the setter:** without a kernel-exposed firmware attributes API, installing the client does not create that firmware functionality. Do not install `ipmitool` merely because the binary is missing when no native BMC device has been established.

No supported remote BIOS-setting write path is yet demonstrated. Treat the desired `Always On` state as **unverified**, not as applied.

## Decision after audit

- **fwupd supports an AC-recovery key:** establish the precise setting name and firmware-accepted `Power On` value; introduce a separately approved idempotent setter.
- **Local IPMI reports a supported power restore policy:** consider a separately approved `ipmitool chassis policy always-on` implementation, with pre-/post-read and host identity gates.
- **Only vendor tooling supports it:** design a board-specific adapter and verify vendor documentation.
- **No writable remote interface:** document that configuration needs out-of-band KVM/BIOS access, rather than claiming that Ansible can set it.

Do not execute a setter or reboot until the board and firmware interface are identified and reviewed. If no power management interface exists, Ansible can still document policy expectations and verify Proxmox guest autostart but cannot enforce the physical host AC recovery configuration.

## Next checks after enabling hardware recovery

Review required guests' `onboot` and their start order/delays, especially identity, DNS, databases and dependent applications. Verify resulting startup during an independently planned maintenance window. Do not test by cutting power to a live host.
