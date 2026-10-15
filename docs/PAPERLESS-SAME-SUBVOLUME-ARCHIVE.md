# Bergen Paperless – same-subvolume-Archiv im versteckten Quellordner

**Entwicklungsstand 15.10.2026, Draft-PR #81. Keine Produktivfreigabe.**

## Entscheidung und Verzeichnisstruktur

Für jeden der vier konfigurierten Scan-Quellordner wird ein
Unterverzeichnis **.paperless-archive** vorgesehen:

    Paperless/
      Scan.pdf
      .paperless-archive/
        2026-10/
          <v1-Sender-Receipt-ID>.pdf

Der Unterordner liegt im selben konfigurierten Scan-Quellordner.
Er muss tatsächlich dasselbe Dateisystem beziehungsweise Btrfs-
Subvolume verwenden. Die Implementierung prüft gleiche
Device-ID und verwendet ausschließlich
**renameat2 mit RENAME_NOREPLACE**. Falls die Kernel-
Operation nicht verfügbar oder die Verschiebung über eine
Subvolume-Grenze notwendig ist, wird abgebrochen. Es gibt
keinen Copy-Delete-Fallback, keine Zielüberschreibung und
keinen automatischen 30-Tage-Purge.

Der Inotify-Watcher beobachtet nur die unmittelbaren
Scan-Ordner, nicht deren Unterverzeichnisse. Der v1-Sender
ignoriert Verzeichnisse ohne PDF-Endung; seine bestehenden
Receipts werden nicht verändert.

## Implementierte Komponenten

- ansible/files/paperless/prepare_synology_hidden_archives.py:
  Root-Audit und optional nur Verzeichniserstellung für alle
  konfigurierten Scopes, jeweils UID paperless-sync, Modus 0700;
  zusätzlich das private Archiv-Journal im Sender-State.
- ansible/playbooks/prepare-paperless-synology-hidden-archives.yml:
  Audit als Standard, Verzeichniserstellung nur mit explizitem
  paperless_hidden_archive_prepare=true.
- ansible/files/paperless/synology_same_volume_archive_move.py:
  Manueller v1-SENT-Archivierungsworker. Nur ein Scope/Dateiname,
  SHA-256-, Identitäts- und Importbelegprüfung, exklusives
  senderseitiges sync.lock; fsync von Dateiinhalten und Journal;
  ARCHIVE_PREPARED vor dem Rename, ARCHIVED nach synchronisiertem
  Rename und erneuter Integritätsprüfung. Unklarer Status
  blockiert weitere Ausführung bis zur manuellen Reconciliation.
- ansible/playbooks/stage-paperless-synology-archive-worker.yml:
  Separates Staging des Workers unter dem bereits existierenden
  root-eigenen Synology-Codeverzeichnis, Hash-Abgleich und
  fehlender Aktivierungsgate.
- ansible/files/paperless/select_one_verified_archive_move.py:
  Strikte Auswahl eines einzelnen NAS-v1-SENT-Receipts mit
  korrespondierender lebender Paperless-IMPORTED-Dokument-ID
  und SHA-256.
- ansible/playbooks/archive-paperless-verified-import.yml:
  Frischer, getrennter Live-Export von venombox/LXC 126
  und Synology, Vergleich auf dem Controller, Übertragung des
  ausgewählten Belegs direkt zum NAS-Worker. Ausschließlich
  Dry-Run, solange keine separate Freigabe vorliegt.

**Vorerst nur v1-SENT:** Der nachgelagerte v2-Transport-
und Importpfad ist noch nicht produktiv aktiviert.
Nach Archivierung darf ein neuer Scan mit gleichem alten
Dateinamen den v1-Receipt-Schutz nicht umgehen; die
Versionierung des Senders bleibt deshalb ein separates Thema.

## Controller-Abnahme der neuen Funktionen

Auf einem aktuellen Worktree des PR #81:

    python3 -m unittest discover -s tests -p 'test_paperless_synology_same_volume_archive_move.py' -v
    python3 -m unittest discover -s tests -p 'test_paperless_select_one_archive_move.py' -v

Ansible-Syntax ohne Ausführung auf den Hosts:

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/prepare-paperless-synology-hidden-archives.yml \
      -e @ansible/vars/paperless-synology.local.yml --syntax-check

Nach dem bereits bestandenen lesenden NAS-Audit mit fünf fehlenden
Verzeichnissen kann ein Administrator ausdrücklich nur die
**fünf leeren Verzeichnisse** anlegen:

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/prepare-paperless-synology-hidden-archives.yml \
      --vault-id paperless@prompt \
      -e @ansible/vars/paperless.vault.yml \
      -e @ansible/vars/paperless-synology.local.yml \
      -e '{"paperless_hidden_archive_prepare": true}'

