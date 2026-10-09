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
Read-back waren erfolgreich; die IDs sind damit belegt. **Ein MQ-SEARCHGRP-
Nachweis steht weiterhin aus.** Ebenso offen sind die auf transportseitige
Identitäten begrenzten MQ-OAM- und CHLAUTH-Freigaben; bis dahin keine
Transportkanäle starten oder `mq_topology_channel_security_verified=true`
setzen. Keine Rechtevergabe auf Verdacht.

MQ-Konfiguration nach LDAP-Anlage (lesend geprüft): Beide QMgr melden
`AUTHORMD(SEARCHGRP)`, `CLASSGRP(posixGroup)`, `FINDGRP(member)`,
`GRPFIELD(cn)` und `BASEDNG(cn=groups,dc=bergen,dc=intern)`.
`dspmqaut -t qmgr -p bgttransa` auf A und `-p bgttransb` auf B
lieferten jeweils `rc=0`, ohne Berechtigungseinträge. Das bestätigt die
Konfiguration, noch **nicht** die erfolgreiche MQ-Gruppenrechteauflösung.
Eine kontrollierte OAM-Positiv-/Negativprobe steht aus.

LDAP-Gruppenabfrage vom 09.10.2026 mit OR-Filter auf beide
Transportbenutzer ergab genau `MQBGTTRANSA` → `bgttransa` und
`MQBGTTRANSB` → `bgttransb` über `member`. Kein weiterer
passender Gruppen-DN im lesbaren Suchergebnis. Das ist noch kein
MQ-OAM-Positivnachweis; ohne diesen keine Channel-Security-Freigabe.

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
