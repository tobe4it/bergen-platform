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
