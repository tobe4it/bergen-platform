# Bergen-AI – isolierte interne Proxmox-Bridge (Konzept / Preflight)

**Stand 19.10.2026. Kein produktiver Apply freigegeben.**

## Ziel

Eine dedizierte, auf `venombox` lokal gebridgte KI-Transportebene für
**Bergen-AI / Ollama (LXC 110)** und **Paperless (LXC 126)**.
**Bergen-syslog (LXC 120)** soll später unter eigener Freigabe folgen.
Die vorhandenen Netzinterfaces, DNS/LDAP/OIDC, Mail-/Syslog-Einspeisung und
Rückwege dürfen bei der Einführung nicht verändert werden.

Ollama ist derzeit über eine IPv6-Wildcard und effektiv auch über IPv4
auf Port 11434 erreichbar. Der im Oktober ausgeführte **nicht autorisierte
bp-controller-TCP-Test** war für beide Adressfamilien erfolgreich.
Eine neue Bridge ALLEIN beseitigt diese Angriffsfläche **nicht**.
Die bisherige Paperless-Ollama-Verbindung funktioniert bereits.
Sie wird erst dann bewusst umgestellt, wenn das private Netz und alle
Rollback-Gates geprüft sind.

## Technische Zieltopologie (nicht implementiert)

```text
                       venombox (Proxmox)
 ┌─────────────────────────────────────────────────────────┐
 │                                                         │
 │ LXC110 bergen-ai            LXC126 bergen-paperless     │
 │  ├── net0: unverändert       ├── net0: unverändert      │
 │  └── net1: 172.30.110.2/28   └── net1: 172.30.110.3/28 │
 │              │                          │                │
 │              └──────── vmbr90 ──────────┘                │
 │                     kein physischer Uplink              │
 │                     keine Host-IP / kein Gateway        │
 │                                                         │
 │  LXC120 bergen-syslog (später, extra Freigabe)          │
 │  └── mögliche net1: 172.30.110.4/28                     │
 └─────────────────────────────────────────────────────────┘
```

**Namenskonvention:** `vmbr90` ist ein lokaler Linux-Bridge-Name und kein UniFi-VLAN 90. Die Ziffernfolge einer Proxmox-Bridge hat keine automatische Beziehung zu einer UniFi-VLAN-ID. Der zuvor vorgeschlagene Name `vmbr10` wurde verworfen, weil das UniFi-Netz `unifi` bereits VLAN-ID 10 verwendet und gleiche Nummern hier verwirren würden. Die neue Bridge muss ohne Uplink/Bridge-Port, VLAN-Tag und Gateway bleiben. Die Eignung von `vmbr90` ist noch **nicht** geprüft.

**Vorläufige** Bridge `vmbr90`; **vorläufiges** RFC1918-/28-Netz
`172.30.110.0/28`. Adressen sind **nicht reserviert/zugewiesen**.
Der initiale Audit prüft Host und LXC110/126/120 auf sichtbare
IPv4-Adress-/Routingüberlappungen und die Bridge-Namensbelegung; er
kann nicht alle VPN-, UniFi-, Docker-/Podman-, Fremdhost-, Off-Host-
oder nicht laufenden Namespace-Netze ausschließen. Der Betreiber
muss das Subnetz deshalb vor dem Deploy zusätzlich gegen das
vollständige IPAM/UniFi- und VPN-Inventar prüfen.

Eine mögliche **Basisdefinition**, erst nach Freigabe anzuwenden:

```ini
auto vmbr90
iface vmbr90 inet manual
    bridge-ports none
    bridge-stp off
    bridge-fd 0
```

Diese Bridge erhält weder IPv4- noch IPv6-Hostadresse, physisches
Interface, VLAN-Trunk noch IP-Gateway. Die zusätzlichen CT-Interfaces
werden mit **festen IPv4-Adressen ohne Default-Route** versehen,
`firewall=1` allein ist **kein** Filterbeweis.