Direkt danach das Leseaudit für die **tatsächlichen** DSM-ACLs der
neu angelegten Ordner mit
`-e '{"paperless_require_hidden_archives": true}'` wiederholen.
Ohne diesen expliziten Post-Provision-Modus ist
`ARCHIVE_CANDIDATE ABSENT` ein reiner Hinweis und verhindert den
frühen, lesenden ACL-Audit nicht. Mit dem neuen Schalter werden
fehlende Archive bzw. das private Journal als BLOCKER gewertet.
**Boolesche Zusatzvariablen als JSON übergeben**, nicht als einfache
`-e name=true`-Strings. Der ACL-Audit zeigt zuerst alle
Befunde und schlägt anschließend bei erkannten geerbten Benutzer-/
Familiengruppenrechten oder technischen BLOCKERn fehl. Solche
Rechte sind vor jeder PDF-Archivierung separat zu entfernen/
einzuschränken; die reine POSIX-0700-Prüfung reicht nicht aus.
Ein leerer Archivordner darf bereits bestehen, **aber kein
Commit-Gate und keine Verschiebung**.

Der erste echte Aufruf des Verzeichnis-Playbooks bleibt
ein READ-ONLY-AUDIT. Erst nach Prüfung der ACLs darf der
Operator ausdrücklich die Ordnererstellung aktivieren.
Das Staging des Workers ist nochmals ein separater Schritt.

Ein einzelner Controller-Dry-Run kann nach erfolgreichem
Staging mit dem exakten Dateiparameter

    -e paperless_archive_only='Familie/Scan.pdf'

aufgerufen werden. Alle weiteren erforderlichen NAS-
und Paperless-Variablen stammen aus dem bestehenden
ignorierten Inventar und Vault. Keine Dateinamen,
Kennwörter oder Belege in Git oder PR-Kommentaren speichern.

## DSM-ACLs: Linux-Modus auf neu angelegten Archivordnern

Nach dem Anlegen der vier versteckten Ordner auf MountainCloud gab
`synoacltool -get` auf ihnen `rc=255` mit
`(synoacltool.c, 596)It's Linux mode` zurück. Das bedeutet in diesem
konkreten Fall: **keine native Synology-ACL auf dem Archivordner**.
Die ursprünglichen Scan-Eingangsordner bleiben dagegen
DSM-ACL-gesteuert. Der private Archivordner wird nicht in DSM-ACLs
umgewandelt, solange ein wirksamer POSIX-Modus ausreicht.

Der Read-only-Audit akzeptiert ausschließlich die eindeutige
Linux-Modus-Meldung bei `root`-geprüftem Verzeichnistyp,
Eigentümer `paperless-sync`, POSIX-Modus `0700` und
demselben `st_dev` wie der Scan-Eingangsordner. Er gibt
`HIDDEN_ARCHIVE_POSIX_PRIVATE <scope>` aus.
Andere `synoacltool`-Fehler, abweichende Eigentümer/Modi,
Device-Wechsel oder neu auftretende native DSM-ACLs
bleiben ausdrücklich **BLOCKER**.

Beispiel für die strenge erneute Prüfung:

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/audit-paperless-synology-acls.yml \
      --vault-id paperless@prompt \
      -e @ansible/vars/paperless.vault.yml \
      -e @ansible/vars/paperless-synology.local.yml \
      -e '{"paperless_require_hidden_archives": true}'

**Das ist noch keine produktive Freigabe.** Die effektiven
Zugriffsrechte müssen mit echten nichtprivilegierten NAS-/
LDAP-Identitäten positiv (`paperless-sync`) und negativ
(Familie, Eltern, Kinder, sonstige Benutzer) überprüft werden.
Insbesondere haben Mitglieder der Familiengruppen umfassende
Rechte auf den **übergeordneten Eingangsordnern**. Damit muss
gesondert geprüft werden, ob der versteckte Archivordner
selbst umbenannt oder entfernt werden könnte. Ein rein
privater Inhalt (`0700`) schützt nicht automatisch den
Verzeichniseintrag im beschreibbaren Elternverzeichnis.
Solche Prüfungen dürfen die realen Archive nicht als
Testobjekte umbenennen oder löschen.

## Schutz des Archiv-Verzeichniseintrags

**Wichtig:** `0700` schützt bei klassischen POSIX-Rechten den
Inhalt des versteckten Archivs; die Lösch-/Rename-Berechtigung am
*übergeordneten Scan-Eingangsordner* ist eine andere Frage.

