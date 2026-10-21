# Nextcloud restore test 701 on venombox: offline first phase

The verified Synology backup is a 4.5-GB GNU tar.gz containing the Nextcloud
31.0.14.1 installation including config.php and data, plus nextcloud.sql.gz.
The backup lives on the dedicated mx2 Nextcloud NFS export. The existing
venombox NFS share is for Proxmox backups **and is not the same export**.
Do not mount the Nextcloud share directly on PVE merely to save copy time.

## Verified host preflight (19 Oct 2026)

- venombox: Proxmox 9.2.20; local-zfs has about 1.8 TB available.
- All ZFS pools healthy, VMID 701 clusterwide unused.
- local Rocky 9 (20240912) and Debian 13 container templates exist.
- Existing services VMIDs 100-143 remain untouched; 801/816 are legacy.
- For production fidelity, test guest should start from Rocky Linux 9,
  with compatible PHP 8.3 and MariaDB package versions.
- LXC 701 is **test-only** and outside the legacy VMID 800-899 interval.

## First phase: provision with no network

This phase creates only a stopped, unprivileged, protected Rocky 9 container
with an explicitly absent net0 interface. It does not install packages, copy
backup data, restore SQL, start the guest, or contact mx1/mx2.

From bp-controller in an isolated worktree:

    BASE="$HOME/bergen-platform"
    cd "$BASE"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git worktree add --detach "$HOME/bergen-platform-nextcloud-restore" \
      origin/feat/nextcloud-isolated-restore-701-20261019
    cd "$HOME/bergen-platform-nextcloud-restore"

Run the default read-only preflight first:

    ansible-playbook \
      -i "$BASE/ansible/inventory.yml" \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/prepare-nextcloud-isolated-restore-701.yml \
      --vault-id infra@prompt

Expected: NEXTCLOUD_RESTORE_701_READ_ONLY_READY; no changes.

Only after personally reviewing identity and storage output, expressly
approve provisioning:

    ansible-playbook \
      -i "$BASE/ansible/inventory.yml" \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/prepare-nextcloud-isolated-restore-701.yml \
      --vault-id infra@prompt \
      -e nextcloud_restore_701_apply=true

Expected: NEXTCLOUD_RESTORE_701_PROVISIONED_OFFLINE. Guest exists but remains
**stopped**, has no network configuration, onboot=0, unprivileged=1,
protection=1, rootfs local-zfs:48 (GiB). Host workspace is
/var/lib/vz/nextcloud-restore-test (root:root, mode 0700).

This preparation is deliberately **single-use**: rerunning the playbook
after VMID 701 exists fails the collision guard rather than updating or
deleting an existing guest.

## Next separate tasks (not automated by this preflight)

1. Inventory currently enabled backing access between venombox and mx2.
   Use an authenticated, pinned SSH host key and a strictly bounded
   **read-only** source path. Never broaden NFS export permissions or
   use the normal Proxmox backup export as a substitute.
2. Copy one completed Synology snapshot archive to the protected local
   host workspace, verify SHA256 digest and re-check archive paths before
   extracting it. Ensure no archive path traversal, unsafe links or
   unexpected absolute file paths. Never extract into the PVE host root.
3. Install exactly compatible PHP modules, webserver and MariaDB into
   the guest. As the guest is networkless, package acquisition must be
   handled separately via a reviewed offline package cache/repository.
   Do not attach it to a production bridge for convenience.
4. Start guest only after verifying net0 remains absent, then transfer the
   verified archive using a controlled host-to-guest mechanism; verify
   ownership/permissions and SELinux compatibility within unprivileged LXC.
5. Import SQL only in the disposable **guest** MariaDB; set test-only
   Nextcloud config/trusted domains/data path and disable side effects
   (cron, SMTP, LDAP/OIDC, external storage, shares/Collabora, outgoing
   notifications). Do not make API calls from restored accounts.
6. Check Nextcloud status, app and version compatibility, data existence,
   representative restored file and share metadata through localhost
   within the guest. Record restore time, failures and corrective changes.
7. Keep the guest isolated until deliberately decommissioned.

## Boundaries

Do not delete stale mx1 code or DB until separate restore approval.
Do not alter the mx2 backup script/timer, production Cloud, the public DNS,
Synology NAS exports or legacy PVE containers. This preflight cannot by
itself prove disaster recovery, since it stops before loading any backup.


## Phase 2A: read-only selection and transfer preflight

After phase 1 has created the offline 701 guest, independently verify that
VMID, isolated state and latest completed Synology snapshot still match:

    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-nextcloud-restore"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git switch --detach origin/feat/nextcloud-isolated-restore-701-20261019

    ansible-playbook \
      -i "$BASE/ansible/inventory.yml" \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/audit-nextcloud-restore-transfer-readonly.yml \
      -e @"$BASE/ansible/vars/mail-tls.local.yml" \
      -e @"$BASE/ansible/vars/mail-nextcloud-stack.local.yml" \
      -e @"$HOME/bergen-platform-nextcloud-backup/ansible/vars/nextcloud-backup.local.yml" \
      --vault-id infra@prompt

The final local backup configuration path must exist and be a protected ignored
YAML file. Do not copy passwords to a git-tracked path. The audit verifies only
the latest completed snapshot metadata and its two completion markers; it
does **not** rehash the entire archive and it performs no transfer. It also
reports the source's PHP and MariaDB versions to plan compatible offline
package acquisition.

Expected results:
- VENOMBOX_701_ISOLATED_STOPPED
- one safe snapshot ID and its archive size
- NEXTCLOUD_RESTORE_TRANSFER_PREFLIGHT_READY
- changed=0, failed=0

Next phase will choose a bounded SSH transport or equivalent explicit file
delivery, with independent digest verification on venombox. Never bypass
host-key verification or widen the Synology NFS export.

## Phase 2B: pinned archive transfer

Use ansible/playbooks/transfer-nextcloud-restore-archive.yml for controller-
relayed SSH. Its default execution checks both SSH identities, the pinned
completed source snapshot, and the stopped isolated destination. It does not
transfer data without an explicit apply setting.

Pass the same three protected site-local variables files as for phase 2A.
Specify nextcloud_restore_snapshot_id=20261019T043001Z-3349088. First run
without an apply flag; expect NEXTCLOUD_RESTORE_TRANSFER_READ_ONLY_READY.

A second run with nextcloud_restore_transfer_apply=true streams this one
archive over the controller in bounded memory. The target refuses to
overwrite existing files and uses SHA-256 and length verification before
committing a complete root-only local archive. The controller also verifies
the in-flight bytes. Guest 701 remains stopped without network.

The destination path is:
  /var/lib/vz/nextcloud-restore-test/nextcloud-20261019T043001Z-3349088.tar.gz

Both SSH links require trusted keys and prohibit agent forwarding. Do not
widen the NAS export or weaken host-key checking to fix SSH auth failures.

## Phase 3A: audit archive before any extraction

The transport was independently verified by identical SHA-256 on mx2 and
venombox. A power outage interrupted a later command result; the actual
target archive already existed with its full expected length. Do not repeat
the transfer.

From the existing detached restore worktree on bp-controller:

    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-nextcloud-restore"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git switch --detach origin/feat/nextcloud-isolated-restore-701-20261019

    ansible-playbook       -i "$BASE/ansible/inventory.yml"       -i "$BASE/ansible/inventory.local.yml"       ansible/playbooks/audit-nextcloud-restore-archive-readonly.yml       --vault-id infra@prompt

The audit is **read-only** and requires stopped, protected and networkless
LXC 701. It rechecks exact pinned SHA-256, scans the entire gzip tar
catalog without extraction, rejects path traversal, duplicate entries,
special/device files, links or setuid/setgid files, checks required
Nextcloud files, and decompresses SQL within the tar stream to check gzip
integrity and target schema selection. It prints only safe counts and
boolean findings. It does not read secrets into Ansible-visible output.

Expected: NEXTCLOUD_RESTORE_ARCHIVE_READ_ONLY_VERIFIED, changed=0,
failed=0. If an archive link is detected, stop and review that archive
construct separately instead of permitting arbitrary extraction.

After success, independently inspect the offline guest base OS packages
before approving extraction or SQL import. The test guest must never share
a production MariaDB, mail endpoint or trusted Cloud hostname. No cleanup
of mx1 is authorized yet.


## TAR special-member classification after strict audit failure

The strict restore archive audit refused a member that is neither an
ordinary file nor a directory, reporting NON_REGULAR_ARCHIVE_MEMBER.
GNU tar can represent symlinks and hardlinks; neither can be blindly treated
as safe. The SHA-256 hash was checked independently against the NAS archive.

First classify the complete archive in a **read-only** fashion:

    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-nextcloud-restore"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git switch --detach origin/feat/nextcloud-isolated-restore-701-20261019

    ansible-playbook       -i "$BASE/ansible/inventory.yml"       -i "$BASE/ansible/inventory.local.yml"       ansible/playbooks/diagnose-nextcloud-restore-archive-types-readonly.yml       --vault-id infra@prompt

Successful diagnosis displays numeric counts of regular files, directories,
hardlinks, symlinks, FIFO/device records and other types. It also groups link
targets into inside-html, outside-html and absolute/unsupported categories.
No member names, account paths or link targets are printed.

The result NEXTCLOUD_ARCHIVE_TYPE_DIAGNOSTIC_READ_ONLY_COMPLETE is
**not** authorization to extract or import. Review the counts and target
safety first, then design a type-aware extraction process bound to the
isolated guest and explicitly reject unsafe records. Never extract the
backup directly into the PVE host filesystem.


## Phase 3C: strict safe-internal-symlink audit

Archive classification confirmed that all 162 non-regular members are symbolic
links; no hardlinks, devices or FIFOs, and none of the link targets directly
point outside html. The strict archive audit now permits only symbolic links
that resolve through every link hop inside the html namespace to existing
archived entries. It rejects escaping links, loops, dangling links, and any
archive member stored underneath a symlink. Resolution processes each
relative path component in filesystem order; it never collapses .. before
resolving an earlier symlink. No extraction occurs.

