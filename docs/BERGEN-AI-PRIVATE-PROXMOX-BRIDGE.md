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


### Phase 0d Live-Befund – 19.10.2026, 20:46 (Europe/Berlin)

Operator-Ausführung auf `venombox`: Syntaxprüfung erfolgreich;
Live-Read-only-Audit `ok=7 changed=0 failed=0 unreachable=0`.

```text
STATUS=VISIBLE_STORAGES_SCANNED
STORAGE_COVERAGE=VISIBLE_ONLY
ACTIVE_BACKUP_STORAGES=2
CT110_BACKUPS=NONE_IN_SCANNED_STORAGES
CT126_BACKUPS=RECENT_METADATA_ONLY
BACKUP_INTEGRITY=NOT_TESTED
MOUNT_COVERAGE=NOT_ATTESTED
RESTORE_TEST=NOT_ATTESTED
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

**Bewertung:** In den zwei sichtbaren, abgefragten Proxmox-Backup-Storages
wurde kein `vzdump-lxc-110-*.tar.*`-Archiv gefunden. Ein aktuelles
klassisches LXC126-Archiv erscheint in den Metadaten. PBS-
Backupobjekte (`backup/ct/...`), alternative Dateinamen, externe
Systeme und nicht sichtbare Storages werden durch die eingeschränkte
Archivnamen-Erkennung nicht ausgeschlossen. **Keine** Aussage über
Vollständigkeit/Integrität von CT126-Mounts oder Restore-Fähigkeit.

LXC110 gilt bis zu einem überprüften Sicherungs-/Restore-Nachweis als
**Rollback-Gate offen**. Ein künftiger Sicherungsjob oder einmaliger
`vzdump` benötigt einen eigenen, expliziten Betreiberentscheid.


## Phase 0e – CT110 Sicherungsplan und Datenmounts (read-only, vorbereitet)

Wegen `CT110_BACKUPS=NONE_IN_SCANNED_STORAGES` untersucht eine zusätzliche
**nicht schreibende** Prüfung:
`ansible/playbooks/audit-bergen-ai-ct110-backup-policy-readonly.yml`.

Sie liest nur die aktuelle `pct config 110` und die im PVE-Cluster
sichtbaren `/cluster/backup`-Jobdefinitionen. Sie gibt ausschließlich
Kategorien aus:

- CT110-Rootfs in der Konfiguration vorhanden;
- zusätzliche LXC-Mountpoints, insbesondere Host-Bind-Mounts, vorhanden;
- explizite Mountpoint-`backup=1`-Flags beziehungsweise fehlende Flags;
- Proxmox-Backup-Jobs mit expliziter VMID-Auswahl oder `all`-Regel;
- nicht interpretierbare/fehlende Jobs verbleiben `UNVERIFIED` oder
  `NO_MATCH_IN_VISIBLE_PVE_JOBS`, **nie** „kein Backup existiert“.

Der Audit prüft **keine** lokalen Systemd-/Cron-Jobs, NAS-/PBS-Sicherungen,
Scheduler-Ausführung, Snapshot-Konsistenz, Archivintegrität oder
Restore-Fähigkeit. Besonders wichtig ist die Abgrenzung zwischen
`pct config`-Mountpoint-Flags und tatsächlich im Archiv enthaltenen
Inhalten. Ein `backup=1` ist dafür alleine kein Nachweis. Ein Bind-Mount
kann eine separate Sicherungsstrategie benötigen.

Abfrage auf `bp-controller`:

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
  ansible/playbooks/audit-bergen-ai-ct110-backup-policy-readonly.yml \
  --syntax-check

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-ct110-backup-policy-readonly.yml \
  --vault-id ai@prompt
)
```

Die Laufzeitabfrage erstellt **keine** Backups und ändert keine Timer,
Proxmox-Gäste, Netzwerke, Systemeinstellungen oder Daten. Eine
separate, explizit genehmigte Backup-Einrichtung und ein isolierter
Restore-Nachweis sind weiterhin erforderlich. **Alle Apply-Gates gesperrt.**


### Phase 0e – Live-Ergebnis (19.10.2026, 20:57 Europe/Berlin)

Der Operator hat `audit-bergen-ai-ct110-backup-policy-readonly.yml`
auf `venombox` ausgeführt: `ok=7 changed=0 failed=0 unreachable=0`.

```text
STATUS=POLICY_INVENTORY_ONLY
CT110_ROOTFS=CONFIGURED
CT110_EXTRA_MOUNTS=NONE
CT110_EXTRA_MOUNT_BACKUP_FLAGS=NO_EXTRA_MOUNTS
PVE_BACKUP_JOB_SELECTION=NO_MATCH_IN_VISIBLE_PVE_JOBS
VISIBLE_PVE_BACKUP_JOB_COUNT=0
OTHER_BACKUP_SYSTEMS=NOT_INSPECTED
MOUNT_CONTENT_BACKUP=NOT_PROVEN
CT110_BACKUP_SCHEDULE_EFFECTIVE=NOT_PROVEN
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

**Bewertung:** CT110 hat ein konfiguriertes LXC-Rootfs und keine
weiteren in der Proxmox-LXC-Konfiguration aufgeführten `mpN`-Mounts.
Die PVE-Cluster-API `/cluster/backup` meldet null sichtbare Jobs.
Das belegt ausdrücklich **nicht**, dass es keine lokalen Systemd-/
Cron-, Synology-, PBS- oder anderen Sicherungsmechanismen gibt.
Die vorangegangene Phase 0d hatte in zwei Proxmox-sichtbaren
Backup-Storages kein passendes klassisches CT110-Archiv nachgewiesen.
Damit ist eine geprüfte Sicherung für die bevorstehende Netzänderung
weiterhin **nicht belegt**.

**Abgrenzung der bestehenden Paperless-Backup-Rolle:**
`ansible/roles/proxmox_vzdump_backup` implementiert den gesondert
freizugebenden Systemd-Backup-Timer für CT126. Dessen feste
Sicherheitsannahmen (Gastidentität, `local-zfs`-Rootfs und
separater `mp0` mit `backup=1`) passen nicht direkt auf CT110.
Zudem verwendet dessen Service `vzdump --mode stop`, also
einen Backup-Modus, der eine Betriebsunterbrechung beinhaltet.
Weder Rolle noch Timer dürfen unverändert für CT110 aktiviert werden.

**Plan vor einer CT110-Sicherung (gesonderte Freigabe):**

1. In CT110 lesend prüfen, wo Ollama-Modelle, Open-WebUI-Daten,
   Container-Volumes und SQLite/andere persistente Daten liegen;
   auch innerhalb des Gasts eingehängte Dateisysteme und
   Ausschlussregeln prüfen. `CT110_EXTRA_MOUNTS=NONE` allein
   beweist keine vollständige Datensicherung.
2. Die tatsächlichen Backup-Jobs außerhalb der PVE-Cluster-API
   (Systemd-Timer, Cron, externe NAS-/PBS-Mechanismen) inventarisieren,
   um eine Doppelplanung und konkurrierende Rotationen zu vermeiden.
3. Das konkrete Host-Storage, freie Kapazität, NFS-Ziel, Zugriffsrechte
   und temporären Ablageplatz prüfen. Kein `prune` oder `--remove 1`
   ohne ausdrückliches Retention- und Schutzkonzept.
4. Snapshot- und Stop-Mode anhand des CT110-Storage und der
   notwendigen Applikationskonsistenz vergleichen. Ein Backup soll
   nicht ohne Genehmigung einen Stop/Restart von Bergen-AI auslösen.
5. Eine ausdrücklich freigegebene erste Sicherung als eigenes
   Change-Ereignis vorsehen; deren Existenz, Vollständigkeit,
   Archivintegrität und später ein **isolierter** Restore-Nachweis
   sind gesonderte Freigabeschritte.
6. Bestehende Paperless-Sicherungen unverändert lassen. Eine
   CT110-Automatisierung benötigt einen unabhängig freizugebenden
   Timer mit eigener Retention und nachgewiesenem Ausführungspfad.

**Netzwerk-Apply bleibt ausgeschlossen:** Externe UniFi-/VPN-Netze,
unabhängiger Proxmox-Konsolenzugriff, Konfigurations-Sicherungen und
Anwendungs-/Restore-Freigaben fehlen weiterhin. `vmbr90`,
LXC-`net1`, Ollama-Binding und Paperless bleiben unangetastet.


## Phase 0f – erste einmalige CT110-Sicherung (operatorfreigegeben, noch nicht ausgeführt)

**Freigabeumfang:** Der Betreiber hat die **einmalige Sicherung von
LXC 110 Bergen-AI** genehmigt. Kein regelmäßiger Job, keine Backup-Rotation,
keine Proxmox-/Netzwerkänderungen und kein Restore sind freigegeben.

Da der Proxmox-`stop`-Modus den Container über die gesamte
Archivierungsdauer anhalten kann, verwenden wir zunächst ausschließlich
`--mode snapshot`. Proxmox kann den Container dafür kurz suspendieren;
bei nicht unterstützter Snapshot-Fähigkeit **nicht** automatisch auf
`stop` oder `suspend` zurückfallen. Es gibt keine bewussten
`pct stop`-/`pct start`-/`pct reboot`-Kommandos. Ein Snapshot ist
dennoch kein Nachweis einer anwendungskonsistenten Wiederherstellung.

**Ziel:** genau CT110 auf dem schon verwendeten NFS-Storage
`bergen-synology-backup`, komprimiert als zstd-`vzdump`, ohne Entfernen
bisheriger Backups (`--remove 0 --prune-backups keep-all=1`), ohne
Systemd-Timer.

Zwei getrennte Playbooks:

- `preflight-bergen-ai-ct110-oneoff-backup-readonly.yml`: Gastidentität,
  laufender Zustand, `pct`-Rootfs ohne separate konfigurierte `mpN`,
  bekannte persistente Open-WebUI-Daten im Gast-Rootfs, tatsächlich
  erkannte weitere Dateisysteme im Gast, aktives NFS-Ziel, verfügbaren
  Platz am Ziel und in `/var/tmp` sowie ältere CT110-Archive auf dem
  gewählten Storage **ohne Änderungen** prüfen.
- `backup-bergen-ai-ct110-once.yml`: importiert den Preflight im
  **gleichen Lauf** und verlangt zusätzlich den exakten
  operatorseitigen Bestätigungstext
  `APPROVE_CT110_SNAPSHOT_BACKUP_ONCE`. Bei einem nicht eindeutig
  positiven Preflight wird `vzdump` **nicht gestartet**. Die Verifikation
  prüft anschließend, ob CT110 noch läuft und ein neues,
  nichtleeres Archiv im NFS-Storage als Metadatum sichtbar ist.
  Danach sind Backup-Datenintegrität, enthaltene Daten und Restore
  ausdrücklich **noch nicht attestiert**.

Die Gastprüfung ist konservativ. Wenn `podman`, Open WebUI oder Ollama
weitere Hostdaten außerhalb des LXC-Rootfs nutzen, eine Mount-Art nicht
erkannt wird oder der Proxmox-Storage sein Backup-Content-Flag nicht
liefert, muss zuerst die Herkunft verifiziert werden. **Keinesfalls**
nur zum Erzwingen eines grünen Status den Audit abschwächen.

### Auf bp-controller: erst read-only Preflight

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"

git -C "$WT" fetch origin feat/bergen-ai-private-bridge-20261019
git -C "$WT" switch --detach origin/feat/bergen-ai-private-bridge-20261019
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/preflight-bergen-ai-ct110-oneoff-backup-readonly.yml \
  --syntax-check
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/preflight-bergen-ai-ct110-oneoff-backup-readonly.yml \
  --vault-id ai@prompt
)
```