Bei den bisher beobachteten Synology-ACLs erhalten
`Familie@bergen.intern` und `Eltern@bergen.intern` an ihren
jeweiligen Scan-Eingangsordnern `rwxpdDaARWc--`. Darin
steht `D` für **Delete child** und `d` für Delete.
Damit besteht ein konkreter möglicher Schutzbruch:
Berechtigte Gruppenmitglieder könnten unter Umständen den
Eintrag `.paperless-archive` umbenennen oder entfernen,
selbst wenn sie den Inhalt nicht öffnen können.

Die neue, ausschließlich lesende Prüfung
`audit-paperless-synology-archive-entry-protection.yml`
liest die nativen DSM-ACLs aller vier Scan-Eingangsordner.
Sie blockiert bei nichtadministrativen Delete-/Write-Grants.
**Sie versucht niemals**, den echten Archivordner umzubenennen
oder zu löschen. Sie leitet auch aus einem fehlenden
auffälligen Allow-Eintrag **keine endgültige Freigabe**
ab: wirksame LDAP-/SMB-Rechte müssen unabhängig mit
unprivilegierten Testidentitäten geprüft werden.

Erwartete Gegenmaßnahme bei bestätigter Gefährdung:
Archivwurzel in ein **root-kontrolliertes, nicht von
Scanner-/Familiengruppen umbenennbares Verzeichnis**
auf demselben Btrfs-Subvolume verlagern, statt
blind Berechtigungen auf bestehenden Scan-Eingängen
zu ändern. Die Zielorte müssen über Mountinfo und native
DSM-ACLs je Scope nachgewiesen werden; ein Pfad im anderen
Subvolume ist **keine** rename-basierte Archivlösung.

Die bis dahin angelegten vier versteckten Ordner bleiben
leer, der Move-Worker gesperrt. Keine ACL-Autoänderung
oder automatische Bereinigung.

## Standortentscheidung nach bestätigtem Vierfach-Blocker

Der reale, **lesende** DSM-Parent-ACE-Audit vom 15.10.2026 ergab:

- `Privat/thomas`: Delete/Rename-Grant für `thomas@bergen.intern`
- `Privat/nadja`: Delete/Rename-Grant für `nadja@bergen.intern`
- `Eltern`: Delete/Rename-Grant für `Eltern@bergen.intern`
- `Familie`: Delete/Rename-Grant für `Familie@bergen.intern`

Ergebnis `RISKY_SOURCE_ACL_GRANTS 4`,
`ARCHIVE_ENTRY_PROTECTION_BLOCKED`, `NO_FILES_CHANGED`.

**Folge:** Die angelegten vier `.paperless-archive`-Ordner
bleiben leer. Der aktuelle Worker `synology_same_volume_archive_move.py`
verwendet noch genau diese geblockten Quell-Unterordner und darf
ausdrücklich **nicht** für produktive Archivierungs-Renames
freigegeben werden, selbst wenn seine 30+ Offline-Tests bestehen.
Es gibt keine neue Commit-Freigabe und keine automatische
30-Tage-Bereinigung.

**Geplante Alternative:** ein geschützter Archivstamm außerhalb
der beschreibbaren Eingangsordner, aber **auf dem jeweiligen
Subvolume**. Da die Synology `homes` und `paperless-scan`
als getrennte Btrfs-Subvolumes verwendet, sind mindestens zwei
Archivstämme erforderlich. Exakte Pfade erst nach Audit festlegen.

Neuer rein lesender Standort-Audit:

    python3 -m unittest discover -s tests \
      -p 'test_paperless_protected_archive_candidates.py' -v

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/audit-paperless-synology-protected-archive-candidates.yml \
      --vault-id paperless@prompt \
      -e @ansible/vars/paperless.vault.yml \
      -e @ansible/vars/paperless-synology.local.yml

Der erste Live-Aufruf des Standort-Audits vom 15.10.2026
brach **lesend, ohne Dateiveränderung** bei
`UNRECOGNIZED_NATIVE_ACL_ENTRY` ab. Das bedeutet:
mindestens eine DSM-ACE-Darstellung am ermittelten
Dateisystem-Wurzelverzeichnis ist noch nicht vom Parser abgedeckt.
**Es gibt noch keinen freigegebenen Standort.** Das
Diagnose-Update gibt bei unbekannten ACEs die betreffende
Scope-Kennung und den auf 240 Zeichen begrenzten
`UNRECOGNIZED_PARENT_ACE`-Eintrag aus, setzt den
jeweiligen Kandidaten auf `BLOCKER` und analysiert
die restlichen Scopes weiter. Keine Erweiterung des
ACL-Parsers ohne anhand realer NAS-Ausgabe überprüfte Syntax.