Run the existing read-only audit again after updating the restore worktree:

    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-nextcloud-restore"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git switch --detach origin/feat/nextcloud-isolated-restore-701-20261019

    ansible-playbook       -i "$BASE/ansible/inventory.yml"       -i "$BASE/ansible/inventory.local.yml"       ansible/playbooks/audit-nextcloud-restore-archive-readonly.yml       --vault-id infra@prompt

Expected on success:
NEXTCLOUD_RESTORE_ARCHIVE_READ_ONLY_VERIFIED
and verified_symbolic_link_count: 162, changed=0 and failed=0.

This only clears the integrity and path gate. Before any extraction,
prepare an independent, constrained, guest-only extraction procedure
without restoring production credentials/cron/network services.


## Phase 4A: offline Rocky 9 runtime inventory (no restore writes)

The pinned archive passed sha256, gzip SQL, manifest, entry-path and all
162 symlink chain checks on 19 October 2026:
NEXTCLOUD_RESTORE_ARCHIVE_READ_ONLY_VERIFIED, changed=0, failed=0.
The archive is not yet extracted. This is a prerequisite, not a functioning
recovery of Nextcloud.

Prepare one local, offline guest inventory. The existing protected VMID 701
has no network interface and host autostart disabled. Never attach a NIC just
to install RPM packages.

From bp-controller in the isolated worktree:

    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-nextcloud-restore"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git switch --detach origin/feat/nextcloud-isolated-restore-701-20261019

Default read-only preflight:

    ansible-playbook       -i "$BASE/ansible/inventory.yml"       -i "$BASE/ansible/inventory.local.yml"       ansible/playbooks/inspect-nextcloud-restore-701-offline-runtime.yml       --vault-id infra@prompt

Expected NEXTCLOUD_RESTORE_701_START_READ_ONLY_READY, changed=0 and
failed=0. The root-only archive must still have the expected byte count.

After explicitly approving a guest startup, run the same command with:
    -e nextcloud_restore_701_start=true

Only VMID 701 is started. Then pct exec obtains operating system and
bounded installed RPM status, verifying that only loopback exists. Expected:
NEXTCLOUD_RESTORE_701_OFFLINE_RUNTIME_INVENTORY_READY, changed=1, failed=0.
No RPM installation, SQL import, archive extraction, service activation
or production host changes are performed.

The startup playbook is intentionally single-use and requires the guest
to be stopped. After a successful approved boot, do not blindly rerun
this playbook: continue with a separate running-guest preflight.


## Phase 4B: guest started but initial package audit failed

The operator explicitly booted VMID 701. Proxmox confirmed it running,
but the immediately following pct-exec OS/network/package inventory
exited nonzero and was concealed by no_log. This does not invalidate the
already verified archive. DO NOT rerun the phase 4A start playbook, since
it demands a stopped guest and has a gated pct start.

Use the dedicated read-only running-guest diagnosis instead:

    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-nextcloud-restore"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git switch --detach origin/feat/nextcloud-isolated-restore-701-20261019

    ansible-playbook       -i "$BASE/ansible/inventory.yml"       -i "$BASE/ansible/inventory.local.yml"       ansible/playbooks/inspect-nextcloud-restore-701-running-readonly.yml       --vault-id infra@prompt

The separate playbook first verifies host, stopped-only guest's now
running state, guest config and no network device configuration. Then
it probes pct exec independently and reads guest OS, actual interface
count and installed RPM package statuses. All commands are read-only.
It prints sanitized execution return codes and allowlisted package
statuses, never raw guest stderr. It cannot restart the guest, install
packages, extract data, open networking or import a database.

Expected successful result:
NEXTCLOUD_RESTORE_701_RUNNING_OFFLINE_INVENTORY_VERIFIED,
changed=0, failed=0.

On failure, stop and inspect the sanitized diagnostic status. Do not
alter existing production hosts or reset the guest to bypass a failed
isolation assertion.


## Phase 4C: sysfs bonding_masters false interface corrected

On the already-running and networkless guest, the first runtime inventory
reported one non-loopback entry. The operator independently inspected the
actual network namespace and found only loopback, with 127.0.0.1/8 and
::1/128; there were no non-loopback addresses, interfaces, or external routes.

The false positive was a regular sysfs control file named bonding_masters
under /sys/class/net. That path is NOT a network interface. Both the
single-use boot playbook and the running-guest readonly inventory have
been corrected to count **only symlink netdevice entries** in that
directory, explicitly requiring the loopback device to be present.

No guest settings or network configuration were changed. Do not rerun
the guest boot playbook: VMID 701 is already running.

Run the running-guest read-only inventory playbook again after fetching
the updated restore branch. Expected:
NEXTCLOUD_RESTORE_701_RUNNING_OFFLINE_INVENTORY_VERIFIED
with NON_LOOPBACK_DEVICES=0, changed=0, failed=0.

The output so far shows Rocky Linux 9.4, Python3, OpenSSL and gzip
installed; PHP, MariaDB, nginx, httpd, tar and rsync are absent.
These software dependencies must be delivered using a separately
reviewed offline package installation plan. No NIC is permitted.


## Phase 5A: read-only offline RPM-source inventory

The already-running test guest passed the separate runtime audit:
Rocky Linux 9.4, zero non-loopback devices, working pct exec and rpm.
The verified recovery archive remains on the venombox host and is neither
extracted nor imported.

The guest has gzip, Python3 and OpenSSL, but lacks PHP, MariaDB,
nginx/httpd, tar and rsync. Before acquiring an RPM bundle, inspect
**exact installed package versions and sources** on the production
reference mx2 using strictly read-only queries (rpm -qa, /etc/yum.repos.d
section identifiers, /etc/dnf/modules.d enabled streams, php -m).
The inventory reads but never prints repository base URLs, credentials,
Nextcloud config.php or document paths. Cached RPM availability is
reported as count and aggregate bytes only.

From bp-controller in the existing restore worktree:

    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-nextcloud-restore"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git switch --detach origin/feat/nextcloud-isolated-restore-701-20261019

    ansible-playbook       -i "$BASE/ansible/inventory.yml"       -i "$BASE/ansible/inventory.local.yml"       ansible/playbooks/audit-nextcloud-restore-offline-package-sources.yml       -e @"$BASE/ansible/vars/mail-tls.local.yml"       -e @"$BASE/ansible/vars/mail-nextcloud-stack.local.yml"       --vault-id infra@prompt

Expected: NEXTCLOUD_RESTORE_OFFLINE_PACKAGE_INVENTORY_READY,
changed=0 and failed=0. Source mx2 and test guest 701 remain unchanged.

After reviewing version and provider metadata, design a separate offline
RPM bundle acquisition on a **non-production** machine with network
access. Do not attach a network interface to guest 701 or run package
downloads/updates on mx2. An RPM dependency closure and signature
verification must be established before anything is installed.

Do not copy production PHP configuration, credential files, mail settings
or LDAP/OIDC secrets into a guest that could be networked later. The
proven SHA-256 archive may itself contain production credentials; keep
the test guest permanently isolated and disable scheduled jobs, outgoing
notifications, background syncs, external services and login integrations
before any functional testing.


## Phase 5A accepted: reviewed RPM source/guest inventory (2026-10-19)

The operator provided the completed read-only package inventory from
Bergen-Mail. Ansible recap: localhost=2, venombox=7 and source=6 tasks;
changed=0, failed=0 on every host.

**mx2**: Rocky Linux 9.8, PHP 8.3.35 using Remi module
php:remi-8.3, MariaDB 10.11.18 using Rocky AppStream module
mariadb:10.11; Redis 6.2.24, installed nginx 1.20.1 and httpd 2.4.62.
Both webservers installed does NOT establish which serves Nextcloud.
Installed PHP extensions include intl, gd, ldap, imagick, mbstring,
bcmath, zip, redis, apcu, smbclient and mysqlnd.
Enabled repo IDs: appstream, baseos, crb, epel,
epel-cisco-openh264, extras, remi-modular, remi-safe, rspamd.
mx2 RPM cache has zero files.

**LXC 701**: Rocky Linux 9.4; enabled repos appstream, baseos,
extras; no enabled module streams. RPM, dnf, Python 3, gzip and
OpenSSL available. PHP, MariaDB, webservers, tar and rsync absent.
Guest RPM cache has zero files. Only loopback networking.

Version compatibility gate: The guest base release is 9.4 whereas
mx2 is 9.8. Supplying only PHP and MariaDB RPMs from 9.8 can create
inconsistent or missing dependency sets. A controlled, complete,
signed, offline 9.8 base-alignment transaction is necessary before
using the restored environment for meaningful functionality checks.

## Phase 5B design: networked non-production builder, offline guest

This is a **design only**: no downloads, installs, extraction, imports,
guest networking or production changes are authorized yet.

1. Establish a separate, disposable, networked non-production builder
   matching Rocky Linux 9.8 x86_64. Do not make mx2 the builder.
2. Verify actual webserver usage and required extensions read-only
   before choosing the minimal Nextcloud package set.
3. Configure trusted Rocky baseos/appstream/crb, EPEL and Remi with
   PHP stream remi-8.3 and MariaDB stream 10.11. Do not assume the
   exact archived RPM versions are still available; report missing
   NEVRAs instead of automatically substituting newer versions.
4. Resolve the **full** 9.4-to-9.8 offline RPM transaction, including
   RPM dependencies and module metadata. Verify upstream GPG signatures
   with independently trusted keys, and pin sha256 and NEVRA for each RPM.
5. Test the transaction in an expendable offline rehearsal environment.
   Check venombox staging free space and actual free capacity in the
   48 GiB guest rootfs before staging or installing anything.
6. After separate operator approval, stage an immutable root-only
   bundle on venombox. Pass packages into LXC 701 only by explicitly
   scoped Proxmox local copy operations. Keep VMID 701 with zero NICs.
