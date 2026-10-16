<!-- bergen-platform-handbook: managed -->
# From zero to your own IT: learning and setup path

[Deutsch](DE-Self-Hosting.md) | [English](EN-Start.md)

**Who is this for?** You want to host services yourself but have no server, Proxmox installation or Ansible controller yet. Start here. Work through one stage at a time; a complete Bergen deployment is not required for learning.

**First goal:** A Linux test guest you can access, running one small application with a proven recovery procedure. Only then entrust important everyday data to it. For an existing deployment, use [Emergency help](EN-Emergency.md) and [Operations](EN-Operations.md).

## 1. Understand the responsibility

Self-hosting means choosing where data lives and how systems are configured, while taking responsibility for updates, accounts, backups and troubleshooting. An application can run on your own computer and still depend on outside services, for example for sending messages or obtaining certificates.

| Term | In your first setup |
| --- | --- |
| Server | A computer providing a function; a suitable spare test computer can suffice |
| Client | The browser, phone or computer using that function |
| Host and guest | The host provides resources; a VM or LXC is a separate guest on it |
| Service and data | Software can be replaced; documents, databases and settings must survive |
| Local and public | Reachable on your home network does not mean reachable from the Internet |
| Operations | Regular checks, updates, backups and the ability to restore |

**Exercise:** Write down one concrete goal, such as finding documents on your home network. Identify its users, the data it creates and how long an outage would be tolerable. Start with one service and test data.

## 2. Plan a small learning environment

You need a management computer with a browser and terminal, plus a separate Linux test environment. Initially this can be a VM on an existing computer. A later Bergen setup adds Proxmox as a dedicated virtualization host. Synology, UniFi, VLANs, LDAP, your own domain and every application at once are not prerequisites for the first Linux exercise. Individual Bergen roles may nevertheless depend on existing services of this kind.