### Erst bei PRECHECK_PASSED und SAFE_TO_ATTEMPT_SINGLE_BACKUP=True

Dann (in einem `tmux`-Fenster auf `bp-controller`) **einmalig**:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/backup-bergen-ai-ct110-once.yml \
  --syntax-check
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/backup-bergen-ai-ct110-once.yml \
  -e bergen_ai_ct110_oneoff_approval=APPROVE_CT110_SNAPSHOT_BACKUP_ONCE \
  --vault-id ai@prompt
)
```

Nur der zweite Befehl der zweiten Gruppe enthält einen mutierenden
`vzdump`-Schritt; er ist **kein** Check-Mode-Aufruf. Fällt der
Snapshot-Backup-Lauf aus, darf er wegen einer möglichen Teilsicherung
nicht blind wiederholt werden. Der `rescue`-Zweig prüft den Gaststatus,
startet jedoch keinen Container neu. Mögliche Modell-/WebUI-
Funktionseinschränkungen während des Snapshot-Suspends sind vorher
betrieblich einzuplanen. Besonders wichtig: die fortlaufende Integrität
der SQLite-/Podman-Daten und die Wiederherstellbarkeit müssen durch
separate, später freizugebende Tests validiert werden.

**Nicht durch die Freigabe umfasst:** Änderungen an `vmbr90`,
`net1`, Ollama-Binding, Paperless-Konfiguration, Systemd-Timern,
Proxmox-Backuplaufplänen, Retention/Pruning, Host-Neustarts oder
irgendeine Bereinigung vorhandener Archive.


### Phase 0f – Live-Ergebnis: korrekt blockiert (19.10.2026)

Der Operator hat zunächst den CT110-Oneoff-Preflight und anschließend
das genehmigte Einmalsicherungs-Playbook ausgeführt. Beide haben
den gleichen Sicherheitsbefund geliefert:

```text
AUDIT=READ_ONLY
STATUS=REVIEW_REQUIRED
CT110_IDENTITY=EXTRA_MOUNTS_REQUIRE_REVIEW
WEBUI_DATA=UNVERIFIED
GUEST_MOUNTS=UNVERIFIED
BACKUP_TARGET=NFS_ACTIVE_WITH_FREE_SPACE
TEMP_SPACE=LOCAL_TMP_SPACE_OK
ARCHIVE_STATE=NO_CT110_ARCHIVE_ON_SELECTED_STORAGE
SAFE_TO_ATTEMPT_SINGLE_BACKUP=False
BACKUP_EXECUTED=False
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

Bei der genehmigten Einmalsicherung war das zusätzliche
Approval-Gate erfolgreich, das anschließende
`CT110_BACKUP_PREFLIGHT_REVIEW_REQUIRED` hat aber den
`vzdump`-Schritt **vorher** blockiert. `changed=0`, `failed=1`
bedeutet hier die erwartete fail-closed Sperre. **Keine**
Sicherung, kein Backup-Retry, kein Gast-Neustart.

Der ältere PVE-Backup-Policy-Audit meldete `CT110_EXTRA_MOUNTS=NONE`;
dieser ältere Scope zählt aber nur `mpN`-Zeilen. Der
Oneoff-Preflight sperrt vorsichtshalber auch
`lxc.mount.auto` und `lxc.mount.entry`. Insbesondere
`lxc.mount.auto` **kann** gewöhnliche virtuelle
Systemdateisysteme (proc/sys/cgroup) definieren, ohne eine
zusätzliche persistente Datenquelle zu bezeichnen. Es gibt
aber **noch keinen Beleg**, welcher Fall auf dem realen CT110
zutrifft.

### Phase 0f.1 – präzise Mount-Diagnose, read-only

`audit-bergen-ai-ct110-mount-directives-readonly.yml`
liest nur `pct config 110`, den CT110-Status und prüft die
bekannte Open-WebUI-Datenverzeichnis-Zuordnung **ohne** Inhalte,
Pfadnamen, Quellmounts oder andere Betriebsdetails auszugeben.
Es unterscheidet in Zustandskategorien:

- Proxmox-`mpN`-Direktiven vorhanden/fehlend;
- `lxc.mount.auto`: Standard-Pseudodateisysteme oder unbekannte Werte;
- `lxc.mount.entry`: Geräte-/Systemziele gegenüber sonstigen Zielorten;
- sonstige Hooks/Excludes vorhanden/fehlend;
- bekanntes persistentes Open-WebUI-Verzeichnis: Gast-Rootfs
  oder anderes Gast-Mount.

Die Ausgabe ist **Diagnostik, keine Freigabe**.
Auch bei Standard-Pseudomounts ist die reale Abdeckung
von Open WebUI, Ollama-Modellen, Podman-Volumes und
zusätzlichen Dateisystemen gesondert nachzuweisen.
Keine automatische Lockerung der Oneoff-Backup-Gates.

Auf bp-controller:

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
  ansible/playbooks/audit-bergen-ai-ct110-mount-directives-readonly.yml \
  --syntax-check

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-ct110-mount-directives-readonly.yml \
  --vault-id ai@prompt
)
```

**Bis zur Bewertung:** `backup-bergen-ai-ct110-once.yml` **nicht
erneut starten**. Alle Backup-, Timer-, Netzwerk- und
Inference-/Paperless-Apply-Gates bleiben gesperrt.


### Phase 0f.1 – Live-Befund und Präzisierung der Gerätequelle (19.10.2026)

Der Operator hat `audit-bergen-ai-ct110-mount-directives-readonly.yml`
erfolgreich mit `ok=7 changed=0 failed=0` auf `venombox` ausgeführt.

```text
CT110_CONFIG_IDENTITY=VERIFIED
PVE_MP_DIRECTIVES=NONE
PVE_MP_COUNT=0
LXC_MOUNT_AUTO=ABSENT
LXC_MOUNT_AUTO_COUNT=0
LXC_MOUNT_ENTRY=DEVICE_OR_PSEUDO_TARGETS_PRESENT
LXC_MOUNT_ENTRY_COUNT=1
OTHER_MOUNT_OR_EXCLUDE_DIRECTIVES=NONE
WEBUI_DATA_MOUNT=GUEST_ROOTFS
BACKUP_EXECUTED=False
BACKUP_AUTHORIZED=False
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

**Bewertung:** Das eine Mount-Ziel liegt in einem Geräte- oder
Pseudo-Systemverzeichnis; der tatsächliche Host-Quellpfad und die
Mount-Optionen waren im ersten Live-Audit **nicht** belegt. Das
Open-WebUI-Datenverzeichnis liegt dagegen nachweislich auf dem
Gast-Rootfs. Die vollständige Sicherbarkeit von Ollama-/Podman-Daten
und der gerätebezogene Host-Mount müssen weiter geprüft werden.

**Schärfung des bestehenden Read-only-Audits:** Der Bericht enthält jetzt
zusätzlich `LXC_MOUNT_ENTRY_DEVICE_ORIGIN`. Dazu wird **die gesamte**
Mount-Direktive geprüft und ausschließlich als exakt übereinstimmender
FUSE-/TUN-/DRI-Geräte-Bind oder als nicht ausreichend verifizierter
Mount eingeordnet. Insbesondere darf ein beliebiger Host-Quellpfad mit
`/dev` als Ziel **keine** positive Klassifikation erhalten. Es
werden keine Rohpfade oder Optionen ausgegeben, keine Änderungen
vorgenommen und **keine Backup-Freigabe** erteilt.