7. Require an offline-only dnf transaction (all external repositories
   disabled) and package signature checks; re-check guest network
   before and after the installation. Do not enable cron, LDAP/OIDC,
   notification services or external storage.
8. Separately approve safe, guest-confined archive extraction,
   scrub external endpoints and production secrets before launching
   the app, import SQL into the guest-only DB and test Nextcloud
   via loopback. Keep both mx1 and mx2 unchanged throughout.

The source inventory lists only selected package prefixes, not
the full RPM dependency closure. The module/repo names alone do
not prove downloads or package compatibility.


## Alternative accepted for planning: Rocky Linux 9.8 LXC template on venombox

The operator's 2026-10-20 read-only PVE inventory established:

- PVE appliance templates advertised:
  rockylinux-9-default_20240912_amd64.tar.xz,
  rockylinux-10-default_20251001_amd64.tar.xz.
- The first (Rocky 9, older image) is already on the local template
  storage, 99.54 MB. There is no explicitly versioned 9.8 PVE template.
- local-zfs active; approx. 1.86 billion KiB reported available.
- Running unprivileged LXC 701 has onboot=0, protection=1,
  no configured netX, and only loopback. The sysfs
  bonding_masters entry is a control file, not an interface.
- IDs 702 and 790 appear absent from pct list, but must be rechecked
  against cluster and config inventory immediately before reservation.

A separate non-production Rocky 9.x unprivileged LXC **could** be
created from the existing PVE image on local-zfs. Allow network access
to **the disposable builder only**, with no imported backup or
production credentials. Rocky Linux supports in-major upgrades from
9.x to 9.8 using dnf upgrade. Require a read-only review of the
Proxmox bridge/VLAN, reachable trusted Rocky repositories, OS release,
signature verification policy and adequate disk space before allowing
the upgrade. Do not attach any NIC to LXC 701.

After controlled upgrade, reboot and verify /etc/os-release, rpm
database and package signatures. Remove build credentials, machine
identity, SSH host keys if any, system logs and cached networking
state; then shut down the builder and remove its PVE netX settings
before converting the guest to an immutable named versioned PVE
template. Ensure clones cannot accidentally inherit a route or
network adapter.

An optional second stage can build a **separate, clean Nextcloud
runtime template** from the Rocky 9.8 base, install Remi PHP 8.3
and AppStream MariaDB 10.11 plus required extensions (as pinned /
confirmed available), using dnf dependency resolution **while the
builder is networked**, then sanitize and remove its network
configuration before templating. Never copy Nextcloud archives,
config.php, SQL dump, LDAP credentials or other production secrets
into a connected build container.

A fresh networkless LXC cloned from the fully provisioned runtime
template could serve as an isolated restore guest. **A template
does not upgrade existing LXC 701**; using another VMID such as 702
requires a separately approved amendment to the current 701-locked
playbooks and restore runbook. Never delete, replace, reset or
reconfigure the protected 701 as a shortcut. The previously staged,
SHA-verified backup on venombox may be reused only after new guest
identity, protection, mounts, hash and network gating are explicitly
revalidated.

No commands in this section have been run; no PVE resources or
production systems have been changed. Begin with read-only network
topology and free VMID checks; require explicit operator approval
before any build-guest creation or template conversion.


## Phase 5C: read-only template builder preflight on venombox

A fresh manual inspection on 2026-10-20 confirmed PVE
pve-manager/9.2.20 (kernel 7.0.14-19-pve), candidate VMIDs 702,
790 and 791 absent, and controller CT100 attached to vmbr2 with
firewall=1 and DHCP. Local Rocky 9 PVE template already present.
The vmbr2 UP state is **not** proof of authorized internet egress,
DNS access or the expected VLAN/firewall policy.

After fetching this branch on the existing bp-controller detached
worktree, execute **only** the standalone read-only preflight:

    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-nextcloud-restore"
    git fetch origin feat/nextcloud-isolated-restore-701-20261019
    git switch --detach origin/feat/nextcloud-isolated-restore-701-20261019
    ansible-playbook \
      -i "$BASE/ansible/inventory.yml" \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/audit-rocky-9-lxc-template-builder-readonly.yml

The preflight verifies the exact PVE host, cluster-wide free IDs,
existing local template and SHA-256, vmbr2 presence, CT100's
existing bridge and firewall flag, CT701's continued protection and
networklessness, local and local-zfs active and ZFS pool health.
It does not authorize network egress or mutate any host/guest.
Expected: ROCKY_9_8_LXC_TEMPLATE_BUILDER_READ_ONLY_READY,
changed=0, failed=0.

Only after separate approval and an exact reviewed network policy
should an **independent** disposable LXC 790 be created as a
networked Rocky 9-to-9.8 builder. Never run builder commands on 701.


## VM bridge and firewall policy evidence (2026-10-20)

Direct read-only operator output on venombox:

- vmbr2: inet dhcp; physical bridge port enp195s0.2 (802.1q
  subinterface), bridge-vlan-aware yes, bridge-vids 2.
- 'bridge vlan show dev vmbr2' reports PVID 1 untagged for the
  bridge interface itself. This does not negate the VLAN 2
  encapsulation of the physical enp195s0.2 uplink.
- '/cluster/firewall/options' and '/nodes/venombox/firewall/options'
  each reported only a digest; no explicit enable flag in those
  responses.
- No '/etc/pve/firewall/100.fw' was present.
- CT100 net0 has bridge=vmbr2 and firewall=1, but this setting
  does **not** prove that packet filtering is actually active or that
  the upstream UniFi policy restricts inter-VLAN/internal access.

**Network security gate still OPEN / BUILD APPLY NOT APPROVED.**
Do not attach the planned Rocky 9.8 build guest 790 to vmbr2
merely because CT100 uses it. Prefer a disposable, egress-only build
VLAN/network with DNS, HTTPS and signed RPM repositories accessible
but no unnecessary access to internal or production servers. Confirm
Proxmox firewall daemon/policy and upstream UniFi isolation. A
transient or permanent builder NIC must not be inherited into the
networkless runtime template or restore candidate.

The existence of the bridge, free VMIDs and a successful SHA-256
inventory establishes technical feasibility, **not** authorization
of outbound or lateral network traffic.


## Follow-up network review, 2026-10-20 (read-only evidence)

The operator ran the exact requested checks directly on venombox.
The bridge stanza for vmbr0 is "inet dhcp" with physical
"bridge-ports enp195s0". Previously established vmbr2 is on
enp195s0.2 with VLAN 2. The grep command produced no matching
iface entries for vmbr3 or vmbr6 in the main
/etc/network/interfaces file; their configuration and topology
remain unverified (the PVE configuration sources the interfaces.d
directory).

The legacy Proxmox firewall CLI reported
"pve-firewall status: disabled/running". Cluster and node firewall
rules both returned [] and CT100 has no /etc/pve/firewall/100.fw.
These results establish **no effective PVE classic firewall
enforcement for this candidate network**, but they do not exclude
the alternative nftables-based proxmox-firewall daemon or
upstream UniFi firewall rules. No egress/isolation guarantee
is established.

Before attaching network to an untrusted or disposable builder,
read-only verify nftables backend, host policies and bridge topology:

    systemctl is-active proxmox-firewall || true
    systemctl is-enabled proxmox-firewall || true
    systemctl is-active pve-firewall || true
    if command -v nft >/dev/null; then
      nft list tables
    fi
    grep -R -H -E '^(auto |iface |[[:space:]]*bridge-ports|[[:space:]]*bridge-vlan-aware|[[:space:]]*bridge-vids)' /etc/network/interfaces /etc/network/interfaces.d 2>/dev/null

Neither an active service alone nor absence of PVE rules proves
the upstream UniFi segmentation policy. Review upstream router
rules before enabling a builder NIC. Do not expose CT701 or a
restore archive to the build network. Never change host-wide
firewall configuration during the restore project without a
separately planned change window; such a change could affect
production LXC workloads.


## Alternative to any connected PVE build guest: vetted LXC rootfs

Additional host evidence (2026-10-20):
- systemctl is-active proxmox-firewall: active.
- systemctl is-enabled proxmox-firewall: enabled.
- nft list tables: no tables printed in that command output.
  A running service **does not establish installed nft filter rules**.
  Do not assume that a classic pve-firewall status of disabled/running
  proves nftables disabled; both observations must be retained.
- The main interface configuration has vmbr0 -> enp195s0 untagged,
  vmbr2 -> enp195s0.2 VLAN 2 (DHCP and vlan-aware),
  vmbr3 -> enp195s0.3 (inet manual) and
  vmbr6 -> enp195s0.6 (inet manual).
  There is no demonstrated safe temporary egress-only build segment.
- No host-wide firewall change is approved.

An external, separately tested LXC-ready Rocky Linux 9 amd64
"default" rootfs.tar.xz is available at
https://images.linuxcontainers.org/images/rockylinux/9/amd64/default/
(recent distro-builder builds; public index includes compatibility
for unprivileged LXC). The selected build directory includes
SHA256SUMS and its SHA256SUMS.asc signature, plus individual
rootfs.tar.xz.asc. The rootfs build reports only "9" in the public
catalog; **confirm actual minor version as 9.8 by inspecting the
archive's etc/os-release or etc/rocky-release, and later a booted
guest, before publishing it as 9.8**. Unlike Rocky's independently
published OCI image, this is a third-party LXC artifact and needs
verified, independently trusted distributor signing keys.

This makes it possible to acquire a root filesystem with the
already-networked bp-controller and transfer it to the local PVE
template cache with pinned hash and secure copy, without attaching
a network adapter to a new build CT. Merely reading the public image
index and verifying the source metadata is the next approved
**read-only** step; downloads, staging, VMID allocation, guest
creation, etc. still require separate, explicit approval and
fail-closed playbooks. Review the image license/source, rootfs type,
path safety, metadata, signature, file ownership and its boot
compatibility in a disposable unprivileged networkless test CT
prior to converting CT790 to a cloneable template.