Check hardware against the [Proxmox requirements](https://www.proxmox.com/en/products/proxmox-virtual-environment/requirements) and your planned guests. Host minimum requirements are not a resource plan for all applications. Allow for RAM, storage, electricity and a separate backup destination. AI models are a later addition, not the sizing baseline for a first learning server.

Privately record each device's name, purpose, management address, operating system, data location and backup destination. Plan your own names, addresses and free space; wiki examples are not a valid site configuration. A VLAN is a logically separate network; a bridge is a virtual switch. Continue with [Networks and identities](EN-Network-Identity.md).

**Continue when:** You can identify the test computer unambiguously and do not need production data for the exercise.

## 3. Learn Linux before automating it

Install a supported Linux appropriate to your intended use in the test environment. For the Proxmox route, read the official [installation guide](https://pve.proxmox.com/pve-docs/chapter-pve-installation.html), prepare installation media, deliberately select the target disks and plan management networking. **The Proxmox installer erases existing data on the selected drives.** Use a dedicated device or empty test drives.

Then check the local management interface, clock and network access. An initial certificate warning requires independent verification of server identity; do not permanently disable TLS checks. Create a Linux test guest in Proxmox with documented storage and networking. A VM has its own kernel; LXC shares the host kernel. For later application containers, choose the approach supported by the relevant runbook.

In the guest, learn to log in, find files, understand permissions, use package management and read service status and logs. Run commands from [Linux and containers](EN-Linux-Containers.md) on the machine specified there. The Proxmox console provides a way back when guest SSH does not work yet.

**Exercise:** Create and read a text file in your home directory, then find it after logging in again. Check the hostname, free disk space and time. Configure SSH with your own key and verify the host fingerprint through the console.

**Continue when:** You know whether you are working on the host, a guest or your management computer, and can reach the guest without working SSH.

## 4. Understand a first application

Choose a small application with its own official installation guide, a local test account and test data. Install it only in the test guest. Record its version, start/stop procedure, port, configuration file and persistent data paths. Allow only the local network access needed for the test.

Test as a user: open it, log in, save something, log out, log in again and retrieve what you saved. Restart the guest in a controlled way and repeat the test. A running process alone does not prove the application works.

The Bergen [Pi-hole guide](https://github.com/tobe4it/bergen-platform/blob/main/docs/PIHOLE.md) is one possible later application route: initially query it explicitly from a single test client. Change DNS for the whole household only after successful tests. Mail servers, central login and family archive migration come later because more dependencies are involved.

**Continue when:** You can explain where data lives and what starts after a reboot.

## 5. Back up and actually restore

Read [Backup and recovery](EN-Backup-Recovery.md) before adding important data. Back up application settings and data together; databases require a consistent backup method. A snapshot on the same device does not replace a separate backup.

Restore the test guest or application data to a separate destination. Avoid duplicate IP addresses and unintended connections to real accounts or devices. Open the restored application and check the test file. Record the date, steps, result and required keys. The first exercise is complete only after this test.

**Continue when:** You can retrieve important test data without the original guest and explain how backup access remains possible in an emergency.

## 6. Learn Bergen and Ansible gradually

Git records configuration development. Ansible executes described tasks on selected computers. The **controller** runs Ansible; the **inventory** identifies its targets. Read [Automation and secrets](EN-Automation-Secrets.md) for the basics.

On a management computer with Git, first inspect the public code:

```sh
git clone https://github.com/tobe4it/bergen-platform.git
cd bergen-platform
git status
git log -1 --oneline
```

This does not install a platform. Read README, ENGINEERING and the documentation for the chosen service. A clone includes neither your secrets nor a suitable private site configuration.

**Setting up the first controller is a separate step.** If necessary, start with a manually configured Linux computer or VM and the [official Ansible introduction](https://docs.ansible.com/projects/ansible/latest/getting_started/index.html). Ansible must already run somewhere before it can configure another controller. Practise against your test guest only, using a separate learning inventory.

The existing `create-controller.yml` and `bootstrap-controller.yml` playbooks are not universal first-install commands. The reviewed version expects local Proxmox/vault variables or an existing SSH key on the executing computer, among other prerequisites. The bootstrap playbook also grants broad passwordless sudo. Proxmox API calls in the reviewed controller playbooks disable certificate verification; this is not a recommended way to establish trust in a new setup. Before use, review and adapt these assumptions, privileges and TLS trust to your own environment. See the [reviewed bootstrap code](https://github.com/tobe4it/bergen-platform/blob/e9078b80c9bb3fed7b02a6b1749b6187b241350d/ansible/playbooks/bootstrap-controller.yml) and [controller creation code](https://github.com/tobe4it/bergen-platform/blob/e9078b80c9bb3fed7b02a6b1749b6187b241350d/ansible/playbooks/create-controller.yml).

Before any real run, review targets and variables, check syntax, list affected hosts and read the playbook. `--check` is an additional aid only; support varies by module and playbook. Afterwards, verify the user-facing function and check a subsequent run for unexpected changes.

**Continue when:** You know exactly which computer will change, where secrets are held and how to restore the previous data state.

## 7. Turn the lab into a small operational setup

Expand in this order: stable local names and addresses; a first backed-up application; repeatable setup; logs and maintenance; further users and appropriate permissions; then central identity or external access if needed. Give every addition a functional test and a recovery route. Router port forwarding is not a necessary part of getting started.

Keep the existing DNS, mail or file service until its replacement has been tested. Synology and UniFi describe parts of the reference environment; other devices require suitable configuration of their own. Do not assume identical group names, networks or paths.

**Ready for everyday use:** Another authorized person can log in, complete a typical task and arrange help using your notes. A named person checks updates and backups. Use [Operations](EN-Operations.md) and [Private handover](EN-Handover.md).

---

[Contents](EN-Start.md) · [Understanding the architecture](EN-Architecture.md) · [Sources](EN-Sources.md)