Der zweite echte NAS-Lauf vom 15.10.2026 bestätigte die
zwei vorgeschlagenen Standortwurzeln:

| Scopes | Quelle `st_dev` | Kandidat |
| --- | ---: | --- |
| `Privat/thomas`, `Privat/nadja` | 47 | `/volume1/homes/.bergen-paperless-archive` |
| `Eltern`, `Familie` | 1048641 | `/volume1/paperless-scan/.bergen-paperless-archive` |

`paperless-scan` ergab
`NATIVE_PARENT_NO_OBVIOUS_DELETE_GRANT`; `homes` war
wegen des speziellen DSM-ACE-Principals
`owner::allow:rwxpdDaARWcCo:fd--` noch blockiert,
`ARCHIVE_PARENT_BLOCKERS 2`.
Der Parser kennt jetzt **nur diese zusätzlich beobachtete
Sonderform `owner::`** und behandelt sie ausschließlich dann
als Eigentümerrecht von `root`, wenn das geprüfte
Elternverzeichnis `st_uid == 0` hat. Jede andere unbekannte
Sonderform und jeder nichtadministrative Delete-/Rename-Grant
bleibt gesperrt. Die 19 angepassten Tests und der erneute
Live-Audit stehen noch aus; kein Standort ist produktiv
freigegeben.

Dieser Audit steigt von jedem konfigurierten Scan-Verzeichnis
zu dessen oberstem `st_dev`-gleichen Verzeichnis auf,
prüft dessen root-Eigentümer und native DSM-ACLs auf
mögliche nichtadministrative Delete-/Rename-Grants und
schlägt einen separaten `.bergen-paperless-archive`-Unterordner
vor. Keine Verzeichniserstellung, ACL-Änderung oder
Test-Umbenennung. Ein scheinbar sicherer Kandidat bleibt
`ARCHIVE_PARENT_CANDIDATES_NEED_EFFECTIVE_TEST`
bis zu **echtem Subvolume-ID-Nachweis**, effektiven
LDAP-/SMB-Rechtetests, Backup/Restore und zur Anpassung
des Workers an den neuen, zentral geschützten Zielpfad.

## Unabhängige Freigabe und Vorbereitung je NAS-Standort

**Entscheidung 15.10.2026:** Ein Standort-Blocker darf den
anderen Standort nicht aufhalten. `homes` und
`paperless-scan` werden vollständig **getrennt** auditiert
und die *leeren* geschützten Verzeichnisse werden nur für
den ausdrücklich gewählten Standort erstellt.

Der überarbeitete Read-only-Standort-Audit unterstützt:

    -e paperless_archive_site=paperless-scan
    -e paperless_archive_site=homes

Ohne Standortfilter (`all`) bleiben die Gesamtübersicht
und das strenge globale Ergebnis erhalten. Mit Filter
werden ausschließlich die **zwei erwarteten Quell-Scopes**
des jeweiligen Standorts geprüft. Die Anzahl der erwarteten
Devices wird dann `1` statt `2`.

Neue getrennte Standortvorbereitung:

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/prepare-paperless-synology-protected-archive-site.yml \
      --vault-id paperless@prompt \
      -e @ansible/vars/paperless.vault.yml \
      -e @ansible/vars/paperless-synology.local.yml \
      -e paperless_archive_site=paperless-scan

**Dieser Befehl ist ausschließlich lesend.** Erst nach
bestandenen Regressionstests und dem gesonderten
Live-Preflight wird für **denselben** Standort explizit
hinzugefügt:

    -e '{"paperless_protected_archive_prepare": true}'

Dieser Befehl legt nur folgende **leere** Verzeichnisse an:

    /volume1/paperless-scan/.bergen-paperless-archive/
      Eltern/
      Familie/

Die nachgelagerte Variante `paperless_archive_site=homes`
kann unabhängig geprüft und vorbereitet werden:

    /volume1/homes/.bergen-paperless-archive/
      Privat/
        thomas/
        nadja/

Die Python-Standortvorbereitung ermittelt die Wurzelpfade
aus der laufenden, root-eigenen Synology-Konfiguration.
Sie vertraut keinen hart kodierten Device-Zahlen und
prüft Eigentümer, tatsächliche Device-Grenzen,
native DSM-ACLs des Elternverzeichnisses, leere
bisherige Quell-Archive, private Eigentümer/Modi
und **Abwesenheit des Move-Gates** erneut direkt
auf der NAS. Unbekannte ACEs, nichtadministrative
Löschrechte sowie geerbte native DSM-ACLs auf den
neuen geschützten Ordnern blockieren.

