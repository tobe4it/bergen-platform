# Bergen-AI – Freigabe Eltern- und Kinder-Chatprofile

Betreiberfreigabe 19.10.2026. Versionierte, gesondert gesicherte
Bereitstellung von vier privaten Modellen auf Open WebUI 0.10.2.
Dieser Branch aktiviert keine Benutzer-/Gruppenmitgliedschaften.

## Modelle und feste ACLs

- bergen-eltern-qwen25 -> qwen2.5:14b-instruct-q4_K_M -> nur Eltern-Gruppe read
- bergen-kinder-lernen -> qwen2.5:14b-instruct-q4_K_M -> nur Kinder-Gruppe read
- bergen-eltern-sprachen -> mistral-nemo:12b -> nur Eltern-Gruppe read
- bergen-kinder-sprachen -> mistral-nemo:12b -> nur Kinder-Gruppe read

Für beide Kinderprofile ist der gleiche vollständige Systemprompt
ansible/files/bergen_ai/prompts/learning_companion_de_v1.md maßgeblich.
Dort gilt insbesondere VORSAGEN UNTERSAGT: keine fertigen, zur Abgabe
bestimmten Hausaufgaben, Aufsätze, Übersetzungen oder Programme. Lernhilfe,
Denkschritte, alternative Übungsaufgaben und Fehlerfeedback bleiben erlaubt.
Das ist eine pädagogische Modellanweisung, keine technische ACL.

bge-m3:latest bleibt reines Embedding-/späteres RAG-Modell; keine
Chatfreigabe. Paperless #113 bleibt ein unabhängiges Projekt.

## Technische Sicherheitsgrenzen

- ausschließlich unterstützte lokale HTTP-APIs auf Loopback, kein direkter
  SQLite-Write; keine User-/Gruppen-/OIDC-/Paperless-Änderung;
- Version Open WebUI exakt 0.10.2, geprüfter Podman-Datenmount,
  MODEL_ACCESS_BYPASS=false, native OAuth-Group-Verwaltung ausgeschaltet;
- aktuelle LXC-Datenbank wird streng lesend auf null bestehende
  Gruppenmitgliedschaften geprüft: andernfalls verweigert dieser ERSTE
  Modell-Rollout den Apply;
- genau drei vorhandene, standortspezifische Gruppen und die zwei exakten
  lokalen Ollama-Tags werden geprüft, sonst Abbruch;
- Modellinventar muss vor dem ersten Apply leer sein. Nach einem
  erfolgreichen Apply sind exakt die vier privaten Aliasprofile mit
  genau je einer gruppengebundenen Leseberechtigung zulässig;
- aktiver Admin-API-Bearer aus verschlüsseltem Vault, no_log in allen
  geschützten Ansible-Tasks und keine Ausgabe von IDs, Token, Prompts
  oder Konto-/Gruppennamen;
- vor Apply überprüftes Open-WebUI-Backup und erwarteter Fingerprint aus
  demselben read-only Audit. Auf halbfertige oder veränderte Modellbestände
  wird nicht automatisch erneut geschrieben;
- Rollback über Modell-API nur nach separater Freigabe und unverändertem
  Vier-Profil-Fingerprint. Kein blindes Löschen älterer Modelle.

## Start auf bp-controller

Basis-Repository unverändert lassen. Ein separates detached Worktree
benutzen:

    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-family-model-activation"
    BR="feat/bergen-ai-family-model-activation-20261019"
    git -C "$BASE" fetch origin "$BR"
    test ! -e "$WT"
    git -C "$BASE" worktree add --detach "$WT" "origin/$BR"

Im existierenden Worktree statt worktree add:
    git -C "$WT" switch --detach "origin/$BR"

Bereits vorhandene lokale Dateien im BASIS-Repository:
  ansible/vars/bergen-ai-family-audit.local.yml
  ansible/vars/ai-oidc.vault.yml

Die erste enthält drei tatsächliche Familien-/Eltern-/Kindergruppennamen
und den gewählten Host bergen-ai. Die zweite muss den gültigen
administrativen Open-WebUI-Bearer als vault_open_webui_admin_token
enthalten. Die bisherige Gültigkeit dieses Tokens ist nicht nachgewiesen;
bei API_UNAVAILABLE_OR_DENIED zuerst seine Rotation prüfen, nicht
am Berechtigungsmodell vorbei arbeiten.

