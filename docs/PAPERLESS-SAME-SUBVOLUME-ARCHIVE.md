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

## Noch gesperrte produktive Verschiebung

Der echte Commit benötigt eine von root außerhalb
dieser Playbooks bereitgestellte Freigabedatei
(state_parent/archive-move.enabled), UID 0,
Modus 0600, ohne Hardlink/Symlink. Der Standard des
Controller-Playbooks ist commit=false; keines der neuen
Playbooks erzeugt den Gate.

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