Wichtig: Dual-Homing jedes LXC bedeutet, dass ein kompromittierter
LXC potentiell zwischen seinen beiden Interfaces weiterleiten könnte,
falls Forwarding/NAT später aktiviert wird. Isolation muss an der
Anwendungsbindung und ergänzend an Gast-/Proxmox-Firewall geprüft werden.
Eine interne Bridge ersetzt **keine** pro-Anwendung Authentifizierung,
keine Dokument-ACL und nicht den Schutz gegen unbefugte App-Clients.

## Schritt 0 – read-only Preflight (als einziger Schritt implementiert)

Ansible-Playbook:

`ansible/playbooks/audit-bergen-ai-private-bridge-readonly.yml`

Auf bp-controller:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
git -C "$BASE" fetch origin feat/bergen-ai-private-bridge-20261019
if test -e "$WT/.git"; then
  git -C "$WT" switch --detach \
    origin/feat/bergen-ai-private-bridge-20261019
else
  test ! -e "$WT"
  git -C "$BASE" worktree add --detach "$WT" \
    origin/feat/bergen-ai-private-bridge-20261019
fi
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-readonly.yml \
  --syntax-check

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-readonly.yml \
  --vault-id ai@prompt
)
```

Der Audit prüft ausschließlich:

- Existenz von `vmbr90` im Host-Kernel und in `/etc/network/interfaces*`.
- Verweise auf `vmbr90` in PVE-LXC/VM-Konfigurationen.
- Identität und Zahl der NICs in LXC110, LXC126, LXC120.
- IPv4-Routen und Interface-Netze des PVE-Hosts sowie dieser
  **drei** LXCs auf Konflikte mit dem **vorgeschlagenen** /28.

Er gibt ausschließlich nichtidentifizierende Zustandskategorien
aus. Keine internen Ist-IP-Adressen, MACs, Routenzeilen,
Benutzeridentitäten, Log- oder OCR-Inhalte. Keine Netzpakete,
KI-Aufrufe, PVE-Änderungen, Neustarts oder Anwendungs-Updates.

Auch `STATUS=CANDIDATE_LOCALLY_UNCONFLICTED` bedeutet **NICHT**,
dass die Bridge oder das Subnetz endgültig freigegeben sind:
`SUBNET_CLEARANCE=NOT_PROVEN` und `APPLY_AUTHORIZED=False`.

## Live-Befund vmbr90 / Phase 0 (19.10.2026)

Der Betreiber hat den ersten, schreibgeschützten Preflight auf
`venombox` mit `ok=7, changed=0, failed=0` abgeschlossen:

```text
STATUS=CANDIDATE_LOCALLY_UNCONFLICTED
BRIDGE_CANDIDATE=vmbr90
BRIDGE_KERNEL=ABSENT
BRIDGE_CONFIG=ABSENT
BRIDGE_GUEST_REFERENCES=NOT_REFERENCED_IN_SCANNED_GUESTS
CT110_NETWORK_INTERFACE_COUNT=1
CT126_NETWORK_INTERFACE_COUNT=1
CT120_NETWORK_INTERFACE_COUNT=1
SCOPED_IPV4_ROUTE_OVERLAP=NO_OVERLAP_IN_SCOPED_ROUTES
SUBNET_CLEARANCE=NOT_PROVEN
PROXMOX_APPLY_GATE=BLOCKED_PENDING_REVIEW
INFERENCE_API_ACCESS_GATE=BLOCKED_PENDING_RESTRICTED_BIND_AND_TEST
```

Die Bridge ist nach dem geprüften lokalen Inventar **frei**.
Die provisorische Netzplanung ist dadurch **nicht** freigegeben.

### Phase 0b – weitere LXC- und Container-Subnetze (read-only)

Die ergänzende Prüfung
`ansible/playbooks/audit-bergen-ai-private-bridge-extended-readonly.yml`
liest die erkannten statischen LXC-Netzdefinitionen und die
IPv4-Adressen und Routen aller **laufenden** Proxmox-LXC auf
`venombox`. Zusätzlich werden die Podman-Netzdefinitionen
von LXC 110 und 126 sowie Docker-Netzdefinitionen auf dem
Proxmox-Host (falls installiert) gegen das vorgeschlagene
`172.30.110.0/28` abgeglichen. Sie verändert nichts und
gibt ausschließlich klassifizierte Befunde aus.

Nach erfolgreicher GitHub-CI auf `bp-controller` ausführen:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
cd "$WT"
git fetch origin feat/bergen-ai-private-bridge-20261019
git switch --detach origin/feat/bergen-ai-private-bridge-20261019
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-extended-readonly.yml \
  --syntax-check
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-extended-readonly.yml \
  --vault-id ai@prompt
)
```