**Nicht** Teil der Vorbereitung sind: PDF-Import,
Archivierungsworker-Umbau, Quell-PDF-Rename,
ACL-Änderung an bestehenden Scans, Gate-Erstellung
oder automatischer Purge. Eine erfolgreiche
`PROTECTED_SITE_PREPARED`-Meldung ist nur
ein Staging-Nachweis, keine produktive
Freigabe der Löschkette. Der neue Worker muss
die beiden standortbezogenen Archivwurzeln
noch ausdrücklich statt der bisherigen
`.paperless-archive`-Unterordner verwenden.

## Beide geschützten Standorte eingerichtet: 15.10.2026

Die kontrollierte Verzeichniserstellung ist auf der Live-NAS
für **beide** Standorte einzeln erfolgreich:

- `paperless-scan`: Wurzel und `Eltern`/`Familie` erstellt;
  Device `1048641`, `PROTECTED_SITE_PREPARED paperless-scan`.
- `homes`: Wurzel, `Privat`, `Privat/thomas`,
  `Privat/nadja` erstellt; Device `47`,
  `PROTECTED_SITE_PREPARED homes`.

Beide Playbooks meldeten `ok=4 changed=1 failed=0`,
`NO_SCAN_OR_RECEIPT_FILES_CHANGED`,
`ARCHIVE_GATE_ABSENT` und
`ARCHIVE_COMMIT_NOT_AUTHORIZED`.
Die zuvor korrigierten Regressionstests für zwei
Standorte und ACL-Sonderfälle liefen mit **22/22 + 12/12**.

Die vollständige Read-only-Nachprüfung der beiden
eingerichteten Archivbäume **ist auf der Live-NAS erfolgreich**:
auf `paperless-scan` `PROTECTED_ARCHIVE_EMPTY_TREE_VERIFIED
paperless-scan 3`, auf `homes`
`PROTECTED_ARCHIVE_EMPTY_TREE_VERIFIED homes 4`.
Beide Ansible-Läufe: `ok=4 changed=0 failed=0`,
`PREPARE_DISABLED`, `NO_FILES_CHANGED`,
`ARCHIVE_COMMIT_NOT_AUTHORIZED`. Damit wurden alle sieben
erwarteten Verzeichnisobjekte inklusive tatsächlichem
`paperless-sync`-Eigentümer, Modus `0700`, Device,
fehlenden DSM-nativen Unterordner-ACLs und
dem erwarteten leeren Inhaltsbaum geprüft.
Die zusätzlichen Offline-Regressionstests liefen nach
Korrektur der Linux-mode-Fixture mit **15/15**.

Die vorher angelegten `.paperless-archive`-Ordner
innerhalb der vier beschreibbaren Quell-Scan-Verzeichnisse
sind **nicht** zur Archivierung freigegeben. Der
vorbereitete geschützte Archivbaum enthält weiterhin
keine PDF-Dokumente.

**Die Archivierungsfreigabe ist weiterhin gesperrt**:
Im Entwicklungsbranch wurde der Worker auf die geschützten
Wurzeln umgestellt. Vor einem ersten Live-Dry-Run müssen
die neuen Offline-Tests vollständig erfolgreich laufen
und ausschließlich der deaktivierte Worker mit
`stage-paperless-synology-archive-worker.yml` ausgerollt
werden. Der tatsächliche kontrollierte Rename bleibt bis
zum vollständigen Standort-Acceptance-Test gesperrt.
Insbesondere sind effektive LDAP-/SMB-Rechtetests,
Backup- und Restore-Probe, Scanner-Race-Prüfung,
Btrfs-Subvolume-ID / Linux-`renameat2` und echte
Importbeweiskette noch nötig. Bis dahin darf keine
Archiv-PDF entstehen.

## Worker-Umstellung auf beide geschützten Archive

Der Entwurfs-Worker
`ansible/files/paperless/synology_same_volume_archive_move.py`
erhält jetzt das Zielverzeichnis **explizit** als
`archive_scope_dir`. Der produktive CLI-Einstieg
wählt den Pfad ausschließlich aus den root-kontrollierten
`synology_config.SETTINGS["sources"]`, der erwarteten
Scope-zu-Standort-Zuordnung und der ermittelten
`st_dev`-Grenze. Die Device-Wurzel muss `root`
gehören und exakt `homes` bzw. `paperless-scan`
heißen. Alle geschützten Verzeichnis-Komponenten
müssen dem technischen `paperless-sync`-Benutzer
gehören, Modus `0700` haben und auf demselben
Device liegen. Für `Privat/thomas` und
`Privat/nadja` wird auch die zusätzliche
`Privat/`-Zwischenebene geprüft.

