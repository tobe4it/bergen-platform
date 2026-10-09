# Temporärer MQ-Zwei-Knoten-Transportaudit (Evaluation)

Die Transportprüfung erstellt pro Lauf ausschließlich eigene MQ-Objekte mit
eindeutigem Prefix `BGT.<7-HEX-ZEICHEN>`. Kanäle und XMITQs werden **nicht**
als dauerhafter Sollzustand bereitgestellt. Das statische
`mq-transport-objects.yml` wurde entfernt.

## Laufbezogene Objekte

Pro Lauf erzeugt `bergen_mq_topology.py` über den bestehenden,
TLS-authentifizierten JSON-MQSC-REST-Reconciler:

| Auf A (BERGENLAB) | Auf B (BERGENLABB) |
| --- | --- |
| QLOCAL `<prefix>.AX` mit `USAGE(XMITQ)` | QLOCAL `<prefix>.BX` mit `USAGE(XMITQ)` |
| SDR `<prefix>.A2B` | RCVR `<prefix>.A2B` |
| RCVR `<prefix>.B2A` | SDR `<prefix>.B2A` |

Sender und Receiver verlangen `TLS_AES_256_GCM_SHA384` und die Audit-Prüfung
verifiziert zur Laufzeit `DISPLAY CHSTATUS` mit `RUNNING`, `SECPROT(TLSV13)`
und dem ausgehandelten CipherSpec auf beiden Enden. Anschließend folgen je
Richtung fünf Transportvarianten mit zeitlich begrenzten MQ-GETs; die QREMOTE-
und Ziel-QLOCAL-Fixtures sind ebenfalls laufbezogen.

## Separate transport PKI preparation and activation

The pinned IBM MQ container imports extra certificates from
`/etc/mqm/pki/keys/<label>` and peer CA anchors from
`/etc/mqm/pki/trust/<label>` when starting. The existing default
`bergenlab` stays lexicographically ahead of `bergentransport`.
The transport channel declarations now explicitly set
`CERTLABL(bergentransport)` and the receivers require
`SSLCAUTH(REQUIRED)` (mutual TLS).

**Phase 1: certificate preparation (no service restart):**

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/mq-transport-pki-prepare.yml \
  -e mq_transport_pki_prepare=true --ask-vault-pass
```

This creates independently signed transport keys and two unique CAs on the
two MQ hosts, each with `serverAuth` + `clientAuth`; then exchanges ONLY
the public peer CA using delegated SSH. Private CA and identity keys remain
on their respective hosts. No existing `bergenlab` files are rewritten.
Ansible does not automatically attach the prepared files to a running
container.

**Phase 2: reviewed activation, separate change window:**

Preview before approval:

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/mq-transport-pki-activate.yml \
  -e mq_transport_pki_activate=true \
  -e mq_transport_restart_approved=true \
  --check --diff --ask-vault-pass
```

Only after reviewing the exact Quadlet diff and scheduling the impact of
restarting each MQ evaluation service may the same command be executed
without `--check`. It executes serially, verifies the existing pinned
image, checks prepared files, validates all existing nonblank Quadlet lines irrespective of their order (including the legacy LDAP-mount placement), inserts **exactly two read-only mount lines in one atomic replacement directly after the existing TLS mount**, preserving all other existing Quadlet lines, restarts
each MQ service if the Quadlet changed, and checks labels imported into
the running MQ key store. The standard `bergenlab` label must remain
unchanged; verify this by `DISPLAY QMGR CERTLABL` after activation.
Restarts interrupt existing MQ connections and are never authorized by
certificate preparation itself.

The pending service restarts and actual TLS 1.3 interoperability have
**not** been executed. Treat any import discrepancy as a stop condition,
not permission to weaken TLS.

## Entscheidung: getrennte, nicht privilegierte Transportidentitäten

Die Audit-Benutzer `bgtaudita` und `bgtauditb` behalten ihre bisherigen
Clientrechte. Die Queue-Manager verwenden `AUTHORMD(SEARCHGRP)` über LDAP
und sollen eigene Transport-Dienstidentitäten bekommen:

