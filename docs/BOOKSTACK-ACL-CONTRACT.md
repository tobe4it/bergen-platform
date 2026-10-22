# BookStack: verbindlicher OIDC-/ACL-Vertrag

Status: DESIGN ONLY · 2026-10-18. Keine produktiven Benutzer-/Rollenänderungen.

## 1. Sicherheitsinvarianten

1. Zugang nur über individuelle Familienkonten; keine öffentliche Leseberechtigung.
2. Eltern lesen jedes persönliche Buch eines **minderjährigen** Kindes, ohne damit Bearbeitungs-/Löschrecht zu erhalten.
3. Geschwister lesen oder bearbeiten persönliche Bücher der jeweils anderen Kinder **nicht**.
4. Persönliche Bücher von Elternteilen sind voneinander getrennt; das globale Elternrollen-Grant darf sie nicht sichtbar machen.
5. Eltern- und Familienrollen erhalten keine indirekten Rechte über andere Rollen, Default-Rolle, Shares, Shelf oder Kommentare.
6. BookStack-Administratoren können alle Inhalte sehen. Administrative Ausnahmen sind technisch unvermeidbar und müssen organisatorisch getrennt werden.
7. OIDC-Rollenänderungen sind für bestehende Sessions und langlebige API-Tokens gesondert zu behandeln; Login-Synchronisierung allein ist kein sofortiger Entzug.

## 2. Identitätsvertrag mit OIDC-Provider

ID-Token (keine token- oder claimbasierten Geheimnisse protokollieren):
- issuer: umgebungsspezifisch, per HTTPS, exakte Konfiguration.
- sub: stabiler, nicht wiederverwendeter Schlüssel pro Familienidentität. Keine Namen/E-Mail-Adressen als alleiniger Identitätsschlüssel.
- email, name: Anzeige/Benachrichtigung, keine ACL-Identität.
- groups: Array der gruppenspezifischen IDs/Namen im **ID-Token**; nicht nur in UserInfo.
- Signatur: RS256 (derzeit BookStack-Anforderung), JWKS/discovery vom festgelegten Issuer. PKCE verwenden.
- Minimale Scopes: openid, profile, email, erforderliche group-Claims; keine unnötigen Personendaten.

BookStack-Vorgaben bei Aktivierung:

    AUTH_METHOD=oidc
    AUTH_AUTO_INITIATE=true
    OIDC_NAME=Family SSO
    OIDC_ISSUER=https://idp.example.invalid
    OIDC_ISSUER_DISCOVER=true
    OIDC_CLIENT_ID=__SET_VIA_VAULT__
    OIDC_CLIENT_SECRET=__SET_VIA_VAULT__
    OIDC_USER_TO_GROUPS=true
    OIDC_GROUPS_CLAIM=groups
    OIDC_ADDITIONAL_SCOPES=groups
    OIDC_REMOVE_FROM_GROUPS=true
    OIDC_FETCH_AVATAR=false
    OIDC_DUMP_USER_DETAILS=false

Diese Werte sind ein **nicht lauffähiges Beispiel**. Echte URL, Auth-Client, Claims und Secrets gehören ausschließlich in git-ignorierte Site-Variablen/Ansible Vault. Registrierungsrolle ohne globales Leserecht setzen.

### Gruppen-Mapping

Logische Rollen (Anzeigenamen unabhängig von IdP-Domains):
- wiki-family: Mitgliedschaft in Gruppe Familie.
- wiki-children: Mitgliedschaft in Gruppe Kinder.
- wiki-parents: Mitgliedschaft in Gruppe Eltern.
- wiki-personal-<stable-id>: genau **eine** zugehörige Person; getrennte BookStack-Rolle pro Person.
- wiki-operator: separat geschützte administrative Identität (nicht normale Elternrolle).

BookStack kann pro Rolle External Authentication IDs mit OIDC-Gruppen matchen. Die vollständigen Gruppen-IDs inklusive Domains werden pro Site gemappt. Beispiele wie Familie@EXAMPLE.INVALID oder wiki-personal-A1@EXAMPLE.INVALID sind niemals produktive Defaults.

**Wichtige Korrektur:** Bei OIDC_REMOVE_FROM_GROUPS=true fallen manuell vergebene persönliche Wiki-Rollen bei der Anmeldung möglicherweise weg, wenn sie nicht im OIDC-Claim vorkommen. Daher auch persönliche Mitgliedschaften durch IdP-Gruppen ausdrücken; keine lokale manuelle Personal-Rolle als einzige Wahrheitsquelle. Nicht alternativ OIDC_REMOVE_FROM_GROUPS=false setzen, da dadurch entzogene Gruppenrechte im Wiki verbleiben können.

