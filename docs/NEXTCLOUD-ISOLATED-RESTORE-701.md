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
