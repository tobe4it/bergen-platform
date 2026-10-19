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

## Verified audit baseline (2026-10-19, venombox)

**First run:** `ok=12 changed=0 failed=0 skipped=4`.
**Extended run:** `ok=18 changed=0 unreachable=0 failed=0 skipped=4`.

Read-only findings:
- Proxmox `pve-manager/9.2.20`, running kernel `7.0.14-19-pve`.
- System DMI: `Micro Computer (HK) Tech Limited / AI Series`.
- Board DMI: `Shenzhen Meigao Electronic Equipment Co.,Ltd / F8BSC`.
- Firmware: `American Megatrends International, LLC. / 1.04` dated `04/11/2025`.
- UEFI boot: true.
- `/sys/class/firmware-attributes`: absent.
- `/sys/class/ipmi` and `/dev/ipmi0`: absent.
- Neither `fwupdmgr` nor `ipmitool` is installed; their respective queries were skipped.
- No firmware settings, guest startup settings, software or host runtime state were changed.

**Model evidence:** The official Minisforum AI X1 user manual lives in an `AI+X1-370+-365+-260+-255` download path and names board `F8BSC`. Distinguish this from Minisforum's separate **AI X1 Pro** model before selecting any firmware image.
- Minisforum support page: https://www.minisforum.com/de/pages/product-info
- AI X1 F8BSC manual: https://pc-file.s3.us-west-1.amazonaws.com/AI%2BX1-370%2B-365%2B-260%2B-255/user%2Bmannul/%E7%94%B5%E5%AD%90%E6%A1%A3%E8%AF%B4%E6%98%8E%E4%B9%A6%2BF8BSC%2B%28MP%2BV2.0%29%2B2025.5.16.pdf

**AC power recovery:** Other Minisforum AMD devices expose the option at `Advanced → AMD CBS → FCH Common Options → AC Power Loss Options → Ac Loss Control → Always On`, or alternatively under `Advanced → ACPI`. These are **unverified candidate menu paths** on the inventoried F8BSC / AMI 1.04.
- Community reports: https://www.reddit.com/r/MiniPCs/comments/1cr2rwl/minisforum_venus_series_um790_how_to_start/
- https://www.reddit.com/r/MINISFORUM/comments/1m8upsj

### Operational decision

Do **not** presume a remote BIOS write path exists. The absence of a local IPMI device and OS firmware attributes makes standard Linux-side management unlikely. Installing clients alone cannot prove a BMC or firmware API exists.

Preferred solution: In a scheduled maintenance window with a physically attached screen/keyboard or genuine out-of-band KVM, locate the exact AC recovery setting, choose `Always On`, save, restart and record the outcome. Avoid remotely booting into an inaccessible BIOS setup. Document the setting as a manually established host prerequisite in Ansible; do not misrepresent it as enforced. If a vendor-supported Linux setter becomes available, add an independently gated, exact hardware/firmware-specific apply role with before/after checks.

For physical model confirmation without sending serial numbers, the CPU model can be read locally with `lscpu`. Do **not** flash firmware images based on a generic `F8BSC` board name or an AI X1 Pro article.

## Remote-only paths while no physical console is available

**Hard constraint:** A headless host must never be rebooted into UEFI Setup using `systemctl reboot --firmware-setup` or `efibootmgr` without a working independent KVM/video path. It may remain unreachable indefinitely.

1. **AMI Setup Control Environment (AMISCE / SCELNX_64):** AMI offers a utility that can export or import firmware HII setup variables directly from Linux/EFI on *compatible* Aptio firmware, independently of the kernel `firmware-attributes` sysfs class. Intel provides AMISCE for its **own** M10JNP2SB board, not as a tested driver for F8BSC. Compatibility depends on firmware-integrated AMI modules (e.g., `SmiVariable`), so **do not execute unsigned/unverified third-party firmware binaries or perform imports on this headless production host**. Request a model- and BIOS-version-approved method from Minisforum; evaluate a read-only export only after validating provenance, compatibility, logging and a rollback/recovery procedure.
   - https://www.intel.com/content/www/us/en/download/19551/amisce-ami-setup-control-environment-utility-for-m10jnp2sb.html
   - https://device.report/m/ccdcec75ea8df1dab05cf35cb7d8643b3ad9c7bf6c1df9b738dc01397c413237
2. **Wake-on-LAN fallback:** the extended audit checks physical NIC names and their `ethtool` `Supports Wake-on` / `Wake-on` values without modifying them. `Wake-on: g` means Linux has armed magic-packet wake in the current configuration, **not** proof of startup after full mains failure (G3). An independent always-on network device (e.g. NAS/router) would be needed to transmit packets after a power outage. Test across a planned cold start before relying on it; changing WoL is an independently gated change. `bp-controller` is hosted by `venombox` and cannot wake its own powered-off host.
3. **External power-button controller:** a remotely managed relay across the physical power-button pins can solve this reliably even when the BIOS has no AC recovery option, but needs a **one-time on-site installation**. A remotely controlled AC socket alone cannot press the power button and is insufficient when AC recovery is disabled.

**No software-only path is guaranteed to recover the host after full AC loss** until either the exact BIOS recovery policy is confirmed or Wake-on-LAN recovery across G3 is empirically demonstrated.

## Decision after audit

- **fwupd supports an AC-recovery key:** establish the precise setting name and firmware-accepted `Power On` value; introduce a separately approved idempotent setter.
- **Local IPMI reports a supported power restore policy:** consider a separately approved `ipmitool chassis policy always-on` implementation, with pre-/post-read and host identity gates.
- **Only vendor tooling supports it:** design a board-specific adapter and verify vendor documentation.
- **No writable remote interface:** document that configuration needs out-of-band KVM/BIOS access, rather than claiming that Ansible can set it.

Do not execute a setter or reboot until the board and firmware interface are identified and reviewed. If no power management interface exists, Ansible can still document policy expectations and verify Proxmox guest autostart but cannot enforce the physical host AC recovery configuration.

## Next checks after enabling hardware recovery

Review required guests' `onboot` and their start order/delays, especially identity, DNS, databases and dependent applications. Verify resulting startup during an independently planned maintenance window. Do not test by cutting power to a live host.