| Ziel-QMgr | Geplante MCA-Identität | Geplante LDAP-Gruppe | Erwartetes Peer-Zertifikat |
| --- | --- | --- | --- |
| BERGENLAB (A) | `bgttransa` | `MQBGTTRANSA` | `CN=bergen-mq-lab-b transport`; Issuer `CN=Bergen MQ Transport CA BERGENLABB` |
| BERGENLABB (B) | `bgttransb` | `MQBGTTRANSB` | `CN=bergen-mq-lab transport`; Issuer `CN=Bergen MQ Transport CA BERGENLAB` |

**LDAP-Identitäten am 09.10.2026 angelegt und zurückgelesen.** Beide Konten
(`bgttransa` UID 1000016, `bgttransb` UID 1000017) und die eigenen Gruppen
(`MQBGTTRANSA` GID 1000016, `MQBGTTRANSB` GID 1000017) wurden über das
explizit freigegebene Ansible-Provisionierungsplaybook angelegt. Ausführung:
`ok=20 changed=5 failed=0 skipped=1`; vier `ldapadd`-Aufrufe wurden
als `changed` gemeldet, außerdem die Entfernung der kurzlebigen
LDAP-Bind-Passwortdatei. Der authentifizierte LDAP-Read-back und die
Prüfung der POSIX-IDs sowie `member`/`memberUid` bestanden. MQ-OAM,
CHLAUTH und MQ-Transport wurden dabei nicht konfiguriert.
Keine Passwörter oder Bind-Secrets ins Repository aufnehmen.

Vor einem Transport-Start sind folgende unabhängige Sicherheitsnachweise
erforderlich:

1. LDAP-Identitäten und Gruppen existieren; die vorgesehenen `MCAUSER`
   sind auf den Ziel-QMgrn als nicht administrativ verifiziert; keine
   Mitgliedschaft in `mqm` oder administrativen LDAP-MQ-Gruppen.
2. `CHLAUTH TYPE(SSLPEERMAP)` stimmt auf dem empfangenden Queue-Manager
   mit *Kanalmaske*, Quelladresse, `SSLPEER` (peer subject) und
   `SSLCERTI` (peer issuer) überein. Vor dem Start ist
   `DISPLAY CHLAUTH(... ) MATCH(RUNCHECK)` in Positiv- und Negativfällen
   zu prüfen. `BGT.CLIENT` darf nicht betroffen sein.
3. Receiver `SSLCAUTH(REQUIRED)`, `SSLCIPH(TLS_AES_256_GCM_SHA384)`,
   `CERTLABL(bergentransport)` und dedizierte nicht privilegierte
   `MCAUSER` sind per `DISPLAY CHANNEL` nachgewiesen.
4. `PUTAUT(DEF)` wird belassen. Für den Receiver-MCA erforderliche
   `+connect/+inq/+setall` auf dem Ziel-QMgr und `+put/+setall` auf
   **exakt laufbezogenen Zielqueues** müssen gesondert geprüft werden.
   Keine pauschale `BGT.*`-Freigabe, kein `+alladm`, kein `mqm`.
   OAM-Lifecycle: vor dem Routing erteilen, mit eigener Eigentumsprüfung
   und beweisbar sicherer Rücknahme; bei Ungewissheit FAIL und Retain.
5. Das derzeitige temporäre Transportmodul setzt noch keine CHLAUTH- oder
   OAM-Fixtures um; `mq_topology_channel_security_verified` darf deshalb
   noch **nicht** als belegt gelten.

Schema- und Verzeichnisprüfung vom 09.10.2026: anonyme LDAPS-Suche,
administrativer `ldapwhoami`-Bind sowie Vault-Ladeprüfung erfolgreich;
LDAP-Preflight `ok=6 changed=0 failed=0`, lesender Provisionierungscheck
`ok=10 changed=0 failed=0`. Das veröffentlichte `cn=Subschema` weist
`person` mit `MUST(sn,cn)`, `posixAccount` mit
`MUST(cn,uid,uidNumber,gidNumber,homeDirectory)` sowie `posixGroup`
mit `MUST(cn,gidNumber)` aus. Die Gruppen-LDIF nutzt `memberUid`
(laut `posixGroup` optional) und `member` mit `extensibleObject`
wie die bestehende MQ-Gruppe. Der anschließende LDAP-Schreiblauf und
Read-back waren erfolgreich; die IDs sind damit belegt. Der nachfolgende
kontrollierte `+inq`-Gruppentest hat die MQ-SEARCHGRP-Auflösung für beide
Transportidentitäten positiv nachgewiesen (siehe unten). Die für den
Nachrichtentransport benötigten MQ-OAM- und CHLAUTH-Freigaben sind dennoch
weiterhin offen; bis dahin keine Transportkanäle starten oder
`mq_topology_channel_security_verified=true` setzen.

