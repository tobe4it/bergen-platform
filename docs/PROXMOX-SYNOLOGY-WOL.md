# Synology MountainCloud -> venombox: Wake-on-LAN after NAS boot

## Purpose and verification boundary

Prepare a separately approved DSM **Triggered Task -> Boot-up** to send bounded Magic Packets after MountainCloud boots from restored mains power.

Physical target: venombox, Proxmox 9.2.20, F8BSC / AMI 1.04; wired NIC `enp195s0`. The host NIC now runs with `Wake-on: g` under draft PR #120. The DS920+ is reported to start automatically once AC power returns.

**Observed transport proof (2026-10-19):**
- A manual `synonet --wake [target MAC] eth0` was sent from the NAS.
- Running venombox captured the corresponding packet using `tcpdump -Q in` on physical `enp195s0`.
- The frame contained Ethernet broadcast, IEEE 802.1Q VLAN **3**, EtherType **0x0842**, 6 x FF followed by 16 copies of the target MAC. One inbound packet, zero kernel drops.
- Frame source MAC matched wake target MAC; it cannot authenticate the sender, but capture direction and timing prove the observed packet delivery to the running host.
- No new UniFi broadcast relay is required for this **observed** traffic path.

**Not verified:** successful waking of the host from S5, or from full AC loss/G3. Do not shut down or power-cycle the physically inaccessible host to test.

## Behavior of staged script

Source: `ansible/files/power-recovery/synology-venombox-wol-onboot.sh`

- POSIX /bin/sh using existing DSM `/usr/syno/sbin/synonet`.
- Requires DSM root, exact `eth0`, and a site-local root-protected MAC file.
- Waits up to 5 minutes for carrier, then 60 seconds for network settlement.
- Sends **12** magic packets at **30-second** intervals. Bounded runtime, no daemon and no ongoing schedule.
- No firmware changes, NIC configuration, NAS routing/VLAN/firewall changes, service shutdown or Proxmox changes.
- Return code and logs indicate packet-send requests only: actual host power-on cannot be inferred from script success.

## Approval-controlled DSM setup (NOT DEPLOYED)

1. Review the script and decide whether repeated Wake-on-LAN after **every NAS reboot** is acceptable.
2. Create a NAS directory `/volume1/bergen-recovery` owned by root with restrictive permissions (suggested mode 0700). Ensure it belongs to a stable data volume.
3. Copy the reviewed script to `/volume1/bergen-recovery/venombox-wol-onboot.sh` with root owner and executable permissions (suggested mode 0700).
4. Create `/volume1/bergen-recovery/venombox-wol.mac` containing **only one MAC address** (plain text). Protect it with root ownership and mode 0600. **Never commit site-local identifiers to Git.**
5. Confirm source files are readable by DSM Task Scheduler root. Validate POSIX syntax: `/bin/sh -n /volume1/bergen-recovery/venombox-wol-onboot.sh`.
6. In DSM **Control Panel -> Task Scheduler**, create a **Triggered Task -> User-defined Script -> Boot-up** under user **root** (labels may differ across DSM language/version). Configure task command as:
   
   `/bin/sh /volume1/bergen-recovery/venombox-wol-onboot.sh`
7. **Keep task disabled** until a separate explicit operator approval. Inspect existing DSM tasks to avoid duplicate wake triggers.
8. After approval, first **manually** execute the script while venombox stays **running**; record the DSM result and verify at least one inbound Magic Packet with bounded `tcpdump -Q in`. Only then enable boot trigger.
9. Do **not** use an unplanned venombox shutdown, power disconnect or NAS restart as a test.

If the NAS Task Scheduler does not support an initially disabled Boot-up trigger, do not create an active Boot-up task merely to store the command; review the UI first.

## Rollback and limitations

Disable only the dedicated DSM task; leave NAS interface and Proxmox configuration unchanged. If desired, remove only the approved script and local MAC file after confirming no tasks depend on them. NAS reboot is unnecessary to disable the task.

The sender emits packets after the NAS itself boots, not while it is off. A NIC may receive VLAN-tagged WoL in S0 but reject it in firmware standby/S5/G3. Neither this script nor a successful send proves restart after full AC loss. BIOS `Power On after AC Loss` remains an independent, unverified configuration prerequisite for robust G3 recovery.