An already-available local PVE stock Rocky 9 archive remains the
fallback if the alternative rootfs cannot pass validation. This
does NOT eliminate the later need for a separately validated
PHP/MariaDB RPM dependency supply chain to build the Nextcloud
runtime template. Keep CT701 protected, with no NIC and without
modifications; do not make a downloaded image part of its rootfs.


## Candidate Rocky 9 amd64 LXC rootfs, HTTP-only evidence (2026-10-20)

The operator checked the *specific, time-pinned* public URL
https://images.linuxcontainers.org/images/rockylinux/9/amd64/default/20261018_03:16

On bp-controller, curl HEAD followed a redirect and returned HTTP 200
for rootfs.tar.xz; Content-Length=107425612 bytes. The published
SHA256SUMS names rootfs.tar.xz with digest:

    1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5

SHA256SUMS.asc HEAD also returned 200; Content-Length=833.
**This does not yet establish authenticity, actual downloaded
archive integrity, release minor version, or Proxmox suitability.**
No rootfs download, VMID allocation or guest changes have been
reported. The Linux Containers image service warns that past
builds are retained briefly, so pinning the exact archival bytes
matters. The service publishes unofficial Linux distribution images
built with distrobuilder.

Next read-only gate on the already-networked bp-controller:
fetch only small upstream SHA256SUMS, SHA256SUMS.asc,
image.yaml (if available) and build.log (if available)
into a restricted scratch directory, identify the signing key
fingerprint from the signature *without treating it as trusted*,
then compare the signer against independently authenticated
Linux Containers project material. Never auto-import a key
obtained solely from the same image host and declare success.
Download rootfs.tar.xz only with deliberate approval, then
verify its digest against the signed checksum manifest before
inspecting tar member types and the embedded OS release marker.
Do not extract an unverified tar as root or import it into PVE.
Production mx1/mx2 and guest 701 remain unchanged.


## Rocky 9.8 rootfs downloaded to bp-controller (2026-10-20)

The operator downloaded the three files SHA256SUMS,
SHA256SUMS.asc and rootfs.tar.xz from the exact pinned
20261018_03:16 linuxcontainers.org image path into a
mode-0700 staging directory on bp-controller:

    /home/ansible/rocky9-lxc-20261018/

The real local rootfs.tar.xz passed independent
sha256sum -c against the previously recorded SHA-256:

    1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5

Read-only tar inspection confirmed an embedded regular
etc/rocky-release file, with contents
"Rocky Linux release 9.8 (Blue Onyx)", and
usr/lib/os-release with ID=rocky and VERSION_ID=9.8.
etc/os-release is a symlink to ../usr/lib/os-release.

The GPG packet inspection command returned **no matching lines**,
which cannot be considered successful signature verification.
Investigate signature encoding, local gpg availability and
independently authenticated issuer key. Verify detached
SHA256SUMS.asc over exact SHA256SUMS after approving the
independent issuer fingerprint. Do not silently accept a key
obtained from the same image server.

No import to PVE, root filesystem extraction, guest creation or
modification to protected CT701 is authorized yet. Before any
rootfs consumption as root, audit all tar entry paths, symlink
chains, hardlinks, special node types and ownership/permissions;
use an approved, disposable networkless guest boot test.


## LXC image signing key provenance and missing local verification tool

On 2026-10-20 the operator reported on bp-controller that
`gpg` and `gpgv` are not installed. The local downloaded
`SHA256SUMS.asc` was identified by `file` as an OpenPGP
signature (armored PGP signature). The previously empty
`gpg --list-packets` filtered output was caused by the missing
command, **not** proof of a broken signature.

The independently published Linux Containers community discussions
identify the historic image-signing key as:

    E7FB0CAEC8173D669066514CBAEFF88C22F6E216
    LXC pre-built images <lxc-devel@lists.linuxcontainers.org>

External cross-references:
https://discuss.linuxcontainers.org/t/3-0-unable-to-fetch-gpg-key-from-keyserver/2015
https://discuss.linuxcontainers.org/t/invalid-gpg-signature-on-index-file-of-downloadable-images/12330

These are prior attestations for the image-signing key, **not**
successful verification of this October 2026 SHA256SUMS signature.
The operator should install GnuPG on the **non-production controller
only if approved**, use a new isolated GnuPG home, download the public
key from an independent key distribution service such as
keyserver.ubuntu.com, match its **entire** fingerprint to the value
above, import it only into that isolated keyring, and demand a
successful detached signature verification of local SHA256SUMS.asc
over local SHA256SUMS with exactly this fingerprint before considering
the archive authenticated. Reject any mismatch or unverifiable key;
never add a key to a global trusted system keyring or waive signature
verification. Retain separate archive SHA256 verification.

No template import, rootfs extraction, guest network, package
installation in CT701, or mx2/mx1 operation follows from this
key-discovery result.


## GnuPG installation via existing controller IaC, not ad-hoc apt

The existing controller OS is Debian 13 and was bootstrapped using
ansible/playbooks/bootstrap-controller.yml. That playbook's
controller_packages list has been extended with gnupg, gpgv and
file, all installed via ansible.builtin.apt state=present.
Its existing apt-cache refresh and package task, plus narrowly
scoped Debian 13/bp-controller assertions and a post-install
binary stat check, now carry the tag "controller_packages".
This is **deliberately not a full controller re-bootstrap**:
other tasks in the original playbook also manage authorized SSH
keys, sudoers, venv and Galaxy collections; never accidentally
rerun those merely to add GnuPG.

From bp-controller in the existing restore worktree (whose branch
contains the updated controller baseline), first check that the
worktree is clean, then fetch and detach the current head:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BR="feat/nextcloud-isolated-restore-701-20261019"
    test -z "$(git -C "$WT" status --porcelain)"
    git -C "$BASE" fetch origin "$BR"
    git -C "$WT" switch --detach "origin/$BR"

Only bp-controller should be targeted, via explicit local connection;
the production hosts mx1 and mx2 and Proxmox guest 701 are out of
scope. Exact audit/installation command:

    "$BASE/.venv/bin/ansible-playbook" \
      -i "$BASE/ansible/inventory.yml" \
      -i "$BASE/ansible/inventory.local.yml" \
      "$WT/ansible/playbooks/bootstrap-controller.yml" \
      --limit bp-controller \
      --tags controller_packages \
      -e ansible_connection=local \
      --vault-id infra@prompt \
      --check --diff

Inspect the results. Repeat the exact command **without** --check
--diff only on explicit operator authorization for controller package
changes; afterwards rerun again to verify convergence.
Note apt update_cache can report changed when cache is stale;
the meaningful idempotence gate is that package installation
reports changed=0 on the second apply.

The tagged run cannot create an LXC, attach guest networking, touch
the Nextcloud archives or alter production Nextcloud/mx2.
After installation require command -v gpg, gpgv and file to work,
then resume signature verification using the isolated keyring
with a separately verified image-signing key fingerprint.


## bp-controller package baseline proof (2026-10-20)

The operator executed the existing controller's Ansible package-only
bootstrap, targeting bp-controller with tag controller_packages,
after an Ansible --check run predicted installation of 17 packages
(0 upgrades, 0 removals). An observed subsequent real run
reported:

    PLAY RECAP bp-controller: ok=6 changed=0 unreachable=0 failed=0

The package version inventory was already converged by this
observed execution: the apt package task was `ok`, and post-install
stat checks passed for `/usr/bin/gpg`, `/usr/bin/gpgv`,
`/usr/bin/file`. The operator independently confirmed binaries
via `command -v`, and `gpg --version` reported GnuPG 2.4.7
(libgcrypt 1.11.0). As that run had changed=0, **do not
infer that it itself installed packages**; it confirms their
presence and that the IaC package baseline is idempotent.

Next step is the local, independent OpenPGP signature check,
with an isolated restrictive GnuPG home, a full
`E7FB0CAEC8173D669066514CBAEFF88C22F6E216` primary signer
fingerprint pinned from an external Linux Containers community
source, `gpg --verify SHA256SUMS.asc SHA256SUMS`, and a repeat
rootfs SHA256 comparison. No production guest/network/host
modification is involved.


## Signed Rocky 9.8 image VERIFIED (2026-10-20)

The operator's local GnuPG run on bp-controller succeeded against
the exact downloaded detached signature and checksum text:

- GOODSIG and VALIDSIG for independently pinned signing key
  `E7FB0CAEC8173D669066514CBAEFF88C22F6E216`.
- Signer: `LXC pre-built images <lxc-devel@lists.linuxcontainers.org>`.
- Signature creation: 2026-10-18 19:10:03 UTC.
- The literal checksum line for rootfs.tar.xz matched pinned digest
  `1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5`.
- `sha256sum -c` on local rootfs returned `OK`.
- End-of-proof marker:
  `ROCKY_9_8_IMAGE_SIGNATURE_AND_SHA256_VERIFIED`.

GnuPG printed TRUST_UNDEFINED because the key was imported only
into an isolated keyring without Web-of-Trust certifications.
That is normal for an intentionally narrow trust root, and is
**distinct from a failed detached signature**. Trust is supplied
by the independently checked full key fingerprint; the end-to-end
signature check succeeded. Do not confuse a good signature with a
security assessment of every file or symlink in an external rootfs.

### Subsequent archive-structure audit, no container creation

The repository now includes two independent, no-write components:
`ansible/files/nextcloud/audit_rocky_lxc_rootfs.py` and
`ansible/playbooks/audit-rocky-9-lxc-rootfs-readonly.yml`.
The former refuses execution as root or on an unexpected host;
opens the exact archive read-only with O_NOFOLLOW, checks exact
size and pinned SHA256, streams every xz-tar entry without
extraction, checks relative paths and unsafe traversal, duplicate
names, release markers, tar type classifications, symlink chains,
dangling or escaping symbolic links, and counts privileged-mode
files. It refuses hardlinks, device nodes, FIFOs, unknown records,
and archive members underneath symlink prefixes. It reports
counts and a bounded result with no member names. The latter
runs on bp-controller, connection=local, become=false, changed=0.

