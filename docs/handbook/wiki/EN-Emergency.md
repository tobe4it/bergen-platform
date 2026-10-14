<!-- bergen-platform-handbook: managed -->
# Emergency: taking over today

[Deutsch](DE-Emergency.md) | [English](EN-Start.md)

**Public edition 1.0, 2026-10-14.** Examples do not replace a private deployment inventory.

## The first goal

Keep everyday connectivity, communication and important files available. A new caretaker does not need to rebuild the platform immediately. Leave functioning equipment running while you establish what is actually in use.

## The first thirty minutes

1. Do not factory-reset devices, reinstall services or start broad upgrades.
2. Use a familiar device on its usual home network to test the internet, email and file access. Record the time and exact error.
3. Find the private handover record and the separately protected recovery envelope. The public wiki contains neither real credentials nor a deployment inventory.
4. Contact the designated caretaker. Keep a contact route that does not depend solely on the platform's own email.
5. Preserve provider contracts and invoices. Continue the internet, domain, DNS, mail-gateway and storage services until their dependencies are understood.

## Checks an inexperienced user can make

Check power and the normal indicator lights on router, switches, NAS and server. Determine whether one device or everyone is affected. Does mobile internet work while the home connection fails? Does the application fail to open, or only reject a login?

Photographs of cabling, device labels and an error can help a caretaker. Keep passwords and access QR codes out of those pictures. Record the last known change; an accurate symptom is more useful than a guessed diagnosis.

Stop when a screen asks to erase or overwrite data, when disks report failure, when there is an unfamiliar certificate warning, or when no recoverable backup is known. Preserve the existing state and ask the caretaker to investigate.

## Following a power failure

The caretaker checks network connectivity first, then central DNS, directory and storage services, then the Proxmox host and required applications. The automation controller manages configuration; it does not replace a running mail or file service.

Use the normal power button for a device that is off. Do not repeatedly unplug a running device. Electrical damage, unusual smells or dangerous noises require appropriate professional help.

## A useful incident message

“Since __, __ has failed on __ devices. Mobile internet works/does not work. The last change was __. The exact error is __. Router, NAS and server are powered. Please check the current inventory and backups before changing anything.”

## Learning check

Why avoid a broad reset? It can remove the network rules, names and stored configuration needed by otherwise healthy services, and it cannot recover lost documents.

---

[Contents](EN-Start.md) · [Sources](EN-Sources.md) · [Prepare private handover](EN-Handover.md)