Zwei unabhängige Claims/Checks: (a) Role sync der bekannten Gruppen, (b) Bestandsabgleich aller erwarteten Personal-Gruppen. Unbekannte OIDC-Gruppen dürfen keine BookStack-Rolle erhalten; nach Client-/IdP-Umstellung den Claim-Vertrag erneut prüfen.

## 3. Rechte pro Buch

R = lesen; C = Seiten/Unterstrukturen erzeugen; U = aktualisieren; D = löschen. Zusätzlich Berechtigung zum Verwalten von Berechtigungen, Export und Sharing **nicht** pauschal erteilen.

| BookStack-Buch | wiki-family | wiki-children | wiki-parents | persönliche Owner-Rolle | Sonstige |
|---|---|---|---|---|---|
| Haus & Alltag | R | R | R,C,U,D | — | keine |
| Gemeinsame Projekte | R | R,C,U (nach Inhaltsfreigabe) | R,C,U,D | — | keine |
| Kinder gemeinsam | R | R,C,U | R,C,U,D | — | keine |
| Eltern | keine | keine | R,C,U,D | — | keine |
| Persönlich: Kind A | keine | keine | R | R,C,U für A | keine |
| Persönlich: Kind B | keine | keine | R | R,C,U für B | keine |
| Persönlich: Elternteil P | keine | keine | keine | R,C,U für P | keine |
| Persönlich: Elternteil Q | keine | keine | keine | R,C,U für Q | keine |

Eigener Bereich: D (Delete) standardmäßig AUS; versehentliches Löschen soll nicht ohne Restore möglich sein. Ausnahmen werden separat genehmigt. Persönliche A/B/P/Q sind **abstrakte Testidentitäten**, keine realen Namen.

Allgemeine Rollen dürfen keine systemweiten Asset-Berechtigungen erhalten, die persönliche Bücher öffnen. Auf jedem Schutz-Buch:
- In der BookStack-Permissions-Ansicht „Everyone Else“ auf explizit KEINE Rechte setzen (nicht „Inherit defaults“).
- Anschließend ausschließlich die erlaubten Rollen pro Buch ausdrücklich aktivieren.
- Keine Admin-Systemrolle für Alltagskonten; Admin umgeht Book-Rechte.
- Jede Änderung an Shelf/Book/Chapter/Page mit ACL-Regression prüfen; Permissions auf Shelves kaskadieren **nicht** automatisch zu Büchern.
- Rechte sind kumulativ: Wo gleich spezifische Zuweisungen kollidieren, kann ein Grant gewinnen. Gewollte Rolle ausdrücklich als Allow am Buch hinterlegen, ungewollte nicht.
- Keine Inhaltslinks zu privaten Büchern in für Geschwister sichtbaren Seiten, die Titel/Metadaten verraten können; Suche, Bilder und Anlagen ebenfalls testen.
- Generische „Familie“-Leserechte niemals auf persönliches Buch kopieren.

## 4. Rollenzuständigkeit und Lebenszyklus

- Beide Eltern erhalten wiki-parents (Leserecht Kind A/B; Vollzugriff Eltern-Buch), zusätzlich jeweils eine eigene Personal-Rolle.
- Jedes Kind erhält wiki-children und eigene Personal-Rolle; Geschwister-Personalgruppen bleiben strikt getrennt.
- Eintritt: IdP-Identität verifizieren, Gruppe vergeben, BookStack-Rollenabgleich kontrollieren, eigenes Buch mit deny-by-default erzeugen, Matrix testen.
- Austritt/Sperrung: IdP-Zugriff entfernen, BookStack-Sessions und API-Tokens untersuchen/entziehen, anschließend Zugehörigkeit in BookStack prüfen. Nicht nur zukünftigen OIDC-Login blockieren.
- Volljährigkeit: Regel „Eltern lesen private Kinderbücher“ endet **nicht technisch automatisch**, solange das Buch als Kindbuch der Elternrolle zugeordnet ist. Deshalb Pflichtprozess mit Erinnerungs-/Prüfdatum und expliziter Berechtigungsentscheidung vor/bei Volljährigkeit.
- Namens-/Domain-Wechsel: mapping external_auth_id/subject erhalten; Gruppendomäne in Site-Variablen aktualisieren; nie neue Benutzer durch wechselnde Mailadresse erstellen.
- Sorgerechts-/Familienrollenwechsel und technische Administrationskonten bedürfen separater dokumentierter Behandlung.

## 5. Konkreter Negativtest-Katalog vor Freigabe

Prüfung **mit echten getrennten Testkonten** in isolierter Testumgebung; positive und negative Pfade jeweils UI, Suche, direkte URL, Bild/Anhang, API soweit aktiviert.