To invoke from the controller's isolated restore worktree:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BR="feat/nextcloud-isolated-restore-701-20261019"
    test -z "$(git -C "$WT" status --porcelain)"
    git -C "$BASE" fetch origin "$BR"
    git -C "$WT" switch --detach "origin/$BR"
    "$BASE/.venv/bin/ansible-playbook" \
      -i "$BASE/ansible/inventory.yml" \
      -i "$BASE/ansible/inventory.local.yml" \
      "$WT/ansible/playbooks/audit-rocky-9-lxc-rootfs-readonly.yml" \
      --limit bp-controller \
      --vault-id infra@prompt

Expected if all safety criteria are met:
`ROCKY_LXC_ROOTFS_STRUCTURAL_AUDIT_PASS`, changed=0.
If the signed distribution includes an unsupported archive type
or incompatible symlink, the audit **must block**; that is a
review gate, not a reason to auto-bypass it. Only then decide
whether a constrained, disconnected disposable PVE guest can
be built. No template or other VMID is created in this phase.


## Rocky 9.8 rootfs: dangling symbolic-link diagnosis (20 Oct 2026)

The pinned 107425612-byte rootfs tar.xz passed its SHA-256 check, but the
full structural audit still blocks on `DANGLING_SYMLINK`. Earlier
classification measured 11408 regular files, 2901 directories, 1603
hardlinks to earlier regular files, 2151 symbolic links (59 absolute), and
one regular file containing a Linux-literal backslash in its name.
No devices/FIFOs or archive extraction were observed.

This is **not** an import failure to work around by disabling symlink
checks. A missing archived target can be an ordinary broken link, an
alternative installed only in another environment, or a path materialized
when proc/sys/dev/run is mounted inside an actual guest. Do not infer which
one applies from the previous error alone.

A separate diagnostic reads the *same* pinned archive on bp-controller as
unprivileged user ansible, checks SHA-256/size before parsing, applies
O_NOFOLLOW and an unchanged-file check, and outputs **only** aggregate
counts of resolved, implicit-directory, root-target, dangling, looping or
escaping symlinks. Dangling targets are categorized into fixed broad
rootfs tree classes, without exposing names or link targets. CI runs
synthetic tests for expected, missing, runtime and adversarial targets.

From the existing detached restore worktree, first fetch and switch to the
current reviewed feature branch; refuse dirty worktrees:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BRANCH="feat/nextcloud-isolated-restore-701-20261019"
    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
      echo "STOP: worktree contains local changes"
    else
      git -C "$WT" fetch origin "$BRANCH" &&
      git -C "$WT" switch --detach "origin/$BRANCH" &&
      "$BASE/.venv/bin/ansible-playbook" \
        -i "$BASE/ansible/inventory.yml" \
        -i "$BASE/ansible/inventory.local.yml" \
        "$WT/ansible/playbooks/diagnose-rocky-9-lxc-rootfs-symlinks-readonly.yml" \
        --limit bp-controller --vault-id infra@prompt
    fi

The conditional ensures that a failed fetch or refused worktree switch
also prevents invoking an older diagnostic.

Expected: `ROCKY_LXC_ROOTFS_SYMLINK_DIAGNOSTIC_COMPLETE`,
`changed=0`, `archive_extracted=false`, `ct701_changed=false`, and
`import_gate=BLOCKED_PENDING_STRUCTURAL_AUDIT`. The diagnosis is *not*
`ROCKY_LXC_ROOTFS_STRUCTURAL_AUDIT_PASS` and does not authorize import,
creation, extraction, changing network configuration, modifying CT 701,
or removal of mx1. Only after reviewing the actual missing-target
classification may the structural auditor and the separate guest-confined
import design be reconsidered.

## Rocky 9.8 rootfs: seven reviewed missing link targets (20 Oct 2026)

The unprivileged, SHA256-confirmed graph inspection found exactly seven
unresolved symlinks in the signed, size-pinned Rocky 9.8 rootfs:

- `etc/mtab -> ../proc/self/mounts`: the procfs mount table appears only
  when the container runtime mounts procfs.
- `etc/systemd/system/systemd-firstboot.service -> /dev/null`:
  conventional systemd unit masking; the device node belongs to the
  container's device filesystem.
- `var/lock -> ../run/lock`: a runtime directory.
- Four entries beneath `usr/lib/.build-id/` refer to absent
  `usr/sbin/tc`, two ncurses++ sonames and `usr/bin/coreutils.single`.
  These are build-ID bookkeeping links, **not evidence that these binaries
  are installed**. Their RPM ownership and runtime necessity must be
  evaluated separately before assembling a Nextcloud runtime.

The rootfs structural gate now accepts only these seven exact
`(symlink name, original link target, resolved rootfs target)` triples.
The exception is available only after verifying the one pinned 107425612-byte
archive's SHA256. A change of names, destinations, unresolved counts, or
unexpected missing link is rejected. All seven are required by the pinned
real-archive audit, and tests reject unknown runtime links, arbitrary
`.build-id` links and substituted targets. Device nodes, FIFO records,
duplicate/traversing TAR members, hardlink escapes and symlink loops
remain prohibited.

Re-run `ansible/playbooks/audit-rocky-9-lxc-rootfs-readonly.yml`
on `bp-controller` using the guarded fetch-and-switch instructions in the
previous section. Success requires exactly 3 pinned runtime-link exceptions
and 4 pinned build-ID exceptions, a SHA256 pass, and `changed=0`.

**A successful structural audit is NOT import authorization.**
`template_import_authorized=false` and `guest_restore_authorized=false`
are explicitly asserted. Separately inspect the offline template-builder
and plan a Proxmox-safe guest-confined importer; never extract this archive
onto the controller or PVE host root. Keep CT 701, mx1 and mx2 unchanged.

## Rocky 9.8 rootfs structural PASS and privileged-bit review gate

On 2026-10-20 the operator ran the pinned, signed Rocky 9.8 rootfs structural
audit on bp-controller with `changed=0 failed=0`. Recorded metrics:
11,408 regular files; 2,900 non-root directories plus root marker;
1,603 validated hardlinks; 2,151 symlinks including 59 absolute;
exactly 3 pinned runtime-target exemptions and 4 pinned .build-id exemptions;
one regular filename containing a literal Linux backslash;
and **14 regular files carrying SUID/SGID bits**. No extraction or
CT701 changes. Both `template_import_authorized` and
`guest_restore_authorized` remained false.

The next **read-only** gate inventories only those fourteen system files,
without printing their contents, touching the Proxmox host or altering
the signed archive. It independently rehashes the pinned archive in one
`O_NOFOLLOW` descriptor, reruns the rootfs structural checks, counts
privileged modes and prints at most 14 path/mode/UID/GID records for
operator review. This is intended to identify unexpected world-writable,
root-owned, or SUID/SGID binaries, not to approve execution.

On bp-controller as `ansible`:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BRANCH="feat/nextcloud-isolated-restore-701-20261019"
    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
      echo "STOP: worktree contains local changes"
    else
      git -C "$WT" fetch origin "$BRANCH" &&
      git -C "$WT" switch --detach "origin/$BRANCH" &&
      "$BASE/.venv/bin/ansible-playbook" \
        -i "$BASE/ansible/inventory.yml" \
        -i "$BASE/ansible/inventory.local.yml" \
        "$WT/ansible/playbooks/audit-rocky-9-lxc-rootfs-privileged-modes-readonly.yml" \
        --limit bp-controller --vault-id infra@prompt
    fi

Required diagnostic result:
`ROCKY_ROOTFS_PRIVILEGED_MODE_REVIEW_REQUIRED`, `changed=0`,
`privileged_file_count=14`, and no import approval. Human review
must follow; a list of SUID/SGID files is not proof of exploitation.

### Separate offline import design (no apply implementation yet)

1. Keep the previously verified signed rootfs read-only on bp-controller.
   Explicitly authorize a transport phase only after rechecking
   `venombox` identity, cluster-wide VMID availability, current
   `local` template storage, `local-zfs` capacity, ZFS health,
   destination path and the exact source SHA256. Never use production
   mx1/mx2 hosts as import builders.
2. Stage in a private root-only *file* on the PVE node, under a
   non-overwriting destination and with full post-transfer SHA256
   verification. Do not extract to a PVE host directory or bind it into
   a running guest. Do not infer validity from only file size or filename.
3. Review PVE 9 `pct create` unpack behavior for the exact signed
   archive, the unprivileged UID/GID map, xattrs/capabilities, the
   14 privileged modes, symlink semantics and cleanup on partial
   create. Establish an explicit rollback/recovery plan before any
   PVE operation with write effects.
4. Only on *separate explicit approval* consider a newly allocated,
   stopped, unprivileged, protected and networkless disposable base
   guest **790** from the verified PVE-local archive. Recheck 790
   cluster-wide immediately before creation. PVE-managed unpack
   is preferable to a host-root `tar -x`, but not automatically safe;
   no actual `pct create` command is approved by this document.
5. Keep **701** as the existing protected isolated restore test,
   **791** as a separately approved future Nextcloud runtime template,
   and **702** as a separately approved future restore candidate.
   Do not change, overwrite, upgrade or network CT701 implicitly.
6. After isolated guest creation under a later apply gate, verify
   zero NICs, stopped state, unprivileged mapping, filesystem metadata,
   package database coherence, and safe boot under separate review.
   Avoid importing live Nextcloud data or any production credentials.
7. A structural PASS and SUID inventory do **not** grant a template,
   package-installation, guest-start, SQL-restore, production DNS,
   or mx1 decommission authorization.

Prior to a mutable phase, check the precise PVE host and storage
configuration live; previous inventories can become stale.


### Privileged-bit audit result and next read-only builder preflight

