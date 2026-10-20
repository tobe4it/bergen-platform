# Bergen-AI ↔ Paperless: einmaliger vmbr90-Transport-Apply

**Stand 20.10.2026. Vorbereitet, nicht auf venombox ausgeführt. Draft PR #119.**

Dieses getrennte, ausdrücklich autorisierungspflichtige Playbook
legt **nur** eine neue Proxmox-Linux-Bridge und zwei zusätzliche
Schnittstellen an. Es verändert kein primäres `net0`, keine
bestehenden Host-Gateways, keine `vmbr0`-Bridge, kein Ollama
und kein Paperless.

| Objekt | Ziel |
| --- | --- |
| venombox | `vmbr90` nur lokal, `bridge-ports none`, ohne Host-IP/Gateway (IPv6 am Host-Bridge-Interface deaktiviert) |
| CT110 (bergen-ai) | `net1 eth1` auf `vmbr90`, `172.30.110.2/28`, `ip6=manual` |
| CT126 (bergen-paperless) | `net1 eth1` auf `vmbr90`, `172.30.110.3/28`, `ip6=manual` |
| CT120 (syslog) | unverändert |
| Ollama / Paperless API | unverändert, bestehende Verbindung bleibt zunächst aktiv |

## Strikte Freigabebedingungen vor dem ersten mutierenden Task

`apply-bergen-ai-vmbr90-transport-once.yml` importiert die
**gleichen Live-Read-only-Preflights** in jedem Lauf:
IPAM/extern, lokal, erweiterte LXC-/Podman-Netze und WireGuard.
Das Playbook verweigert die Ausführung, falls einer dieser
Nachweise unvollständig oder widersprüchlich ist.

1. Im *nicht eingecheckten*
   `ansible/vars/bergen-ai-bridge-ipam.local.json` müssen
   **alle** UniFi-/VPN-/Offhost-Netze tatsächlich vollständig
   erfasst und die Kategorien danach jeweils ausdrücklich mit
   `complete: true` bestätigt sein. Ein bloßes Umstellen der
   drei Booleschen Werte ohne reale Prüfung ist **keine** Freigabe.
   Der letzte Livebefund war
   `OPERATOR_DECLARED_INCOMPLETE`.
2. Auf `venombox` ist ein **unabhängiger**, von
   SSH und der geänderten Proxmox-Netzkonfiguration
   unabhängiger, getesteter Konsolenzugang sowie ein
   praktikabler Rückweg erforderlich. Dies wurde bisher
   nicht attestiert. Eine `-e`-Variable ersetzt keine
   echte Konsolenprüfung.
3. CT110 und CT126 müssen unverändert laufen, mit je
   genau einem `net0`; `vmbr90`, `net1` und das neue
   Netzwerk-Drop-in müssen vollständig frei sein.
   Alle Live-Netzinventare müssen negative Kollision
   bestätigen, einschließlich des deklarierten /28.
4. Für beide CTs sind aktuelle Backup-Metadaten und
   das aktive Synology-NFS sowie lesbare
   Ursprungs-Konfigurationsquellen erforderlich.
   CT110-Zstandard-/TAR-Integrität wurde schon geprüft;
   CT126-Archiv-Restore ist noch nicht belegt.
5. `/etc/network/interfaces` muss die
   `source /etc/network/interfaces.d/*`-Zeile
   enthalten; es darf kein offener
   `/etc/network/interfaces.new`-Änderungsentwurf
   existieren. `ifupdown2` muss installiert sein.
   Bei abweichender Host-Netzwerktopologie bricht
   der Apply **vor einer Änderung** ab.

Die ausdrückliche Freigabe gilt **nur** für die genannten
zwei NICs und die neue Bridge, **nicht** für Firewall-
Policyänderungen, Ollama-Binding, Anwendungs-Endpoint,
LLM-Katalogisierung oder einen CT-Neustart.

## Ausführung auf bp-controller (tmux + verifizierte Konsole)

