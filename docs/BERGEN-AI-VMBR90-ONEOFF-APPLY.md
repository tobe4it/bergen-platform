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

## Phase 1.2 – Live-Gatediagnose 20.10.2026, 09:47

Der Betreiber führte `audit-bergen-ai-vmbr90-apply-gates-readonly.yml`
auf `bp-controller` aus: `localhost ok=6 changed=0 failed=0`,
`venombox ok=36 changed=0 failed=0`.

```text
IPAM_DECLARED_RANGES=PASS
IPAM_SCOPE_COMPLETE=BLOCKED
BRIDGE_UNUSED=PASS
CT110_CT126_CT120_NIC_BASELINE=PASS
LXC_PODMAN_NETWORK_RANGES=PASS
LIVE_WIREGUARD_RANGES=PASS
HOST_AND_CT_CONFIG_READABLE=PASS
BACKUP_NFS=PASS
CT110_RECENT_BACKUP_METADATA=PASS
CT126_RECENT_BACKUP_METADATA=PASS
HOST_IFUPDOWN2_DROPIN_PRECHECK=PASS
CT110_CT126_RUNNING_NET0_ONLY=PASS
HOST_SOURCE_DIAGNOSTIC=EXPLICIT_SOURCE_NO_PENDING_EDIT
CT110_LAYOUT_DIAGNOSTIC=RUNNING_NET0_ONLY
CT126_LAYOUT_DIAGNOSTIC=RUNNING_NET0_ONLY
INDEPENDENT_CONSOLE_ACCESS=NOT_ATTESTED_BY_THIS_AUDIT
FULL_NETWORK_CLEARANCE=NOT_PROVEN
NETWORK_CHANGES=NONE
APPLY_AUTHORIZED=False
```

**Eindeutig lokalisierter technischer Blocker:**
Das manuelle, ausschließlich auf dem `bp-controller`
gehaltene IPAM-Manifest ist noch nicht für alle drei
Netzwerkbereiche als vollständig bestätigt. Alle
elf anderen technischen Gate-Kategorien bestanden.
Der frühere mutierende Apply blieb `changed=0`;
Bridge, NICs und Anwendungskonfigurationen blieben unberührt.

Das erneute Apply ist **nicht** deshalb zulässig,
weil elf von zwölf Gates bestanden haben. Für
`ansible/vars/bergen-ai-bridge-ipam.local.json`
müssen die tatsächlich erfassten Netzbereiche
`unifi`, `vpn`, `other_hosts` fachlich
überprüft, fehlende IPv4-CIDRs ergänzt und erst
danach die jeweiligen `complete`-Werte bestätigt
werden. Das bloße Umschalten auf `true` ohne
vollständige Netzwerkprüfung wäre keine
technische Freigabe. Die drei Bereiche umfassen:

- UniFi: VLANs, Netze, manuelle/statische Routen;
- VPN: aktive und ruhende WireGuard-/OpenVPN-
  oder andere Site-to-Site-Netze samt relevanten
  Peer-Präfixen und Remote-Netzen;
- Andere Hosts: NAS, Hypervisoren, VMs, Podman-/
  Docker-Overlays und externe statische Routen.

**Datensparsamer Inspektionsbefehl (bp-controller,
read-only, keine IP-Adressen in der Ausgabe):**

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path.home() / "bergen-platform-ai-private-bridge/ansible/vars/bergen-ai-bridge-ipam.local.json"
if p.is_symlink() or not p.is_file():
    raise SystemExit("IPAM_FILE=ABSENT_OR_UNSAFE")
v = json.loads(p.read_text())
for name in ("unifi", "vpn", "other_hosts"):
    entry = v["scopes"][name]
    print(f"{name.upper()}_COMPLETE={entry['complete']}")
    print(f"{name.upper()}_NETWORK_COUNT={len(entry['networks'])}")