Operator log on 2026-10-20 confirms the dedicated privilege inventory
completed: bp-controller `ok=6 changed=0 unreachable=0 failed=0`,
`privileged_file_count=14`, `setuid_count=11`, `setgid_count=3`,
`world_writable_privileged_count=0`, SHA256 verified and structural
audit passed. Both `template_imported` and
`template_import_authorized` remain false. The shared log excerpt
contains the final six file records, not all 14; do not claim the
remaining eight file paths individually reviewed. The Ansible gate
now also asserts the observed counts and that none of the privileged
regular files is world-writable.

The next existing strictly read-only planning gate is
`ansible/playbooks/audit-rocky-9-lxc-template-builder-readonly.yml`
against `venombox`. It checks the PVE major, cluster VMID
availability for 702/790/791, current source PVE template checksum,
bridge `vmbr2` state and controller reference, storage and ZFS health,
and that CT701 remains protected without any configured NIC.
`network_egress_authorized: false` remains a design result;
the preflight does not authorize connecting a builder to production
networks or creating a container.

The separate SHA256-pinned Linux Containers rootfs archive on
bp-controller is **not** the same artifact as the older PVE-local
Rocky 9 template checked by this builder preflight. A clean
PVE-managed import path, verified staging transfer, signature and
hash provenance, and PVE template acceptance/metadata semantics
must be independently established before any guest creation.


## Rocky 9.8: successful builder preflight and direct signed-image staging gate

On 2026-10-20 the operator re-ran the Rocky builder feasibility
playbook on venombox with non-multiplexed SSH and the correct Vault ID,
and observed `ROCKY_9_8_LXC_TEMPLATE_BUILDER_READ_ONLY_READY`,
`ok=18 changed=0 failed=0 unreachable=0`. The host was Proxmox VE
9.2.20; cluster VMIDs 702/790/791 were unused at check time; local
template and local-zfs storage were active, pools healthy, vmbr2 was
up, and existing CT701 remained protected and networkless. No guest
was created or changed. `network_egress_authorized=false`
and `network_rules_reviewed=false`.

The preflight tested the *older* Rocky 9 locally on the PVE host,
SHA256 `1388b51286e88639f63a5ac8440f838b65ff84d23b9b8f0b69ce03b54a91db70`.
That is NOT the separate, previously signature-checked Rocky 9.8
Linux Containers rootfs, SHA256
`1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5`.

Before connecting any builder to vmbr2, check a direct staging path
for the signed Rocky 9.8 tar.xz. Proxmox system container images are
compressed rootfs TAR archives that `pct create` can consume via a
`local:vztmpl/...` storage volume, but this fact does not prove this
specific archive is safely importable or that all ownership, xattrs
and systemd behavior will survive extraction. Documentation:
https://github.com/proxmox/pve-docs/blob/master/pct.adoc

A new controller/venombox **read-only** staging preflight checks:
- Source: exact SHA256/size, full link/path audit, SUID/SGID count,
  fixed Rocky 9.8 release and `template_import_authorized=false`.
- Destination: exact Proxmox host and 9.x version, currently free
  VMIDs 702/790/791, absent target filename and absent local VMID
  790 configurations, root-owned real template cache directories,
  adequate free staging capacity, active local/local-zfs and healthy ZFS.
- Isolation: existing CT701 remains unprivileged, protected, onboot=0,
  with zero configured NICs; no bridge rule, interface or egress is
  modified by this playbook.

Proposed **future** PVE-local staging path:
`local:vztmpl/rockylinux-9.8-lxc_20261018_amd64.tar.xz`.
The preflight does not copy, extract, create guests, or authorize an
apply operation. VMID 790 would be a future isolated base CT until
`pct template 790` is separately authorized; 791/702 are only
reserved candidate numbers in the architecture, not actual PVE
reservations.

On bp-controller, in the existing detached restore worktree:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BRANCH="feat/nextcloud-isolated-restore-701-20261019"
    SSH_ARGS="-C -o ControlMaster=no -o ControlPath=none -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=2"
    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
      echo "STOP: worktree contains local changes"
    else
      git -C "$WT" fetch origin "$BRANCH" &&
      git -C "$WT" switch --detach "origin/$BRANCH" &&
      ANSIBLE_SSH_ARGS="$SSH_ARGS" "$BASE/.venv/bin/ansible-playbook" \
        -i "$BASE/ansible/inventory.yml" \
        -i "$BASE/ansible/inventory.local.yml" \
        "$WT/ansible/playbooks/audit-rocky-9-8-direct-import-staging-readonly.yml" \
        --vault-id infra@prompt
    fi

Expected on successful current-state checks:
`ROCKY_9_8_DIRECT_TEMPLATE_STAGING_READ_ONLY_READY`,
`changed=0 failed=0`, no guest or archive copy.
The next gate is an authenticated, size- and SHA256-pinned,
strictly non-overwriting file transport from bp-controller to venombox
with post-transfer verification and explicit user approval for any
write. **Do not** stage/import the archive or call `pct create`
based on this read-only preflight alone.

Direct Rocky 9.8 boot might avoid enabling outbound networking
just to update Rocky 9.4 to 9.8. Future Nextcloud runtime PHP/RPM
dependency acquisition still requires its own separate, approved
offline supply-chain process.


## Rocky 9.8 staging transport: protected no-overwrite gate

The operator's direct staging read-only preflight on 2026-10-20 completed
with **bp-controller ok=5** and **venombox ok=22**, both changed=0,
failed=0 and unreachable=0. It reverified the signed, SHA256-pinned
Rocky 9.8 rootfs and all destination conditions; no file was
transferred, no guest created and CT701 remained unchanged. The
expected source archive is 107425612 bytes with SHA256
`1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5`.

The new `ansible/playbooks/stage-rocky-9-8-lxc-rootfs.yml` imports
the **entire** two-host read-only preflight on every invocation.
Its default is **read-only**. Only an explicit, separately authorized
`rocky_rootfs_staging_apply=true` may copy the source into a new
root-only `.part` file, verify exact SHA256 and byte count again
on venombox, and publish by an atomic hardlink creation that cannot
replace an existing destination. The final SHA256 is independently
verified via Ansible stat. This operation only places the file in
`/var/lib/vz/template/cache/`, never extracts it or calls `pct create`.
The updated source preflight also rejects an existing partial file,
and requires the local Proxmox storage to advertise `vztmpl`
template content.

**Run now WITHOUT an apply flag** on bp-controller:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BRANCH="feat/nextcloud-isolated-restore-701-20261019"
    SSH_ARGS="-C -o ControlMaster=no -o ControlPath=none -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=2"
    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
      echo "STOP: dirty worktree"
    else
      git -C "$WT" fetch origin "$BRANCH" &&
      git -C "$WT" switch --detach "origin/$BRANCH" &&
      ANSIBLE_SSH_ARGS="$SSH_ARGS" "$BASE/.venv/bin/ansible-playbook" \
        -i "$BASE/ansible/inventory.yml" \
        -i "$BASE/ansible/inventory.local.yml" \
        "$WT/ansible/playbooks/stage-rocky-9-8-lxc-rootfs.yml" \
        --vault-id infra@prompt
    fi

Expected: `ROCKY_9_8_ROOTFS_STAGING_READ_ONLY_READY`,
`changed=0 failed=0`. No transfer takes place. The operator must
personally review results before any separate apply approval. Do not
run with the apply flag based solely on this documentation.

If a later approved transfer fails after the temporary file was
created, **do not rerun with an apply flag** blindly. The partial file
must be examined and any cleanup explicitly approved. If the final
filename already exists, do not overwrite it or use the original
preflight as a receipt; use a separately reviewed, read-only SHA256
and ownership audit to establish whether the stage completed.

Neither a successful file transfer nor rootfs structural PASS
authorizes a PVE guest create, import, start, network connection,
package download, Nextcloud SQL restore or production mx1 cleanup.
The source archive is distinct from the older PVE Rocky 9 image.


### Proxmox storage capability API fix (2026-10-20)

The first default-no-write staging workflow reached its venombox PVE
storage-capability check, then blocked at an invalid CLI invocation,
`pvesm config local`, returning rc=255
(`ERROR: unknown command 'pvesm config'`). Controller/source audit
succeeded; target preflight remained incomplete. The run reported
bp-controller ok=5 changed=0 and venombox ok=16 changed=0 failed=1.
No files transferred, guests created, or network settings changed.

Proxmox VE 9.2 exposes configured datacenter storages through the
documented `pvesh get /storage --output-format json` read-only API.
The IaC now selects exactly one storage id `local` from JSON and
demands directory type `dir`, expected path `/var/lib/vz`,
`vztmpl` in the comma-delimited content list, not disabled, and
either no node restriction or inclusion of `venombox`. The call and
all assertions remain strictly read-only. CI rejects regression to
the unsupported `pvesm config` CLI. No apply action is approved by
this fix.

Resume by re-fetching the reviewed branch and running the **same
stage-rocky-9-8-lxc-rootfs.yml without an apply flag**, preserving
non-multiplexed SSH and `--vault-id infra@prompt`, as documented above.


### Rocky 9.8 staging read-only preflight passed (2026-10-20)

The operator executed `ansible/playbooks/stage-rocky-9-8-lxc-rootfs.yml`
**without** `rocky_rootfs_staging_apply=true` and observed:

- `bp-controller: ok=5 changed=0 unreachable=0 failed=0`
- `venombox: ok=28 changed=0 unreachable=0 failed=0 skipped=8`
- `ROCKY_9_8_DIRECT_TEMPLATE_STAGING_READ_ONLY_READY`
- `ROCKY_9_8_ROOTFS_STAGING_READ_ONLY_READY`
- `source_rootfs_bytes=107425612`
- `source_rootfs_sha256=1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5`
- `source_archive_transferred=false`, `pct_create_authorized=false`,
  `template_staging_apply_authorized=false`.

The eight skipped tasks are the deliberately disabled mutation and
post-transfer-verification branch. Existing CT701 remained isolated
and protected; no Proxmox template was staged, no CT was created, and
no network or package change was made.