| Scope | Neues Archivziel (vor Monatsunterordner) |
| --- | --- |
| `Privat/thomas` | `/volume1/homes/.bergen-paperless-archive/Privat/thomas/` |
| `Privat/nadja` | `/volume1/homes/.bergen-paperless-archive/Privat/nadja/` |
| `Eltern` | `/volume1/paperless-scan/.bergen-paperless-archive/Eltern/` |
| `Familie` | `/volume1/paperless-scan/.bergen-paperless-archive/Familie/` |

Die alten versteckten `.paperless-archive`-Ordner
unter den beschreibbaren Scan-Eingängen werden **niemals**
als Ziel verwendet; sie bleiben unberührt. Der Rename
bleibt `renameat2(RENAME_NOREPLACE)`, die
Sender-`SENT`-, Paperless-`IMPORTED`- und
SHA256-Beweiskette bleiben unverändert. Das Journal
enthält zusätzlich `archive_site` und den vollständigen
`archive_scope_dir` zur eindeutigen späteren
Wiederherstellung und Crash-Reconciliation.

Die produktive Archivierung wird **pro Standort**
getrennt abgesichert. Nur eine unabhängige, spätere
root-autorisierte Freigabe mit `0600`, ohne
Symlink/Hardlink und unter folgendem Namen könnte
einen Commit erlauben:

- `state_parent/archive-move.homes.enabled`
- `state_parent/archive-move.paperless-scan.enabled`

Die **alte globale** Datei
`state_parent/archive-move.enabled` ist ausdrücklich
keine Freigabe, sondern ein Blocker, sobald sie
existiert. Der Code-Stage-Prozess verweigert die
Installation bei jeder dieser drei Freigabedateien,
auch wenn nur ein Standort betroffen ist.
**Keines der Playbooks erzeugt eine Freigabedatei.**
Der Standard des Controller-Playbooks bleibt
`paperless_archive_commit=false` (Dry-Run).

Für den neuen Stand sind mindestens diese
Offline-Tests auf `bp-controller` durchzuführen:

    python3 -m unittest discover -s tests \
      -p 'test_paperless_synology_same_volume_archive_move.py' -v

Die angepasste Serie (32 Testmethoden, zuletzt nur im
Branch aktualisiert; Lauf auf `bp-controller` steht noch aus)
prüft unter anderem den
pro Standort geschützten Zielpfad, die getrennten
Freigabedateien, Symlink-/Mode-Blocker, Crash-
und Replay-Barrieren sowie echte Kernel-`renameat2`
mit temporären Test-PDFs. Erst nach erfolgreichem
Test und Re-Review darf der Worker in *deaktiviertem*
Zustand auf die NAS übertragen werden.

## Btrfs und echter Kernel-Rename-Test (Stand 15.10.2026)

Der Live-Read-only-Nachweis mit
`btrfs inspect-internal rootid` bestätigt für alle vier
Archiv-Paare identische Btrfs-Subvolume-IDs:

- `Privat/thomas` und `Privat/nadja`: Quelle und
  geschütztes Ziel jeweils Subvolume `437`.
- `Eltern` und `Familie`: Quelle und Ziel jeweils
  Subvolume `7446`.

`SUBVOLUME_FAILURES 0` und `NO_FILES_CHANGED`.
Das ist **noch kein** Nachweis der DSM-Kernel-Unterstützung
für `RENAME_NOREPLACE`.

Dafür gibt es nun den gesonderten, nicht automatisch
ausgeführten Test
`ansible/playbooks/audit-paperless-synology-renameat2.yml`.
Er ist standardmäßig **ausschließlich lesend**:

    -e paperless_renameat2_site=paperless-scan

Erst mit **ausdrücklich gesetztem, booleschem**
`-e '{"paperless_renameat2_probe": true}'` erzeugt er
für genau einen Standort einen isolierten
`0700`-Testordner **direkt unter dem jeweiligen
Subvolume-Root, neben statt innerhalb der produktiven
Scan- und geschützten Archivverzeichnisse**.

In diesem temporären Ordner führt `paperless-sync`
den tatsächlich auf der NAS installierten
`_noreplace_rename`-Kernel-Aufruf aus. Zuerst muss
die Kollision mit bestehendem Ziel
`EEXIST` zurückgeben, ohne Quelle/Ziel zu verändern.
Dann wird eine *selbst erzeugte* Test-PDF aus einem
Test-Unterordner in einen anderen umbenannt.
Dateiinhalt, SHA256, Device und Inode müssen erhalten
bleiben. Anschließend wird **nur** dieser Testordner
bereinigt. Der Test überprüft zusätzlich unmittelbar
zuvor alle drei fehlenden Commit-Gates und die
aktuellen `btrfs rootid`-Zuordnungen.

