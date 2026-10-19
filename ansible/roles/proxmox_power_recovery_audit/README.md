# Proxmox firmware power recovery audit

Read-only hardware and firmware capability inventory for the **physical** Proxmox host `venombox`.

The desired eventual BIOS/UEFI policy is **Power On / Always On** after AC is restored, not merely `Last State`. This policy cannot be enforced by Proxmox guest `onboot` settings, nor by systemd on a powered-off host.

The role checks:
- actual host identity and `pveversion`;
- DMI system and mainboard manufacturer/model (never serial numbers);
- `/sys/class/firmware-attributes`;
- `fwupdmgr get-bios-settings`, when the utility already exists;
- local `ipmitool -I open chassis status`, when the utility already exists.

Missing utilities and unsupported management interfaces are reported but never installed or changed. A failed firmware query **does not prove** firmware configuration is impossible: vendor tooling or BMC out-of-band management may still be available.

All discovery commands are explicitly read-only even with Ansible `--check`; check mode must not suppress inventory or host-identity validation.

No BIOS changes, packages, firmware updates, reboot, IPMI power operations, or PVE VM/LXC settings are performed.

A subsequent, independently approved apply implementation must first bind an exact firmware setting and allowed value to the observed board, compare current vs desired state, reject unsupported hardware and unexpected drift, and require an explicit one-time approval before changing it. Do not automatically reboot a headless host as part of that procedure.