**Next approval boundary:** explicitly authorize only staging the
exact rootfs file to `venombox` using the separately gated
`rocky_rootfs_staging_apply=true`. Approval must not be inferred
from read-only PASS. The staging playbook performs a fresh source
integrity and destination check before copying, requires an absent
temporary and final file, verifies the exact destination SHA256,
and publishes without overwriting. If a partial file or a final
file is found, stop for separate read-only reconciliation; do
not remove or replace it automatically.

**Not authorized:** extracting the archive, calling `pct create`,
starting CT790, modifying protected CT701, enabling a network
connection, importing Nextcloud data, or changing production mx1/mx2.


## Rocky 9.8 staging transfer verified; post-transfer PVE gate

The operator explicitly authorized only file-based archive staging
on 2026-10-20. The observed `stage-rocky-9-8-lxc-rootfs.yml`
apply returned:

- `ROCKY_9_8_ROOTFS_STAGED_SHA256_VERIFIED`
- `bp-controller ok=5 changed=0 unreachable=0 failed=0`
- `venombox ok=35 changed=2 unreachable=0 failed=0 skipped=1`
- Destination:
  `local:vztmpl/rockylinux-9.8-lxc_20261018_amd64.tar.xz`
- Exact bytes: `107425612`, destination SHA256 check passed:
  `1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5`
- Verified source archive copy, atomic publication, final SHA256
  and mode/ownership assertion completed successfully.
- No extraction, CT creation, network change, production change or
  modification of existing protected CT701.

**Do not rerun the staging/transfer playbook:** the expected
file now exists, so its correct fail-closed preflight will refuse
another transfer. Do not remove, rename or overwrite it.

The next separate `ansible/playbooks/audit-rocky-9-8-staged-template-readonly.yml`
checks the file at its final path independently. It verifies
non-symlink root-owned `0600` file metadata, single-link count,
size and SHA256, absent .part file, root-owned storage directories,
`pvesm path` translation, `pveam list local` recognition,
still-unused cluster VMIDs 702/790/791, protected networkless CT701,
active storage and healthy ZFS. No TAR extraction or Proxmox
configuration change is performed.

Execute on bp-controller, without any apply flag:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BRANCH="feat/nextcloud-isolated-restore-701-20261019"
    SSH_ARGS="-C -o ControlMaster=no -o ControlPath=none -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=2"

    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
      echo "STOP: Worktree contains local changes."
    else
      git -C "$WT" fetch origin "$BRANCH" &&
      git -C "$WT" switch --detach "origin/$BRANCH" &&
      ANSIBLE_SSH_ARGS="$SSH_ARGS" "$BASE/.venv/bin/ansible-playbook" \
        -i "$BASE/ansible/inventory.yml" \
        -i "$BASE/ansible/inventory.local.yml" \
        "$WT/ansible/playbooks/audit-rocky-9-8-staged-template-readonly.yml" \
        --limit venombox --vault-id infra@prompt
    fi

Expected `ROCKY_9_8_STAGED_TEMPLATE_READ_ONLY_VERIFIED`,
`changed=0`, `failed=0`, `pve_template_recognized=true`.
This only verifies discovery of the archive as a Proxmox system
container template. Proxmox unpack support, unprivileged UID/GID
mapping, rootfs ownership/capability bits and the behavior of
the future Rocky 9.8 guest have **not** been tested.

**Still closed:** `pct_create_authorized=false`,
no VMID790 allocation, no `pct create`, no `pct template`,
no CT start, no bridge/net0, no guest package installs,
no Nextcloud restore or production mx1/mx2 changes.
A separate human approval and guest-creation runbook will
be needed after this inspection.


## Rocky 9.8: Proxmox template recognition PASS and CT790 creation preflight

On 2026-10-20 the operator completed the independent staged-template
read-only audit on venombox:

- `ROCKY_9_8_STAGED_TEMPLATE_READ_ONLY_VERIFIED`
- `ok=25 changed=0 unreachable=0 failed=0`
- Exact rootfs file size `107425612`, SHA256 matched the independently
  signed rootfs digest `1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5`.
- Root-owned regular template file, mode `0600`, no unfinished partial
  staging archive; `pvesm path` and `pveam list local` both recognized
  the exact template on the expected local cache path.
- VMIDs 702, 790 and 791 remained free at audit time; CT701 remained
  unprivileged, protected and disconnected. Storage and ZFS passed.

The next gate is a **separate zero-write compatibility preflight**,
`ansible/playbooks/audit-rocky-9-8-ct790-create-readonly.yml`.
It imports the complete existing staged-template audit; on the
controller it opens the original pinned archive with O_NOFOLLOW,
verifies its exact SHA256 and repeats structural checks, and reports
bounded UID/GID minimum/maximum values and aggregate PAX/xattr
metadata. It refuses numeric owner IDs outside the default 0..65535
guest user namespace mapping.

On venombox the same-run preflight verifies locally supported
`pct help create` options; verifies one usable root subordinate
UID/GID allocation of at least 65,536 IDs in both `/etc/subuid`
and `/etc/subgid`; and verifies active PVE `local-zfs` storage
advertises `rootdir` content. None of these operations allocates
or mounts a guest. Source identity and template SHA256 proofs
must be present in this same invocation. It does not claim that
an actual unpack will succeed.

Use the detached branch worktree on bp-controller (no apply flag):

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BRANCH="feat/nextcloud-isolated-restore-701-20261019"
    SSH_ARGS="-C -o ControlMaster=no -o ControlPath=none -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=2"
    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
      echo "STOP: dirty worktree"
    else
      git -C "$WT" fetch origin "$BRANCH" &&
      git -C "$WT" switch --detach "origin/$BRANCH" &&
      ANSIBLE_SSH_ARGS="$SSH_ARGS" "$BASE/.venv/bin/ansible-playbook" \
        -i "$BASE/ansible/inventory.yml" \
        -i "$BASE/ansible/inventory.local.yml" \
        "$WT/ansible/playbooks/audit-rocky-9-8-ct790-create-readonly.yml" \
        --limit bp-controller,venombox --vault-id infra@prompt
    fi

Expected if all checks pass:
`ROCKY_9_8_CT790_CREATE_PREFLIGHT_READ_ONLY_READY`, `changed=0`,
`failed=0`, `pct_create_authorized=false`.

### Planned CT790 creation, NOT YET AUTHORIZED

The eventual disposable base guest must be a freshly allocated
VMID `790`, unprivileged, stopped, protected, with no `--net0`,
no additional NIC, no onboot start, and an expressly sized
`local-zfs` root filesystem. Creation must reverify the exact
template SHA256, cluster-wide VMID availability, storage and ZFS
health, and confirm CT701 unchanged immediately before mutation.
No `--ignore-unpack-errors`, no host-root `tar -x`, no guest
start or networking, and no automatic destructive rollback. A
partially failed `pct create` must stop and be inspected rather
than automatically cleaned up.

If the next read-only preflight passes, review a separate,
explicitly approved, one-VMID provisioning playbook and
rollback/recovery plan before running a mutation. The user has
approved **only archival transfer**, which is already completed.
This record does not extend approval to container creation,
network interfaces, rootfs extraction, installing guest packages,
restoring Nextcloud data or removing the production instance.


### CT790 metadata auditor: PAX key-counter correction (2026-10-20)

The first operator run of the CT790 read-only ownership-metadata preflight
completed the staged-template inspection on venombox successfully
(`ok=25 changed=0 failed=0`), then failed on bp-controller's
`audit_rocky_lxc_idmap_metadata.py` after 3 successful controller
tasks, with `ROCKY_9_8_UID_GID_METADATA_AUDIT_BLOCKED` and generic
`ARCHIVE_READ_ERROR`. This was a **code defect**, not evidence of
an invalid or corrupted Rocky image. No writes or guest allocation
occurred.

Root cause: POSIX TAR PAX extended headers are a dictionary
`{name: string_value}`. The audit called
`collections.Counter.update(member.pax_headers)`, which
interpreted string metadata values as numeric counts; repeated
fields can cause Python `TypeError` and the summary calculation
could also fail. This now counts **header key occurrences** using
`counter.update(headers.keys())`, with checks for dictionary
shape and string names. Synthetic regression tests cover repeated
PAX metadata and expected numeric category counts. The error path
also distinguishes `AUDITOR_INTERNAL_ERROR` for unexpected code/data
type failures rather than mislabeling them `ARCHIVE_READ_ERROR`.

The existing rootfs and Proxmox template hash proofs remain valid;
however, the UID/GID ownership audit is **not yet passed** until
the corrected read-only preflight runs to completion on both hosts.

Operator recovery: fetch the reviewed feature branch in the clean
worktree, and rerun only
`ansible/playbooks/audit-rocky-9-8-ct790-create-readonly.yml`
without any apply variable, using the existing nonmultiplexed SSH
and `--vault-id infra@prompt` commands documented above.
Never rerun the signed-rootfs staging/transfer playbook;
the transferred template file is already present and verified.
The PVE CT790 creation gate remains closed.


## Rocky 9.8: CT790 creation-readiness PASS; gated no-write provisioning proposal

On 2026-10-20 the corrected signed-rootfs CT790 creation-readiness
audit completed fully on the operator's infrastructure:

- `ROCKY_9_8_CT790_CREATE_PREFLIGHT_READ_ONLY_READY`
- `bp-controller: ok=6 changed=0 unreachable=0 failed=0`
- `venombox: ok=33 changed=0 unreachable=0 failed=0`
- The Rocky 9.8 template remained recognized and SHA256-verified.
- All recorded archive owner UID/GID values fit into the checked
  default user namespace range; required Proxmox subuid/subgid
  allocation resources were available.
- `pct help create` exposed the required flags and `local-zfs`
  advertised rootdir content. The existing CT701 was unchanged,
  with no NIC. No VMID790 was created.
- The result explicitly retains `pct_create_authorized=false`.

