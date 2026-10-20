# Bergen-AI: OIDC-Familienrollen und vier private Chatprofile

**Betriebsstand:** 20.10.2026; Open WebUI 0.10.2, Podman/Quadlet im bestehenden LXC `bergen-ai`, Ollama lokal. Dies ist der aktuelle Runbook- und Release-Nachweis für die Änderungen aus PRs #122–#125. Ältere erste-Installation-Anweisungen, die abgeschalteten OIDC-Gruppensync und null Mitglieder voraussetzen, gelten **nicht mehr**.

## Architektur

Drei vorhandene, zentral über Synology verwaltete OIDC-Rollengruppen: `Familie`, `Eltern` und `Kinder`. Tatsächliche standortspezifische Gruppennamen und Domänen stehen ausschließlich im lokalen ignorierten `ansible/vars/bergen-ai-family-audit.local.yml` (Mapping `bergen_ai_family_group_expected`). **Keine vier weiteren OIDC-Gruppen erforderlich.** Ein neuer OIDC-Callback synchronisiert die vorhandenen Gruppenzugehörigkeiten; ein Seiten-Reload allein reicht nicht.

`ENABLE_OAUTH_GROUP_MANAGEMENT=true` aktiv, `ENABLE_OAUTH_GROUP_CREATION=false` und `ENABLE_OAUTH_ROLE_MANAGEMENT=false` deaktiviert; `DEFAULT_USER_ROLE=pending` bleibt die Voreinstellung.

| Private Alias-ID | Name | Ollama-Basis | ACL |
| --- | --- | --- | --- |
| `bergen-eltern-qwen25` | Bergen AI – Eltern | `qwen2.5:14b-instruct-q4_K_M` | nur Eltern, read |
| `bergen-eltern-sprachen` | Bergen AI – Sprachen | `mistral-nemo:12b` | nur Eltern, read |
| `bergen-kinder-lernen` | Bergen AI – Lernbegleiter | `qwen2.5:14b-instruct-q4_K_M` | nur Kinder, read |
| `bergen-kinder-sprachen` | Bergen AI – Sprachtrainer | `mistral-nemo:12b` | nur Kinder, read |

`Familie` hat **keinen eigenen Modellgrant**. `bge-m3:latest` ist ausschließlich Embedding, kein Chatprofil. Alle Kinderprofile erhalten denselben **vollständigen** versionierten Lernprompt `ansible/files/bergen_ai/prompts/learning_companion_de_v1.md` mit „Vorsagen untersagt“. Die Elternprofile verwenden den konstanten `PARENT_PROMPT` im Stager. **Systemprompts sind keine technische Zugriffssperre.** Paperless, Websuche, externe Tools, Memory anderer Personen und RAG werden nicht dadurch freigegeben.

**Beschreibung der Profile:** Das aktuell gespeicherte generische Metadatenfeld ist „Privates Bergen-AI Gruppenmodell“. Die zuvor besprochenen verständlichen individuellen Profilbeschreibungen wurden noch **nicht** als vier unterschiedliche Beschreibungen produktiv aufgespielt; ihre redaktionelle Einführung wäre ein eigener, idempotent abgesicherter Änderungsumfang.

## Verifizierte produktive Fakten (20.10.2026)

- Gruppensync per geschützter Quadlet-Änderung aktiviert, Open WebUI neugestartet/gesund und effektives ENV bestätigt: `STATUS=GROUP_SYNC_ENABLED`; `ok=16 changed=3 failed=0`.
- Nach erneuter OIDC-Elternanmeldung: `ADULT_MEMBERS=1`, `FAMILY_MEMBERS=1`, `ADULT_USER_ROLES=1`, `CHILD_MEMBERS=0`. Der Auditor hat **nicht** selbst die rohen OIDC-Claims validiert.
- Vor Modellanlage: beide Ollama-Tags vorhanden, vier Alias-Sollprofile und Prompt-Policy plausibilisiert; `STATUS=READY_FOR_PRIVATE_PROFILES` und getrenntes Admin-API-Stager-Audit `STATUS=EMPTY_READY`.
- Produktiver Ansible-API-Apply via **bestehendem Administrator-Session-JWT**, ohne `sk-`-Schlüssel oder Aktivierung des globalen API-Key-Schalters: `STATUS=PRIVATE_PROFILES_STAGED`, `CREATED=4`, `CHANGED=True`, `ok=8 failed=0`. Gruppen-, OIDC- und Paperless-Konfiguration blieben unverändert.
- Unabhängiger `mode=ro`-SQLite-Audit: `REGISTERED_MODELS=4`, `MODEL_GRANTS=4`, `PUBLIC_READ_GRANTS=0`, `CHILD_RAW_MODEL_READ_GRANTS=0`, `UNKNOWN_OR_FOREIGN_MODEL_GRANTS=0`. Qwen und Mistral jeweils 2 aktive Aliase, je 1 Erwachsenen-/Kinder-READ-Grant. Zwei Elternmodelle wurden außerdem im iPhone-Browser eines angemeldeten Elternkontos gezeigt.
- **Nicht attestiert:** positiver Kinder-E2E-Test, direkte API-Deny-Tests von Kinder-/Pending- und Revoked-Sessions, fail-closed Rechteentzug bei leerem/fehlendem `groups`-Claim, Nachweis eines tatsächlichen Backup-Restores. Das `backup_verified=true` aus dem schreibenden Operator-Aufruf ist ein Freigabe-Boolean und **kein** unabhängiger Restorenachweis.