Auf `bp-controller` den aktuellen Code holen und nur das
Read-only-Playbook erneut ausführen:

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
  ansible/playbooks/audit-bergen-ai-ct110-mount-directives-readonly.yml \
  --vault-id ai@prompt
)
```

Erst nach diesem Ergebnis darf die **separat** konservativ zu
überarbeitende Sicherungs-Vorprüfung erneut erfolgen. Die bereits
genehmigte Einmalsicherung ist nach dem bisherigen Stand weiterhin
gesperrt: `SAFE_TO_ATTEMPT_SINGLE_BACKUP=False`.
Das bestehende mutierende Playbook `backup-bergen-ai-ct110-once.yml`
nicht erneut starten. Keine automatische Aufweichung der Gates.


### Phase 0f.1 – Live-Nachprüfung: Gerätequelle noch unbestimmt (19.10.2026, 21:34)

Beim zweiten Operator-Lauf der erweiterten Mount-Diagnose:
`venombox ok=7 changed=0 failed=0`.
`CT110_CONFIG_IDENTITY=VERIFIED`;
`PVE_MP_COUNT=0`, `LXC_MOUNT_AUTO_COUNT=0`;
`LXC_MOUNT_ENTRY_COUNT=1`,
`LXC_MOUNT_ENTRY=DEVICE_OR_PSEUDO_TARGETS_PRESENT`,
`LXC_MOUNT_ENTRY_DEVICE_ORIGIN=UNVERIFIED`,
`WEBUI_DATA_MOUNT=GUEST_ROOTFS`.
**Kein** Backup gestartet oder freigegeben.

Die Quell-/Options-Diagnose verlangte in ihrer ersten Version
ausnahmslos sechs Felder (`src dst none opts 0 0`).
LXC-`lxc.mount.entry` kann aber auch vier Felder
(`src dst none opts`) enthalten. Dies könnte das
`UNVERIFIED` verursachen; das tatsächliche Format des
CT110-Mounts ist aus der sanitisierten Ausgabe **nicht** erkennbar.

Der Read-only-Audit akzeptiert nach Korrektur beide
Schreibweisen **ausschließlich bei exakten, restriktiv
whitelisteten Geräte-Quell-/Ziel-/Options-Kombinationen**.
Zusätzlich `LXC_MOUNT_ENTRY_FORMAT` mit
`FOUR_FIELD_FORM`, `SIX_FIELD_FORM`, `OTHER_FIELD_COUNT`
oder `UNVERIFIED`. Andere Quellen oder abweichende Optionen
bleiben gesperrt (`SOURCE_OR_OPTIONS_REVIEW`).
Die Korrektur erweitert weder das erlaubte Geräteinventar
noch die Freigaben. Regressionstests und CI sind erfolgreich.

Der Operator muss nun denselben **read-only**
`audit-bergen-ai-ct110-mount-directives-readonly.yml`
erneut mit aktuellem Branch ausführen. Der mutierende
`backup-bergen-ai-ct110-once.yml` bleibt **gesperrt**.
Auch bei exakter Gerätebindung müssen die Ollama-/Podman-Daten
vor Backup-Apply überprüft werden.


### Phase 0f.1 – FUSE-Ursprung live bestätigt (19.10.2026, 21:40)

Der korrigierte Audit hat auf `venombox` ausschließlich lesend
`ok=7 changed=0 failed=0` ergeben. Die relevante Klassifikation:

```text
CT110_CONFIG_IDENTITY=VERIFIED
PVE_MP_DIRECTIVES=NONE
LXC_MOUNT_AUTO=ABSENT
LXC_MOUNT_ENTRY_COUNT=1
LXC_MOUNT_ENTRY=DEVICE_OR_PSEUDO_TARGETS_PRESENT
LXC_MOUNT_ENTRY_DEVICE_ORIGIN=EXACT_FUSE_DEVICE_BIND
LXC_MOUNT_ENTRY_FORMAT=FOUR_FIELD_FORM
OTHER_MOUNT_OR_EXCLUDE_DIRECTIVES=NONE
WEBUI_DATA_MOUNT=GUEST_ROOTFS
BACKUP_EXECUTED=False
BACKUP_AUTHORIZED=False
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

Der einzige zusätzliche LXC-Mount bindet **exakt `/dev/fuse` nach
`/dev/fuse`** mit erlaubten Geräte-Bind-Optionen ein. Das ist kein
separates persistentes Datenvolume; die bisherige pauschale
Mount-Sperre im CT110-Oneoff-Preflight war für diesen einzelnen Mount
zu konservativ.

**Offenes Gate:** Die tatsächliche Ollama-Modellablage und die
Podman-Speicherung müssen separat nachgewiesen werden, bevor ein
Backup gestartet werden darf. Weder die vorhandene Betreiberfreigabe
noch die nachgewiesene FUSE-Gerätequelle reichen allein aus.

### Phase 0f.2 – Ollama-/Podman-Datenabdeckung (read-only, vorbereitet)

Der eigenständige Audit
`ansible/playbooks/audit-bergen-ai-ct110-persistent-data-readonly.yml`
liest auf CT110 ohne Änderungen:

- laufenden Ollama-Service und dessen konfigurierte
  `OLLAMA_MODELS`-Zuordnung;
- `/srv/ai/models`: vorhanden und im Gast-Rootfs;
- Open-WebUI-Podman-`inspect`: genau die erwartete persistente
  `/app/backend/data`-Bind-Zuordnung zu `/srv/ai/open-webui`;
- Open-WebUI-Daten und Podman-Graphroot: im Gast-Rootfs;
- weitere rootverwaltete Podman-Container oder named volumes.

Ausgegeben werden ausschließlich feste Zustandskategorien.
Keine Konfigurationswerte, Modellbezeichnungen, Zugangsdaten,
Source-Mounts oder private Pfade aus Laufzeitdaten werden ausgegeben.
Dies ist eine **punktuelle, begrenzte Inventur** und keine
vollständige Datenintegritäts- oder Restore-Aussage. Rootless Podman,
andere Services, laufzeitabweichende Ollama-Prozessumgebungen und
Applikationskonsistenz erfordern bei Unklarheiten getrennte Prüfung.

Auf `bp-controller`:

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
  ansible/playbooks/audit-bergen-ai-ct110-persistent-data-readonly.yml \
  --syntax-check

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-ct110-persistent-data-readonly.yml \
  --vault-id ai@prompt
)
```

Selbst `STATUS=KNOWN_DATA_PATHS_IN_ROOTFS` darf
**nicht** automatisch `SAFE_TO_ATTEMPT_SINGLE_BACKUP=True`
setzen. Erst Live-Befund, Review und gezielt revidierter
Oneoff-Preflight (mit den bestehenden Geräte-/Datenkontrollen)
ermöglichen den ursprünglich genehmigten einmaligen
`vzdump`. Der mutierende Backup-Befehl bleibt bis dahin gesperrt.


### Phase 0f.2 – Live-Befund: bekannte Ollama-/Podman-Daten im LXC-Rootfs (19.10.2026, 21:47)

Auf `venombox` ausgeführt: `ok=7 changed=0 failed=0`.

```text
STATUS=KNOWN_DATA_PATHS_IN_ROOTFS
OLLAMA_CONFIG=EXPECTED_MODELS_LOCATION
OLLAMA_MODELS_MOUNT=GUEST_ROOTFS
WEBUI_PODMAN_BIND=EXACT_WEBUI_DATA_BIND
WEBUI_DATA_MOUNT=GUEST_ROOTFS
PODMAN_GRAPH_MOUNT=GUEST_ROOTFS
PODMAN_CONTAINERS=ONLY_OPEN_WEBUI
PODMAN_NAMED_VOLUMES=NONE
ALL_PERSISTENT_DATA_PROVEN=False
BACKUP_STARTED=False
BACKUP_AUTHORIZED=False
RESTORE_TEST=NOT_ATTESTED
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

Damit sind die bekannten Ollama-Modelle, Open-WebUI-Anwendungsdaten
und der rootverwaltete Podman-Graphroot auf dem CT110-Gast-Rootfs
nachgewiesen. Der vorherige Live-Audit identifizierte genau einen
`/dev/fuse`-Gerätebind mit vier Feldern, keine gesonderten
Proxmox-`mpN`-Datenträger und keine `lxc.mount.auto`-Direktiven.
Eine vollständige Dateninventur sämtlicher Rootless-/sonstiger
Services und ein Restore-Test bleiben ausdrücklich außerhalb
dieses engen Belegs.

### Phase 0f.3 – Oneoff-Preflight präzisiert (noch nicht live ausgeführt)

Die zuvor zu grobe Sperre für **jede** `lxc.mount.entry` wurde
durch eine **exakte**, auf die Live-Befunde abgestimmte Prüfung
ersetzt. Der Backup-Preflight verlangt jetzt die eine zuvor
verifizierte `/dev/fuse`-nach-`/dev/fuse`-Bind-Direktive mit
geprüften `bind`/`create=file`-Optionen, keine zusätzlichen
`mpN`-/`lxc.mount.auto`-/sonstigen Hooks/Excludes und
alle ursprünglichen NFS-/Temporär-/Backup-Metadaten-Gates.

