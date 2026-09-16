# MQ evaluation client

Dedicated Rocky 9 amd64 LXC with Java 17 JDK, OpenSSL, Python and a locked
`mqtest` service account. No queue manager or Podman runtime is installed.
The deployment collects `com.ibm.mq.allclient.jar` over SSH from a selected
MQ container after resolving the pinned repository digest locally and comparing
its image ID to the container's actual image ID. Tag spelling is not identity.
Source and destination
SHA-256 must match. This is transfer integrity, not an IBM artifact signature.

Files: `/opt/bergen-mq-client/lib/com.ibm.mq.allclient.jar`,
`/opt/bergen-mq-client/provenance.json`, home `/var/lib/bergen-mq-client`.
No client network listener is created. Tests can run as `mqtest` via Ansible
become; no interactive login is required. This role prepares infrastructure only.
Additional JMS dependencies are not installed; the intended initial harness uses
the base MQ Java API. Productive licensing must be clarified with IBM.