MQ-Konfiguration nach LDAP-Anlage (lesend geprüft): Beide QMgr melden
`AUTHORMD(SEARCHGRP)`, `CLASSGRP(posixGroup)`, `FINDGRP(member)`,
`GRPFIELD(cn)` und `BASEDNG(cn=groups,dc=bergen,dc=intern)`.
`dspmqaut -t qmgr -p bgttransa` auf A und `-p bgttransb` auf B
lieferten jeweils `rc=0`, ohne Berechtigungseinträge. Das bestätigt die
ursprüngliche Konfiguration ohne Berechtigungen. Die Gruppenrechteauflösung
wurde anschließend im befristeten OAM-Test nachgewiesen.

LDAP-Gruppenabfrage vom 09.10.2026 mit OR-Filter auf beide
Transportbenutzer ergab genau `MQBGTTRANSA` → `bgttransa` und
`MQBGTTRANSB` → `bgttransb` über `member`. Kein weiterer
passender Gruppen-DN im lesbaren Suchergebnis.

**Erfolgreicher OAM-Positiv-/Negativtest vom 09.10.2026:**
`ansible/playbooks/mq-transport-oam-group-smoke.yml` hat auf jedem
Queue-Manager nach vorausgehendem Baseline-Check einmal `+inq` für
`MQBGTTRANSA` (A) beziehungsweise `MQBGTTRANSB` (B) vergeben.
`dspmqaut` zeigte das Recht beim zugehörigen Benutzer und verweigerte
es dem fremden Transportbenutzer. Der `always`-Block hat `-inq`
auf beiden QMgrn ausgeführt. Ein Vergleich der effektiven Rechte
und der direkten `dmpmqaut`-Gruppeneinträge vor/nach dem Test war
jeweils erfolgreich; A und B meldeten jeweils
`ok=14 changed=2 failed=0`, localhost `ok=3 changed=0 failed=0`.
**Keine dauerhaften OAM-Freigaben aus diesem Test.**
Der Nachweis betrifft nur die Gruppenauflösung, nicht die späteren
`+setall`-/`+put`-Rechte oder die TLS-CHLAUTH-Zuordnung.

## CHLAUTH-Planung: offline, noch nicht angewendet (09.10.2026)

`ansible/module_utils/bergen_mq_chlauth.py` erzeugt einen **reinen
MQSC-Plan** für die beiden exakten, laufbezogenen Receiverkanäle
`BGT.<7HEX>.B2A` auf BERGENLAB und `BGT.<7HEX>.A2B` auf BERGENLABB.
Der Plan benutzt die geprüften IPv4-Adressen der beiden Hosts, die
zertifikatsspezifischen Subjects/Issuers und als `MCAUSER` die
dedizierten LDAP-Benutzer. Unbekannte Hosts, Portänderungen, freie
Kanalnamenmuster und unzulässige Präfixe werden verweigert.

Pro Receiver sind zwei CHLAUTH-Datensätze vorgesehen: eine
`ADDRESSMAP ADDRESS('*') USERSRC(NOACCESS)` als Rückfallsperre
sowie eine enge `SSLPEERMAP` mit `SSLPEER`, `SSLCERTI`, Peer-IP,
`USERSRC(MAP)` und `MCAUSER`. Der Plan sieht vier
`MATCH(RUNCHECK)`-Fälle vor: richtiges Zertifikat, falscher Subject,
falscher Issuer und falsche Quell-IP. Das Prüfmodul wertet nur
eindeutige MQSC-Ergebnisse als bestanden.