Eine der Antwortkategorien kann `SCOPED_AUDIT_INCOMPLETE`
sein, beispielsweise bei einem nicht verfügbaren Podman-Netzwerk,
fehlenden Gast-Tools, dynamischen/gestoppten Netzen oder
nicht lesbaren Laufzeit-Routen. Das ist **kein** Grund,
einen Dienst umzukonfigurieren, sondern ein Auftrag zur
gezielten weiteren read-only Diagnostik.

Auch `NO_OVERLAP_IN_SCANNED_DOMAINS` bleibt beschränkt:
UniFi- und VPN-Netze, QEMU-Gastbetriebssysteme, nicht laufende
Podman-Namespaces sowie Netze auf anderen Hosts und zukünftige
Adressen sind nicht nachgewiesen. Deshalb meldet der Audit
immer `FULL_NETWORK_CLEARANCE=NOT_PROVEN` und
`APPLY_AUTHORIZED=False`. Es erfolgt keine Proxmox-Bridge-/
LXC-NIC-Anlage, Routing-, Firewall- oder Ollama-Konfigurationsänderung.
### Live-Ergebnis Phase 0b – 19.10.2026

Der Betreiber hat die erweiterte Bestandsaufnahme ebenfalls erfolgreich
durchgeführt (`ok=7`, `changed=0`, `failed=0`):

```text
STATUS=NO_OVERLAP_IN_SCANNED_DOMAINS
BRIDGE_CANDIDATE=vmbr90
SUBNET_CANDIDATE=172.30.110.0/28
ALL_LXC_NETWORKS=NO_OVERLAP_IN_SCANNED_GUESTS
LXC_TOTAL=16
LXC_RUNNING=13
LXC_STOPPED=3
PAPERLESS_PODMAN=NO_OVERLAP_IN_SCANNED_NETWORKS
BERGEN_AI_PODMAN=NO_OVERLAP_IN_SCANNED_NETWORKS
PVE_HOST_DOCKER=NOT_INSTALLED
FULL_NETWORK_CLEARANCE=NOT_PROVEN
```

Interpretation: Im dokumentierten Prüfumfang kollidiert weder ein
untersuchtes LXC-Netz noch ein inventarisiertes Podman-Netz mit
dem vorgeschlagenen /28. Die 3 gestoppten LXCs wurden anhand
ihrer **statischen** `pct config`-Netzangaben erfasst, nicht
über aktive Laufzeitinterfaces. Weitere Netzwerk-Namespaces und
dynamisch vergebene IPs bleiben außerhalb des Nachweises.

Der Betreiber hat zudem eine UniFi-Netzwerkliste vorgelegt;
die darin sichtbaren IPv4-Subnetze liegen ausschließlich im
Bereich `192.168.0.0/16` und überschneiden sich nicht mit
`172.30.110.0/28`. Das ist eine Sichtprüfung der gezeigten
UniFi-Netzwerke, keine vollständige IPAM- oder WireGuard-Prüfung.