Erst nach **wirklicher** unabhängiger Konsolenprüfung
und vervollständigtem IPAM:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
git -C "$WT" fetch origin feat/bergen-ai-private-bridge-20261019
git -C "$WT" switch --detach origin/feat/bergen-ai-private-bridge-20261019
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/apply-bergen-ai-vmbr90-transport-once.yml \
  --syntax-check

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/apply-bergen-ai-vmbr90-transport-once.yml \
  -e bergen_ai_vmbr90_oneoff_approval=APPROVE_SCOPED_VMBR90_CT110_CT126 \
  -e bergen_ai_vmbr90_oob_attestation=CONSOLE_VERIFIED_AND_ROLLBACK_AVAILABLE \
  --vault-id ai@prompt
)
```

Das Fehlen oder Scheitern der IPAM-/Konsolen-/Backup-/
Netz-Gates muss den Lauf vor einem mutierenden Task
stoppen. **Nicht durch `--skip-tags`, lokale Änderungen
an den `assert`-Bedingungen oder erfundene Freigaben
umgehen.** Ohne erfüllte Voraussetzungen ist es richtig,
dass die Verbindung noch nicht erstellt wird.

## Wirkung und Rollback

Der Apply legt vor der Änderung im ausschließlich
root-lesbaren Verzeichnis
`/root/bergen-ai-vmbr90-prechange/`
separate Belegkopien der bestehenden Host-/CT-
Konfigurationen an, ohne Originale zu überschreiben.

Anschließend erzeugt er nur
`/etc/network/interfaces.d/bergen-ai-vmbr90`
und startet mittels `ifup vmbr90` **ausschließlich**
die neue, von vorhandenen Bridge-Ports unabhängige
Schnittstelle.
Vor dem Anschluss der LXCs prüft das Playbook außerdem, dass
IPv6 auf der neuen **Host-Bridge** ausdrücklich deaktiviert ist
und noch keine Ports an ihr hängen. Die IPv4/IPv6-Adressierung
bestehender Host-Interfaces wird nicht geändert. **Kein `ifreload -a`, kein Reboot
oder Neustart eines Containers.** Erst dann werden
`pct set 110/126 --net1 ...` angewendet.

Der Postcheck vergleicht `net0` beider Gäste
mit den ursprünglichen Zeilen, bestätigt die
beiden neuen `net1`, weiterhin laufende CTs
und die SHA256-Unverändertheit von
`/etc/network/interfaces`. Auf einen Fehler
folgt ein auf die erkennbaren `net1`-Einträge
und das neue Bridge-Drop-in begrenzter
Rollback-Versuch; danach ein verpflichtender
Fehlerstatus. Bei Hostverlust kann automatisches
Ansible-Rescue **nicht** funktionieren: deshalb
ist Konsolenzugriff unverzichtbar.

**Nicht blind wiederholen.** Die neue Bridge
und das Root-Backupverzeichnis müssen vor
einem gesonderten erneuten Versuch untersucht
werden.

Bei Erfolg meldet das Playbook
`STATUS=VMBR90_PERSISTENT_DEFINITION_AND_CT_NET1_CONFIGURED`.
Dies ist zunächst **nur ein Konfigurationsnachweis**.
Ein positiver L3-Test aus dem Paperless-Podman-
Namespace zum Ollama-Backend
`172.30.110.2:11434` sowie Tests der
bestehenden `net0`-Routen folgen **separat**.

**Wichtig:** `firewall=1` allein beweist keine
aktive Proxmox-Firewallregel. Das aktuelle
Ollama-Binding auf IPv4/IPv6-Wildcard bleibt durch
die reine vmbr90-Verbindung **unverändert exponiert**.
Die beschränkte Bind-Adresse, der Negativtest
vom bp-controller und der Wechsel des
Paperless-Ollama-Endpoints erfordern einen
separaten, dokumentierten und geprüften
Apply. Keine allgemeine automatische Paperless-
LLM-Katalogisierung oder Timeraktivierung.


## Phase 1.1 – Live-Apply vor erster Änderung blockiert (20.10.2026, 09:41)

Der Betreiber hat das ausdrücklich autorisierte Oneoff-Playbook
ausgeführt. Alle vier wiederholten read-only-Preflights erreichten
die finale Apply-Gate-Assertion; insbesondere meldete die aktive
WireGuard-Prüfung `NO_OVERLAP_IN_INSPECTED_LIVE_WG_PEERS`.

Die erste Gate-Assertion brach mit
`VMBR90_IPAM_OOB_BACKUP_OR_LIVE_AUDIT_GATES_NOT_SATISFIED`
ab. Ergebnis:
`localhost ok=6 changed=0 failed=0`,
`venombox ok=28 changed=0 failed=1`.
**Keinerlei Netzwerkschreibaufgabe wurde erreicht.**
Es wurde weder die Bridge noch `net1` angelegt,
noch ein Rollback benötigt. Nicht erneut den
mutierenden Oneoff-Apply starten, bis die blockierende
Bedingung untersucht und real behoben wurde.

`no_log: true` ist notwendig, um private ursprüngliche
Netzwerk-, Host- und Backupdaten nicht offenzulegen.
Daher wird ein **separater, nur lesender** Playbook-
Audit `ansible/playbooks/audit-bergen-ai-vmbr90-apply-gates-readonly.yml`
eingesetzt. Er wiederholt dieselben Netzwerk-/Host-
Preflights, verzichtet vollständig auf den
Freigabe-/Apply-Teil und gibt nur benannte
`PASS`/`BLOCKED`-Kategorien für jede
technische Bedingung aus. Sein zweiter, ebenfalls
lesender Test prüft die strengere `ifupdown2`-/
Host- und `net0`-Baseline.

**Diagnose auf bp-controller (nur dieser read-only-Run):**

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
git -C "$WT" fetch origin feat/bergen-ai-private-bridge-20261019
git -C "$WT" switch --detach origin/feat/bergen-ai-private-bridge-20261019
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-vmbr90-apply-gates-readonly.yml \
  --vault-id ai@prompt
)
```

Die erwarteten Schlüsselfelder umfassen
`IPAM_SCOPE_COMPLETE`,
`IPAM_DECLARED_RANGES`,
`CT110_RECENT_BACKUP_METADATA`,
`CT126_RECENT_BACKUP_METADATA`,
`HOST_IFUPDOWN2_DROPIN_PRECHECK` und
`CT110_CT126_RUNNING_NET0_ONLY`. Die Diagnose
kann **keinen** unabhängigen physischen
Konsolenzugang attestieren und macht aus
einem bloß manuell gesetzten `complete: true`
keinen objektiven IPAM-Nachweis.

Selbst bei allen technischen `PASS`-Meldungen
bleibt `APPLY_AUTHORIZED=False` – der
Read-only-Audit nimmt keine Approvals entgegen.
Erst nach realer Fehlerbehebung, tatsächlicher
IPAM-Vervollständigung und verfügbarer OOB-Konsole
kann ein separater, verantworteter neuer
Netz-Apply-Lauf genehmigt werden.
