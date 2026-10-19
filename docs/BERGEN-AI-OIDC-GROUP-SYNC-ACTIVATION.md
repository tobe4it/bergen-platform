# Bergen-AI – administrative API-Schlüssel und OIDC-Gruppensynchronisierung

## Aktualisierung: Verwaltung ohne neuen API-Schlüssel (20.10.2026)

**Bevorzugter Ansatz:** Die produktive Open-WebUI-OIDC-Konfiguration wird
bereits durch das bestehende Ansible-Playbook
`ansible/playbooks/configure-open-webui-oidc.yml` mit einer privaten
Quadlet-Umgebungsdatei verwaltet. Weil `ENABLE_OAUTH_PERSISTENT_CONFIG=false`
gesetzt ist, kann die Gruppensynchronisierung direkt über diesen vorhandenen
Ansible-Pfad freigegeben werden. **Für den OIDC-Gruppenschalter ist deshalb
kein Open-WebUI-Admin-API-Schlüssel erforderlich.** Ein manuell eingeschalteter
API-Key-Schalter kann auf den vorigen Zustand zurückgesetzt werden, sofern
kein anderer produktiver Dienst auf API-Schlüssel angewiesen ist.

Der versionierte Source-of-Truth-Templatewert wird auf
`ENABLE_OAUTH_GROUP_MANAGEMENT=true` gestellt.
`ENABLE_OAUTH_GROUP_CREATION=false`,
`ENABLE_OAUTH_ROLE_MANAGEMENT=false` und
`DEFAULT_USER_ROLE=pending` bleiben erhalten. Bestehende Issuer,
OIDC-Clientdaten, Redirect-URI, Scopes und Provider-Identität bleiben
unverändert.

**Read-only zuerst:**
`ansible/playbooks/manage-bergen-ai-oidc-group-sync-env.yml`
prüft auf `bergen-ai` die vorhandene root-only Umgebungsdatei,
den Quadlet-Drop-in, die OIDC-Schutzwerte und deren SHA-256-Fingerprint.
Default `bergen_ai_oidc_env_group_mode=audit`, ohne Änderungen und
ohne admin token. Zusätzliche Variablen: nur die vorhandene
Ansible/SSH-Inventarkonfiguration.

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-oidc-sync"
BR="feat/bergen-ai-oidc-group-sync-20261020"
git -C "$BASE" fetch origin "$BR"
if test -e "$WT/.git"; then
  test -z "$(git -C "$WT" status --porcelain)"
  git -C "$WT" switch --detach "origin/$BR"
else
  test ! -e "$WT"
  git -C "$BASE" worktree add --detach "$WT" "origin/$BR"
fi
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-bergen-ai-oidc-group-sync-env.yml \
  --vault-id ai@prompt
)
~~~

Der **separat freigegebene Apply** erfordert die expliziten lokalen Variablen
`bergen_ai_oidc_env_group_mode=apply`,
`bergen_ai_oidc_env_group_approved=true`,
`bergen_ai_oidc_env_backup_verified=true` und
`bergen_ai_oidc_env_expected_sha256` gleich dem unmittelbar zuvor
beobachteten Fingerprint. In einer 0600-lokalen YAML-Datei hinterlegen,
nicht im Git. Erst dann dasselbe Playbook mit `-e @DATEI` ausführen.

Das Playbook erstellt eine root-only 0600 Preimage-Kopie der
OIDC-Umgebungsdatei, ändert nur die eine Gruppenmanagement-Zeile, startet
**den bestehenden** `open-webui.service` neu, prüft den HTTP-Healthcheck
und die effektive Variable im laufenden Container. Der Schutzpfad verweigert
jede unbekannte Konfiguration. Für Rollback gelten gesonderte Approval- und
Fingerprint-Gates; vor dem Rücksetzen prüft es, dass außer der einen
Gruppenmanagement-Zeile keine OIDC-Werte geändert wurden. **Die bekannte
Open-WebUI-0.10.2-Einschränkung beim Entfernen von Gruppen durch leere Claims
bleibt bestehen.** Bestehende Web-Sessions werden nicht automatisch widerrufen.

