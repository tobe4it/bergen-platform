# Paperless: Korrespondenten und Dokumenttypen sichtbarer Dokumente

Stand 22.10.2026: **Read-only audit vorbereitet, nicht produktiv ausgeführt**.

## Verbindliche Zugriffspolitik

Jedes angemeldete menschliche Familienmitglied kann die Korrespondenten und
Dokumenttypen jener Paperless-Dokumente sehen, für die es bereits eine gültige
`view_document`-Berechtigung hat. Der Zugriff auf Metadaten entsteht durch
die Dokumentfreigabe, **nicht umgekehrt**. Er erlaubt weder das Lesen
privater Dokumente noch das Ändern/Löschen von Korrespondenten, Typen
oder Dokumenten.

Ein Metadatenobjekt, das sowohl an ein sichtbares als auch an ein nicht
sichtbares Dokument gebunden ist, kann unter seinem Namen erscheinen.
Die Dokumentliste und Zähler müssen dennoch durch `view_document`
gefiltert bleiben. Im Gegensatz zu den bereits für alle freigegebenen
38 Tags erhalten Familienmitglieder **nicht pauschal alle** Korrespondenten
und Dokumenttypen.

Die neun zuletzt bestätigten nur Thomas zugänglichen Dokumente
bleiben insbesondere vor Nadja verborgen. Dokumente der Gruppe Eltern
bleiben vor den Kinderkonten geschützt.

## Gegenwärtiger Arbeitsstand

Das Script `ansible/files/paperless/audit_visible_document_taxonomy_readonly.py`
erhebt für Paperless-ngx 3.3.0 ausschließlich:

- tatsächliche aktive Mitglieder von `Familie@bergen.intern`;
- effektive per-Dokument-`view_document`-Rechte jeder Person;
- zugehörige `document_type_id` und `correspondent_id` der sichtbaren Dokumente;
- vorhandene `view_documenttype`- und `view_correspondent`-Objektrechte;
- erforderliche vs. fehlende Modellrechte;
- Verweigerung von `Eltern`-Dokumenten gegenüber Kinderkonten;
- noch gesperrte private Dokumente von Thomas gegenüber Nadja.

Die Ausgabe enthält ausschließlich Summen und Statuscodes, keine
Personennamen außer bereits fest programmierten Prüfreferenzen,
keine Metadaten- oder Dokument-IDs, Titel, Inhalte oder Geheimnisse.

**Wichtig:** Ein zukünftiger Rechte-Synchronisierer muss auch *Entzug*
von Metadatenfreigaben berücksichtigen, wenn ein Dokument nicht länger
gemeinsam zugänglich ist. Bereits unabhängig bestehende individuelle Rechte
dürfen dann nicht versehentlich entfernt werden. Deshalb wird zunächst
nur der präzise Rechtebedarf auditiert; **noch kein Apply bereitgestellt**.

## Ausführen auf bp-controller

```bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  WT="$HOME/bergen-platform-visible-taxonomy"
  BRANCH=feat/paperless-visible-document-taxonomy-20261022
  git -C "$BASE" fetch origin "$BRANCH"
  PIN="$(git -C "$BASE" rev-parse FETCH_HEAD)"

  if ! test -d "$WT"; then
    git -C "$BASE" worktree add --detach "$WT" "$PIN"
  fi
  cd "$WT"
  test -z "$(git status --porcelain)"
  git switch --detach "$PIN"

  "$BASE/.venv/bin/python" -m unittest discover -s tests \
    -p 'test_paperless_visible_document_taxonomy.py' -v

  "$BASE/.venv/bin/ansible-playbook" \
    -i ansible/inventory.yml \
    -i "$BASE/ansible/inventory.local.yml" \
    ansible/playbooks/audit-paperless-visible-document-taxonomy.yml \
    --vault-id ai@prompt
)
```

Erwartete Ausgaben: `TYPE_VIEW_GAPS`,
`CORRESPONDENT_VIEW_GAPS`, die fehlenden Modellrechte sowie
`THOMAS_PRIVATE_DENIED_TO_NADJA` und
`CHILD_SEES_ELTERN_DOCUMENTS=0`.

Das Playbook enthält bewusst keinen schreibenden Zweig.
