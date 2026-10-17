# Paperless OIDC/allauth: tatsächlichen Timeout nur lesend prüfen

Nachfolger des historischen [PR #58](https://github.com/tobe4it/bergen-platform/pull/58). Die dort vorgeschlagene Umstellung auf 15 Sekunden beruht auf früher beobachteten Synology-SSO-`ReadTimeout`-Fehlern und dem damaligen Standard von **5 Sekunden**. **Für den aktuellen Produktivstand ist nicht nachgewiesen, ob noch 5, bereits 15 oder ein anderer Wert wirksam ist.**

## Betriebsprüfung

```bash
cd ~/bergen-platform
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-allauth-timeout-readonly.yml
```

Das Playbook prüft auf dem autorisierten Proxmox-Host den laufenden unprivilegierten LXC 126 und die drei Paperless-Systemd-Dienste. Es fragt anschließend **innerhalb des bestehenden Paperless-Containers** den tatsächlichen Wert von `allauth.socialaccount.app_settings.REQUESTS_TIMEOUT` ab und kontrolliert, ob der OIDC-Provider geladen ist. Es liest keine Social-App-Secrets aus, ändert keine Einstellungen und startet keinen Dienst neu. Die Ausgabe nennt ausschließlich den effektiven Sekundenwert, die Kategorie `FIVE_SECONDS` / `FIFTEEN_SECONDS` / `OTHER` sowie die Kategorie des Django-Settings-Moduls.

**Bei 15 Sekunden:** Keine Timeout-Änderung erforderlich; wiederholte SSO-Fehler getrennt diagnostizieren.

**Bei 5 Sekunden, aber ohne aktuelle Timeout-Fehler:** Nicht vorsorglich neustarten. Eine Änderung wäre eine eigene Betriebsentscheidung.

**Bei 5 Sekunden und reproduzierbaren SSO-Timeouts:** Standortbezogene Ist-Quadlets, alleauth-/Paperless-Version, gültige Break-glass-Anmeldung und tatsächliche Proxy-Backend-Anbindung unabhängig prüfen. Danach einen gesonderten, abgesicherten Anpassungs-PR mit vorab überprüftem Backup, Rollback, *ausschließlich* Paperless-App-Neustart und realem Synology-2FA-Negativtest vorsehen.

Der alte Mutationsentwurf aus PR #58 muss **nicht** unverändert übernommen werden: Er verlangt eine ganz bestimmte `PublishPort=127.0.0.1:8000:8000`-Quadlet-Zeile, die für einen Zugriff über einen separaten Proxy-LXC nicht selbstverständlich korrekt ist, und würde den App-Dienst neu starten.

**Grenzen:** Die Prüfung misst keine Latenz des Synology-IDP und keinen OIDC-Login; auch ein effektiver 15-Sekunden-Wert garantiert noch keine erfolgreiche 2FA-Callback-Antwort. OAuth-Credentials, URL-Parameter oder reale Benutzerkennungen dürfen nicht in CI-/Supportlogs gelangen. Die Prüfung verändert weder Scanner, Gruppenarchivierung, ACLs, Datenbank noch Redis.