Er importiert im **gleichen** Ansible-Lauf zudem die aktuelle
Ollama-/Podman-Read-only-Dateninventur. `SAFE_TO_ATTEMPT_SINGLE_BACKUP=True`
wird ausschließlich ausgewiesen, wenn **beide** getrennten
Prüfer durchgelaufen sind und die untenstehenden Kategorien live
wieder bestätigt haben. Das mutierende Oneoff-Playbook prüft die
Bedingungen nochmals mit Ansible-`assert`, bevor `vzdump`
gestartet wird. Eine alte separate Audit-Ausgabe wird nicht
als Ersatz verwendet.

**Sicherungsmodus:** `--mode snapshot`, `--remove 0`,
`--prune-backups keep-all=1`, `--storage bergen-synology-backup`,
genau CT110, kein Timer, kein `pct stop`/`pct start`.
Der Snapshot-Modus kann den Container für die Snapshot-Erstellung
kurz suspendieren und benötigt Snapshot-Fähigkeit des
Rootfs-Storages. Die einmalige Sicherung ist vom Betreiber
genehmigt. Erst wenn der operative Preflight erfolgreich
ist, darf diese separate Einmalaktion tatsächlich laufen.
Weder Archivintegrität noch Restore-Fähigkeit werden dadurch
automatisch attestiert.

Auf `bp-controller` nach aktuellem Branch-Fetch und
`--syntax-check` das einmalige Einmal-Backup-Playbook mit dem
bereits vereinbarten Approval-Wert starten:

```bash
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/backup-bergen-ai-ct110-once.yml \
  -e bergen_ai_ct110_oneoff_approval=APPROVE_CT110_SNAPSHOT_BACKUP_ONCE \
  --vault-id ai@prompt
```

Der mutierende Befehl ist **nicht** idempotent und darf nicht
blind wiederholt werden: Nach erfolgreichem Durchlauf muss das
Archiv zuerst geprüft werden; bei Fehlern läuft nur die manuelle
Ursachenanalyse, kein automatischer Retry oder Gast-Neustart.
Das bestehende Paperless-Backup, alle regelmäßigen Jobs und
sämtliche Netzwerk-Gates bleiben unverändert.


### Phase 0f.3 – Live-Backup-Versuch erneut fail-closed (19.10.2026, 21:58)

Der Betreiber hat den genehmigten einmaligen Backup-Runner gestartet.
Die erneute Prüfung der Anwendungsdaten war erfolgreich:
`DATA_SCOPE_STATUS=KNOWN_DATA_PATHS_IN_ROOTFS`,
`CT110_IDENTITY=RUNNING_ROOTFS_ONLY`,
`WEBUI_DATA=IN_GUEST_ROOTFS`. NFS-Speicher, lokaler
Temporärspeicher und der Zielarchivbestand waren ebenfalls
weiterhin im genehmigten Rahmen. Allerdings meldete die
Gast-Dateisystemprüfung:
`GUEST_MOUNTS=EXTERNAL_OR_UNKNOWN_MOUNT`,
`SAFE_TO_ATTEMPT_SINGLE_BACKUP=False`. Die autorisierte
Backup-Play-Phase stoppte mit
`CT110_BACKUP_PREFLIGHT_REVIEW_REQUIRED`.
Resultat `venombox ok=16 changed=0 failed=1`, **kein**
`vzdump`, keine Produktionseinstellung verändert.

Der noch offene Mount stammt **nicht** aus der bereits als exakte
`/dev/fuse`-Gerätebindung nachgewiesenen `lxc.mount.entry`.
Der alte `guest_mounts()`-Check prüft sämtliche Nicht-Pseudo-
Gast-Dateisysteme und trifft damit etwa auf LXCFS-Dateisysteme unter
`/proc` oder separate Container-/Datenträger-Mounts. Ohne
tatsächlichen Live-Befund darf keine Klasse pauschal freigegeben
werden.

### Phase 0f.4 – enger Read-only-Audit der Gast-Dateisysteme (vorbereitet)

`ansible/playbooks/audit-bergen-ai-ct110-guest-mount-blockers-readonly.yml`
liest **nur** die vom Gast per `findmnt` sichtbare Mount-Hierarchie
und gibt ausschließlich **sanitisierte Klassen und Zähler** aus.
Keine Quellpfade, Roh-Zielnamen, Inhalte, Credentials, Netzwerkänderungen
oder Backup-Autorisierung.

Klassifiziert getrennt:
- übliche `fuse.lxcfs`-Mounts an exakt bekannten Systemzielen,
- separate /etc-Identitätsdatei-Mounts,
- unbekannte Mounts in /proc, /sys, /dev, /run, KI-/Podman-Daten,
  oder sonstige Daten-/Mount-Verzeichnisse,
- Pseudo-Dateisysteme einschließlich Overlay-Mounts als
  eigene **Diagnoseanzahl**, nicht als Freigabenachweis.

`PREVIOUS_PREFLIGHT_BLOCKER_COUNT`, `BLOCKER_CLASSES`,
`LXCFS_SYSTEM_COUNT`, `ETC_IDENTITY_COUNT` und
`OTHER_NONPSEUDO_COUNT` erklären die bisherige Blockade.
Bei unlesbarer, zu großer oder mehrdeutiger Dateisystemstruktur
lautet die Klassifikation `UNVERIFIED`.

Nach aktuellem Branch-Fetch auf `bp-controller` ausschließlich:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
git -C "$WT" fetch origin feat/bergen-ai-private-bridge-20261019
git -C "$WT" switch --detach origin/feat/bergen-ai-private-bridge-20261019
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-ct110-guest-mount-blockers-readonly.yml \
  --vault-id ai@prompt
)
```

Nach diesem *read-only* Live-Ergebnis darf erst bei eindeutiger
Klassifikation die konkrete Gast-Dateisystem-Vorprüfung gezielt
korrigiert werden. `backup-bergen-ai-ct110-once.yml` **nicht**
erneut ausführen, bis ein unabhängiger positiver Preflight vorliegt.
Die Betreiberfreigabe für genau eine Sicherung bleibt sachlich bestehen,
jedoch weiterhin technisch gesperrt. Netzwerk-/Rollback-/Restore-Gates
unverändert offen. PR bleibt Draft.


### Phase 0f.4 – Live-Befund: 12 Gast-Mount-Blocker (19.10.2026, 22:07)

Der Operator-Audit
`audit-bergen-ai-ct110-guest-mount-blockers-readonly.yml`
meldete auf `venombox` `ok=7 changed=0 failed=0`:

```text
STATUS=CLASSIFIED_FOR_REVIEW
TOTAL_MOUNTS=52
PREVIOUS_PREFLIGHT_BLOCKER_COUNT=12
BLOCKER_CLASSES=LXCFS_SYSTEM_TARGET,OTHER_CONTAINER_STORAGE,OTHER_PROC_OR_SYS
LXCFS_SYSTEM_COUNT=8
ETC_IDENTITY_COUNT=0
OTHER_NONPSEUDO_COUNT=4
PSEUDO_OR_OVERLAY_COUNT=39
BACKUP_STARTED=False
BACKUP_AUTHORIZED=False
APPLY_AUTHORIZED=False
```

Die acht LXCFS-Systemziele sind als solche identifiziert.
**Vier weitere** Dateisystem-Mounts sind noch nicht ausreichend
beurteilt. Die Kategorien `OTHER_CONTAINER_STORAGE` und
`OTHER_PROC_OR_SYS` unterscheiden die Zielregion, **nicht**
deren FSType, Host-Quelle oder Backup-Abdeckung. Insbesondere
ist ein Mount in einem Podman-Graphroot nicht allein wegen
seines Zielorts als interner Overlay-Mount zu betrachten.
Die bisherige Kategorie `PSEUDO_OR_OVERLAY_COUNT` umfasst
ebenfalls Overlays und ist kein Integritätsnachweis.

Zur gezielten Auflösung wurde der **gleiche Read-only-Audit**
erweitert: `UNRESOLVED_PROFILES` enthält für die vier
nicht zugeordneten Mounts nur aggregierte **fixe**
Kategorien aus Zielbereich, Dateisystemtypgruppe,
Mount-Quellgruppe und Anzahl. Hinzu kommt
`OVERLAY_MOUNT_COUNT`. Weder reale Pfade noch Mount-Quellen,
Optionen, Dateiinhalte oder geheimhaltungsbedürftige
Hostnamen werden ausgegeben.

Der alte und der neue Backup-Preflight bleiben unverändert
sperrend. Dieser Diagnostikschritt **ändert niemals**
`SAFE_TO_ATTEMPT_SINGLE_BACKUP` und erteilt keine
`vzdump`-Freigabe. Unbekannte, externe, netzgebundene oder
verschachtelte persistente Mounts müssen vor jeder
Freigabe gesondert berücksichtigt werden. Erst den
Read-only-Audit mit frischem Branch ausführen, kein
erneuter mutierender Oneoff-Versuch.

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-ai-private-bridge"
git -C "$WT" fetch origin feat/bergen-ai-private-bridge-20261019
git -C "$WT" switch --detach origin/feat/bergen-ai-private-bridge-20261019
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-ct110-guest-mount-blockers-readonly.yml \
  --vault-id ai@prompt
)
```


### Phase 0f.4 – Profile-Livebefund (19.10.2026, 22:16)