### Fehlender administrativer API-Schlüssel (Live-Befund 19.10.2026 22:21)

Der Betreiber-Preflight wurde korrekt gestoppt:
`VAULT_ADMIN_TOKEN_DEFINED=False`,
`VAULT_ADMIN_TOKEN_MIN_LENGTH_OK=False`, alle sonstigen
nichtgeheimen Voraussetzungen erfüllten das READ_ONLY-Gate.
`PLAY RECAP: ok=1 changed=0 failed=1`. Es wurde weder eine
Modell-API noch eine Gruppen-/Dokumentänderung ausgeführt.

Der Name `vault_open_webui_admin_token` ist eine **separate**
Ansible-Vault-Variable und nicht identisch mit einem Synology
OIDC-Client-Secret oder dem Linux-Vault-Passwort. Ist er nicht
vorhanden, lokal über einen bestehenden autorisierten Open-WebUI-
Administrator einen API-Schlüssel beschaffen und in der bereits
verschlüsselten Datei ergänzen:

    cd "$HOME/bergen-platform"
    ansible-vault edit --vault-id ai@prompt ansible/vars/ai-oidc.vault.yml

Dort den Schlüssel als
`vault_open_webui_admin_token: '<lokal-geheim-verwalteter-Schlüssel>'`
ergänzen, ohne andere Schlüssel zu überschreiben.
Nie auf Kommandozeile, in Chat, im Git oder im Ansible-Output offenlegen.

Open WebUI stellt API-Schlüssel üblicherweise unter dem eigenen
Administratorprofil **Settings → Account → API Keys** bereit.
Wenn der Bereich fehlt, zuerst nur die effektive globale
API-Key-Einstellung im Adminbereich prüfen. Ein notwendiges
temporäres Einschalten muss vom Betreiber bewusst geprüft werden;
**Default-API-Keys für Kinder/Regulärbenutzer bleiben ausgeschaltet**.
Bei einem bestehenden API-Schlüssel kann eine Neuausstellung die
alte Integration sofort ungültig machen. Aktive Secrets nach Abschluss
des Rollouts sicher widerrufen/rotieren.

Danach denselben Default-READ_ONLY-Playbooklauf wiederholen.
`VAULT_ADMIN_TOKEN_DEFINED=True` belegt zunächst nur das Vorhandensein
der Variablen, **nicht** die Wirksamkeit des API-Schlüssels. Das bestätigt
erst der geschützte Admin-GET und der durchgehende STATUS=EMPTY_READY.

READ_ONLY Audit (standardmäßig, keine Freigabe-Flags erforderlich):

    cd "$WT"
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/manage-bergen-ai-family-chat-profiles.yml \
      -e "@$BASE/ansible/vars/bergen-ai-family-audit.local.yml" \
      -e "@$BASE/ansible/vars/ai-oidc.vault.yml" \
      --vault-id ai@prompt

Soll: AUDIT=READ_ONLY, STATUS=EMPTY_READY, CHANGED=False,
REQUIRED_MODELS_PRESENT=YES, CONFIG_SHA256=64-stelliger Wert.

Nach unabhängig verifiziertem Backup/Restore von
/srv/ai/open-webui/webui.db in einer IGNORIERTEN lokalen
0600 YAML-Variablendatei zusätzlich:

    bergen_ai_family_model_mode: apply
    bergen_ai_family_model_approved: true
    bergen_ai_family_model_backup_verified: true
    bergen_ai_family_model_expected_sha256: EXAKTER_LIVE_AUDIT_SHA256

Der APPLY verwendet denselben Ansible-Befehl plus ein zusätzliches
-e @pfad-zu-lokaler-Freigabe-Datei.
Ein erfolgreicher Apply liefert PRIVATE_PROFILES_STAGED, CREATED=4.
Eine zweite Prüfung meldet ALREADY_STAGED.

Sollten API-Token, Modelle oder Datenbankbestand abweichen, wird
fail-closed abgebrochen. Bei Teil-Apply nicht blind wiederholen.

## Interimslösung: Open-WebUI-Gruppen manuell nutzen