Der Test erzeugt **keine** Archiv-PDF unter
`.bergen-paperless-archive`, verschiebt keine
eingehenden Scans, berührt keine Receipts/Journals
und aktiviert keinen Worker. Er kann zunächst
auf `paperless-scan`, anschließend getrennt auf
`homes` ausgeführt werden. Auch ein erfolgreicher
Fixture-Test erlaubt noch **keinen** produktiven Commit.

Neue Regressionstests:

    python3 -m unittest discover -s tests \
      -p 'test_paperless_synology_renameat2_probe.py' -v

Ansible-Syntaxprüfung vor Remote-Probe:

    ansible-playbook -i ansible/inventory.yml \
      -i ansible/inventory.local.yml \
      ansible/playbooks/audit-paperless-synology-renameat2.yml \
      --syntax-check

**Live-Stand 15.10.2026:** Die neue Offline-Testserie
lief zunächst mit 8/8 grün und der reine
`paperless-scan`-Preflight bestand mit
`PROTECTED_SUBVOLUME_ID 7446`,
`PROTECTED_SOURCE_SCOPES_VERIFIED 2`,
`PROBE_DISABLED`, `NO_FILES_CHANGED`.
Der nachfolgende Live-`--probe`-Versuch
**brach noch vor dem Kernel-Rename** mit
`SYNODB_RENAME_PROBE_BLOCKED UNSAFE_NEW_FIXTURE`
ab. Die darauffolgende lesende Diagnose
belegte die Ursache: Das neu erstellte Verzeichnis
`/volume1/paperless-scan/.bergen-rename-probe-nvv2h7kc`
hatte UID/GID `0:0`, Modus `0000`, Device
`1048641`, Inode `317` und native, von
`/volume1/paperless-scan` **geerbte DSM-ACLs**
(inklusive Lese-ACE für `Familie@bergen.intern`).
Es war **leer**. Der Btrfs-Root selbst meldet
ebenfalls POSIX-Modus `0000` und wird über
die DSM-ACL verwaltet.

Die korrigierte Probe entfernt deshalb
`synoacltool -del` **ausschließlich an einem
neu erzeugten, inode-, device-, uid- und
leerheitsgeprüften eigenen Testordner**, nicht
am Subvolume-Root oder an den geschützten
Archiven. Anschließend werden `paperless-sync`
und POSIX `0700` gesetzt und `It's Linux mode`
mit strengem Format sowie die unveränderte
Subvolume-ID geprüft. Jede unerwartete ACL,
fehlgeschlagene ACL-Entfernung, unbekannte
Datei oder geänderte Inode blockiert.

**Wichtige Sicherheitskorrektur:** Die erste Version
prüfte `UNSAFE_NEW_FIXTURE` außerhalb des
`try/finally`-Cleanup. Daher kann ein
`.bergen-rename-probe-*`-Restordner auf der NAS
verblieben sein. Er darf **nicht blind gelöscht**
werden; zuerst nur lesend den Inhalt, Inode,
Eigentümer, Modus, Device und native Synology-ACL
inventarisieren. In der folgenden Entwicklungsfassung
liegt auch dieser Check innerhalb von `try/finally`:
Vor Beginn des eigentlichen Fixtures wird nur
`rmdir` auf einem nachweislich unveränderten,
**leeren** eigenen Testordner versucht; nach Start
nur eine exakt bekannte Teststruktur gelöscht,
bei fremden Dateien oder Inodewechsel weiterhin
fail-closed. Zusätzliche fünf Offline-Tests
wurden ergänzt. Fünf weitere Offline-Tests
überprüfen die strikt isolierte ACL-Normalisierung
(aktuell **18** Tests, erneute Ausführung
**noch ausstehend**).

**Keinen erneuten Live-Probe versuchen**, bevor
der oben benannte alte, leere Testordner nach
zusätzlicher Identitätsprüfung kontrolliert per
`rmdir` entfernt und die korrigierte 18-Test-Serie
sowie der lesende Vorab-Audit bestanden sind.
Beide Archiv-Commit-Gates bleiben gesperrt.

## Synology-ACL-Header: tatsächliche Ausgabe (15.10.2026)

