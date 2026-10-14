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

## TLS-Architektur: zuerst Terminierung feststellen

Die eingecheckte Open-WebUI-Quadlet-Vorlage startet die Anwendung mit
Host-Netzwerk und HTTP-Port 3000. **Kein HTTPS-Listener oder Reverse Proxy
ist in dieser Rolle definiert.** Der Ist-Zustand ist vor jeder Änderung
read-only zu prüfen:
`ansible/playbooks/audit-open-webui-tls-readiness.yml`.

Bevorzugte Architektur: HTTPS an einem vorhandenen, vertrauenswürdigen
Reverse Proxy terminieren, der bereits am automatischen Wildcard-
Erneuerungsprozess teilnimmt. Von dort ausschließlich den notwendigen
internen Upstream zu Open WebUI (Port 3000) erlauben, Host-/Forwarded-
Header sauber setzen und den Upstream netzseitig begrenzen. DNS kann
Split-Horizon nutzen; es ist kein öffentlicher Zugang erforderlich.

**Wenn ein bestehender Gateway-Proxy terminiert, darf der Wildcard-
Private-Key nicht zusätzlich in LXC 110 verteilt werden.** Nur der
terminierende TLS-Endpunkt benötigt ihn. Wenn stattdessen eine
separate TLS-Terminierung im KI-LXC zwingend erforderlich ist, muss
zunächst ein eigener geprüfter Distributions-Adapter mit eingeschränktem
Zielpfad, atomarem Austausch, Reload, Fingerprint-/SAN-/Ablaufprüfung,
Rollback und Zertifikats-Liveprüfung entwickelt werden.

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
- Bei bestehendem Gateway: vorhandenes Wildcard-Zertifikat und
  Renewal-Hook/Reload des Gateways nutzen; ggf. nur neuen Virtual Host
  hinzufügen, **keine** zusätzliche Schlüsselverteilung.
- Bei eigenem TLS-Endpunkt: separaten, streng eingeschränkten Consumer
  mit geprüftem SSH-/Proxmox-Transport, Dateirechten, SAN und Ablauf,
  Transaktions-/Rollback-Logik und TLS-Listener-Tests implementieren.
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

**Stand:** Zielname und Integrationsabsicht dokumentiert.
Weder DNS noch TLS-Terminierung noch ein neuer Zertifikats-Consumer
wurden bislang produktiv eingerichtet.
