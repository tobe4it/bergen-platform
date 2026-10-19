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
 │              └──────── vmbr10 ──────────┘                │
 │                     kein physischer Uplink              │
 │                     keine Host-IP / kein Gateway        │
 │                                                         │
 │  LXC120 bergen-syslog (später, extra Freigabe)          │
 │  └── mögliche net1: 172.30.110.4/28                     │
 └─────────────────────────────────────────────────────────┘
```

**Vorläufige** Bridge `vmbr10`; **vorläufiges** RFC1918-/28-Netz
`172.30.110.0/28`. Adressen sind **nicht reserviert/zugewiesen**.
Der initiale Audit prüft Host und LXC110/126/120 auf sichtbare
IPv4-Adress-/Routingüberlappungen und die Bridge-Namensbelegung; er
kann nicht alle VPN-, UniFi-, Docker-/Podman-, Fremdhost-, Off-Host-
oder nicht laufenden Namespace-Netze ausschließen. Der Betreiber
muss das Subnetz deshalb vor dem Deploy zusätzlich gegen das
vollständige IPAM/UniFi- und VPN-Inventar prüfen.

Eine mögliche **Basisdefinition**, erst nach Freigabe anzuwenden:

```ini
auto vmbr10
iface vmbr10 inet manual
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

- Existenz von `vmbr10` im Host-Kernel und in `/etc/network/interfaces*`.
- Verweise auf `vmbr10` in PVE-LXC/VM-Konfigurationen.
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
`vmbr10` zuerst als reinen lokalen Switch anlegen; erst nach
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