**Abgrenzung:** Das frühere REST-API-Playbook
`manage-bergen-ai-oidc-group-sync.yml` ist für diesen Host nicht nötig und
soll hier **nicht** benutzt werden. Der separate PR #123 Modell-Installer
verwendet noch Admin-API-Authentifizierung; die tokenlose Ausführung
des OIDC-Gruppenschalters allein ersetzt dessen Modell-API nicht.
Privatberechtigungen und Kinderlernregel müssen weiterhin separat
abgenommen werden.

---
**Betreiberfreigabe am 20.10.2026:** Admin-API-Schlüssel aktivieren und die
vorhandenen OIDC-Gruppen automatisch bei Anmeldung zuordnen. Synology/OIDC
ist bereits per Ansible eingerichtet und wurde in Paperless als
gruppenliefernder Identity Provider bestätigt. Das bestehende
`configure-open-webui-oidc.yml` wird **nicht neu ausgeführt**.

## Reihenfolge und Betrieb

1. Im bestehenden Open-WebUI-Administrationskonto die globale Funktion
   **API-Schlüssel erstellen** unter Adminbereich → Einstellungen →
   Allgemein/Authentifizierung (Beschriftung versionsabhängig) aktivieren.
   **Keine** API-Key-Berechtigung für normale Konten oder Kinder freigeben.
   In Open WebUI 0.10.2 prüft der API-Key-Erzeugungs-Endpunkt ausdrücklich
   `auth.enable_api_keys` UND für Nicht-Admins
   `features.api_keys`; Admins dürfen die Schlüssel nur bei aktiviertem
   globalem Schalter erstellen. Die Admin-Gesamtkonfiguration nicht mit
   einem unvollständigen POST überschreiben.
2. Im bereits vorhandenen Administratorprofil einen Admin-API-Schlüssel
   erzeugen und ausschließlich in der vorhandenen verschlüsselten
   lokalen Datei `$HOME/bergen-platform/ansible/vars/ai-oidc.vault.yml`
   unter `vault_open_webui_admin_token` hinterlegen. Dazu
   `ansible-vault edit --vault-id ai@prompt ansible/vars/ai-oidc.vault.yml`
   aus dem Basischeckout verwenden; keinen Token im Chat, Terminalargument,
   CI oder Git ausgeben. Den OIDC-Client-Secret **nicht** als Admin-Token
   verwenden.
3. **Zuerst** die vier freigegebenen privaten Modellprofile per
   `feat/bergen-ai-family-model-activation-20261019` / PR #123
   kontrolliert einrichten, Backup/Restore prüfen und in READ_ONLY die
   exakt vier gruppengebundenen Modellfreigaben bestätigen. Das
   Modell-Staging verlangt die noch ausgeschaltete native
   Gruppensynchronisierung und null Gruppenmitglieder.
4. **Danach** das neue `manage-bergen-ai-oidc-group-sync.yml` ausführen:
   zunächst AUDIT, anschließend nach Backup- und Fingerprint-Freigabe APPLY.
   Der Apply setzt *ausschließlich* diese OIDC-Einstellungen:
   `ENABLE_OAUTH_GROUP_MANAGEMENT=true`,
   `OAUTH_GROUP_CLAIM=groups`,
   `ENABLE_OAUTH_GROUP_CREATION=false` und
   `ENABLE_OAUTH_ROLE_MANAGEMENT=false`.
   OIDC-Client, Issuer, Scopes und Standardrolle `pending` bleiben
   unverändert. Die drei bereits vorhandenen lokalen Open-WebUI-Gruppen
   werden anhand exakter, instanzspezifischer Namen geprüft, nicht
   automatisch neu erstellt.
5. Testkonten **neu per OIDC anmelden** und das Gruppenergebnis sowie die
   Sichtbarkeit beider freigegebener Kinder- und Elternmodelle beobachten.
   Die OIDC-Scope-Zeile `openid email groups` allein beweist noch nicht,
   dass der `groups`-Claim in genau dem für Open WebUI erwarteten Format
   und mit den lokalen Gruppennamen enthalten ist. Bei `0`
   Mitgliedschaften nach Anmeldung den Claim-Bezug auf dem Server
   kontrollieren. **Keine** öffentlichen Modellberechtigungen als
   Umgehung konfigurieren.

