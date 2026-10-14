<!-- bergen-platform-handbook: managed -->
# Sources and maintenance

[Deutsch](DE-Sources.md) | [English](EN-Sources.md)

## Project sources

Repository main baseline: `7b465fad95be476e853f0b74e9e86e1d125fd4f5`; handbook edition 1.0, 2026-10-14.

- [README and architecture](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/README.md)
- [Architecture](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/ARCHITECTURE.md)
- [Mail backend](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/MAIL.md)
- [Mail TLS operations](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/MAIL-TLS-OPERATIONS.md)
- [Mail TLS synchronization](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/MAIL-TLS-AUTOSYNC.md)
- [Pi-hole](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/PIHOLE.md)
- [EVCC](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/EVCC.md)
- [MQTT](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/MQTT.md)
- [Syslog](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/ansible/roles/syslog/README.md)
- [MQ evaluation](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/MQ-LAB.md)
- [MQ LDAP preparation](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/MQ-LDAP.md)
- [Daytrading collector](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/DAYTRADING.md)
- [Updates](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/UPDATE.md)
- [Roadmap / recovery boundary](https://github.com/tobe4it/bergen-platform/blob/7b465fad95be476e853f0b74e9e86e1d125fd4f5/docs/ROADMAP.md)

## Official documentation

- [GitHub wiki editing](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages)
- [Proxmox backup source](https://github.com/proxmox/pve-docs/blob/master/vzdump.adoc)
- [Ansible Vault](https://docs.ansible.com/projects/ansible/latest/vault_guide/index.html)
- [Podman Quadlet](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
- [UniFi VLANs](https://help.ui.com/hc/en-us/articles/9761080275607-Creating-Virtual-Networks-VLANs)
- [Nextcloud backup](https://docs.nextcloud.com/server/latest/admin_manual/maintenance/backup.html)
- [Nextcloud restore](https://docs.nextcloud.com/server/latest/admin_manual/maintenance/restore.html)
- [Paperless administration](https://docs.paperless-ngx.com/administration/)

## Maintenance and limitations

Update both editions together and keep prerequisites, effects and acceptance conditions aligned. This public handbook derives from project documentation and a generalized German handover draft. Private deployment details were removed; no private runtime or restore acceptance is claimed.

The roadmap distinguishes implemented code from remaining acceptance. Read vendor documentation for the actual installed version. Paperless and AI identity, intake and denial tests require deployment-specific evidence.

Wiki sources and blank printouts are maintained through repository review. GitHub stores the wiki in its own Git repository; the documented publisher requires an initialized wiki. Unrelated existing wiki pages are preserved.