Der Operator meldete für LXC 110 aus dem erweiterten
`audit-bergen-ai-ct110-guest-mount-blockers-readonly.yml`
(`ok=7 changed=0 failed=0`):

```text
TOTAL_MOUNTS=52
PREVIOUS_PREFLIGHT_BLOCKER_COUNT=12
LXCFS_SYSTEM_COUNT=8
OTHER_NONPSEUDO_COUNT=4
OVERLAY_MOUNT_COUNT=1
UNRESOLVED_PROFILES=
  PODMAN_GRAPH_TREE:BLOCK_OR_COW_FS:OTHER_SOURCE:1
  PODMAN_GRAPH_TREE:FUSE_OVERLAYFS:OVERLAY_SOURCE:1
  PROC_TREE:FUSE_LXCFS:OTHER_SOURCE:1
  SYS_TREE:FUSE_LXCFS:OTHER_SOURCE:1
BACKUP_STARTED=False
BACKUP_AUTHORIZED=False
```

Somit entsprechen zehn der 12 Nicht-Pseudo-Mounts nach ihrer
Dateisystemklasse LXCFS (`/proc`-/`/sys`-Systemmounts).
Ein Mount entspricht der FUSE-Overlay-Laufzeit von Podman.
Ein weiterer unter dem Podman-Graphroot hat einen Block-/CoW-
FSType und eine bisher nicht identifizierte Source-Klasse. Die
Zuordnung dieser beiden Podman-Mounts zu **einem konkreten**
Open-WebUI-Container bzw. dessen gesichertem Datenverzeichnis
bleibt unbewiesen. Das kann ein Bind auf Daten des
LXC-Rootfs sein, **muss aber nicht**.

### Phase 0f.5 – Dateisystemidentität statt weiterer Mount-Typ-Schätzung

Das neue `audit-bergen-ai-ct110-runtime-mount-relationships-readonly.yml`
verifiziert auf dem Gast ausschließlich lesend:

1. Die live von `podman inspect open-webui` gemeldete
   `MergedDir` liegt genau im geprüften rootverwalteten
   Podman-Graphroot und nur **eine** erwartete Podman-Datenbindung
   von `/srv/ai/open-webui` auf `/app/backend/data` existiert.
2. Das FUSE-Overlay ist direkt auf diesem inspizierten
   `MergedDir` gemountet und nicht an einem beliebigen
   Speicherziel.
3. Der Block-/CoW-Bind liegt genau unter diesem
   `MergedDir/app/backend/data`; seine FSType/Quelle
   entspricht der Gast-Rootfs-Basis, **und** sein Verzeichnis
   bezeichnet dieselbe `st_dev`/`st_ino`-Identität wie
   `/srv/ai/open-webui`.
4. Genau zehn `fuse.lxcfs`-Mounts liegen im `/proc`-/`/sys`-
   Systembereich. Alle weiteren Nicht-Pseudo-Mounts müssen
   sich dadurch vollständig erklären lassen. Andernfalls:
   `REVIEW_REQUIRED` oder `UNVERIFIED`.

Die Ausgabe nennt nur fixe Zustandskategorien und Anzahlen,
nicht die Podman-IDs, Daten, realen Mountpfade oder Quellen.
Auch ein positiver Status ist **kein** Backup-/Restore-Proof:
`BACKUP_AUTHORIZED=False`. Das Einmal-`vzdump`-Playbook
und dessen aktuelle Sperre bleiben bis zum Live-Nachweis
**unverändert**. Die zusätzliche Diagnostik wurde per
Regressionstests und Ansible-Syntaxprüfung in GitHub CI
geprüft.

**Auf bp-controller:** Nach dem gewohnten Branch-Fetch nur
das neue schreibgeschützte Playbook ausführen:

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
  ansible/playbooks/audit-bergen-ai-ct110-runtime-mount-relationships-readonly.yml \
  --vault-id ai@prompt
)
```


### Phase 0f.5 – Live-Audit weiterhin gesperrt (19.10.2026, 22:37)

Der Operator hat `audit-bergen-ai-ct110-runtime-mount-relationships-readonly.yml`
auf `venombox` mit `ok=7 changed=0 failed=0` ausgeführt:

```text
STATUS=REVIEW_REQUIRED
PODMAN_INSPECT_RELATIONSHIP=EXACT_SINGLE_WEBUI_BIND
ROOTFS_BIND_INODE_IDENTITY=UNVERIFIED
LXCFS_SYSTEM_MOUNT_COUNT=10
FUSE_OVERLAY_MOUNT_COUNT=1
WEBUI_ROOTFS_BIND_MOUNT_COUNT=0
UNACCOUNTED_NONPSEUDO_MOUNT_COUNT=1
RUNTIME_MOUNTS_MATCH_EXPECTATION=False
BACKUP_EXECUTED=False
BACKUP_AUTHORIZED=False
RESTORE_TEST=NOT_ATTESTED
APPLY_AUTHORIZED=False
```

Damit sind die zehn LXCFS-Systemmounts und der eine Podman-FUSE-
Overlay-Mount bestätigt. Der einzige verbleibende Nicht-Pseudo-
Mount konnte durch den ursprünglichen Vergleich von
`stat -Lc %d:%i /srv/ai/open-webui` mit dem vom Rootfs-Namespace
erreichbaren `MergedDir/app/backend/data` **nicht** identifiziert
werden. `UNVERIFIED` bedeutete in der alten Prüfungslogik
sowohl stat-Lesefehler als auch unterschiedliche Identitäten.

**Kein** Nachweis eines externen Mounts, aber **auch kein**
positiver Bind-/Backup-Nachweis. Es wurde keine Sicherung gestartet.

Derselbe schreibgeschützte Audit erhält nun ausschließlich
diagnostische und sanitisiert ausgegebene Felder:

- `SOURCE_INODE_READ`, `MERGED_INODE_READ` – ob
  `stat` für die beiden bekannten Pfade erfolgreich ist;
- `CONTAINER_PID`, `PROCESS_ROOT_INODE_READ` – ob der
  laufende Open-WebUI-Prozess und dessen
  `/proc/<pid>/root/app/backend/data` im Gast lesbar sind;
- `MERGED_INODE_RELATION` und
  `PROCESS_ROOT_INODE_RELATION` – `IDENTICAL`,
  `DIFFERENT` oder `UNVERIFIED`;
- `BIND_TARGET`, `BIND_FSTYPE_RELATION`,
  `BIND_SOURCE_RELATION` – ob `findmnt` den
  **exakten** Zielpfad und Dateisystemtyp und die
  Source-Familie des LXC-Rootfs bestätigt.

Die numerischen Prozess-IDs, Mount-Quellen und Inodes werden
**nicht ausgegeben**. Selbst ein identischer Inode-Vergleich
erteilt **keine** automatische Backup-Freigabe. Die alte
Prüflogik und `backup-bergen-ai-ct110-once.yml` bleiben
unverändert; bei `DIFFERENT` oder abweichender Source
muss die externe Datenherkunft vor einer Sicherung überprüft
werden. GitHub-CI deckt den Namespace-Unterschied und
nicht übereinstimmende Inodes mit Regressionstests ab.

**Auf bp-controller ausschließlich den bekannten Read-only-Audit
nach Git-Fetch erneut ausführen**, nicht das Einmalsicherungs-
Playbook:

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
  ansible/playbooks/audit-bergen-ai-ct110-runtime-mount-relationships-readonly.yml \
  --vault-id ai@prompt
)
```


### Phase 0f.5 – Read-only Live-Befund 19.10.2026, 22:46

Der Operator hat den erweiterten Runtime-Mount-Audit mit
`ok=7 changed=0 failed=0` auf `venombox` ausgeführt.
`PODMAN_INSPECT_RELATIONSHIP=EXACT_SINGLE_WEBUI_BIND`;
`LXCFS_SYSTEM_MOUNT_COUNT=10`, `FUSE_OVERLAY_MOUNT_COUNT=1`.
Der eine verbleibende Mount wurde nicht zugeordnet
(`UNACCOUNTED_NONPSEUDO_MOUNT_COUNT=1`).

**Wesentliche neue Erkenntnis:** `SOURCE_INODE_READ=AVAILABLE`,
`MERGED_INODE_READ=AVAILABLE`,
`PROCESS_ROOT_INODE_READ=AVAILABLE`,
`CONTAINER_PID=RUNNING_AND_AVAILABLE`,
`MERGED_INODE_RELATION=DIFFERENT`, aber
`PROCESS_ROOT_INODE_RELATION=IDENTICAL`.
Der tatsächlich laufende Open-WebUI-Prozess sieht somit
am Zielpfad im eigenen Mount-Namespace exakt dieselbe
Dateisystem-Objektidentität (`st_dev`/`st_ino`) wie
das bekannte persistente Verzeichnis `/srv/ai/open-webui`
im LXC-Rootfs. Der direkterweise unter `MergedDir`
gelesene Inode weicht davon ab. Das allein ist kein
Grund, einen externen Daten-Mount anzunehmen.

**Separates ungelöstes Gate:**
`BIND_TARGET=NOT_UNIQUE_OR_MISSING`; folglich
`BIND_FSTYPE_RELATION=UNVERIFIED` und
`BIND_SOURCE_RELATION=UNVERIFIED`. Das als zusätzlicher
Block-/CoW-Dateisystem-Mount erkannte Gast-Ziel
entspricht also nicht dem zuvor angenommenen exakten
Pfad `MergedDir/app/backend/data`. Seine Quelle
wurde noch nicht nachgewiesen. **Kein Backup gestartet**.

