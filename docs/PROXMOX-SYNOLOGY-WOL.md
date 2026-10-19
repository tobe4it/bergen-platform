# Synology MountainCloud -> venombox: Wake-on-LAN after NAS boot

## Purpose and verification boundary

Betriebsanleitung für einen freigegebenen DSM-**Ausgelöste Aufgabe → Hochfahren**-Sender: Nach Neustart der Synology werden begrenzt Magic Packets an venombox gesendet. **Keine Inbetriebnahme durch einen künstlichen Stromausfall; venombox, DSM und Netzwerkgeräte werden nicht für den Test neu gestartet.**

Physical target: venombox, Proxmox 9.2.20, F8BSC / AMI 1.04; wired NIC `enp195s0`. The host NIC now runs with `Wake-on: g` after an approved live Ansible apply (tracked in PR #120). The DS920+ is reported to start automatically once AC power returns.

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
- Requires DSM root, exact `eth0`, and a site-local root-protected MAC file (one newline-terminated MAC address, no symlink).
- **Explicit fail-closed arguments:** `--check` checks prerequisites only and exits without packets, sleep or power operations; `--send` is required for packet transmission. Running with no arguments fails.
- Waits up to 5 minutes for carrier, then 60 seconds for network settlement.
- Sends **12** magic packets at **30-second** intervals. Bounded runtime, no daemon and no ongoing schedule.
- No firmware changes, NIC configuration, NAS routing/VLAN/firewall changes, service shutdown or Proxmox changes.
- Return code and logs indicate packet-send requests only: actual host power-on cannot be inferred from script success.

## Behebener Erstlauf-Blocker: SSH-Host-Key-Vertrauensstellung (19.10.2026)

Der **erste** `bp-controller`-Installationslauf ist beim rein lesenden NAS-Preflight mit `rc=255` abgebrochen, bevor Dateien angelegt wurden: `No ED25519 host key is known ... StrictHostKeyChecking=yes`. Ansible: `ok=2 changed=0 failed=1`. Das ist eine gewollte Fail-Closed-Sicherheitsgrenze, keine Aufforderung, die SSH-Host-Key-Prüfung abzuschalten.

Vorgehensweise:
1. Den **vertrauenswürdigen** SSH-ED25519-Host-Key-Fingerprint auf einer bestehenden, bereits authentifizierten DSM-Sitzung ermitteln:
   `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256`.
2. Auf bp-controller den **angebotenen** Schlüssel in eine temporäre Datei holen:
   `ssh-keyscan -T 10 -t ed25519 NAS_SSH_IP > /tmp/mountaincloud-ed25519.known_hosts`
   und den angebotenen Fingerprint mit
   `ssh-keygen -lf /tmp/mountaincloud-ed25519.known_hosts -E sha256` auslesen.
3. Nur bei exakter Übereinstimmung die Zeile in `~/.ssh/known_hosts` des **Ansible-Ausführungsbenutzers** ergänzen. Nicht die privaten NAS-Netzparameter oder SSH-Schlüsselmaterial in Git aufnehmen.
4. `ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes BENUTZER@NAS_SSH_IP 'hostname -s'` als Read-only-Test. Falls danach Public-Key-Authentifizierung oder `sudo -n` scheitert, separat und sicher behandeln. Keinen passwortbasierten Bypass und kein `StrictHostKeyChecking=no`.
5. Danach zuerst das vorgesehene `--check` und erst dann den freigegebenen Installations-Apply erneut ausführen. **Keine** NAS/Host-Neustarts oder Paketsendetests erforderlich.

**Späterer Nachweis:** Die beiden SSH-ED25519-Fingerprints wurden auf NAS und bp-controller unabhängig und exakt verglichen; der Host-Key wurde in der lokalen `known_hosts` abgelegt. `ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes` gab den Hostnamen `MountainCloud` zurück. Der anschließende Ansible-Check und produktive Installationslauf waren erfolgreich.

## Durchgeführte Dateiinstallation und DSM-Aufgabe

Der Betreiber hat Installation und Aktivierung einer DSM-Boot-Aufgabe freigegeben, **ohne NAS-/Host-Neustart oder Stromausfalltest**. Die hier dokumentierte Dateiinstallation wurde durch den Betreiber auf `bp-controller` tatsächlich durchgeführt. Der DSM-Task wird ausschließlich im nativen DSM-Aufgabenplaner erstellt; seine Einstellungen sind nicht durch Ansible ausgelesen. Die Rückmeldung des Betreibers nach der DSM-Anleitung war „Ok“; das ist eine **Betreiberbestätigung**, keine unabhängige Status- oder Funktionsprüfung der DSM-Aufgabe.

1. Auf bp-controller eine **gitignorierte** `ansible/vars/synology-wol.local.yml` mit folgenden Schlüsseln anlegen:

   ```yaml
   synology_admin: "BENUTZER@NAS-SSH-HOST"
   synology_wol_mac: "XX:XX:XX:XX:XX:XX"
   ```

   Werte ausschließlich aus dem privaten Standortinventar übernehmen; niemals in Git committen. Datei mit Modus 0600 schützen.

2. In der Worktree des freigegebenen Branches auf bp-controller ausführen:

   ```bash
   ansible-playbook -i ansible/inventory.yml \
     ansible/playbooks/install-synology-venombox-wol.yml \
     -e @ansible/vars/synology-wol.local.yml \
     -e synology_wol_install_approved=true --syntax-check

   ansible-playbook -i ansible/inventory.yml \
     ansible/playbooks/install-synology-venombox-wol.yml \
     -e @ansible/vars/synology-wol.local.yml \
     -e synology_wol_install_approved=true --check

   ansible-playbook -i ansible/inventory.yml \
     ansible/playbooks/install-synology-venombox-wol.yml \
     -e @ansible/vars/synology-wol.local.yml \
     -e synology_wol_install_approved=true
   ```

   Das Playbook prüft per bestehendem SSH-/sudo-Zugang die Hostidentität, legt bei Freigabe ausschließlich root-kontrollierte Dateien unter `/volume1/bergen-recovery/` an, verweigert fremde/abweichende Dateien und führt `/bin/sh -n` sowie `--check` aus. **Kein Paketversand und keine DSM-Task-Erstellung.** Der Installer wurde auf `bp-controller` live ausgeführt und meldete erfolgreich: `ok=7 changed=1 failed=0 skipped=0`.

3. Im DSM-Aufgabenplaner unter **Systemsteuerung → Aufgabenplaner → Erstellen → Ausgelöste Aufgabe → Benutzerdefiniertes Skript** folgende Aufgabe anlegen:

   | Feld | Wert |
   | --- | --- |
   | Name | Bergen – venombox Wake-on-LAN |
   | Benutzer | root |
   | Ereignis | Hochfahren / Boot-up |
   | Aktiviert | Ja |
   | Benutzerdefiniertes Skript | `/bin/sh /volume1/bergen-recovery/venombox-wol-onboot.sh --send` |

   Einrichtung/Abnahme: Aufgabe als **aktiviert**, Benutzer **root**, Ereignis **Hochfahren** kontrollieren. **Nicht auf Ausführen klicken, keinen Neustart veranlassen.**

4. Rücknahme: Nur diese dedizierte DSM-Aufgabe deaktivieren oder löschen, ohne NAS-/Host-Neustart. Die installierten Dateien dürfen für spätere Wartung verbleiben.

**Stand vom 19.10.2026:** `--syntax-check` bestanden. Check-Modus: `ok=5 changed=0 failed=0 skipped=2`, ausdrücklich ohne Write. Live-Apply: `ok=7 changed=1 failed=0 skipped=0`, bestätigte Meldung `Files: installed/validated`; Installationslauf führte `/bin/sh -n` und Skript-`--check` aus, kein Wake-Paket, kein Reboot. DSM-Aktivierung: vom Betreiber im Dialog anschließend mit „Ok“ quittiert, **nicht unabhängig über DSM-CLI/UI ausgelesen**. Der NAS-Boot-Trigger wurde nicht probeweise gestartet. Verhalten aus S5/G3 bleibt ungeprüft.

## Abnahme und nächste reguläre Kontrolle

- Bei Gelegenheit in **DSM → Systemsteuerung → Aufgabenplaner** kontrollieren: genau eine Aufgabe `Bergen – venombox Wake-on-LAN`, Benutzer `root`, Trigger **Hochfahren**, aktiviert, Skript `/bin/sh /volume1/bergen-recovery/venombox-wol-onboot.sh --send`.
- Ohne NAS-Neustart prüfen; **nicht** manuell starten. Die Installationsprüfung ist bereits erfolgreich, ein zusätzlicher Live-Sendetest ist nicht nötig.
- Auf dem nächsten regulären DSM-Start den Task-Verlauf ansehen. Die Ausgabe `WOL_BOOT_SEND_COMPLETED` bestätigt **nur** erfolgreiche send requests, nicht, dass venombox tatsächlich aus ausgeschaltetem Zustand gestartet ist.
- Falls der Task in DSM nicht auffindbar/aktiv ist, bleibt der operative Abschluss offen, bis die Aufgabe dort nachgewiesen ist.

## Rollback and limitations

Disable only the dedicated DSM task; leave NAS interface and Proxmox configuration unchanged. If desired, remove only the approved script and local MAC file after confirming no tasks depend on them. NAS reboot is unnecessary to disable the task.

The sender emits packets after the NAS itself boots, not while it is off. A NIC may receive VLAN-tagged WoL in S0 but reject it in firmware standby/S5/G3. Neither this script nor a successful send proves restart after full AC loss. BIOS `Power On after AC Loss` remains an independent, unverified configuration prerequisite for robust G3 recovery.
