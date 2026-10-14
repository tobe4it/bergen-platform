# Bergen-AI: einheitlicher FQDN, TLS und Synology SSO

Status: **Entwurf, kein produktives Deployment** (2026-10-15).
Dieser Entwurf erweitert die [Paperless-AI-Autorisierung](PAPERLESS-AI-AUTHORIZATION.md).

## Festgelegte Namen

| Funktion | FQDN / URL |
| --- | --- |
| Paperless (bestehend, produktiv) | `https://paperless.thebergens.net` |
| Bergen-AI / Open WebUI (Ziel) | `https://ai.thebergens.net` |
| Synology SSO Server (bestehend) | `https://sehnde.tbergen.de:5001` |

Der Synology-SSO-Endpunkt ist nicht durch einen Namen aus `thebergens.net`
zu ersetzen: das dortige TLS-Zertifikat lautet auf `sehnde.tbergen.de`.
Der OIDC-Issuer/Discovery-Pfad muss aus der funktionierenden
Paperless-Konfiguration übernommen und gesondert validiert werden.

`ai.thebergens.net` ist durch ein gültiges `*.thebergens.net`-Zertifikat
abgedeckt, sofern dieses SAN tatsächlich vorhanden ist. Der OIDC-Redirect
für Open WebUI ist voraussichtlich
`https://ai.thebergens.net/oauth/oidc/callback`, vorbehaltlich der
Bestätigung anhand der laufenden Open-WebUI-Version. Open WebUI bekommt
einen **eigenen** OIDC-Client; Paperless bleibt unverändert.

## TLS-Architektur: bestehenden bergen-proxy verwenden

**Betreiberbestätigung (15.10.2026):** `bergen-proxy` ist bereits als
Reverse-Proxy-LXC für `paperless.thebergens.net` eingerichtet. **Dieser
LXC ist der verbindliche TLS-Einstiegspunkt für Bergen-AI.** Es wird
kein zweiter Reverse Proxy und kein eigener HTTPS-Listener in LXC 110
eingerichtet.

Ziel-Routing:
`https://ai.thebergens.net` → HTTPS-Virtual-Host auf
`bergen-proxy` → interner HTTP-Upstream `bergen-ai:3000`
(tatsächlicher DNS-Name, Erreichbarkeit und Proxy-Software noch
read-only zu prüfen). Den bestehenden Paperless-Virtual-Host
**nicht verändern**. Externe Erreichbarkeit nicht voraussetzen;
DNS-/Firewall-Exposition getrennt prüfen.

`bergen-proxy` soll das vorhandene `*.thebergens.net`-Zertifikat
verwenden. **Kein Wildcard-Private-Key im KI-LXC**. Die konkrete
Zertifikatsquelle, bestehende Verteilung/Erneuerung und der Live-
Zertifikatspfad des Paperless-Virtual-Hosts auf `bergen-proxy`
müssen vor einer Änderung festgestellt werden. Den bestehenden
funktionierenden Paperless-Proxy-VHost als Konfigurationsreferenz
verwenden; Software (Nginx/Caddy/andere) nicht raten.

Das vorhandene read-only
`ansible/playbooks/audit-open-webui-tls-readiness.yml`
prüft nur den KI-Gast und dessen DNS/Listener, **nicht** den
Proxy. Es ist kein vollständiger TLS-/Proxy-Preflight.
Für eine produktive Änderung sind zuerst Proxy-Inventar, TLS-
Listener, Wildcard-SAN und Erneuerungsweg lesend nachzuweisen.

## Anschluss an die vorhandene Zertifikatsverteilung

Vorhandene Basis: Certbot DNS-01 Wildcard-Linie und
`scripts/mail_tls_sync.py` mit Read-only-Default und explizitem
`--apply`; siehe [MAIL-TLS-AUTOSYNC.md](MAIL-TLS-AUTOSYNC.md).
**Das bestehende Skript ist mail-spezifisch:** Es setzt Postfix/Dovecot,
Mail-TLS-Dateipfade und Ports 993/587/465 voraus. Es darf nicht direkt
für Open WebUI verwendet oder mit erfundenen Mail-Parametern umgangen
werden.

Die Zertifikatserneuerung soll **einmal zentral** erfolgen. Ein
zusätzlicher Consumer `ai.thebergens.net` wird erst nach Festlegung
der HTTPS-Terminierung in die vorhandene Deploy-/Sync-Kette aufgenommen:
- `bergen-proxy`: vorhandene Wildcard-Zertifikatsverteilung und
  den Renewal-/Reload-Weg **für diesen LXC** nachweisen und um den
  neuen Virtual Host ergänzen. Falls das Zertifikat bereits dort
  vorhanden ist, ist keine zusätzliche Kopie nötig.
- Keine Zertifikatsverteilung nach `bergen-ai` und keine neue
  KI-seitige TLS-Terminierung. Vorhandene Consumer (Mail, Paperless)
  unverändert lassen.
- Keine privaten Schlüssel, Token, Host-IP-Adressen oder DNS-API-Secrets
  ins Git-Repository; standortspezifische Angaben nur in ignorierten
  lokalen Variablen und Secrets im Vault.
- Keine DNS-Änderung, Proxy-Freigabe, Zertifikatskopie, Dienstneustarts
  oder SSO-Umschaltung ohne ausdrückliche Freigabe.

## Abnahmekriterien

1. `ai.thebergens.net` wird intern korrekt aufgelöst; keine
   unerwünschte externe Exposition.
2. TLS 1.2/1.3 gemäß Gateway-Policy, gültige Kette, SAN deckt
   `ai.thebergens.net`, SNI funktioniert; HTTP wird auf HTTPS umgeleitet.
3. Erneuerung/Reload erfolgt automatisch, inklusive Nachweis der
   Zertifikatsaktivierung nach Renewal und dokumentiertem Rollback.
4. Open WebUI akzeptiert Synology OIDC mit 2FA-Session-Wiederverwendung;
   eigene Client-ID, validierter Issuer, sichere Redirect-URI,
   geprüfte Kontenzuordnung und Admin-Rückfallzugang.
5. Paperless bleibt mit eigenem OIDC-Client unverändert;
   Benutzeridentität in der späteren Paperless-KI-Abfrage ist
   serverseitig vertrauenswürdig gebunden; Paperless-ACLs bleiben aktiv.

**Stand:** Bestehender Proxy-LXC und produktives Paperless-Routing
durch Betreiber bestätigt; Zielname und Erweiterung dokumentiert.
Ob `bergen-proxy` das Wildcard-Zertifikat bereits automatisch
erhält, ist noch zu prüfen. Kein neuer DNS-Eintrag, Virtual Host
oder Zertifikats-Consumer produktiv eingerichtet.