**Wichtig:** `MATCH(RUNCHECK)` mit nicht vorhandenem Receiver
ergibt `AMQ9519E`; das ist am 09.10.2026 lesend auf beiden QMgrn
nachgewiesen. Die Receiver müssen vor einer Live-RUNCHECK-Prüfung
kontrolliert definiert sein. Geplante `DEFINE`-, `SET CHLAUTH`-
und `ACTION(REMOVE)`-Befehle werden vom Modul **nicht ausgeführt**.
Es gibt derzeit keinen freigegebenen Live-Apply-Pfad: Vor Anwendung
müssen DIT/PKI-Daten, MQSC-Parameter, Priorität zwischen
`SSLPEERMAP` und `ADDRESSMAP`, bestehende Kanäle/Regeln
und die exakten Rückbauschritte geprüft werden. Insbesondere
wäre es unzulässig, eine unbekannte bestehende Regel als
"run-owned" zu entfernen.

Der lesende Live-Preflight vom 09.10.2026 war auf A und B erfolgreich:
`ok=10 changed=0 failed=0` jeweils; `CHLAUTH(ENABLED)`,
`CERTLABL(bergenlab)`, nicht vorhandene reservierte Receiver,
unveränderte `BGT.CLIENT`-Regeln und exakte lokale Transport-Subject-/Issuer-DNs
wurden bestätigt. Das ist keine erfolgreiche CHLAUTH-Verbindungsprüfung.

Die rein lokale Befehlsvorschau `scripts/mq_chlauth_plan.py` gibt beide
Richtungen einschließlich der geplanten positiven/negativen Prüfungen aus.
Die Aktivierungsreihenfolge wurde nach Review explizit auf
**ADDRESSMAP NOACCESS → DEFINE RCVR → SSLPEERMAP-Freigabe**
festgelegt. Damit gibt es kein Zeitfenster mit einem ungesperrten,
neu angelegten Receiver. Die Offline-Vorschau gibt diese Reihenfolge aus;
noch kein Live-Apply.

Der Rückbauplan wurde am 09.10.2026 fail-closed nachgeschärft:
**zuerst SSLPEERMAP entfernen, dann Receiver löschen, erst danach
ADDRESSMAP-NOACCESS entfernen**. Kann der Receiver nicht sicher gelöscht
werden, muss die Sperrregel bestehen bleiben. Für eine Live-Implementierung
sind zusätzlich eigene Eigentumsprüfung und unterbrechungssicheres
Residual-Reporting erforderlich.

Offline-Prüfung auf `bp-controller` nach Pull des Branches:

```bash
PYTHONPATH=ansible python3 -m unittest discover -s tests -p 'test_mq_chlauth.py' -v
python3 scripts/mq_chlauth_plan.py
```

**Stand 09.10.2026 (nach 9 bestandenen CHLAUTH-Planungstests):**
Der isolierte Lifecycle-Controller
`ansible/module_utils/bergen_mq_chlauth_lifecycle.py` sichert vor
jeder Mutation beide Preflight-Prüfungen ab, protokolliert ungewisse
Schreibversuche schon vor der Ausführung und versucht den Rückbau auf
beiden Seiten selbst bei Fehlern. Er behält die `NOACCESS`-Sperre,
wenn die Abwesenheit von Receiver oder Freigaberegel nicht positiv
nachgewiesen ist. `tests/test_mq_chlauth_lifecycle.py` simuliert
Erfolge, Fehler beim Anlegen/Prüfen/Löschen und Unsicherheit.
Der Receiver erhält zusätzlich explizit den dedizierten
`MCAUSER`; die CHLAUTH-Regel muss auf dieselbe Identität abbilden.

**Lesender Adapter (Stand 09.10.2026):**
`ansible/module_utils/bergen_mq_chlauth_readonly.py` akzeptiert nur
einzelne `DISPLAY`-MQSC-Abfragen über einen injizierten Runner. Er
prüft die Abwesenheit des exakt zugehörigen Receivers, einen leeren
CHLAUTH-Namensraum für die Fixture sowie den bestehenden QMGR-,
Client- und Admin-Regelzustand. Die Methoden für Mutationen und
Lifecycle-Verifikation verweigern jeden Aufruf. Die dazugehörigen
`tests/test_mq_chlauth_readonly.py` prüfen auch Ablehnungen bei
Kollisionen und mehrdeutigen MQSC-Rückmeldungen.
Die lesende Laufzeitintegration verwendet
`ansible/playbooks/mq-transport-chlauth-readonly-audit.yml` und
`ansible/library/mq_chlauth_readonly_audit.py`. Ansible führt pro
MQ-Host genau drei `DISPLAY`-Befehle über den vorhandenen Container
aus; nur die Rückgaben werden auf localhost dem geprüften Read-only-
Adapter übergeben. Der Adapter führt selbst keine SSH-, Podman- oder
MQSC-Aufrufe aus und besitzt keine Schreibmethode. Er verweigert
fehlende, unplausible und kollidierende Antworten. Das Script ist
zunächst separat per `--syntax-check` zu prüfen und erst dann lesend
auszuführen. **Der Istzustand ist nur ein Snapshot, keine exklusive
Eigentumssicherung; ein Live-Apply ist weiterhin gesperrt.**