**Freigabestatus: Planung plausibel, produktiver Apply weiterhin
gesperrt.** Folgende Nachweise fehlen vor dem Einrichten:

1. Alle relevanten WireGuard-/Site-to-Site-/Remote-VPN-Netze
   und `AllowedIPs` auf Konflikte gegen das /28 prüfen;
   zusätzlich andere Hypervisoren, NAS und externe VM-Netze
   in die IPAM-Prüfung einbeziehen.
2. Für `venombox` eine wiederherstellbare Sicherung von
   `/etc/network/interfaces` und `/etc/network/interfaces.d/`,
   den aktuellen `pct config` von CT110/CT126 sowie den
   Ollama- und Open-WebUI-Verbindungseinstellungen belegen.
3. Einen funktionierenden Wiederherstellungszugang zum
   PVE-Host und einen Rollback auch bei unerwartetem
   Verlust der primären SSH-Verbindung nachweisen.
4. Nach separater Freigabe zuerst nur die Bridge und
   sekundären, gatewaylosen Interfaces anlegen; keine
   Änderung an `net0`, bestehenden IPs oder Default-Routen.
5. Ollama ausschließlich nach geprüftem Paperless-Podman
   Positivtest auf die interne Adresse binden und
   Open WebUI lokal weiterhin erreichbar halten.
6. Die alte API-Erreichbarkeit vom bisher unautorisierten
   `bp-controller` über IPv4 **und** IPv6 muss anschließend
   negativ getestet und gegebenenfalls durch einen
   expliziten Host-/LXC-Filter zusätzlich abgesichert werden.

**Keine** der Phasen wird durch einen erfolgreichen
Read-only-Audit automatisch autorisiert. Syslog CT120 erhält
bei dieser Migration noch kein zusätzliches Interface.

### Phase 0c – Aktive lokale WireGuard-Routen (read-only)

Da die vorigen Host-/LXC-/Podman-Prüfungen keine Überschneidung mit
`172.30.110.0/28` ergaben und die gezeigten UniFi-Subnetze
aus `192.168.0.0/16` stammen, ist die nächste verbleibende
technische Kollisionsklasse ein aktivierter VPN-AllowedIPs-Prefix.

Der zusätzliche Audit
`ansible/playbooks/audit-bergen-ai-private-bridge-wg-readonly.yml`
prüft ausschließlich die **live** WireGuard-`AllowedIPs` der
Peerlisten auf `venombox` sowie in den verifizierten LXCs 110,
126 und 120. Er zeigt weder Peer-Schlüssel noch tatsächliche
Netzwerkadressen, Interface-Namen oder Tunnelkonfigurationen.
Das Tool führt keine WireGuard-Konfigurationsänderung und
keinen Netzwerkverbindungsversuch aus.