| Nr. | Rolle/Identität | Aktion | Ziel | Erwartung |
|---|---|---|---|---|
| ACL-01 | Kind A | lesen und editieren | eigenes Buch A | erlaubt |
| ACL-02 | Kind A | lesen, suchen, Direktlink | Buch B | verweigert, keine Metadaten |
| ACL-03 | Kind B | lesen, suchen, Direktlink | Buch A | verweigert, keine Metadaten |
| ACL-04 | Kind A | lesen | Buch Eltern | verweigert |
| ACL-05 | Kind A | lesen | Kinder gemeinsam | erlaubt |
| ACL-06 | Elternteil P | lesen | Buch Kind A und B | erlaubt |
| ACL-07 | Elternteil P | editieren/löschen | Buch Kind A/B | verweigert |
| ACL-08 | Elternteil P | lesen und editieren | eigenes persönliches Buch P | erlaubt |
| ACL-09 | Elternteil P | lesen und suchen | persönliches Buch Q | verweigert |
| ACL-10 | Elternteil Q | lesen und suchen | persönliches Buch P | verweigert |
| ACL-11 | Kind B | Bild-/Attachment-Direktlink | Buch A | verweigert |
| ACL-12 | nicht angemeldet | UI/URL/Bild/API | jedes private Buch | verweigert |
| ACL-13 | Kind A | Erstellung/Export/Sharing | Eltern-Buch | verweigert |
| ACL-14 | Kind A | rollenfremde API-Operationen | Buch B/P/Q | verweigert |
| ACL-15 | Elternteil P | eigenes Buch-Bild/Anhang | Buch P | erlaubt |
| ACL-16 | Testkonto ohne Familiengruppe | Lesen/Suche | alle Bücher | verweigert |
| ACL-17 | Kind A nach Gruppenentzug | Suche/API mit neuer Anmeldung und bestehenden Tokens | Buch A | verweigert, Tokens invalidiert |
| ACL-18 | Kind B | globaler Suchindex/Recent Activity | Buch A | keine Leaks |
| ACL-19 | Elternteil Q | Seite mit Includes fremder Personalinhalte | Buch P | kein privater Inhalt |
| ACL-20 | normale Familienrolle | Berechtigungen/Adminfunktionen ändern | jedes Buch | verweigert |

Zusätzlich:
- Prüfen, dass zufällige neue OIDC-Identitäten keine globalen Grants über Default Registration Role erhalten.
- „Deny“ auf Book gegenüber unbeabsichtigten Grants aus mehreren Rollen und Rollen-Overrides testen.
- Nach Änderung/Renaming eines Gruppenclaims kompletten Berechtigungs-Regressionstest wiederholen.
- API-Token immer als Benutzer mit seinem jeweiligen effektiven Recht validieren, nie als Administrator.

## 6. Bergen-AI: ACL-Vertrag für später

**Bis zur separaten Freigabe deaktiviert**. Ein globales RAG-/Index-Dienstkonto für alle Bücher ist unzulässig.

Für später:
1. Authentisierte Session/Identität aus vertrauenswürdigem OIDC-Kontext; Buch- und Seiten-ACL wird bei jedem Read **serverseitig** anhand des BookStack-Rechteträgers erzwungen.
2. BookStack REST API-Authentifizierung über streng getrennte, auf jeweils den berechtigten Benutzer begrenzte Token-Kontexte. OIDC-Token darf nicht einfach als BookStack-API-Token ausgegeben/umgedeutet werden.
3. Keine gemeinsamen Vector Stores, Chat-Verläufe, Caches, Vorschau-Snippets oder Suchindizes über Rollen hinweg; Verweise und Zitate nur wenn der aktuelle Benutzer die Quellen sehen darf.
4. Schreibaufträge nur als nachweisbar einem Benutzer zugeordneter Vorschlag; kein stilles Auto-Update. Freigabe/Versionierung und Konfliktprüfung gegen aktuelle Seitenrevision.
5. Persönliche Kinderbücher: Eltern können lesen/zusammenfassen, aber **nicht** im Namen des Kindes editieren; Administratorumgehungen ausgeschlossen.
6. Revocation vor Cache-TTL bzw. sofortige Sperrung sicherheitskritischer Inhalte; maximale Cache-Lebensdauer und technische Lösung werden **vor** Integration getestet.

Ohne eine nachweisbar robuste usergebundene Identität → API-Rechtekette: **keine KI-Anbindung an private Inhalte**.

## 7. Technische Quellen

- OIDC-Claim-/Sync-Vorgaben: https://www.bookstackapp.com/docs/admin/oidc-auth/
- BookStack-Prioritäten/Vererbung/Kollision: https://www.bookstackapp.com/docs/user/roles-and-permissions/
- Bilder-Schutz: https://www.bookstackapp.com/docs/admin/upload-config/
- Admin-Bypass und Security: https://www.bookstackapp.com/docs/admin/security/