**Lesende Laufzeitprüfung am 09.10.2026 bestanden:** Auf den beiden
MQ-Hosts wurden jeweils drei reine DISPLAY-Aufrufe erfolgreich erfasst
und die Ergebnisse anschließend vom Controller mit dem Read-only-Adapter
validiert: `verification=PASS`, `read_only=true`, `changed=false`,
`failed=false`. Ansible-Recap: BERGENLAB `ok=5 changed=0 failed=0`,
BERGENLABB `ok=5 changed=0 failed=0`, localhost
`ok=2 changed=0 failed=0`. Die exakt geprüften Test-Receiver waren
`BGT.A1B2C3D.B2A` auf A und `BGT.A1B2C3D.A2B` auf B; beide sind
weiterhin nicht definiert. Die Prüfung bestätigt das aktuelle
MQSC-Parser-Verhalten, **nicht** die spätere CHLAUTH-Wirksamkeit nach
Anlage der Regeln oder einen erfolgreichen mTLS-Transport.


```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/mq-transport-chlauth-readonly-audit.yml --syntax-check
```

Die strikt offline arbeitende MQSC-Auswertung
`ansible/module_utils/bergen_mq_chlauth_mqsc.py` fordert pro
Abfrage genau einen vollständig und fehlerfrei verarbeiteten MQSC-Befehl
und wertet echte `DISPLAY CHLAUTH(*) ALL`-Daten nur bei eindeutigen
Datensätzen aus. Beim Receiver-Readback fordert sie `RCVR`,
`TLS_AES_256_GCM_SHA384`, `SSLCAUTH(REQUIRED)`,
`CERTLABL(bergentransport)` und den erwarteten nichtadministrativen
`MCAUSER`. Fehlende, doppelte und unerwartete Angaben führen zum
Abbruch; diese Prüfroutinen haben **keinen** MQSC-Ausführungspfad.
`tests/test_mq_chlauth_mqsc.py` simuliert passende und fehlerhafte
MQSC-Antworten. Die tatsächliche MQSC-Kompatibilität und die
CHLAUTH-RUNCHECK-Auswertung sind noch nicht live nachgewiesen.

**Der Lifecycle-Controller ist noch nicht mit einem Live-MQSC-Adapter
verdrahtet und ändert selbst keine MQ-Objekte.** Besonders die
RUNCHECK-Auswertung bei NOACCESS und die Abwesenheit/eindeutige
Eigentümerschaft der CHLAUTH-Einträge müssen am echten MQ
ausgewertet werden, bevor eine Schreibfreigabe überhaupt möglich ist.

Offline-Lifecycle-Test nach `git pull`:

```bash
PYTHONPATH=ansible python3 -m unittest discover -s tests -p 'test_mq_chlauth*.py' -v
```

Die Tests `tests/test_mq_chlauth.py` prüfen Namen, Richtung,
identitätsgebundene Zulassung, alle vier Probevarianten, verweigerte
abweichende Topologien und den begrenzten Rückbauplan. Noch kein
Ergebnis aus einer tatsächlichen MQSC-Laufzeitprüfung behaupten.

## Schreibzyklus: reine Offline-Vorbereitung (09.10.2026)

`ansible/module_utils/bergen_mq_chlauth_write_contract.py` begrenzt
mögliche künftige MQSC-Mutationen auf genau sechs Befehle je QMgr
(Anlage der Sperre, Definition des Receivers, Zertifikatsfreigabe,
Entfernung der Freigabe, Entfernung des Receivers, Entfernung der Sperre).
Die Befehle und Identitäten müssen dem geprüften Plan exakt entsprechen.
Der enthaltene `OfflineOnlyMutationAdapter` verweigert **auch korrekt
geformte Schreibbefehle**: Er ist keine Live-Ausführung.