Der bestehende Read-only-Audit wurde deshalb um eine
streng begrenzte, **nicht autorisierende** Diagnose des
einen bislang nicht erklärten Mounts ergänzt. Die neuen
`UNRESOLVED_*`-Felder liefern nur enumerierte Klassen:

- `UNRESOLVED_MOUNT_COUNT`: Anzahl ungeklärter
  Nicht-Pseudo-Mounts;
- `UNRESOLVED_TARGET_CLASS` / `UNRESOLVED_TARGET_ROLE`:
  Podman-Graphroot-/Runtime-Unterbereich ohne
  Container-ID oder echten Zielpfad;
- `UNRESOLVED_SOURCE_CLASS`: Relation zu Rootfs-
  Quellbezeichnung oder anderer Device-/Netzwerkquelle;
- `UNRESOLVED_FS_RELATION` und
  `UNRESOLVED_DEVICE_RELATION`: FSType und Gast-
  Gerät-ID im Vergleich zu `/`, nur als gleiche/
  andere/ungeklärte Kategorie.

Ein passendes `SAME_DEVICE` alleine ist noch
**kein** Beweis der `vzdump`-Abdeckung oder
Datenintegrität. Unknown Sources und weitere
Mounts bleiben gesperrt. Das Backup-Preflight-
Playbook wurde **nicht** modifiziert;
`backup-bergen-ai-ct110-once.yml` nicht ausführen,
bis die Herkunft separat gewürdigt wurde.

Auf `bp-controller` nach dem gewohnten Fetch erneut
ausschließlich das bestehende read-only-Playbook
`ansible/playbooks/audit-bergen-ai-ct110-runtime-mount-relationships-readonly.yml`
ausführen. CI umfasst erneute Regressionen gegen
externe Quellen, unbekannte Targets und unterschiedliche
Mount-Geräte, zusätzlich Ansible-Syntax.


### Phase 0f.5 – Live-Befund: letzter Podman-Mount auf demselben Rootfs (19.10.2026, 22:54)

Der Operator hat den erweiterten, schreibgeschützten Runtime-Mount-
Audit mit `ok=7 changed=0 failed=0` auf `venombox` ausgeführt:

```text
PODMAN_INSPECT_RELATIONSHIP=EXACT_SINGLE_WEBUI_BIND
PROCESS_ROOT_INODE_RELATION=IDENTICAL
LXCFS_SYSTEM_MOUNT_COUNT=10
FUSE_OVERLAY_MOUNT_COUNT=1
UNRESOLVED_MOUNT_COUNT=1
UNRESOLVED_TARGET_CLASS=PODMAN_OTHER_GRAPH
UNRESOLVED_TARGET_ROLE=OTHER_GRAPH
UNRESOLVED_SOURCE_CLASS=ROOT_SOURCE_SUBPATH
UNRESOLVED_FS_RELATION=MATCHES_ROOT
UNRESOLVED_DEVICE_RELATION=SAME_DEVICE
BACKUP_EXECUTED=False
BACKUP_AUTHORIZED=False
```

Das letzte Nicht-Pseudo-Dateisystem liegt im rootverwalteten
Podman-Graphroot, hat exakt denselben Dateisystemtyp und
dieselbe Gerät-ID wie das LXC-Rootfs und zeigt in `findmnt`
auf ein **Unterverzeichnis derselben Rootfs-Quelle**.
Es ist damit keine zusätzliche externe Datenquelle
erkennbar. Die aktuelle Funktion dieses Runtime-Mounts
ist nicht abschließend bestimmt; `OTHER_GRAPH` alleine
ist auch kein Datenintegritätsnachweis.

Der tatsächlich laufende Open-WebUI-Container verwendet
nach `podman inspect` und übereinstimmender
`/proc/<pid>/root/app/backend/data`-Dateiidentität
das persistente `/srv/ai/open-webui`-Verzeichnis
im Gast-Rootfs. Der unmittelbare Zugriff auf
`MergedDir/app/backend/data` zeigt andere Inodes,
weshalb diese Namespace-Ansicht **nicht** als Backup-
Nachweis genutzt wird.

### Phase 0f.6 – Enger Same-Run-Oneoff-Preflight

Die bestehende Sicherungsvorprüfung wurde präzise auf
die bestätigte Gastkonfiguration erweitert. Im selben
Preflight-Lauf (nicht aufgrund älterer Audit-Ergebnisse)
müssen neu geprüft werden:

- der einzelne explizite `/dev/fuse`-nach-`/dev/fuse`-
  Gerätebind in der Proxmox-LXC-Konfiguration und keine
  `mpN`-/anderen Mount- oder Exclude-Direktiven;
- `podman inspect open-webui`: genau **eine** erwartete
  Bind-Zuordnung, korrekter rootverwalteter Podman-
  Graphroot, laufender Container und dessen
  `MergedDir` im erwarteten Graphroot-Schema;
- exakte Device-/Inode-Gleichheit von
  `/srv/ai/open-webui` und dem Datenziel aus dem
  Namespace des laufenden Prozesses;
- Gast-`findmnt` enthält genau die zuvor gesehenen
  52 Einträge: Gast-`/` auf ZFS, 39 Pseudo-Mounts,
  genau zehn `fuse.lxcfs` unter `/proc` oder
  `/sys`, ein FUSE-Overlay direkt am inspizierten
  Podman-`MergedDir` und **genau ein** weiteres
  Mount-Ziel im Podman-Graphroot (aber nicht in
  `overlay`, `overlay-containers` oder `volumes`);
- dieses letzte Mount ist **nachweislich ein
  Unterverzeichnis derselben ZFS-Rootfs-Quelle**,
  sein FSType entspricht `/` und die Gerät-ID
  seines Ziels ist identisch zu `/`. Separate
  NFS-/CIFS-/Block-Device-Quellen, nicht bestätigte
  Bind-Daten und weitere Overlay-/Autofs-Mounts
  bleiben gesperrt;
- laufend erneut auszuführende Ollama-/Podman-
  Dateninventur, NFS-Zielspeicher, ausreichend
  `/var/tmp`, noch kein CT110-Archiv am ausgewählten
  Backupziel und separate Operator-Einmalfreigabe.

Die resultierende Kategorie lautet ausschließlich bei
positivem Nachweis
`GUEST_MOUNTS=ROOTFS_INTERNAL_RUNTIME_ONLY`.
Nur dann darf `SAFE_TO_ATTEMPT_SINGLE_BACKUP=True`
werden. Alle Abweichungen sperren. Tests in CI decken
unerwartete/zusätzliche Mounts, Rootfs-Fstype,
unterschiedliche Device-IDs, andere Quell-Dateisysteme,
abweichende Bind-Inodes und geänderte Gastkonfigurationen
ab. Der produktive CT110-Preflight ist **noch nicht**
erneut ausgeführt worden.

**Nächster Operator-Schritt (nur read-only):**

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
  ansible/playbooks/preflight-bergen-ai-ct110-oneoff-backup-readonly.yml \
  --vault-id ai@prompt
)
```

Erst bei `STATUS=PRECHECK_PASSED`,
`GUEST_MOUNTS=ROOTFS_INTERNAL_RUNTIME_ONLY` und
`SAFE_TO_ATTEMPT_SINGLE_BACKUP=True` darf der Betreiber
das zuvor genehmigte **einmalige** Snapshot-Backup erneut
starten. Proxmox-LXC-Snapshots können durch FUSE-basierte
Runtime-Mounts fehlschlagen; es gibt **keinen**
automatischen Fallback auf Stop-Modus, Gast-Neustart
oder Wiederholungsversuch. Selbst ein erfolgreich
erstelltes Archiv ist noch kein Integritäts- oder
Restore-Nachweis. Die Bridge-/Netzwerkfreigabe bleibt
ausdrücklich unberührt.

### Phase 0f.6 – Produktiver CT110-Preflight bestanden (19.10.2026, 23:06)

Der Betreiber führte den nur lesenden Ansible-Preflight **nach** der
gezielten Mount-Anpassung aus. Live-Recap auf `venombox`:
`ok=15 changed=0 unreachable=0 failed=0`.

```text
AUDIT=READ_ONLY
STATUS=PRECHECK_PASSED
CT110_IDENTITY=RUNNING_ROOTFS_ONLY
WEBUI_DATA=IN_GUEST_ROOTFS
GUEST_MOUNTS=ROOTFS_INTERNAL_RUNTIME_ONLY
BACKUP_TARGET=NFS_ACTIVE_WITH_FREE_SPACE
TEMP_SPACE=LOCAL_TMP_SPACE_OK
ARCHIVE_STATE=NO_CT110_ARCHIVE_ON_SELECTED_STORAGE
DATA_SCOPE_STATUS=KNOWN_DATA_PATHS_IN_ROOTFS
SAFE_TO_ATTEMPT_SINGLE_BACKUP=True
BACKUP_EXECUTED=False
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

