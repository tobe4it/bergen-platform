# Podman

Installiert die OCI-Containerplattform der Bergen Platform.

## Installiert

- Podman
- Buildah
- Skopeo
- Netavark
- Aardvark DNS

## Erstellt

- generisches Container-Storage unter `/srv/containers`
- Quadlet Directory

Die Runtime-Rolle verwendet standardmäßig `root:root` und legt keine
anwendungsspezifischen Verzeichnisse oder Gruppen an. Zusätzliche
Storage-Verzeichnisse können über `podman_storage_directories` deklariert
werden. Eigentümer, Gruppe und Modus sind über `podman_storage_owner`,
`podman_storage_group` und `podman_storage_mode` konfigurierbar.

## Nicht enthalten

- Open WebUI
- Redis
- PostgreSQL
- AnythingLLM
- Pi-hole-Datenverzeichnisse

Diese Dienste besitzen eigene Rollen und verwalten ihre eigenen Datenpfade.