## READ_ONLY-Audit (nach Token und Modellprofilen)

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-oidc-sync"
BR="feat/bergen-ai-oidc-group-sync-20261020"
git -C "$BASE" fetch origin "$BR"
if test -e "$WT/.git"; then
  test -z "$(git -C "$WT" status --porcelain)"
  git -C "$WT" switch --detach "origin/$BR"
else
  test ! -e "$WT"
  git -C "$BASE" worktree add --detach "$WT" "origin/$BR"
fi
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-bergen-ai-oidc-group-sync.yml \
  -e "@$BASE/ansible/vars/bergen-ai-family-audit.local.yml" \
  -e "@$BASE/ansible/vars/ai-oidc.vault.yml" \
  --vault-id ai@prompt
)
~~~

Erwartet: `AUDIT=READ_ONLY`, `STATUS=READY`,
`PRIVATE_PROFILES_READY=True`, `GROUP_CLAIM=NOT_EXPLICIT` oder
`GROUPS`, `CHANGED=False`, `CONFIG_SHA256=<64 hex>`. Falls der
Status `PRIVATE_PROFILES_MISSING` lautet, zunächst PR #123 abschließen.

## Kontrollierter Apply

Nach unabhängiger Bestätigung einer restorable Sicherung von
`/srv/ai/open-webui/webui.db` und des geltenden
`CONFIG_SHA256` aus dem unmittelbar vorangegangenen Audit in einer
**ignorierten und 0600-geschützten** lokalen YAML-Datei ablegen:

~~~yaml
bergen_ai_group_sync_mode: apply
bergen_ai_group_sync_approved: true
bergen_ai_group_sync_backup_verified: true
bergen_ai_group_sync_expected_sha256: EXAKTER_AUDIT_FINGERPRINT
~~~

Das identische Ansible-Playbook aufrufen und diese Datei als
zusätzliches `-e @/pfad/zu/approval.local.yml` hinzufügen.
`STATUS=GROUP_SYNC_ENABLED` und `CHANGED=True` bestätigt den
effektiven API-Apply. Anschließend im AUDIT-Modus und durch echte
Neuanmeldungen die Gruppenzuordnung prüfen.

## Bekannte Einschränkung in Open WebUI 0.10.2

Der upstream geprüfte `update_user_groups`-Code entfernt lokale Gruppen
bei neuem OAuth-Login **nur wenn** die empfangene Gruppenliste nicht leer
ist. Bei ganz fehlendem, leerem oder ungültigem `groups`-Claim bleiben
bestehende Gruppenmitgliedschaften erhalten. Auch bestehende Web-Sessions
sind nicht automatisch widerrufen. **Diese Einschätzung wird durch das
Aktivieren des Schalters nicht behoben.** Daher bis zu einer gesonderten
Sicherheitskorrektur:
- bei Entzug einer elterlichen LDAP-/OIDC-Gruppe sofort die lokale
  Open-WebUI-Mitgliedschaft administrativ entfernen und vorhandene
  Sessions/API-Zugriffe kontrollieren;
- keine Gruppen-/Model-Grants auf Eltern-Paperless oder sensible
  Werkzeuge/RAG ausdehnen, bis verlässlicher Echtzeit-Rechteentzug belegt ist;
- Benutzerrollen nicht automatisch verwalten; neue Nutzer bleiben pending,
  bis ihre Rolle ausdrücklich überprüft und bewilligt wurde;
- den `groups`-Claim und die tatsächliche Modell-API-Verweigerung
  einschließlich Kinder-Negativtests prüfen.

Ein `rollback` im Playbook deaktiviert mit neuem Fingerprint und
separater Freigabe die automatische Gruppenzuordnung, **entfernt aber
keine bereits gespeicherten Gruppenmitgliedschaften**. Der gemeldete
Status `GROUP_SYNC_DISABLED_MEMBERSHIP_REVIEW_REQUIRED` verlangt
entsprechend gesonderte Rechte-/Session-Prüfung. Es gibt keinen
automatischen Löschlauf über alle Benutzergruppen.

**Dieser GitHub-Stand ist eine implementierte, CI-geprüfte
Einrichtungsvorlage, keine bereits ausgeführte Änderung im
privaten LXC 110.** Die tatsächliche Aktivierung erfolgt auf
`bp-controller`.
