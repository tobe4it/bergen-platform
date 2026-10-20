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
