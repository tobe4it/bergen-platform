# Bergen-AI Familienberechtigungen – sicherheitsgeprüfte Vorschau

Issue: [#98](https://github.com/tobe4it/bergen-platform/issues/98)

## Reproduzierter Istzustand (read-only, 18.10.2026)

Die produktive Open-WebUI-Instanz **0.10.2** verwendet persistente
Benutzerberechtigungen in SQLite. Nach der in [PR #103](https://github.com/tobe4it/bergen-platform/pull/103)
bereits erfolgreich angewandten vierteiligen globalen Standardrechtebasis
bleiben folgende **globale** Freigaben ON: `features.memories`,
`features.calendar`, `chat.web_upload`, `chat.share`.
Die Gruppenkombination Familie + Kinder würde aktuell außerdem
Websuche, Bildgenerierung, Code-Interpreter und Datei-Uploads freigeben.
Die unabhängige Read-only-Inventur meldet 3 Gruppen mit 0 Mitgliedschaften.

**Das bedeutet keine bewiesene produktive Kinder-Berechtigung.**
Es gibt noch keine Gruppenzuordnungen. Die hypothetische Auswertung
wendet nur die dokumentierte ODER-Verknüpfung der v0.10.2-Gruppen an.

## Zielmatrix (nur Planung, keine Änderung)

| Berechtigung | Global | Familie | Kinder | Eltern |
| --- | --- | --- | --- | --- |
| `features.memories` | OFF | ON | ON | unverändert |
| `features.calendar` | OFF | ON | ON | unverändert |
| `features.automations` | bereits OFF | OFF | OFF | unverändert |
| `features.web_search` | bereits OFF | OFF | OFF | unverändert |
| `features.image_generation` | bereits OFF | OFF | OFF | unverändert |
| `features.code_interpreter` | bereits OFF | OFF | OFF | unverändert |
| `chat.file_upload` | bereits OFF | OFF | OFF | unverändert |
| `chat.web_upload` | OFF | OFF | OFF | unverändert |
| `chat.share` | OFF | OFF | OFF | unverändert |
| API-Schlüssel, freie Toolserver, Webhooks | bisher OFF | OFF | OFF | unverändert |
| `sharing.public_*` | produktiven Istwert getrennt prüfen | OFF | OFF | unverändert |

`Familie` und `Kinder` bleiben getrennte, **flache** Gruppen.
Spätere Kinder müssen ausdrücklich **beiden** Gruppen zugeordnet
werden; die Gruppen sind nicht hierarchisch.
Das Freigabemodell eines Elternteils wird in der Vorschau **nicht verändert**.
`Eltern` kann später ausgewählte Funktionen zusätzlich erhalten.

Die Anwendung erlaubt in v0.10.2 nicht, ein `true` in einer
niedrigeren Gruppe durch ein `false` in einer anderen Gruppe
zu widerrufen. Deshalb sind globale **und** Gruppenrechte zu prüfen.
`features.memories=true` ist keine Garantie für individuelle
Lernfortschritte, `features.calendar=true` kein Nachweis
zuverlässiger Erinnerungszustellung und ein System-Prompt kein
technisches Mittel gegen fertige Hausaufgaben.

## Versioniertes Preview-Audit

`ansible/playbooks/plan-bergen-ai-family-rights-readonly.yml`
berechnet ausschließlich in Python-Speicher, ohne Produktivänderung:
- SHA256 des vollständigen aktuellen Bundles (globale Berechtigungen
  plus die drei gespeicherten Gruppenrechte);
- SHA256 eines möglichen Zielbundles, mit zielgerichtet umgelegten
  Berechtigungen und unveränderten übrigen Werten;
- simulierte `CHILD`-Rechte bei späterer `Familie+Kinder`-Mitgliedschaft;
- Anzahl außerhalb der ausdrücklich vorgesehenen Freigaben
  verbleibender `true`-Werte in Familien- und Kindergruppen;
- kein SQL-DML, kein ORM-Upsert, keine Benutzer-/Gruppenanlage,
  keine lokalen oder externen Benachrichtigungen.

`NEEDS_POLICY_REVIEW` bedeutet, dass weitere schon gespeicherte
Berechtigungen von Familie oder Kindern positiv bleiben. Diese müssen
vor dem Entwurf eines produktiven Appliers einzeln geprüft werden;
sie können mit dem vorgesehenen `false`-Subset nicht einfach
als sicher deklariert werden.

Der Prüfer bricht ab bei: falscher Open-WebUI-Version,
abweichenden Gruppennamen/-zahlen, einer Mitgliedschaft,
bestehenden Gruppen-Ressourcenfreigaben, einer öffentlichen
Gruppen-Share-Policy, nicht administrativen Gruppeneigentümern,
fehlender persistenter SQLite, unbekanntem Schema sowie
fehlender vorheriger globaler vierteiliger Schutzbasis.

## Ausführung auf bp-controller

Eigenen Worktree anlegen, damit PR #103 oder PR #105 unverändert bleibt:

```bash
(
set -euo pipefail

cd "$HOME/bergen-platform-ai-family-audit"
git fetch origin feat/bergen-ai-family-rights-preflight-20261018
git worktree add --detach "$HOME/bergen-platform-ai-rights-preflight" FETCH_HEAD

cp -p ansible/vars/bergen-ai-family-audit.local.yml \
  "$HOME/bergen-platform-ai-rights-preflight/ansible/vars/bergen-ai-family-audit.local.yml"

cd "$HOME/bergen-platform-ai-rights-preflight"
BASE="$HOME/bergen-platform"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/plan-bergen-ai-family-rights-readonly.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/bergen-ai-family-audit.local.yml
)
```

## Release-Gates für spätere produktive Ansible-Änderung

1. Plan-Istzustand unabhängig prüfen und die komplett simulierte
   Zielkonfiguration einschließlich aller nicht vorgesehenen
   verbliebenen `true`-Berechtigungen fachlich abnehmen.
2. Gesondertes **versioniertes** Ansible-Apply mit expliziter Freigabe,
   vorherigem vollständigem gesichertem Berechtigungsbundle, exaktem
   aktuellem SHA, ORM-basierten Schreibzugriffen,
   Schutz vor partieller Anwendung und dokumentiertem Rollback
   erst nach vollständiger Staging-Prüfung.
3. Unabhängiger Read-only-Audit nach Änderung und erneute
   Verifizierung des globalen Fingerabdrucks.
4. Kinder-/Eltern-E2E-Negativtests der tatsächlichen API und
   UI-Berechtigungen, Trennung der individuellen Memories,
   persönliche Kalender mit verifizierter Termin-/Zustellfunktion,
   effektiver Rechteentzug bei Gruppenwechsel und der
   pädagogische Hausaufgabentest.
5. Bis zur Freigabe **keine Gruppenmitglieder**, keine OIDC-
   Autosynchronisierung, keine Paperless-/RAG-Freigabe,
   kein Open-WebUI-Neustart.

Die aktuelle PR implementiert **ausschließlich Stufe 1** und
enthält keinen produktiven Apply- oder Rollback-Code.