PY
```

Für die eigentliche Bearbeitung
`nano ~/bergen-platform-ai-private-bridge/ansible/vars/bergen-ai-bridge-ipam.local.json`
oder einen anderen lokalen Editor benutzen. Das
Dokument bleibt gitignoriert; IPAM-Einträge,
VPN-Peer-Daten und private Netzwerkkonfigurationen
nicht ins Repository oder öffentliche Logs kopieren.

Der unabhängige Proxmox-Konsolenzugang muss
zusätzlich **tatsächlich getestet und durch den
Betreiber bestätigt** sein; die Diagnose
`NOT_ATTESTED_BY_THIS_AUDIT` ist keine Aussage,
dass er vorhanden oder funktionsfähig wäre.

**Nächste sichere Reihenfolge:** bestehendes
IPAM-Manifest read-only auf fehlende Kategorien
prüfen; Quellen vervollständigen; das schon
vorhandene `audit-bergen-ai-vmbr90-apply-gates-readonly.yml`
neu ausführen; erst bei **allen zwölf PASS** und
real geprüfter unabhängiger Konsole den Oneoff-Apply
separat autorisieren. Die eigentliche Ollama-
und Paperless-Endpunktumstellung ist anschließend
weiterhin ein anderer Change.


## Phase 1.3 – Vollständiger Live-Gateaudit (20.10.2026, 10:26)

Der Betreiber hat das strikt schreibgeschützte Playbook
`audit-bergen-ai-vmbr90-apply-gates-readonly.yml`
nach Vervollständigung des ausschließlich lokal gespeicherten
IPAM-Inventars ausgeführt:

```text
AUDIT=READ_ONLY
CHANGED=False
IPAM_DECLARED_RANGES=PASS
IPAM_SCOPE_COMPLETE=PASS
BRIDGE_UNUSED=PASS
CT110_CT126_CT120_NIC_BASELINE=PASS
LXC_PODMAN_NETWORK_RANGES=PASS
LIVE_WIREGUARD_RANGES=PASS
HOST_AND_CT_CONFIG_READABLE=PASS
BACKUP_NFS=PASS
CT110_RECENT_BACKUP_METADATA=PASS
CT126_RECENT_BACKUP_METADATA=PASS
HOST_IFUPDOWN2_DROPIN_PRECHECK=PASS
CT110_CT126_RUNNING_NET0_ONLY=PASS
HOST_SOURCE_DIAGNOSTIC=EXPLICIT_SOURCE_NO_PENDING_EDIT
CT110_LAYOUT_DIAGNOSTIC=RUNNING_NET0_ONLY
CT126_LAYOUT_DIAGNOSTIC=RUNNING_NET0_ONLY
INDEPENDENT_CONSOLE_ACCESS=NOT_ATTESTED_BY_THIS_AUDIT
FULL_NETWORK_CLEARANCE=NOT_PROVEN
NETWORK_CHANGES=NONE
OLLAMA_CHANGED=NO
PAPERLESS_CHANGED=NO
APPLY_AUTHORIZED=False
```

Ansible-Rekapitulation:
`localhost ok=6 changed=0 failed=0`;
`venombox ok=36 changed=0 failed=0`.
Alle zwölf implementierten **technischen** Gates erfüllen
den erforderlichen Vergleichswert. Die IPAM-Vollständigkeit
ist eine Erklärung des Betreibers; keine unabhängige
UniFi-/Offhost-Netzerhebung fand statt.

**Noch erforderliche Freigabe vor dem ersten mutierenden
Apply:** Unabhängigen Proxmox-Konsolenzugang und wirksame
Rollback-Bedienbarkeit tatsächlich prüfen und attestieren.
`INDEPENDENT_CONSOLE_ACCESS=NOT_ATTESTED_BY_THIS_AUDIT`
ist ausdrücklich *kein* positiver Konsolennachweis.
`ROLLBACK_CLEARANCE=NOT_PROVEN` aus dem gesonderten
Baseline-Audit gilt weiterhin für den nicht ausgeführten
Restore-Test. Auch erfolgreiche Metadatenchecks ersetzen
keinen getesteten Container-Restore.

Es wurden weder `vmbr90` noch `net1` erzeugt;
CT110, CT126, Ollama und Paperless blieben unverändert.
Die spätere Ollama-Endpunktbindung und native
Paperless-LLM-Katalogisierung bleiben unabhängige
Änderungen. PR bleibt Draft bis zur Produktionsverifikation.


## Phase 1.4 – Pause ohne unabhängigen PVE-Konsolenzugang (20.10.2026)

Der Betreiber hat ausdrücklich bestätigt, dass für `venombox`
**kein getesteter, von SSH unabhängiger Konsolenzugang**
zur Verfügung steht. Entscheidung: **vmbr90-Apply zurückstellen**.
Der positive 12/12-Netz-Audit ersetzt weder den realen
Out-of-band-Zugang noch die Fähigkeit, eine verlorene
Managementverbindung bei einem Proxmox-Network-Change
wiederherzustellen.

Ab jetzt für die Bridge:
- `apply-bergen-ai-vmbr90-transport-once.yml` nicht ausführen;
  `CONSOLE_VERIFIED_AND_ROLLBACK_AVAILABLE` darf nicht bloß
  zum Bestehen einer Assertion gesetzt werden.
- Keine CT110-/CT126-`net1`-Schnittstelle, kein Bridge-Drop-in,
  kein `ifup vmbr90`, keine Ollama-Bind-Änderung oder
  neue Host-/Guest-Firewallregel über diesen Change.
- Der bisherige Proxmox-/IPAM-/Backup-Audit ist als
  **historische** nicht-mutierende Evidenz archiviert,
  keine dauerhaft gültige Produktivfreigabe.
- Eine spätere Wiederaufnahme erfordert eine neue
  ausdrückliche Betreiberentscheidung, echte unabhängig
  getestete Konsole, frische Same-Run-Preflights und
  geprüfte Rückfallmöglichkeit.

**Neuer priorisierter Arbeitsstrang:** Native Paperless-
Posteingangskatalogisierung nach Draft-PR #114 über
die bereits im echten Paperless-Podman-Namespace
nachgewiesene Verbindung zur Bergen-AI-Ollama-API.
Diese Änderung ist **nicht** durch den pausierten
vmbr90-Apply freigegeben.

**Separater Security-Blocker für Paperless:** Der aktuelle
Ollama-Wildcard-Listener auf TCP/11434 war auch vom
nicht autorisierten `bp-controller` über IPv4 und IPv6
erreichbar (TCP-Test). Vor jeder produktiven
Paperless-Modell-/Endpoint-Konfigurationsänderung oder
Dokumentverarbeitung muss ein wirksames, auf die
autorisierten Clients begrenztes Zugriffskonzept
vorliegen und positiv/negativ getestet werden. Auch
eine mögliche Firewall-Änderung darf nicht durch
falsche OOB-Attestierungen oder einen ungeprüften
Host-Network-Apply erzwungen werden.

Bis dahin nur kontrollierte Read-only-Inspektionen
und Code-/Testvorbereitung; keine Paperless-
Metadatenänderung und keine Timeraktivierung.