## Ansible-Betrieb und Idempotenz

Der aktuelle Sollzustand ist unter `main` nach dem Merge der gestapelten PRs versioniert. Auf `bp-controller` existieren private, ignorierte Inventory-/Site-Dateien und der ausschließlich lokal verschlüsselte Vault (`ansible/vars/ai-oidc.vault.yml`). Den eigenen Admin-Session-JWT dort nur für geschützte Schreibvorgänge als `vault_open_webui_admin_session_jwt` hinterlegen, nie an GitHub oder Chats senden. Keine SQL-Schreibzugriffe oder JWT-Fälschungen.

### Unabhängiger, tokenfreier Sollzustand-Audit

~~~bash
BASE="$HOME/bergen-platform"
cd "$BASE"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-family-model-access-readonly.yml \
  -e "@$BASE/ansible/vars/bergen-ai-family-audit.local.yml" \
  --vault-id ai@prompt
~~~

Erwartet: genau 4 Aliase, 4 private Grants, 0 Public-/Raw-Kinder-/Foreign-Grants und `changed=0`. Dieser Audit ist **nicht** der Snapshot-Fingerprint des schreibenden Stagers.

### Reproduzierbarer, autorisierter Apply

`manage-bergen-ai-family-chat-profiles.yml` startet standardmäßig im `audit`-Modus und liefert den aktuellen API-Stager-Fingerprint. Für den **ersten** Apply braucht es bestätigte wiederherstellbare Sicherung der Daten von `/srv/ai/open-webui` inklusive konsistenter SQLite/WAL-Dateien, eine explizite Genehmigung, einen gültigen Admin-JWT und den Fingerprint eines unmittelbar vorherigen `EMPTY_READY`-Stager-Audits. Ein stale oder fremder Zustand bricht fail-closed ab. Die vier POSTs sind **nicht atomar**; nach einem Teil-Apply niemals blind wiederholen.

Nach erfolgreicher erster Ausführung kann derselbe **bewusst freigegebene** Ansible-Apply mit dem *alten Erst-Apply-Fingerprint* erneut ausgeführt werden. Der Stager überprüft vor einer potenziellen Mutation erneut alle **vier** IDs, Basis-IDs, Namen, aktiven Flags, Systemprompts sowie genau je eine korrekte private Gruppen-READ-Freigabe. Entsprechen alle dem Soll, meldet er **`STATUS=ALREADY_STAGED`, `CREATED=0`, `CHANGED=False`**, auch wenn der frühere Preimage-Fingerprint inzwischen nicht mehr gültig ist. Für *jede tatsächliche* Mutation (First Apply und genehmigtes Rollback) ist dagegen weiter der **aktuelle** Snapshot-Fingerprint erforderlich. Backup-/Approval-Gates bleiben auch beim No-op bestehen. Bei Drift **keine** automatischen Lösch-/Reparaturversuche.

~~~bash
BASE="$HOME/bergen-platform"
cd "$BASE"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-bergen-ai-family-chat-profiles.yml \
  -e "@$BASE/ansible/vars/bergen-ai-family-audit.local.yml" \
  -e "@$BASE/ansible/vars/ai-oidc.vault.yml" \
  -e bergen_ai_family_model_mode=apply \
  -e bergen_ai_family_model_approved=true \
  -e bergen_ai_family_model_backup_verified=true \
  -e bergen_ai_family_model_expected_sha256=8a9d608e2537a1483b2603ebbf4a5b20ef994f952ce0f5429d823bb7e9cc4501 \
  --vault-id ai@prompt
~~~

**Die neue idempotente Second-Apply-Implementierung ist im CI synthetisch getestet; ein zweiter Live-Apply ist damit noch nicht nachgewiesen.** Den Befehl erst nach Audit, gültigem JWT und unabhängiger Backup-Freigabe ausführen. Nach erfolgreichem Deployment Admin-JWT aus Vault entfernen oder rotieren und die Sitzung beenden. Ein Rollback erfordert einen **eigenen** Approval-Gate und den zum aktuellen Vier-Profil-Zustand passenden Fingerprint; er löscht nur die vier Aliase, nicht OIDC oder Paperless.

## Offene Prüfpunkte und Releasegrenze

1. Kinderkonto via Synology erneut anmelden; in `Familie` und `Kinder` bestätigen, ohne Elternmodell-Sichtbarkeit.
2. Positive/negative *direkte* Modell-API-Tests für die vier Aliase und die raw Ollama-IDs mit Eltern-, Kinder-, Pending- und deaktivierter Sitzung durchführen. Nur die UI-Modellliste ist kein API-Deny-Beweis.
3. Gruppenentzug, abgelaufene Sessions sowie fehlende/leere OIDC-Claims in v0.10.2 separat fail-closed testen und gegebenenfalls technisch härten.
4. Konsistentes Backup inklusive WAL sowie Restore-Test nachweisen.
5. Individuelle Modellbeschreibungen nur per separatem geschütztem, idempotentem Metadaten-Update ergänzen.

**Akzeptanz:** vier Profile produktiv und Eltern-Sichtbarkeit nachgewiesen, Sicherheits-E2E für Kinder und Rechteentzug noch nicht freigegeben. Keine Aussage über vollumfängliche Sicherheit sämtlicher Zugriffswege.