A new reviewed but **NOT authorized** proposal lives in
`ansible/playbooks/create-rocky-9-8-ct790-offline.yml`.
It imports the complete three-play read-only preflight
(including source-hash/UID/GID and staged-template checks) on
every execution, plus same-run exact VMID790/CT701 assertions.
With no apply variable, it only prints
`ROCKY_9_8_CT790_CREATE_PLAN_READ_ONLY_READY` and performs
no writes. The implementation pins a disposable first-boot
base CT `790`, hostname `rocky9-base-790`, Rocky 9.8 archive
`local:vztmpl/rockylinux-9.8-lxc_20261018_amd64.tar.xz`,
`local-zfs:16` root filesystem, two CPU cores, 2048 MiB RAM,
zero MiB swap, unprivileged userns, `--ostype centos`,
`nesting=0`, `onboot=0`, `start=0`, `protection=1`, **no
netN options**. Do not assume a custom Rocky template will unpack
correctly just because PVE recognizes its metadata: unpacking itself
is a mutating action that requires its own explicit authorization.

The future (not yet approved) action is doubly gated:
`rocky_ct790_create_apply=true` plus the *exact* separate
`rocky_ct790_create_confirm` approval value in the reviewed
playbook. No provisioning is permitted merely because a CI,
staging, ownership or read-only check passed. PVE creation failures
must **not** trigger automatic destructive cleanup; inspect
any partially allocated CT/ZFS rootfs before deciding recovery.

Use **no apply flag** to review the proposal on bp-controller:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BRANCH="feat/nextcloud-isolated-restore-701-20261019"
    SSH_ARGS="-C -o ControlMaster=no -o ControlPath=none -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=2"
    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
      echo "STOP: worktree contains local changes"
    else
      git -C "$WT" fetch origin "$BRANCH" &&
      git -C "$WT" switch --detach "origin/$BRANCH" &&
      ANSIBLE_SSH_ARGS="$SSH_ARGS" "$BASE/.venv/bin/ansible-playbook" \
        -i "$BASE/ansible/inventory.yml" \
        -i "$BASE/ansible/inventory.local.yml" \
        "$WT/ansible/playbooks/create-rocky-9-8-ct790-offline.yml" \
        --limit bp-controller,venombox --vault-id infra@prompt
    fi

Expected: `ROCKY_9_8_CT790_CREATE_PLAN_READ_ONLY_READY`,
`changed=0 failed=0`, `pct_create_authorized=false`.
The operator must separately approve **CT790 creation only**
after reviewing that complete fresh output. Until then,
nothing is authorized beyond the already completed template
file transport. Converting CT790 to a PVE template, starting it,
attaching networking, provisioning application dependencies, touching
CT701 or production mx1/mx2 are independent future gates.


## Rocky 9.8: CT790 creation proposal read-only PASS

On 2026-10-20 the operator executed
`ansible/playbooks/create-rocky-9-8-ct790-offline.yml` WITHOUT
either CT790 create approval parameter. The three-phase read-only
preflight and proposed creation runbook completed:

- `ROCKY_9_8_CT790_CREATE_PLAN_READ_ONLY_READY`
- `bp-controller: ok=6 changed=0 unreachable=0 failed=0`
- `venombox: ok=35 changed=0 unreachable=0 failed=0 skipped=8`
- Exact pinned archive
  `local:vztmpl/rockylinux-9.8-lxc_20261018_amd64.tar.xz`.
- Proposed new VMID `790`, hostname `rocky9-base-790`,
  `local-zfs:16` rootfs, 2 cores, 2048 MiB RAM, 0 swap,
  unprivileged, `protection=1`, `onboot=0`,
  `start=0`, zero network interfaces.
- All eight mutation/post-creation tasks skipped as expected.
  No new CT exists and CT701 remains protected and disconnected.

This completes **design readiness only**, not unpack/runtime
compatibility or live CT configuration verification. The only
possible next approved mutation is the explicitly gated,
single-VMID CT790 creation with **no** initial boot, NIC,
production connections, or CT701 modifications.
Any `pct create` failure requires a separate read-only
inspection of VMID790, CT configuration and ZFS subvolumes.
Do not perform destructive rollback automatically, retry
a partially failed create blindly, or attempt a start.
An additional explicit operator decision is required before
supplying the two apply approvals.

Upstream Proxmox PCT manual documents the reviewed
`--ostype centos`, `--rootfs`, `--unprivileged`,
`--protection`, `--onboot`, and `--start` flags:
https://github.com/proxmox/pve-docs/blob/master/generated/pct.1-synopsis.adoc

The production mx2 mail service, old mx1, protected CT701,
network policy, and main branch remain untouched.


## Rocky 9.8 CT790 created offline; independent postcreate audit

The user separately and explicitly approved **only one stopped,
protected, unprivileged, networkless CT790 create**, after the
complete signed-rootfs, user namespace and Proxmox prereq gates
had passed. The user applied the previously reviewed two-parameter
approval run from commit
`adf91a9aac4088b5428e91c589f588798c9b867d`.

Operator-supplied actual result (2026-10-21):

- `ROCKY_9_8_CT790_CREATED_OFFLINE_PROTECTED_STOPPED`
- `bp-controller: ok=6 changed=0 unreachable=0 failed=0`
- `venombox: ok=42 changed=1 unreachable=0 failed=0 skipped=1`
- Exact created CTID `790` with hostname `rocky9-base-790`,
  `local-zfs:16` rootfs, 2 cores, 2048 MiB RAM, zero swap.
- The created guest was **stopped**, protected, unprivileged,
  `onboot=0` and had **zero network interfaces**.
- After create the same run checked `pct config 790`, `pct status 790`
  and independently reviewed the existing protected CT701 config.
  No reported CT701 changes; no guest start, template conversion or
  network permissions were authorized.

**Do not run create-rocky-9-8-ct790-offline.yml again.** Unlike
prior pre-create checks, VMID790 **must now exist**, and the pre-create
gate will (correctly) reject a replay due to the VMID collision.

A new `ansible/playbooks/audit-rocky-9-8-ct790-postcreate-readonly.yml`
performs independent **read-only** inspection of the actual CT790
instance without importing any pre-create gate. It asserts the
reviewed stopped, protected, unprivileged, networkless configuration;
the CT790 cluster identity and free planned VMIDs 702/791;
a new source-template SHA256 check; exactly one CT790 rootdir reported
by `pvesm list local-zfs --vmid 790`; a `pvesm path`
resolution of that volume; the configured local-zfs pool;
and matching ZFS filesystem dataset and mountpoint metadata using
`zfs list`. It also checks CT701 isolation again.

The postcreate audit does **not** call `pct mount`,
`pct start`, `pct exec`, `pct template`, `pct set`,
`zfs mount`, `zfs set`, any deletion, or any program that writes
guest content. It does **not** assert the Rocky release inside the
unstarted rootfs or successful boot/runtime compatibility.
If the resulting ZFS mountpoint is unexpected, stop for review;
do not mount or unmount anything merely to make the audit pass.

On bp-controller (NO apply variables):

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-nextcloud-restore"
    BRANCH="feat/nextcloud-isolated-restore-701-20261019"
    SSH_ARGS="-C -o ControlMaster=no -o ControlPath=none -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=2"
    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
      echo "STOP: dirty worktree"
    else
      git -C "$WT" fetch origin "$BRANCH" &&
      git -C "$WT" switch --detach "origin/$BRANCH" &&
      ANSIBLE_SSH_ARGS="$SSH_ARGS" "$BASE/.venv/bin/ansible-playbook" \
        -i "$BASE/ansible/inventory.yml" \
        -i "$BASE/ansible/inventory.local.yml" \
        "$WT/ansible/playbooks/audit-rocky-9-8-ct790-postcreate-readonly.yml" \
        --limit venombox --vault-id infra@prompt
    fi

Expected only if all checks complete:
`ROCKY_9_8_CT790_POSTCREATE_READ_ONLY_VERIFIED`,
`changed=0`, `failed=0`,
`pct_start_authorized=false` and
`pct_template_authorized=false`.

Existing CT701, mx1, mx2, production Nextcloud and network
configuration remain out of scope. Starting or converting CT790
will require its own explicit permission and separate checks.


### CT790 post-create ZFS field-list CLI correction (2026-10-21)

The first strictly read-only post-create audit reached
`Read the specific existing CT790 ZFS dataset without mounting it`,
then failed with `rc=1` while executing the malformed argument
vector `zfs list -H -p -o name type mountpoint refquota rpool/data/subvol-790-disk-0`.
ZFS printed the intended dataset name but treated the following
field names `type`, `mountpoint`, `refquota` as extra dataset
operands. It reported that those unintended datasets did not exist.
The operator's recap was `venombox: ok=24 changed=0 failed=1`.

The correct read-only command passes **one comma-separated field
argument** to `-o`:
`zfs list -H -p -o name,type,mountpoint,refquota rpool/data/subvol-790-disk-0`.
This is encoded as one YAML `argv` list element and covered by a
regression test that inspects the actual parsed command token
sequence. OpenZFS specifies that `-o` accepts a comma-separated
property list; `-H` produces TAB-delimited output.

The failure is a playbook argument-assembly error, **not**
evidence of a missing dataset: earlier same-run Proxmox storage
checks resolved and listed the exact CT790 rootdir successfully.
The ZFS dataset metadata validation has **not yet completed**.
No host or guest state was changed (`changed=0`).

Rerun **only** the updated
`ansible/playbooks/audit-rocky-9-8-ct790-postcreate-readonly.yml`
after refreshing the same clean worktree, with
`--vault-id infra@prompt` and no apply flags. Do **not** rerun
`create-rocky-9-8-ct790-offline.yml`: VMID790 already exists.
A successful independent CT790 post-create audit must still show
`ROCKY_9_8_CT790_POSTCREATE_READ_ONLY_VERIFIED`, changed=0,
failed=0, no CT startup and no template conversion.