Auf `bp-controller`, im bestehenden Private-Bridge-Worktree:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-ai-private-bridge"
git fetch origin feat/bergen-ai-private-bridge-20261019
git switch --detach origin/feat/bergen-ai-private-bridge-20261019
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-wg-readonly.yml \
  --syntax-check
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-wg-readonly.yml \
  --vault-id ai@prompt
)
```

Die Ausgabe `NO_OVERLAP_IN_INSPECTED_LIVE_WG_PEERS` besagt
**ausschließlich**, dass keine Kollision in den gerade aktiven
WireGuard-Peer-Prefixen der vier geprüften Systeme entdeckt
wurde. `NOT_INSTALLED` und `NO_ACTIVE_PEER_PREFIXES` sind
ebenfalls keine Aussagen über abgeschaltete Konfigurationen.
Eine aktuelle Peer-Liste kann `0.0.0.0/0` enthalten;
dies gilt bewusst als Prefix-Überlappung und erfordert
eine separate Routing-/Prioritätsbewertung statt einer
vorschnellen Freigabe.

Nicht aktive Tunnel, UniFi-WireGuard, VPNs auf MX-/NAS-/anderen
Systemen, Site-to-Site-Partner und Drittanbieter-Subnetze
werden nicht geprüft. Die endgültige IPAM-Freigabe bleibt
deshalb bei jedem Audit-Ergebnis offen:
`FULL_NETWORK_CLEARANCE=NOT_PROVEN`, `APPLY_AUTHORIZED=False`.

Der folgende Schritt vor einem produktiven Netzwerk-Apply ist
ein dokumentiertes und geprüftes Restore-/Rollback-Verfahren,
einschließlich Zugang zu Proxmox außerhalb des neu anzulegenden
KI-Netzes; bisher sind weder Bridge noch zusätzliche LXC-NICs
freigegeben.
## Nach dem Audit – gesondert freizugebende Phasen

**Phase 1 – Sicherheits-/Rollback-Design:**
Eindeutiger Subnetzabgleich mit allen eigenen Netzen, Bridges,
VPNs und dem UniFi-Controller. Prüfen, wie Paperless-Podman seine
Quelladresse NATet. Ermitteln, ob weitere lokale Anwendungen
bereits direkt Port 11434 verwenden. Dokumentieren, welches
System die Bridge konfigurieren darf und wie ein Ansible-Playbook
sie idempotent anlegt. Vor einem produktiven Apply Snapshot /
Konfigurations-Backups und sicheren Out-of-band-Zugriff prüfen.
Rollback: letzte bekannte `/etc/network/interfaces`-Version,
zusätzliche `net1`-Konfigurationen und Ollama-/Open-WebUI-
Backend-Variablen gesondert versioniert sichern.

**Phase 2 – Transport-Test ohne produktive Umstellung:**
`vmbr90` zuerst als reinen lokalen Switch anlegen; erst nach
vorheriger Prüfung nur die zusätzlichen CT-Interfaces einhängen,
bestehende `net0` und Default-Routen nicht ändern. Jeweils
einmalige Erreichbarkeitstests zwischen LXC110 und Paperless
aus der **echten Paperless-Podman-Anwendung**, inkl. gesonderter
Prüfung, ob Podman-NAT den Gast-zu-Gast-Pfad beeinträchtigt.
Weder Paperless-LLM-Konfiguration noch globale KI/RAG aktivieren.

**Phase 3 – Ollama-Exposition einschränken:**
Den Ollama-Dienst auf die **interne IP** statt der bisherigen
IPv6-Wildcard binden und den lokalen Open-WebUI-Client gezielt
auf diesen Endpoint umstellen **nur unter eigenständigem
Wartungsfenster**. Das kann einen Ollama-Neustart erfordern;
diesen nicht stillschweigend auslösen. Prüfen, dass Open WebUI
und Paperless nach der Umstellung funktionieren und dass
bp-controller/ungewollte LAN-Clients die alte IPv4- und IPv6-
Endpunktverbindung **nicht** mehr aufbauen können. Ein gültiger
host-/CT-seitiger Filter kann als Defense-in-Depth hinzukommen.
Niemals `OLLAMA_HOST=0.0.0.0` oder `[::]` als endgültige
Freigabe behandeln.

**Phase 4 – Paperless-LLM-Katalogisierung:**
Erst nach sauberer Verbindung sowie Prüfung von Backup,
Paperless-Konfigurationsfingerprint, Eltern-ACL und
Datensparsamkeit den separat geschützten LLM-Konfigurations-
Apply aus Paperless-Draft-PR #114 behandeln. Ein-Dokument-
Pilot und automatischer Timer sind unabhängige Freigaben.
Das Inbox-Tag bleibt bis zur menschlichen Prüfung bestehen.
Globale Paperless-KI-Oberfläche, Embeddings und RAG bleiben
aus, bis eine separate Entscheidung getroffen wird.

**Phase 5 – später:** LXC120 bergen-syslog via eigene Freigabe;
Loganalyse liest und anonymisiert nur begrenzte Zeitfenster
(inkl. Postfix/Dovecot aus der zentralen Syslog-Sammlung).
Keine eigenständige Mail-KI-Netzroute und keine automatisch
ausgeführten LLM-Betriebseingriffe. Für weitere Kunden ist ein
authentifizierter Inferenz-Proxy mit Quoten und unabhängigen
Service-Identitäten vorgesehen.

## Betriebsgrenzen

- Kein Merge nach `main` bedeutet keine produktive Aktivierung.
- `ansible --check` ist kein Ersatz für den kontrollierten
  Netzwerk-Rollback bei späteren Anwendungen.
- Proxmox-Hostmanagement, Backup-NFS, LDAP, Paperless-SSO und
  bestehender Daten-/Internetpfad dürfen nicht unterbrochen werden.
- `bergen-syslog` und andere künftige KI-Clients werden **nicht**
  schon bei der Paperless-Einführung freigeschaltet.


## Phase 0c – externe Netzbereiche und Rollback-Belege (read-only)

Der weitere, **nicht schreibende** Preflight
`ansible/playbooks/audit-bergen-ai-private-bridge-external-gates-readonly.yml`
hat zwei unabhängig begrenzte Teile:

1. **Auf dem bp-controller (localhost):** Ein ausschließlich lokal gehaltenes,
   manuell aus der UniFi-Konfiguration, allen WireGuard-/Site-to-Site-/
   Remote-VPN-Konfigurationen und den übrigen Hosts/Hypervisoren/NAS
   zusammengestelltes CIDR-Inventar wird gegen `172.30.110.0/28` geprüft.
   `0.0.0.0/0` als Full-Tunnel-`AllowedIPs` wird als Sonderfall zur
   Prüfung klassifiziert, nicht als eindeutige Netzbelegung. Es gibt **keine**
   UniFi-API-Abfrage, keine VPN-Anmeldung und keine Netzwerkverbindung.
2. **Auf venombox:** Lesbarkeit der Netzwerkquellen und der bisherigen
   `pct config`-Bestände 110/126, lokale WireGuard-`AllowedIPs` (falls
   `wg` verfügbar), NFS-Mount-Metadaten und allenfalls vorhandene aktuelle
   `vzdump-lxc-110/126`-Dateimetadaten. Es werden **keine** Backup-Inhalte
   gelesen, Sicherungen erzeugt, Geräte konfiguriert oder Pakete versendet.

Ein solches Host-Inventar kann keine externen VPN-Netze, keine PBS-Backups,
keinen funktionierenden Restore und keinen Konsolenzugriff bescheinigen.
Daher bleiben **`FULL_NETWORK_CLEARANCE=NOT_PROVEN`**,
**`ROLLBACK_CLEARANCE=NOT_PROVEN`** und
**`APPLY_AUTHORIZED=False`** bei **jedem** Ergebnis.

### Lokales Netz-Inventar vorbereiten

Die lokale Datei wird nicht eingecheckt. Die drei Kategorien müssen
vollständig geprüft werden, bevor `complete` in der jeweiligen Kategorie
auf `true` gesetzt wird:

- `unifi`: alle UniFi-Netze, VLANs sowie relevante Controller-Routen;
- `vpn`: alle Tunnelnetze, WireGuard-AllowedIPs und Site-to-Site-Routen,
  auch auf anderen Geräten als venombox;
- `other_hosts`: andere Hypervisoren, VMs, NAS, Container-Overlays,
  statische Routen und bekannte zukünftige reservierte Subnetze.

Leere Listen mit `complete: true` sind eine reine **Operator-Erklärung**,
kein unabhängiger Beweis. Zusätzliche Netze im Eigentümerbereich sind
einschließlich Supernetzen anzugeben. Die Datei darf **keine Tokens,
Passwörter, privaten Schlüssel oder Konfigurationsdumps** enthalten.

Auf `bp-controller` im **bestehenden** Worktree:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
cd "$WT"
git fetch origin feat/bergen-ai-private-bridge-20261019
git switch --detach origin/feat/bergen-ai-private-bridge-20261019

IPAM="$WT/ansible/vars/bergen-ai-bridge-ipam.local.json"
test ! -L "$IPAM"
if test ! -e "$IPAM"; then
  install -m 0600 docs/examples/bergen-ai-bridge-ipam.local.json.example "$IPAM"
fi
# Eine bestehende lokale Datei niemals überschreiben.
# Die Datei anschließend im Editor vervollständigen.
# Der Standort ist ausschließlich im Feature-Worktree gitignored.
"$BASE/.venv/bin/python3" -m unittest discover -s tests \
  -p 'test_bergen_ai_private_bridge_external_gates.py' -v
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-external-gates-readonly.yml \
  --syntax-check
)
```