Betreiberentscheidung 20.10.2026: Die vorhandenen drei Gruppen werden
zunächst **manuell in Open WebUI** gepflegt. Die dauerhafte automatische
Synology-OIDC-Zuordnung folgt getrennt in Issue #98. Dies ist eine
kontrollierte Übergangslösung; Identitätsentzug aus Synology entfernt
bis dahin **nicht automatisch** die lokale Open-WebUI-Mitgliedschaft.

Die Reihenfolge ist verbindlich:

1. Erst die vier *privaten* Aliasmodelle kontrolliert per Staging-Playbook
   anlegen und deren Berechtigungen nachprüfen. Für die erste Freigabe
   verweigert das Playbook zu Recht jede bereits bestehende Mitgliedschaft;
   die Mitgliedschaften erst **danach** pflegen.
2. Im administrativen Open-WebUI-Gruppenbereich nur **tatsächlich
   identifizierte vorhandene Konten** zuordnen. Nicht aus E-Mail-Adressen
   oder einer gespeicherten OAuth-Verknüpfung die Rolle erraten. Ein
   Elternkonto erhält `Familie` und `Eltern`, ein Kinderkonto
   `Familie` und `Kinder`; niemals beides.
3. Unterstützte Open-WebUI-v0.10.2-API-Routen sind
   `POST /api/v1/groups/id/{id}/users/add` und
   `POST /api/v1/groups/id/{id}/users/remove`. Für den ersten
   Betrieb die administrative Gruppenoberfläche nutzen, damit keine
   User-ID oder Admin-API-Token in Kommandozeile oder Git erscheint.
4. Das vorhandene `pending`-Konto **nicht pauschal** freischalten.
   Freigabe der Rolle `user` nur nach expliziter Identitätsprüfung.
   Der Admin-Account ist kein tauglicher Nachweis der Rechte regulärer
   Benutzer.
5. Danach Eltern-/Kinder-Modelle mit einem echten unprivilegierten Konto
   per UI und Direkt-API gegentesten: nur die zwei passenden Modelle,
   keine öffentlichen Rohmodelle, keine fremden Profile, keine
   Eltern-Paperless-Dokumente. Beide Kinderprofile müssen
   `Vorsagen untersagt` erfüllen.
6. Bis zur automatischen Zuordnung müssen Gruppenänderungen in Synology
   **auch lokal** nachvollzogen werden. Mitglieder bei Entzug sofort
   aus der entsprechenden lokalen Open-WebUI-Gruppe entfernen und
   die Wirkung auf aktive Sessions/API-Zugriffe testen.

**Kein Workaround durch Public/Familie-Model-Grants** und keine globale
Rollenfreigabe an alle Benutzer.

## Danach: automatische Benutzerzuordnung nach Issue #98

Der Live-Iststand vom 19.10.2026 war:
vier Open-WebUI-Konten, davon zwei user, eines pending, eines admin,
drei gespeicherte OAuth-Verknüpfungen, NULL Gruppenmitglieder.
Private Modell-Aliase sind ohne tatsächliche Mitgliedschaft für
Endnutzer NICHT sichtbar. Deshalb ist das private Modell-Staging noch
keine vollständig aktivierte Eltern-/Kinderanwendung.

Ein gespeicherter OAuth-Link beweist nicht die aktuelle Zugehörigkeit
bei Synology. Vor der Gruppenzuordnung Identitäts-Claims für genau
diese drei allowlist-Gruppen validieren. Leere/fehlende Claims,
Gruppenentzug, deaktivierte Konten, Sessions und API-Token müssen
zuverlässig entziehen; keine pauschale DEFAULT_USER_ROLE=user,
kein ungetestetes ENABLE_OAUTH_GROUP_MANAGEMENT=true und keine
öffentlichen Model-Grants. Nicht manuell IDs erraten.

Danach reale Positiv-/Negativtests pro Kind/Elternkonto an UI und API:
beide kindlichen Aliasprofile verfügbar, Elternprofile/Rohmodelle
gesperrt, kein RAG/Paperless-Datenzugriff. Die beiden Kinderprofile
müssen den 10-Fälle-Vorsagen-E2E-Katalog in frischen und mehrturnigen
Chats erfüllen.

Status: Versioniertes Bereitstellungsverfahren und Tests, produktiver
Apply und Gruppenzuordnung von GitHub aus NICHT durchgeführt.