**Ergebnis:** Die Sicherung ist nach dieser Live-Prüfung technisch
startfähig. Weiterhin ist **kein** CT110-Backup erstellt.
Das bestehende `backup-bergen-ai-ct110-once.yml` führt die
schreibgeschützten Same-Run-Prüfungen erneut aus; nur bei
erneut positivem Befund und vorhandener Betreiberfreigabe
`APPROVE_CT110_SNAPSHOT_BACKUP_ONCE` startet exakt ein
`vzdump 110` auf `bergen-synology-backup` im Snapshot-Modus.
Es gibt keinen automatischen Stop-Fallback, Retry oder Prune.
Das Vorhandensein eines Archivs ist anschließend separat zu
prüfen; ein Restore-/Integritätsnachweis steht aus.
Netzwerk-Apply und Bridge bleiben unabhängig gesperrt.

Freigegebener Operator-Aufruf auf `bp-controller` (in einer
bestehenden tmux-Sitzung; **nicht blind wiederholen**):

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
  ansible/playbooks/backup-bergen-ai-ct110-once.yml \
  -e bergen_ai_ct110_oneoff_approval=APPROVE_CT110_SNAPSHOT_BACKUP_ONCE \
  --vault-id ai@prompt
)
```

### Phase 0f.7 – Snapshot abgeschlossen, Ansible-Postcheck wegen YAML-String fehlgeschlagen (20.10.2026, 06:15)

Der Betreiber hat das bereits genehmigte, einzige `vzdump 110`
auf `bergen-synology-backup` angestoßen. Alle unabhängigen
Same-Run-Gates und die ausdrückliche Einmalfreigabe waren
erfolgreich. Der Async-Task meldete:

```text
ASYNC OK on venombox: jid=None
changed: [venombox]
```

**Danach** war `pct status 110` erfolgreich lesbar. Die
folgende `ansible.builtin.assert`-Bedingung hatte jedoch einen
YAML-Quoting-Fehler und brach ab mit
`Conditional expressions must be strings`. Der Rescue-Pfad
berichtete `CT110_RUNNING=True`. Die späteren
Archiv-Metadaten-Aufgaben wurden **nicht** ausgeführt.
Play-Recap: `ok=21 changed=1 failed=1 rescued=1`.

Das ist **kein Beleg eines fehlgeschlagenen `vzdump`**;
der asynchrone Ansible-Task meldete OK. Dennoch war
das Archiv auf dem NFS-Ziel noch nicht nachgewiesen.

**Korrektur im Draft-PR #119:** Die Postcheck-Bedingung wird
nun als kompletter YAML-String quotiert:

```yaml
- "ct110_after.stdout | trim == 'status: running'"
```

Außerdem wird `oneoff_backup_exec.rc == 0` ausdrücklich
assertiert. Das mutierende Oneoff-Playbook darf **nicht**
erneut ausgeführt werden; das bereits erzeugte Archiv
muss separat geprüft werden. Ein zweiter Versuch wäre
ohne manuelle Bestandsprüfung potenziell redundant.

**Neuer ausschließlich lesender Postbackup-Audit:**
`ansible/playbooks/audit-bergen-ai-ct110-postbackup-archive-readonly.yml`.
Er fragt nur `pct status 110`, das aktive NFS-Mount und
die PVE-Storage-Metadaten ab. Er gibt in einem begrenzten
Statusrahmen aus:

- `CT110_STATE` und `BACKUP_TARGET`;
- `CT110_ARCHIVE_COUNT` am ausgewählten NFS-Ziel;
- `CT110_ARCHIVE_METADATA`: höchstens
  `ONE_NONEMPTY_ZSTD_ARCHIVE_VISIBLE`, **nicht**
  `BACKUP_INTEGRITY=TESTED` und **kein** Restore-Beleg.

Der Audit öffnet, entpackt oder verändert Archive nicht;
er startet weder `vzdump` noch einen LXC-Neustart und
weist alle Netzwerk-Freigaben weiterhin zurück. Die
Bedingungen für einen späteren Archiv-Integritätscheck
sind gesondert zu definieren. Der PR bleibt Draft.

Auf `bp-controller` nach dem gewohnten Branch-Fetch
**ausschließlich** dieses Read-only-Playbook ausführen:

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
  ansible/playbooks/audit-bergen-ai-ct110-postbackup-archive-readonly.yml \
  --vault-id ai@prompt
)
```

### Phase 0f.8 – CT110-Einmalbackup als Archiv nachgewiesen (20.10.2026, 06:21)

Nach dem Ansible-Quoting-Fehler in der ursprünglichen Postcheck-
Stufe hat der Betreiber den strikt lesenden
`audit-bergen-ai-ct110-postbackup-archive-readonly.yml`
ausgeführt. Live-Recap `venombox ok=7 changed=0 failed=0`:

```text
STATUS=ARCHIVE_PRESENT_NOT_VALIDATED
CT110_STATE=RUNNING
BACKUP_TARGET=EXPECTED_ACTIVE_NFS
CT110_ARCHIVE_COUNT=1
CT110_ARCHIVE_METADATA=ONE_NONEMPTY_ZSTD_ARCHIVE_VISIBLE
BACKUP_EXECUTED_BY_THIS_AUDIT=False
ARCHIVE_CONTENTS_CHECKED=False
BACKUP_INTEGRITY=NOT_TESTED
RESTORE_TEST=NOT_ATTESTED
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

**Bestätigt:** genau ein nicht leeres CT110-`.tar.zst`-Archiv
ist auf dem aktiven Synology-NFS-Ziel über die PVE-Storage-
Metadaten sichtbar, und CT110 läuft weiterhin. Eine
zweite Sicherung ist nicht erforderlich und darf nicht
ohne separate Neufreigabe ausgeführt werden.

**Grenze:** Volid, Größe und PVE-Metadaten beweisen weder
die Zstandard-Stream-Integrität noch die Lesbarkeit der
enthaltenen TAR-Struktur, geschweige denn eine gelungene
Wiederherstellung.

### Phase 0f.9 – Vollständige Read-only-Archivstromprüfung vorbereitet

Neues, separat aufzurufendes Playbook:
`ansible/playbooks/verify-bergen-ai-ct110-archive-stream-readonly.yml`.
Es beginnt mit einem frischen Gast-, NFS- und PVE-Metadaten-
Nachweis: genau ein Archiv mit stimmigem Namen, positiver
und gegenüber dem Dateisystem unveränderter Größe,
reguläre (nicht symbolische) Datei auf dem erwarteten
NFS-Mount. Andere Storage-IDs, leere Archive, fehlende
Tools und während der Prüfung wechselnde Metadaten
führen zu `REVIEW_REQUIRED` bzw.
`CHECK_FAILED_OR_UNAVAILABLE`.

Die Prüfung liest das **eine bestehende Archiv zweimal
vollständig** über NFS, ohne Änderungen:

1. `zstd -q -t -- <Archiv>` validiert den komprimierten
   Datenstrom einschließlich vorhandener Zstandard-
   Prüfsummen.
2. `tar -I zstd -tf <Archiv>` prüft die vollständig
   lesbare TAR-Verzeichnisstruktur. Die Member-Liste und
   sämtliche Fehlermeldungen werden verworfen, nicht
   in Ansible-Logs oder andere Dateien geschrieben.

Beide Subprozesse werden einzeln zeitlich begrenzt
und eine gesamte Prozessgruppe bei Ablauf abgebrochen;
der Ansible-Aufruf verwendet einen längeren
Async-Zeitraum. Die Prüfung kann auf NFS **spürbare
Leselast** verursachen (zwei vollständige Durchläufe)
und soll nur einmal gezielt gestartet werden. Es
werden **keine** TAR-Inhalte extrahiert, keine Container
gestoppt/neu gestartet, keine Backups erneut gestartet,
keine Dienste, Netzwerke oder Bridge-Konfiguration
verändert.

Nur bei vollständigem Erfolg heißt der Status
`COMPRESSED_STREAM_AND_TAR_READABLE`; weiterhin
`RESTORE_TEST=NOT_ATTESTED`,
`ROLLBACK_CLEARANCE=NOT_PROVEN` und
`APPLY_AUTHORIZED=False`. Die Wiederherstellbarkeit
muss gesondert in einer isolierten Testumgebung
nachgewiesen werden. Ein erfolgreicher Stream-Check
ersetzt weder Restore-Test noch betriebliche Freigabe.

**Operator-Aufruf (einmal, auf bp-controller, tmux empfohlen):**

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
  ansible/playbooks/verify-bergen-ai-ct110-archive-stream-readonly.yml \
  --vault-id ai@prompt
)
```

### Phase 0f.9 – Archivstream und TAR vollständig bestanden (20.10.2026, 06:45)

Der Betreiber führte auf `venombox` die getrennte
`verify-bergen-ai-ct110-archive-stream-readonly.yml` aus.
Nach 17 schreibgeschützten Async-Polls beendete die
Prüfung erfolgreich: `ok=7 changed=0 failed=0`.

```text
AUDIT=READ_ONLY
STATUS=COMPRESSED_STREAM_AND_TAR_READABLE
VERIFY_STAGE=FINISHED
ZSTD_STREAM_CHECK=PASS
TAR_READ_CHECK=PASS
FILE_STABLE_AFTER_CHECK=YES
CT110_STATE_AFTER=RUNNING
BACKUP_INTEGRITY=STREAM_AND_TAR_ONLY_NOT_RESTORE_VERIFIED
BACKUP_EXECUTED=False
BACKUP_RETRIED=False
ARCHIVE_EXTRACTED=False
RESTORE_TEST=NOT_ATTESTED
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
```