Der Live-Lauf liest die lokale Datei standardmäßig relativ zum
aktuellen Worktree, ohne einen Dateipfad per `-e` zu übergeben:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-external-gates-readonly.yml \
  --vault-id ai@prompt
)
```

Die Beispielvorlage beginnt bewusst mit drei unbestätigten Bereichen.
`IPAM_STATUS=NO_OVERLAP_IN_DECLARED_RANGES` bedeutet **nur**, dass
die eingegebenen CIDRs sich nicht schneiden.
`SCOPE_COVERAGE=OPERATOR_DECLARED_COMPLETE` ist eine
Selbsterklärung zur Erfassungsabdeckung, keine Freigabe.

Für einen späteren Change sind weiterhin **separate** Nachweise erforderlich:
konsistente, verschlüsselt verwahrte Kopien der PVE-Netzwerk-Konfiguration,
`pct config` 110/126, Ollama-/Open-WebUI-Verbindungsparameter,
**wiederherstellbare** Sicherungen von LXC110/126 einschließlich persistenter
Daten, getesteter Restore und unabhängig funktionierender
Out-of-band-/Konsolenzugriff. Weder die Existenz einer `vzdump`-Datei
noch eine lesbare aktuelle Konfiguration erfüllen diese Gates. Keine
Bridge-/NIC-/Firewall-/Ollama-Änderung wird in diesem Schritt durchgeführt.

**Separate Freigabe vor produktivem Apply erforderlich.**


### Live-Befund Phase 0c (19.10.2026, erster Lauf)

Auf `bp-controller` ausgeführt: localhost `ok=6 changed=0 failed=0`,
`venombox ok=7 changed=0 failed=0`.

```text
IPAM_STATUS=NO_OVERLAP_IN_DECLARED_RANGES
IPAM_SCOPE_COVERAGE=OPERATOR_DECLARED_INCOMPLETE
IPAM_SOURCE_QUALITY=MANUAL_INPUT_NOT_INDEPENDENTLY_VERIFIED
HOST_STATUS=REVIEW_INCOMPLETE
HOST_NETWORK_CONFIG=READABLE_SOURCE_ONLY
CT110_CONFIG=UNVERIFIED
CT126_CONFIG=UNVERIFIED
BACKUP_MOUNT=NFS_MOUNT_PRESENT_ONLY
CT110_BACKUP=NO_RECENT_FILE_METADATA
CT126_BACKUP=RECENT_FILE_METADATA_ONLY
PVE_LOCAL_WG=NO_OVERLAP_IN_LOCAL_WG_ALLOWED_IPS
CONFIG_BACKUP=NOT_ATTESTED
OLLAMA_WEBUI_CONFIG_BACKUP=NOT_ATTESTED
RESTORE_TEST=NOT_ATTESTED
OOB_CONSOLE=NOT_ATTESTED
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

