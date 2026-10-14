# Paperless-ngx 3.3 – Benutzerrechte und Eigen-Tag-Löschung

Referenz: https://docs.paperless-ngx.com/usage/#permissions und
Paperless-ngx v3.3.0 `src/documents/permissions.py`,
`src/documents/views.py` sowie `src/documents/models.py`.

## Verbindliche Grundsätze

- Eigene Tags dürfen gelöscht werden; reguläre Benutzer benötigen
  `documents.delete_tag` auf Modellebene. Der API-Endpunkt
  `TagViewSet` nutzt `PaperlessObjectPermissions`, das zusätzlich
  Eigentümerschaft bzw. explizite Objektberechtigung prüft.
- Vor der globalen Freigabe müssen alle Tags einen Eigentümer haben.
  Bei `owner=NULL` lässt Paperless die Objektprüfung durch.
- Fremde `delete_tag`-Objektfreigaben an Benutzer oder Gruppen sind
  Ausschlusskriterien. Insbesondere bleiben die 18 admin-eigenen
  Standard-Tags vor Löschung durch normale Benutzer geschützt.
- Das Löschen eines Tags entfernt dessen Dokumentzuordnungen,
  löscht aber keine Dokumente. Ein Tag mit Dokumenten kann daher
  inhaltlich relevant sein; Löschvorgänge erfolgen bewusst im UI.
- Kein `delete_document` auf gemeinsam genutzten Dokumenten.
  Keine Erweiterung von `is_staff`, `is_superuser` oder Workflows.

## Weitere Berechtigungen – Audit statt pauschaler Freigabe

| Modell | Empfohlene Nutzung | Entscheidung |
| --- | --- | --- |
| SavedView | Eigene gespeicherte Ansichten erstellen/bearbeiten/löschen | Audit, danach gesondert freigeben |
| Note | Notizen an zugänglichen Dokumenten | Paperless prüft im Dokument-Endpunkt view_document/change_document; fehlende globale Note-Rechte bedeuten nicht automatisch fehlende Notizfunktion |
| CustomField | Vorhandene Felder lesen/verwenden | Eigentümerregel und Datenmodell prüfen |
| StoragePath | Pfade lesen/verwenden | Keine unkontrollierte Pfadverwaltung |
| PaperlessTask | Eigene Tasks ansehen | Audit |
| ShareLink | Externe Freigabelinks | Standardmäßig nicht vergeben |
| Workflow | Globale Regeln, Dokumenteigentümer und Berechtigungen | Admin |
| AppConfig | Instanzweite OCR-/Systemkonfiguration | Admin |
| User/Group | Benutzer-/Gruppenverwaltung | Admin |
| SystemMonitoring/GlobalStatistics | Instanzinformationen bzw. Statistiken | Nicht pauschal vergeben |

Hinweis: Die Dokumentation unterscheidet globale Modellrechte von
Objektrechten. Der Besitzer darf eigene Objekte verändern, benötigt
aber weiterhin die passende globale Berechtigung.

## Ansible

`ansible/playbooks/prepare-paperless-user-rights.yml` führt
standardmäßig nur einen lesenden Audit aus. Er protokolliert für alle
aktiven regulären Konten die tatsächlich wirksamen globalen Rechte
und alle Sicherheitsblocker für `delete_tag`.

Nach Prüfung und ausdrücklicher Freigabe aktiviert
`-e paperless_user_rights_apply=true` **ausschließlich**
`documents.delete_tag` für die aktiven erwachsenen Tag-Verwalter
`nadja` und `thomas` (nicht `thomas3`).
Vor dem Commit werden die Tag-Editor-Basisrechte, unbesessene Tags und fremde
Löschobjektberechtigungen erneut überprüft. Es werden keine
Objektberechtigungen hinzugefügt und keine Tags oder Dokumente
verändert.

Neue Konten benötigen weiterhin die Benutzer-Baseline.