Der vorhandene CT110-Zstandard-Datenstrom wurde vollständig
geprüft und die darin enthaltene TAR-Struktur ist komplett
lesbar. Das Archiv blieb während beider NFS-Lesedurchgänge
unverändert; der produktive CT110 läuft weiter. Es fand
weder eine Extraktion noch ein Wiederherstellungsversuch statt.
Dieses Ergebnis beweist **noch nicht**, dass ein isolierter
Gast erfolgreich gestartet und dessen Anwendungskonfiguration
vollständig wiederhergestellt werden kann.

### Phase 0f.10 – Isolierten Wiederherstellungstest nur vorbereiten

`pct restore` kann ursprüngliche Netz- und Gastkonfigurationen
übernehmen. Deshalb ist ohne explizit geprüftes Netzwerk- und
Startverbot **kein** Gast-Restore zulässig. <https://pve.proxmox.com/pve-docs/pct.html>

Der neue read-only Infrastrukturcheck
`audit-bergen-ai-ct110-isolated-restore-feasibility-readonly.yml`
prüft jetzt lediglich:

- Produktiver CT110 läuft weiterhin.
- Der Vorschlag **VMID 910** ist in den Proxmox-
  Clusterressourcen **und** dem lokalen LXC-Index
  zum Prüfzeitpunkt unbenutzt. Die 800er-VMIDs bleiben
  für Altcontainerübernahmen reserviert. Der Check
  reserviert keine VMID (Race-Gate bleibt offen).
- Der produktive Rootfs-Speicher lässt sich
  als `local-zfs` mit begrenzter Rootfs-Kapazität
  interpretieren. Dort ist aktiver `rootdir`-fähiger
  ZFS-Speicher mit mindestens Original-Rootfs-Größe
  plus 10 GiB Reserve vorhanden. Fehlende Angaben,
  falscher Speichertyp oder geringer freier Platz
  sperren die Kandidatenfreigabe.
- Das Backup-NFS ist aktuell wirklich als `nfs`/
  `nfs4` eingehängt und in PVE aktiv. Die PVE-
  Metadaten zeigen weiterhin **genau ein**
  nicht leeres CT110-Backup im erwarteten Format.

Der Status `RESTORE_ENVIRONMENT_CANDIDATE` ist nur eine
mögliche positive **Infrastrukturinventur**,
**keine Wiederherstellungsfreigabe**.
`ARCHIVE_CONFIG_SANITIZATION=NOT_PROVEN`,
`NETWORK_ISOLATION=NOT_PROVEN`,
`RESTORE_AUTHORIZED=False`,
`RESTORE_TEST=NOT_ATTESTED`,
`APPLY_AUTHORIZED=False` bleiben auch bei positivem
Infrastrukturbefund bestehen. Keine automatische
Erstellung/Start/Löschung irgendeines Gasts.

**Operator-Aufruf auf bp-controller (read-only):**

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
  ansible/playbooks/audit-bergen-ai-ct110-isolated-restore-feasibility-readonly.yml \
  --vault-id ai@prompt
)
```

Erst danach separat prüfen: `pvesm extractconfig` der
bestehenden Sicherung ohne Extraktion von Anwendungsdaten,
eindeutige neutrale Gastidentität, `onboot=0`,
keinerlei `netN`-/sonstiger Netzzugang,
keine externe Bind-/Device-Mounts und
ein Restore-Verfahren, das diese Eigenschaften
**vor** einer etwaigen Gastaktivierung garantiert.
Ein Restore darf nie VMID 110, existierende Test-VMIDs,
Original-IP, das Originalvolume oder einen produktiven
Dienst überschreiben. Weiterhin kein mutierendes
Restore-Playbook, keine automatische Bereinigung und keine
Netzwerk- oder Bridge-Freigabe.

### Phase 0f.10 – Restore-Infrastruktur live freigeprüft (20.10.2026, 06:52)

Der Betreiber führte den vollständig lesenden
\`audit-bergen-ai-ct110-isolated-restore-feasibility-readonly.yml\`
auf \`venombox\` aus. \`PLAY RECAP: ok=7 changed=0 failed=0\`.

\`\`\`text
STATUS=RESTORE_ENVIRONMENT_CANDIDATE
SOURCE_CT110_STATE=RUNNING
CANDIDATE_VMID=910
CANDIDATE_VMID_STATE=UNUSED_AT_CHECK_TIME
TARGET_STORAGE_CLASS=ACTIVE_ROOTDIR_ZFS_WITH_BUFFER
BACKUP_NFS_STATE=EXPECTED_ACTIVE_NFS
CT110_ARCHIVE_METADATA=ONE_NONEMPTY_CT110_ZSTD_ARCHIVE
ARCHIVE_STREAM_CHECK=PREVIOUSLY_REPORTED_PASS_NOT_RECHECKED
ARCHIVE_CONFIG_SANITIZATION=NOT_PROVEN
NETWORK_ISOLATION=NOT_PROVEN
RESTORE_EXECUTED=False
RESTORE_AUTHORIZED=False
NEW_GUEST_CREATED=False
GUEST_STARTED=False
RESTORE_TEST=NOT_ATTESTED
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
\`\`\`

Damit sind VMID 910 (nur zum Prüfzeitpunkt), aktives
\`local-zfs\` einschließlich Kapazitätspuffer sowie das
aktive Synology-Backup-NFS für einen späteren Restore
**geeignete Kandidaten**. Der frühere Zstandard-/TAR-
Integritätsnachweis gilt weiterhin, wurde hier jedoch
nicht erneut durchgeführt. **Keine Gastanlage oder
Netzwerkänderung hat stattgefunden.**

### Phase 0f.11 – Archivierte LXC-Konfiguration getrennt und geheimnisschonend prüfen

Offenes Risiko: Eine Standard-Wiederherstellung kann
die im CT110-Archiv vorhandenen \`netN\`-Schnittstellen,
die produktive Identität, \`onboot\`-Flags und
Mount-/Device-Direktiven übernehmen. Der isolierte
Restore darf deshalb *nicht* bereits auf Grundlage der
Infrastrukturprüfung erfolgen.

Ein weiteres strikt lesendes Playbook
\`ansible/playbooks/audit-bergen-ai-ct110-archived-restore-config-readonly.yml\`
importiert zuerst nochmals den rein lesenden
Infrastruktur-Audit. Es liest dann mit dem dokumentierten
Proxmox-Kommando \`pvesm extractconfig <volid>\` nur die
gespeicherte LXC-Konfiguration aus **genau einem**
CT110-Archiv und klassifiziert sie innerhalb des
temporären Prüfprozesses. Die originale Konfiguration
wird weder in Logs noch in Dateien geschrieben.

Nur diese bereits bekannte bzw. begrenzte
Prüfevidenz wird sichtbar:

- \`CONFIG_READ=PARSED\` / \`UNVERIFIED\`,
  \`STATUS=KNOWN_SOURCE_CONFIGURATION\` /
  \`REVIEW_REQUIRED\` / \`UNVERIFIED\`;
- Anzahl archivierter \`netN\`-Schnittstellen;
- archivierter \`onboot\`-Wert als
  \`ENABLED\`, \`DISABLED\`, \`ABSENT\`, \`OTHER\`;
- erwarteter Ursprungshostname als Statusklasse,
  \`local-zfs\`-Rootfs und \`unprivileged: 1\`;
- Anzahl \`mpN\` und gefährlicher oder unbekannter
  \`lxc.*\`-/Hook-/Device-Direktiven;
- Nachweis, ob genau das historisch bereits bekannte
  \`/dev/fuse\`-Device-Bind vorhanden ist.

**Es werden keine Original-IP-Adressen, MACs, Bridge-
Namen, Netzwerkrouten, Passwörter, Mount-Quellpfade
oder vollständigen Konfigurationswerte ausgegeben.**
Alle anderen Typen/zusätzlichen Mounts/Mehrfachwerte
bleiben \`REVIEW_REQUIRED\`.

Auch \`STATUS=KNOWN_SOURCE_CONFIGURATION\` bedeutet
ausschließlich, dass die *ursprüngliche*
LXC-Konfiguration dem erwarteten Profil entspricht,
**nicht** dass die geplante Restore-Konfiguration
netzlos ist. Deshalb bleiben die Gates auch dann:

\`\`\`text
ARCHIVE_CONFIG_SANITIZATION=NOT_PROVEN
NETWORK_ISOLATION=NOT_PROVEN
GUEST_START_POLICY=NOT_PROVEN
RESTORE_EXECUTED=False
RESTORE_AUTHORIZED=False
RESTORE_TEST=NOT_ATTESTED
ROLLBACK_CLEARANCE=NOT_PROVEN
APPLY_AUTHORIZED=False
\`\`\`

**Nächster Operator-Schritt auf bp-controller**, nur
den neuen schreibgeschützten Audit ausführen:

\`\`\`bash
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
  ansible/playbooks/audit-bergen-ai-ct110-archived-restore-config-readonly.yml \
  --vault-id ai@prompt
)
\`\`\`

Erst nach dieser Konfigurationsinventur ist zu entscheiden,
wie die produktiven \`netN\`-/\`onboot\`-/Device-Parameter
**vor einer eventuellen Aktivierung** garantiert
neutralisiert werden könnten. Eine spätere mutierende
Restore-Probe braucht eine gesonderte ausdrückliche
Genehmigung. VMID 910 ist nicht reserviert; unmittelbar
vor einer möglichen Anlage muss erneut konfliktfrei
geprüft werden. Keine Änderung an produktivem CT110,
VMIDs 800–899, NFS-Archiv oder \`vmbr90\`.
