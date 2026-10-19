# Gated persistent Wake-on-LAN for venombox

This role implements **only wired NIC** Magic-Packet wake on the physically audited
`venombox` host. It does **not** implement or claim motherboard BIOS/UEFI
`Power On after AC Loss`. Proxmox guest autostart is a separate configuration.

2026-10-19 audited hardware: F8BSC board / AMI BIOS 1.04, physical wired NIC
`enp195s0`, driver-exposed `Supports Wake-on: pumbg`, initially `Wake-on: d`,
active 2.5 Gbit/s link. Wireless NIC `wlp194s0` is out of scope.

## Safety
- Defaults **read-only**: `power_recovery_wol_approved=false`.
- All writes require separate explicit CLI approval and exact host/board/BIOS
  preflight. Missing packages, unknown NIC, modified/foreign existing unit,
  unsupported mode and unexpected current value all fail closed.
- Uses a dedicated systemd oneshot at boot, not direct edits of Proxmox
  `/etc/network/interfaces` or `interfaces.new`. Never invokes
  `ifreload`, `ifdown`, `ifup`, reboot, or firmware tools.
- With approval, the systemd service runs `ethtool -s enp195s0 wol g`
  once immediately and each boot. The NIC remains otherwise configured as-is.
- No network reconfiguration is *intended*, but an NIC driver/firmware interaction
  cannot be ruled out. Preserve a working SSH session and out-of-band network
  monitoring during the initial change.
- Existing managed unit is only accepted if byte-identical, root-owned and
  `0644`; all other existing units cause a hard stop.
- If a guest or another tool resets NIC WoL mode later, the current one-shot
  service won't automatically correct it until the next execution/boot.
- `g` confirms driver Magic Packet support, **not** recovery after mains loss
  (G3). Linux cannot force an unsupported motherboard standby-power policy.
- Never intentionally shut down this remote-only host to test WoL without
  a confirmed power-button/KVM recovery option.

## Run from bp-controller

```bash
ansible-playbook -i ansible/inventory.yml \
  ansible/playbooks/configure-proxmox-wol.yml --syntax-check

# Safe default: audit only
ansible-playbook -i ansible/inventory.yml \
  ansible/playbooks/configure-proxmox-wol.yml

# Preview the explicitly gated change without applying it
ansible-playbook -i ansible/inventory.yml \
  ansible/playbooks/configure-proxmox-wol.yml \
  -e power_recovery_wol_approved=true --check --diff

# ONLY after a separate operational approval:
ansible-playbook -i ansible/inventory.yml \
  ansible/playbooks/configure-proxmox-wol.yml \
  -e power_recovery_wol_approved=true
```

Read-only postcheck:

```bash
ansible venombox -i ansible/inventory.yml -b -m command \
  -a '/usr/sbin/ethtool enp195s0'
```

The default read-only mode does not alter the system. Adding the unit and
enabling it are separate from BIOS AC recovery and from Synology sending magic
packets. The independently approved Synology receiver path and boot-time sender are described in [PROXMOX-SYNOLOGY-WOL.md](../../../docs/PROXMOX-SYNOLOGY-WOL.md). The packet was captured inbound at the running physical NIC. Firmware startup after full AC loss (G3) is still unverified.

## Confirmed live adoption, 2026-10-19

The operator ran the syntax-check and explicitly gated check/diff, then approved
and executed the live apply. Ansible reported `ok=21 changed=2 failed=0
skipped=1`. Subsequent NIC state was `Wake-on: g`, and the dedicated
`bergen-venombox-wol.service` unit was installed and enabled. No Proxmox
reboot, network reload, NIC down/up or firmware operation took place.

The Synology delivery test independently captured an inbound tagged Ethernet
Magic Packet (VLAN 3, EtherType 0x0842) at `enp195s0` while the host was
running. This proves packet arrival only in the running state; it does not
prove that the firmware will wake the host from S5 or G3.

**Operating rule:** Never shut down or power-cycle the remotely inaccessible
host merely to validate power recovery. A later physically supervised hardware
AC-power policy review is a separate change.