`ansible/playbooks/mq-transport-chlauth-write-review.yml` führt
ausschließlich lokale Tests aus und verweigert die Flags
`mq_chlauth_live_apply` sowie `mq_chlauth_write_approved`.
Für eine echte Schreibfreigabe fehlen weiterhin eine belastbare
Eigentums-/Sperrstrategie, ein dauerhaftes Änderungsjournal,
MQSC-Readbacks nach jeder Mutation und reproduzierbarer Rückbau
bei Teilfehlern. Der bisherige lesende Audit bleibt unverändert.

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/mq-transport-chlauth-write-review.yml --syntax-check
```

Diese Syntaxprüfung ändert keine MQ-Objekte und gibt keine Freigabe
für einen späteren Live-Lauf.

**Dauerhaftes Offline-Journal (Vorbereitung):** Das Modul
`ansible/module_utils/bergen_mq_chlauth_journal.py` schreibt
`BEGIN`/`INTENT`/`RESULT`/`CLEAN` als verkettete JSONL-Datensätze
mit `fsync` pro Datensatz in ein ausschließlich dem ausführenden
Benutzer gehörendes 0700-Verzeichnis (Dateien 0600). Ein exklusives
POSIX-`flock` schützt kooperative Prozesse **nur auf demselben
Controller**. Jeder unvollständige, beschädigte oder mit unbekanntem
Ausgang beendete Lauf blockiert neue Journals und erfordert manuelle
Prüfung. Ein `CLEAN` darf nur nach unabhängigen, erfolgreich
bestätigten Readbacks **beider** Queue-Manager protokolliert werden.
Die Prüfsumme erkennt unbeabsichtigte Beschädigungen, ist jedoch
kein Manipulationsschutz. Die neun isolierten Tests in
`tests/test_mq_chlauth_journal.py` simulieren Abbrüche, Sperrkonflikte,
ungültige Zustände und Journalbeschädigung.
Das Journal ist bislang **nicht an einen MQ-Schreiber angeschlossen**,
stellt keine globale MQ-Objektsperre dar und garantiert daher
keine Eigentümerschaft gegenüber anderen MQ-Administratoren.
Der Review-Playbook-Output zeigt nach erfolgreichem Testlauf
die konkrete `Ran N tests`-Zeile.

**Offline-Integration von Journal und Lifecycle:** Die neue Datei
`ansible/module_utils/bergen_mq_chlauth_journaled_offline.py` verbindet
den getesteten Lifecycle, die feste Befehlsfreigabe und das fsync-Journal
nur mit einem ausdrücklich gekennzeichneten In-Memory-Fake. Vor jeder
simulierten Mutation wird `INTENT` geschrieben, danach `RESULT`.
Ein Fehler erhält `UNKNOWN`; auch bei anschließender erfolgreicher
Bereinigung bleibt das Journal bewusst unvollständig, damit der
Fall unabhängig geprüft werden kann. Nur ein vollständig erfolgreicher
Test mit bestätigtem Cleanup beider Seiten erhält `CLEAN`.
`tests/test_mq_chlauth_journaled_offline.py` prüft diesen Ablauf
einschließlich Abbruch, RUNCHECK-Fehler und Verweigerung nicht
gekennzeichneter Runner. **Kein Live-MQSC-Writer wird angeschlossen.**
Die fünf neuen Tests sind noch auf dem Controller auszuführen.

## Unveränderliche Infrastruktur / Vorbedingungen

Die Testautomatisierung **ändert nicht** Firewall, CA-Trust, CHLAUTH,
CONNAUTH, MQM-Benutzer, Queue-Manager-weite DLQ oder bestehende Kanäle.

Vor Live-Ausführung sind separat nachzuweisen:

1. A↔B TCP/1414 mit beidseitig quelladressbeschränkter Freigabe auf den
   tatsächlich aktiven Firewall-Schichten (firewalld, Proxmox, ggf. UniFi).
   Die vorhandene Regel für `192.168.20.108/32` gestattet nur den Clientzugriff.
   Die neue Rolle erlaubt zusätzliche QMgr-Quellen nur als kanonische `/32`
   auf TCP/1414. Die Hostvariablen lösen A bzw. B aus dem Inventory auf.
   Vor einer Anwendung: `ansible/playbooks/mq-client-firewall.yml --check --diff`,
   Ausgabe der beiden Queueserver vergleichen, dann nach Freigabe ohne Check-Modus
   ausführen und Runtime/Permanent/Proxmox gegenprüfen.
2. Die beiden QMgr benutzen unabhängige CAs. **Jeder QMgr muss dem
   Messaging-Zertifikat beziehungsweise dessen CA des anderen QMgr vertrauen.**
   Die CA-Dateien auf `bp-controller` oder dem Java-Testclient allein genügen
   nicht. Die aktive MQ-Key-Repository-Konfiguration ist separat zu prüfen.
3. CHLAUTH-Regeln und OAM-Berechtigungen müssen für die eigens gestarteten
   Sender-/Receiver-Kanäle und die temporären BGT-Zielqueues minimal
   autorisiert sein. Keine pauschale CHLAUTH-Deaktivierung und kein `mqm`
   als MCAUSER.
4. Ausdrückliche Testfreigabe und Prüfung des aktuellen (lokalen,
   Git-ignorierten) `ansible/vars/mq-topology/audit.yml`.

## Ausführung (erst nach Sicherheitsprüfung)

Neuer Opt-in-Schalter im lokalen vars-File:

```yaml
mq_topology_transient_transport: true
mq_topology_peer_firewall_verified: true
mq_topology_cross_ca_verified: true
mq_topology_channel_security_verified: true
mq_topology_accept_partial: true
```

**Die drei `_verified`-Angaben sind Operatorbestätigungen**, keine
automatischen Firewall-, TLS-Trust- oder CHLAUTH-Nachweise. Sie dürfen nur
nach unabhängigem Nachweis auf `true` gesetzt werden.

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/mq-topology-audit.yml \
  -e @ansible/vars/mq-topology/audit.yml \
  --syntax-check --ask-vault-pass
```