**Ein Audit-Bug wurde danach identifiziert:** Die erste Version hatte
`r"^net0:\\s"` anstelle von `r"^net0:\s"`; das kann eine
normale `pct config`-Zeile `net0: name=…` nicht erkennen.
Die CT110-/CT126-`UNVERIFIED`-Werte aus diesem ersten Lauf sind daher
**kein Hinweis auf tatsächlich fehlende Netzinterfaces**. Korrektur und
Regressionstest sind im Feature-Branch, GitHub-CI erfolgreich. Der
**korrigierte Live-Lauf steht noch aus**.

Das Backup-Ergebnis für LXC110 betrifft ausschließlich die auf dem
angegebenen NFS-Mount unter `dump/` in den letzten sieben Tagen
erkannten `vzdump-lxc-110-*.tar.*`-Dateimetadaten. Es schließt ältere,
anders benannte oder extern gespeicherte Backups nicht aus. LXC126-
Dateimetadaten sind weder ein Integritäts- noch ein Restorebeweis.
Externe UniFi-/VPN-/Off-Host-Netze sind weiterhin unvollständig.
**Keine Apply-Erlaubnis.**


## Phase 0d – Proxmox-Backup-Storage-Inventur (Read-only, noch nicht live getestet)

Die Phase 0c fand auf dem direkt eingebundenen NFS unter `dump/` für LXC110
keine Archiv-Dateimetadaten mit Zeitstempel innerhalb von sieben Tagen. Das ist
**kein** Beleg für eine fehlende Sicherung. LXC126 hatte aktuelle Dateimetadaten,
aber ohne Integritäts- oder Restore-Nachweis.

