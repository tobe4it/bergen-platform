# Paperless-ngx: effektive Leserechte – Abnahmeprotokoll

Stand: 2026-10-14 (Bedienerprotokoll vom bp-controller; nicht unabhängig durch GitHub CI ausgeführt)

## Geprüfter Stand

- Ziel: Proxmox `venombox`, LXC 126 `bergen-paperless`, Podman-Container `bergen-paperless`.
- Prüfskript: `ansible/playbooks/audit-paperless-permissions.yml` auf Branch `feat/paperless-effective-permission-audit-20261015`, Korrekturcommit `9941e9b`.
- Aufruf durch Betreiber: Ansible mit beiden Inventories, `--vault-id paperless@prompt` und den beiden lokalen Variablendateien.
- Ergebnis aus dem vom Betreiber bereitgestellten Lauf: `AUDIT_RESULT PASS failures= 0`; Ansible `ok=4 changed=0 unreachable=0 failed=0`.
- Vorheriger V2-Lauf: 35 bestandene Checks, 1 Fehler in der Interpretation einer insgesamt verweigerten Dokumentliste. V3 behandelt eine HTTP-403/404-Gesamtverweigerung nur bei ausschließlich negativen Erwartungen als gültiges Ergebnis.

## Nachgewiesene Fälle (36 Checks)

| Dokument | Benutzer | Erwartung | Detail | Download | Liste |
| --- | --- | --- | --- | --- | --- |
| 10, privat Thomas | thomas | erlaubt | 200 | 200 | sichtbar |
| 10, privat Thomas | nadja | verweigert | 404 | 403 | unsichtbar |
| 10, privat Thomas | thomas3 | verweigert | 403 | 403 | Liste 403 |
| 11, privat Thomas | thomas | erlaubt | 200 | 200 | sichtbar |
| 11, privat Thomas | nadja | verweigert | 404 | 403 | unsichtbar |
| 11, privat Thomas | thomas3 | verweigert | 403 | 403 | Liste 403 |
| 12, Eltern | thomas | erlaubt | 200 | 200 | sichtbar |
| 12, Eltern | nadja | erlaubt | 200 | 200 | sichtbar |
| 12, Eltern | thomas3 | verweigert | 403 | 403 | Liste 403 |
| 13, Familie | thomas | erlaubt | 200 | 200 | sichtbar |
| 13, Familie | nadja | erlaubt | 200 | 200 | sichtbar |
| 13, Familie | thomas3 | verweigert | 403 | 403 | Liste 403 |

Zusätzlich bestätigte der Betreiber manuell in der Paperless-Oberfläche die gegenseitige Trennung der privaten Bereiche von Thomas und Nadja. Das automatische Audit enthält noch **keinen** Test mit einem Nadja gehörenden privaten Dokument.

## Aussagegrenzen und Freigabesperre

Der Test nutzt `rest_framework.test.APIClient.force_authenticate` innerhalb des Paperless-Prozesses. Er prüft die DRF-Autorisierung für diese Identitäten und vier Dokumente, **nicht** die echte Anmeldung oder Token-Weitergabe.

Nicht abgedeckt: OIDC/LDAP-Login, Reverse-Proxy, API-Token-Scopes, Kinderidentität, Volltextsuche, Vorschau/Thumbnail, Anhänge/weitere Endpunkte, neu importierte Dokumente, Benutzer- und Gruppenänderungen, sowie Bergen-AI/Open-WebUI/RAG. Es gibt keine Aussage über eine künftige KI-Integration.

**Sicherheitsgate:** Kein produktiver KI-Dokumentenzugriff und kein globaler, über alle Benutzer geteilter Paperless-API-Token. Eine KI-Anbindung benötigt eine serverseitig verifizierte Benutzeridentität, per Request durchgesetzte Paperless-Berechtigungen, negative Tests für Treffer, Snippets, Vorschau, Downloads, Embeddings und Caches sowie Fail-Closed bei Identitätsverlust.

Die Ergebnisse dieses Protokolls sind eine dokumentierte Betreiberbeobachtung und kein reproduzierbarer CI-Beweis. Bei ACL-, Versions- oder Workflow-Änderungen erneut ausführen.
