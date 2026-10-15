# Bergen-AI über den bestehenden Bergen-Proxy

Status: **Draft / nicht produktiv aktiviert**. Auf der bestehenden
`nginx_reverse_proxy`-Rolle aufgebaut (PR #46). Kein neuer Reverse Proxy,
keine Änderung des produktiven Paperless-VHosts, keine zweite Wildcard-Key-Kopie
und kein neues Zertifikat.

## Feststehender Ist-Zustand (read-only geprüft)

- `bergen-proxy` LXC 125: Nginx auf TCP 443, nicht auf TCP 80.
- `paperless.thebergens.net`: bestehender VHost
  `50-internal-paperless.thebergens.net.conf`, Upstream
  `http://127.0.0.1:18000`; ein SSH-Prozess lauscht auf Loopback:18000.
- Zertifikatspfad im vorhandenen VHost:
  `/etc/nginx/tls/fullchain.pem`. Kein lokales Certbot-Verzeichnis
  und kein lokaler Certbot/TLS-Timer im Audit nachgewiesen.
- `bergen-ai` LXC 110: Open WebUI auf TCP 3000 (bereits separat geprüft).

- Nachträglich per `ps -ww -C ssh` nachgewiesen: Paperless verwendet einen
  **direkten SSH-Forward** aus LXC 125, mit an die interne Proxy-IPv4
  gebundenem SSH-Client, dedizierter Tunnelidentität, gepinntem Ed25519-
  Hostschlüssel, ausschließlich Public-Key-Authentifizierung und
  `-L 127.0.0.1:18000:127.0.0.1:8000`. Der AI-Tunnel übernimmt dieses
  Transportmuster, aber **nicht** die Paperless-Identität.
- Read-only AI-Preflight: `ai.thebergens.net` und
  `paperless.thebergens.net` lösen im Proxy beide auf dessen interne
  Adresse auf; der lokale Port 13000 ist frei; das vorhandene Zertifikat
  deckt `ai.thebergens.net` ab; `nginx -t` besteht.

**Noch nicht belegt:** der automatische Wildcard-Renewal-Distributionsweg
zum Proxy, die lokale gitignorierte Proxy-Konfiguration, die tatsächliche
AI-LXC-SSH-Identität/Hostkey-Prüfung und die End-to-End-Tunnel-Erreichbarkeit.
Diese Fakten dürfen nicht aus generischen Beispielen abgeleitet werden.

## Ziel und Grenzen

```text
https://ai.thebergens.net
   -> bestehender Nginx in LXC 125 (TLS *.thebergens.net)
   -> http://127.0.0.1:13000 auf LXC 125
   -> dedizierter SSH-Forward (LXC 125 -> LXC 110)
   -> 127.0.0.1:3000 in LXC 110 (Open WebUI)
```

Der zusätzliche lokale Port 13000 ist eine neue, noch nicht produktiv
bestätigte Wahl. Kein direkter Netzwerkzugriff auf die Loopback-Adresse
eines anderen LXC. Kein WAN-Ingress, keine DNS-API-Änderung und keine
Firewall-Öffnung durch diese Änderung.

### Voraussetzung: bereits geprüfter SSH-Transport

Das Deployment legt **keine** SSH-Schlüssel an, verteilt keine Keys und
ändert weder `authorized_keys` noch `known_hosts`. Vor Aktivierung muss
im Proxy-LXC eine root-eigene SSH-Konfigurationsdatei existieren, die den
Alias `ai_proxy_ssh_alias` über den geprüften Pfad zum KI-LXC auflöst.
Der produktive Paperless-Tunnel verwendet ausdrücklich keinen PCT-ProxyCommand
(`ProxyCommand=none`), sondern eine direkte SSH-Verbindung. Für AI ist
dieses bewährte Muster vorgesehen; die tatsächliche AI-LXC-Adresse und
der SSH-Server müssen separat bestätigt werden. Die Host-Key-
Prüfung bleibt zwingend aktiv; ein eigener minimal berechtigter Tunnel-Key
ist zu bevorzugen. Die genaue Konfiguration ist **standortspezifisch** und
wird nicht im öffentlichen Repository erfunden.

Der Tunnel-Unit-Entwurf verwendet **wie Paperless einen dedizierten\nnicht privilegierten technischen Benutzer** (`User`/`Group`, kein root),\nein getrenntes Arbeitsverzeichnis unter `/var/lib` und die\nsystemd-Härtungen `ProtectSystem=strict`, `ProtectHome=true`,\n`PrivateDevices=true`, eingeschränkte Adressfamilien und leeres\n`CapabilityBoundingSet`. Die SSH-Client-Konfiguration gehört dem\nAI-Tunnel-Benutzer und hat Modus 0600; ein eigener Schlüssel und eine\neigene gepinnte `known_hosts`-Datei sind Voraussetzung.\n\nDer Tunnel-Unit-Entwurf verwendet `ssh -4 -b <lokale Proxy-IPv4> -F ...`
mit `-N -T -L 127.0.0.1:13000:127.0.0.1:3000`,
`BatchMode=yes`, `IdentitiesOnly=yes`, deaktivierter Passwortanmeldung,
`StrictHostKeyChecking=yes` und `ExitOnForwardFailure=yes`.
Damit bleibt Open WebUI nur über den authentisierten SSH-Transport
erreichbar. Der Dienst wird bei Fehlern neu gestartet.

### Nginx

Der AI-VHost wird mit **derselben** Vorlage
`ansible/roles/nginx_reverse_proxy/templates/internal-proxy-site.conf.j2`
wie die anderen verwalteten HTTPS-Sites erstellt. Sie enthält den
WebSocket-Upgrade, Forwarded-Header und die bestehende Client-CIDR-
Allowlist. Die globale WebSocket-Map muss bereits existieren.
Der bestehende Paperless-VHost wird nicht gerendert, verändert oder gelöscht;
sein SHA-256 wird vor und nach der Aktivierung verglichen.

### Zertifikat und DNS

Der AI-VHost nutzt die **bereits vorhandenen** Dateien
`/etc/nginx/tls/fullchain.pem` und `/etc/nginx/tls/privkey.pem`.
Der Playbook-Preflight prüft die Zertifikatsabdeckung für
`ai.thebergens.net` und mindestens 14 Tage Restlaufzeit.
Es kopiert/erneuert keine Schlüssel. Vor einer produktiven Freigabe muss
die existierende Verteilung und Aktivierung nach Renewal nachgewiesen werden.

Die interne DNS-Zone **löst im Proxy bereits** `ai.thebergens.net` auf
dieselbe interne Proxy-Adresse wie `paperless.thebergens.net` auf. Dieser PR ändert
keine DNS-Einträge. Die interne Auflösung und unerwünschte externe
Erreichbarkeit müssen separat kontrolliert werden. Die vorhandene
Produktionskonfiguration lauscht nicht auf Port 80: **HTTP→HTTPS-Redirect
ist hier nicht vorhanden**; kein neuer HTTP-Listener wird stillschweigend
aktiviert.

## Ablauf auf bp-controller

Zuerst read-only (auf Basis dieses Branches, mit beiden Inventories):

```bash
cd ~/bergen-platform
source .venv/bin/activate
git fetch origin
git show origin/feat/bergen-ai-existing-proxy-tunnel-20261015:ansible/playbooks/preflight-bergen-ai-proxy.yml > /tmp/preflight-bergen-ai-proxy.yml
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  /tmp/preflight-bergen-ai-proxy.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Die Ausgabe enthält TLS-SAN, DNS, Nginx und die belegten lokalen Ports.
Die Aktivierung ist erst zulässig, wenn die **separate AI-Tunnelidentität\nauf Proxy und AI-Gast** angelegt, der SSH-Zugriff auf den\nbenötigten Forward eingeschränkt, der SSH-Hostkey verifiziert und die\nAnmeldung ohne Passwort als dieser Benutzer erfolgreich geprüft ist.\nDie vorliegende Aktivierung legt **weder Benutzer noch Schlüssel oder\nSSH-Autorisierungsregeln** an; ohne diese Vorbereitung verweigert sie\ndie Ausführung. Danach müssen der SSH-Alias und die private
CIDR-Allowlist in `ansible/group_vars/all/bergen-proxy.yml` geprüft
sind, die interne DNS-Zuordnung besteht und der Zertifikats-Renewal-Weg
bestätigt wurde.

Für einen späteren **separat freigegebenen** First Install: Feature-Branch
zuerst in einem eigenen Worktree auschecken, damit keine anderen lokalen
Änderungen auf `bp-controller` überschrieben werden. Danach Syntaxcheck:

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/activate-bergen-ai-proxy.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml \
  -e @ansible/group_vars/all/bergen-proxy.yml --syntax-check
```

**Nicht ohne Live-Freigabe ausführen.** Das Aktivierungsplaybook benötigt
zusätzlich `-e ai_proxy_deployment_approved=true`. Es verweigert
bestehende AI-Konfigurationsdateien, validiert Nginx vor dem Reload und
entfernt die neu angelegten AI-Dateien und den Tunnel bei Fehlern.
Es erstellt keinen DNS-Eintrag, keine SSH-Identität und keine TLS-
Erneuerungsautomatik. Kein `--check` als Ersatz für den lesenden Preflight:
Systemd-/Tunnel-Start ist in Check-Mode nicht sinnvoll simulierbar.

## Nachkontrolle

- `https://paperless.thebergens.net` funktioniert unverändert.
- `https://ai.thebergens.net` liefert gültiges Zertifikat und Open WebUI,
  einschließlich WebSocket-Upgrade und korrekt gesetzter Proxy-Header.
- Nur `127.0.0.1:13000` lauscht auf dem zusätzlichen Backend-Port;
  der SSH-Dienst ist aktiv und startet nach Reboot neu.
- Interne DNS-Zuordnung stimmt, keine unerwünschte WAN-Exposition.
- Zertifikatswechsel nach zentralem Renewal löst auf dem Proxy
  tatsächlich den erforderlichen Nginx-Reload aus.
- SSO/OIDC ist ein separater Schritt und wird hier nicht verändert.


## Produktive Paperless-Tunnel-Referenz (15.10.2026)

`systemctl cat bergen-paperless-tunnel.service` bestätigt, dass die
Produktivimplementierung **nicht als root** läuft. Sie verwendet
`User=paperless-tunnel-client`, `Group=paperless-tunnel-client`,
`WorkingDirectory=/var/lib/bergen-paperless-tunnel`, `UMask=0077`,
`ProtectHome=true`, `ProtectSystem=strict`, `PrivateDevices=true`,
`RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6` und
`CapabilityBoundingSet=` sowie explizite SSH-Optionen zur
Hostkey-/Public-Key-Prüfung. Der SSH-Forward bindet ausschließlich
`127.0.0.1:18000` und erreicht das Paperless-Backend auf Loopback:8000.

Das AI-Unit-Template wurde entsprechend gehärtet. Es wird **nicht**
der Paperless-SSH-Schlüssel kopiert oder wiederverwendet.

Die AI-LXC-Adresse, die SSH-Server-Konfiguration auf LXC 110,
dessen Hostkey und die auf diesen einen Forward eingeschränkte
`authorized_keys`-Regel sind noch nicht nachgewiesen. Diese müssen
vor einer produktiven Aktivierung gesondert geprüft werden.