Der zusätzliche Audit
`ansible/playbooks/audit-bergen-ai-private-bridge-backups-readonly.yml`
fragt ausschließlich über den lokalen `pvesh get`-Zugriff des Knotens
`venombox` die auf diesem Knoten **sichtbaren Proxmox-Storages mit
Backup-Inhalten** ab und liest deren Volumen-Metadaten. Er klassifiziert
LXC110 und LXC126 getrennt als aktuelle, ältere, unklare oder nicht
in den überprüften Storages beobachtete Archiv-Metadaten.

Damit prüfen wir auch alternative Proxmox-Storages, nicht nur
`/mnt/pve/bergen-synology-backup/dump`. Nicht erreichbare, deaktivierte,
externe oder anders verwaltete Speicher bleiben ausdrücklich außerhalb
eines vollständigen Nachweises. PBS-/NAS-Sicherungen, die nicht als
`vzdump-lxc-*.tar.*` in den abgefragten Volumenlisten erscheinen,
können unerkannt bleiben.

Auf `bp-controller` ausführen:

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
  ansible/playbooks/audit-bergen-ai-private-bridge-backups-readonly.yml \
  --syntax-check

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-private-bridge-backups-readonly.yml \
  --vault-id ai@prompt
)
```

Der Audit enthält keine Schreibbefehle; er meldet ausschließlich
Zustandskategorien ohne Volume-Namen, Zeitstempel, Dateiinhalte oder
Zugangsdaten. `CT110_BACKUPS=NONE_IN_SCANNED_STORAGES` bedeutet
**nicht**, dass überhaupt keine Sicherung existiert.
Selbst `RECENT_METADATA_ONLY` beweist weder valide Daten noch eine
wiederherstellbare Konfiguration. Laufender Proxmox-Backup-Plan,
Datenträgermounts, kryptographische Integrität, ein isolierter Restore-Test
sowie ein unabhängiger Host-Konsolenzugang sind vor einem
Netzwerk-Change weiter zu verifizieren.

**Unverändert:** `APPLY_AUTHORIZED=False`,
`FULL_NETWORK_CLEARANCE=NOT_PROVEN`,
`ROLLBACK_CLEARANCE=NOT_PROVEN`. Kein Merge nach `main`
und kein produktiver Proxmox-/Ollama-/Paperless-Apply.