Live-Ausführung ohne `--check` nur im ausdrücklich freigegebenen Testfenster;
das Playbook legt dann temporäre Objekte an. Ohne
`mq_topology_transient_transport: true` bleibt das vorherige Auditverhalten
erhalten. Statische `sender_channel`- und `xmitq`-Einträge sind für den
temporären Modus nicht erforderlich und sollen leer bleiben.

## Fehlerschutz und Cleanup

- Vor einer Mutation wird auf beiden Queue-Managern die Abwesenheit
  **aller** geplanten Testobjekte kontrolliert. Namenskollisionen stoppen den
  Test ohne Definitionen.
- Auch ein nicht eindeutig bestätigter DEFINE- oder START-Versuch wird als
  möglicher eigener Restbestand protokolliert.
- Nach den Nachrichtenprüfungen werden die laufbezogenen QREMOTE-/Zielqueues
  unter den bestehenden Vorsichtsregeln bereinigt.
- Danach werden nur gestartete Senderkanäle mit
  `STOP CHANNEL ... MODE(QUIESCE)` geordnet beendet. Für jedes Kanalpaar muss
  `DISPLAY CHSTATUS CURRENT` die Inaktivität nachweisen.
- Der Sender muss vor dem STOP `INDOUBT(NO)` melden. Jede XMITQ muss
  `USAGE(XMITQ)`, `CURDEPTH=0` und `DISPLAY QSTATUS UNCOM(0)` bzw.
  `UNCOM(NO)` nachweisen.
  Erst dann sind DELETE für die eigenen, leeren XMITQs und inaktiven Kanäle
  zulässig. Status- oder Kommunikationsunsicherheit führt zum **Retain**.
- Keine FORCE-, PURGE-, CLEAR-, Timeout-Blind-Retry- oder Fremdobjekt-Löschung.
  Reste gehen in `evidence.json` und den Prüfbericht ein; sie ergeben `FAIL`.

Das lokale Testmodul prüft den Objekt-Lifecycle mit Fake-MQ-REST-Antworten.
Es ist **kein** Live-Nachweis der MQ-Web-REST-Kommandos, der
Zertifikatsvertrauensstellung oder der Kanalberechtigungen. Für einen
erfolgreich akzeptierten transienten Audit müssen alle zehn
`a:remote-*`/`b:remote-*`-Tests `PASS` haben.
Andere ausdrücklich verschobene Fälle bleiben `NOT_TESTED`.