Der zweite explizite `paperless-scan`-Kernel-Probe-Lauf
brach **vor jeder Verschiebung** mit
`UNEXPECTED_INHERITED_FIXTURE_ACL` ab. Der
bereinigte `try/finally`-Pfad bestätigte dabei
`ISOLATED_EMPTY_FIXTURE_CLEANED paperless-scan`.
Ein danach kontrolliert angelegter, unveränderter
Diagnoseordner (`st_dev=1048641`, `root:root`,
POSIX-Modus `0000`) zeigte mit zwei identischen,
lesenden `synoacltool -get`-Aufrufen:

    ACL_GET_1_RC 0
    ACL_GET_2_RC 0
    'ACL version: 1 \\n'
    'Archive: is_inherit,is_support_ACL \\n'

Die Kopfzeilen enthalten im DSM **zusätzliche
Leerzeichen vor dem Zeilenende**. Der alte Parser
forderte dagegen `ACL version: 1\\n` ohne
Leerzeichen. Der Diagnoseordner wurde unmittelbar
per `rmdir` entfernt:
`EMPTY_DIAGNOSTIC_FIXTURE_REMOVED`,
`NO_SOURCE_OR_ARCHIVE_FILES_CHANGED`.

Korrektur auf diesem Draft-Branch: Der Parser
akzeptiert ausschließlich **horizontale abschließende
Leerzeichen/Tabs** in den beiden erwarteten
Kopfzeilen. Exit-Code muss weiterhin 0 sein,
`stderr` muss leer bleiben, die Reihenfolge,
`ACL version: 1` und
`Archive: is_inherit,is_support_ACL` müssen
unverändert stimmen. Keine Änderung an
Owner-/Device-/Inode-/Subvolume-Checks, an
`synoacltool -del`-Beschränkung auf den eigenen
neuen *leeren* Testordner oder an den
Commit-Gates.

Fünf weitere Regressionstests decken genau die
DSM-Ausgabe mit Zeilenend-Leerzeichen, die
unformatierte Ausgabe, falsche Flags/Reihenfolge,
führende oder interne Leerzeichen sowie
Toolfehler ab (**23** Tests insgesamt,
**Ausführung des neuen Stands ausstehend**).
Bis zum bestandenen Test: **kein erneuter
Live-Kernel-Probe-Lauf**.

## Noch gesperrte produktive Verschiebung

Vor einer Standort-Commit-Freigabe müssen alle
offenen Sicherheits- und Wiederherstellungsnachweise
erfüllt werden; eine nur strukturell eingerichtete
Archivwurzel ist noch **keine** Rename-Freigabe.

Vor einer Freigabe müssen folgende Punkte erfüllt sein:

1. Neue Offline-Tests und Ansible-Syntax vollständig bestanden.
2. Verzeichnisse und **native DSM-ACLs** in allen vier Scopes
   geprüft, insbesondere keine Sichtbarkeit privater Archive
   für Kinder oder unberechtigte Familienmitglieder.
   Ein führender Punkt im Ordnernamen schützt keine Daten.
3. Echte Subvolume-/Device-Prüfung und Linux-
   RENAME_NOREPLACE-Funktion auf Synology DSM nachgewiesen.
4. Ein frisches NAS-Backup samt Restore-Test für Archiv und
   Journal bestätigt (nur LXC-vzdump reicht dafür nicht).
5. Race mit anderen DSM-Schreibprozessen beim Scanner-Input
   ausgeschlossen oder kontrolliert. Ein bloßes lstat direkt
   vor rename verhindert nicht jede konkurrierende Ersetzung.
6. Eigens erzeugte Test-PDF von Synology bis Paperless
   kontrolliert importiert, vollständige Owner-/ACL-Prüfung
   bestanden und Archiv-Dry-Run bestätigt.
7. Manuell freigegebener Einzel-Rename mit bestätigter
   Archivkopie und Wiederherstellung, einschließlich Crash-
   und Wiederanlaufszenarien. Keine automatischen Retries.
8. Die 19 historischen v1-Receipts bleiben unverändert.

## Retention

Das ARCHIVED-Journal enthält den UTC-Archivzeitpunkt.
Ein Purge-Worker existiert **nicht**. Archive bleiben
daher auch nach den ersten 30 Tagen unverändert erhalten,
bis eine unabhängige Retention-Freigabe implementiert ist.
Die Herkunftsdatei im Eingang wird beim atomaren Rename
entfernt – hierfür sind die oben genannten Prüfungen
unverzichtbar.

**Status:** Entwurf im Repository. Keine produktive
Installation oder Freigabe. Der frühere gemeinsame Offline-
Teststand von 181/181 gilt nur für Commit b18ee48;
die neuen Komponenten müssen gesondert getestet werden.
