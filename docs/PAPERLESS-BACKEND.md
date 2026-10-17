# Paperless-Backend: Installationsvorlage und Bestandsaudit

**Stand 17.10.2026:** Aus [PR #54](https://github.com/tobe4it/bergen-platform/pull/54) eigenständig auf `main` übernommene, standardmäßig deaktivierte **Erstinstallationsvorlage**. Die produktive Installation auf dem vorhandenen Proxmox-LXC ist bereits eingerichtet. Ein Git-Merge ist **keine Migration oder Reinstallation**.

## Trennung von bestehender Anlage und Greenfield-Installation

1. **Bestehende Anlage (empfohlen):** `audit-paperless-existing-backend-readonly.yml` über den bereits verwendeten Proxmox-Inventarhost ausführen; verifiziert LXC-Identität, unprivilegierten LXC, ZFS-Root und dediziertes Datenvolume sowie den Zustand von PostgreSQL, Redis und Paperless ohne Mutation. Der Check reproduziert nicht die ursprüngliche Installation und kontrolliert nicht die geheimen Umgebungsdateien.
2. **Neue Anlage:** Der aufbewahrte Podman/Quadlet-Role stellt PostgreSQL, Redis und Paperless getrennt in einem **vorher geprüften, leeren, unprivilegierten** Debian-LXC bereit. Er installiert **keinen** Proxmox-Gast. Die Annahmen zu FUSE, Nesting, Storage, Image-Tags, Firewall und Netzfreigaben bedürfen einer separaten Standortprüfung.
3. **Sicherheit:** `paperless_deployment_approved`, `paperless_first_install_approved` und `paperless_start_approved` stehen standardmäßig auf `false`. Die Erstinstallationsrolle lehnt bestehende Container-Quadlets, Vault-Env-Dateien oder persistente DB-/Dokumentordner **vor jeder Paketinstallation oder Änderung** ab, auch wenn Deploy-Freigaben gesetzt wurden.
4. **Transport:** `pct_ssh_proxy.py` ermöglicht den doppelt per SSH-Schlüssel gepinnten Controller→Proxmox→LXC-Transport ohne Öffnung einer isolierten Gast-VLAN-SSH-Route. Die reale `ansible_ssh_common_args`-Konfiguration bleibt ausschließlich im ignorierten Site-Inventar. Ein genehmigter Erstinstallationslauf ist nur erlaubt, wenn die bestehende Quelle und der Gast-Hostkey zuvor unabhängig bestätigt wurden.
5. **Netzgrenze:** Die Erstinstallationsvorlage veröffentlicht `127.0.0.1:8000` **im Gast**. Ein separater Nginx-Proxy-LXC ist über diese Adresse nicht erreichbar. Diese Vorlage darf nicht stillschweigend als aktuelle produktive Proxy-Konfiguration übernommen werden. Die reale Backend-Erreichbarkeit erfordert eine zusätzliche, separat freigegebene Netzwerk-/Proxy-Integration.
6. **Backups:** Das persistente LXC-Datenvolume muss einbezogen sein; das Backup-IaC befindet sich im eigenständigen Folge-PR #55. Ein erfolgreicher VZDump-Lauf beweist nicht automatisch, dass ein vollständiger Wiederherstellungstest aktuell ist.

## Standortprüfung (ohne Schreibzugriff)

```bash
cd ~/bergen-platform
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-existing-backend-readonly.yml
```

Erwarteter Abschluss `PAPERLESS_EXISTING_BACKEND_READONLY_OK`. Die Verwendung von `pct exec` erfolgt über den bereits autorisierten Proxmox-Host; ein direkter LAN-SSH-Zugriff auf den Gast ist nicht erforderlich.

## Greenfield-Vorlage

Die historischen Konfigurationsbeispiele unter `docs/examples/paperless.local.example.yml` und `paperless.vault.example.yml` enthalten keine gültigen Secrets. Die Vorinstallation und das eigentliche Starten sind getrennte explizite Entscheidungen, niemals ein Side Effect der Bestandsprüfung.

Für die genaue ursprüngliche Rollenstruktur siehe [historisches Design #54](https://github.com/tobe4it/bergen-platform/pull/54); die dortigen Proxmox-/Proxy-/LDAP-Integrationserklärungen dürfen **nicht** als aktuell getestete Live-Aussage übernommen werden. Dieses Release ermöglicht ausschließlich die **sichere Reproduzierbarkeit eines erstmaligen, isolierten Backends** bei vollständig abgenommener Zielumgebung. Die bestehende laufende Instanz wird ausdrücklich nicht „adoptiert“ oder durch einen historischen Role-Stand überschrieben.

## Grenzen

Kein produktiver Container-Neustart, keine Veränderung an OIDC/TLS, NAS-/ACL-/Scanner-Timern, Proxmox-Mounts oder UniFi. Für eine vollständig wiederherstellbare Produktionsinstallation fehlen weiterhin eine **adoptierende Konfigurations-Reconciliation** gegen die bestehenden Quadlets/Umgebungsdateien sowie ein kontrollierter Restore-Test einer tatsächlich frisch aufgebauten Instanz. Diese Aufgaben sind von der hier ausgelieferten **Erstinstallationsvorlage** getrennt zu behandeln.
