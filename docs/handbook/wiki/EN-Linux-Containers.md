<!-- bergen-platform-handbook: managed -->
# Linux, SSH and containers

[Deutsch](DE-Linux-Containers.md) | [English](EN-Start.md)

**Public edition 1.0, 2026-10-14.** Examples do not replace a private deployment inventory.

## Proxmox and its guests

The node or host is the physical Proxmox server. An LXC/CT is a separate Linux guest sharing the host kernel. A virtual machine has its own operating-system kernel. Podman may run another layer of application containers inside an LXC.

Proxmox uses guest IDs for containers as well as virtual machines. An ID is not an IP address. Match the name and ID before any action. The web interface commonly uses HTTPS port 8006; use the trusted URL from the private inventory.

Summary shows status and resources; Resources shows assignments; Console provides a guest console. Menu wording depends on language and version. “Running” proves only that the guest is running, not that its application is healthy.

The root filesystem holds Linux and applications. Additional mountpoints expose other storage inside the guest. ZFS is a storage system; a snapshot records a prior state, often on the same storage. Bind mounts and external data need special backup attention. Do not use Remove as troubleshooting, and distinguish a forced Stop from a controlled shutdown.

## Linux users, paths and commands

`root` is the administrative account. `sudo` grants an allowed command additional privileges. Prefer a normal account for routine work. `/` is the top directory; `/etc` commonly holds configuration, `/var/lib` persistent application state, `/var/log` logs and `/home` user homes. `~` refers to the logged-in user's home. Filename case can matter.

These read-only commands help identify the current system and resources:

```sh
hostname
whoami
pwd
ls -lh
df -h
free -h
```

`hostname` identifies the computer, `whoami` the user and `pwd` the working directory. `ls` lists files. `df` reports filesystem usage and `free` memory. Linux uses memory for cache; low “free” memory alone is not proof of a fault.

In `ls -lh /var/log`, the program is `ls`, `-lh` contains options and `/var/log` is the target. Spaces separate arguments; quotes can group them. A displayed `$` or `#` prompt is normally not copied as part of the command.

“Permission denied” suggests rights; “No such file” a missing path; “Command not found” missing software or the wrong environment. Record the exact message before increasing privileges. Ctrl+C stops many foreground commands; q exits many paginated viewers. Password entry commonly displays no characters.

## SSH and server identity

SSH provides an encrypted remote console. A public key may be installed on servers; its private counterpart must remain protected. A key passphrase is not necessarily the Linux account password. A server host key identifies the remote computer: independently verify new or changed fingerprints instead of accepting them blindly.

The controller manages the project checkout and Ansible environment. Interactive accounts and automation accounts can differ. Record both. Where the controller's VLAN cannot directly reach an application VLAN, use the configured Proxmox-mediated path. A direct SSH failure is not proof that the intended mediated path is broken; do not broaden firewall rules merely to make it work.

From a verified Proxmox console, a read-only example is:

```sh
hostname
pct list
pct status 900
```

ID 900 is an example only; select a confirmed existing guest first. `pct list` displays identities and states. A caretaker can then inspect the identified guest:

```sh
pct exec 900 -- hostname
pct exec 900 -- systemctl --failed --no-pager
```

Missing application units can be expected on a deliberately prepared guest. Do not create them simply because a status command returned no result. Shared diagnostic output may contain users, addresses or document titles; send only relevant excerpts and never private keys or vault contents.

## systemd services and timers

A service unit manages a program; a timer runs a scheduled task. Active describes current activity, enabled normally describes startup enablement for ordinary units. A timer may be active while its short-lived service is inactive between runs. Prepared services may intentionally be disabled.

For native EVCC on its own host, read-only inspection is:

```sh
systemctl status evcc --no-pager
systemctl is-active evcc
journalctl -u evcc -n 40 --no-pager
systemctl list-timers --all --no-pager
```

Status includes recent messages; journalctl reads the log; the timer list shows scheduled work. A restart interrupts activity. Confirm the host, service, expected state, ongoing work and recovery plan first. A whole-host restart affects multiple applications and can obscure the original evidence.

A successful certificate timer run with nothing due does not demonstrate a real unattended renewal, distribution and consumer reload. Those outcomes need separate evidence.

## Podman, images and Quadlet

An image is a packaged application; a container is a running instance. Persistent data lives in assigned directories or volumes. Replacing an image must preserve that data. A fresh image does not contain personal files from the previous instance.

Quadlet connects Podman to systemd. Root-managed definitions commonly live in `/etc/containers/systemd/`. A `name.container` definition generates a `name.service`. Edit the managed source or template, not the generated service. Quadlet startup is controlled by its definition's Install section; ordinary `systemctl enable` is not the right approach for these generated units.

Inspect the appropriate Podman account in the correct guest:

```sh
podman ps
podman ps -a
systemctl --failed --no-pager
```

Root and an ordinary user can have separate Podman instances. An empty list therefore does not prove the application is absent. Some applications, including the reference EVCC service, run natively without Podman.

Record pinned image versions, persistent paths and backup coverage. Never use volume pruning or deletion of data directories as general troubleshooting.

## Reverse proxies

A reverse proxy receives web requests and forwards them to an internal application. It may handle HTTPS while the application listens on another port. Record public names, certificate ownership and internal targets together. A healthy proxy page does not by itself prove the backend works.

---

[Contents](EN-Start.md) · [Sources](EN-Sources.md) · [Prepare private handover](EN-Handover.md)
