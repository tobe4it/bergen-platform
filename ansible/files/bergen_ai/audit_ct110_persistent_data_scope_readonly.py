#!/usr/bin/env python3
"""Read-only, bounded CT110 Ollama/Podman persistent-data inventory.

Run on venombox; commands execute in CT110. Return fixed classifications only;
never emit raw Podman inspect, paths from runtime, environment, mount source,
model names, tokens or file content. NOT a backup/restore clearance.
"""
import json
import shlex
import subprocess

FRAME = "BERGEN_AI_CT110_DATA_SCOPE_V1:"
VMID = "110"
WEBUI_DIR = "/srv/ai/open-webui"
MODELS_DIR = "/srv/ai/models"
WEBUI_DST = "/app/backend/data"
MAX_BYTES = 160000


def query(argv, timeout=15, limit=MAX_BYTES):
    try:
        process = subprocess.run(["pct", "exec", VMID, "--"] + argv,
                                 capture_output=True, timeout=timeout, check=False)
        if process.returncode != 0 or len(process.stdout) > limit:
            return None
        return process.stdout.decode("utf-8", "strict")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def query_json(argv):
    raw = query(argv)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def rootfs_dir(path):
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 512:
        return "UNVERIFIED"
    real = query(["realpath", "-e", path], limit=1200)
    if real is None:
        return "UNVERIFIED"
    real = real.strip()
    if not real.startswith("/") or "\n" in real:
        return "UNVERIFIED"
    kind = query(["test", "-d", real], limit=16)
    if kind is None:
        return "UNVERIFIED"
    mount = query(["findmnt", "-n", "-T", real, "-o", "TARGET"], limit=1200)
    if mount is None:
        return "UNVERIFIED"
    return "GUEST_ROOTFS" if mount.strip() == "/" else "OTHER_GUEST_MOUNT"


def podman_webui(inspect):
    if not isinstance(inspect, list) or len(inspect) != 1 or not isinstance(inspect[0], dict):
        return "UNVERIFIED"
    obj = inspect[0]
    mounts = obj.get("Mounts")
    if not isinstance(mounts, list) or not 1 <= len(mounts) <= 64:
        return "UNVERIFIED"
    data_mounts = [m for m in mounts if isinstance(m, dict) and m.get("Destination") == WEBUI_DST]
    if len(data_mounts) != 1:
        return "DATA_MOUNT_NOT_UNIQUE"
    item = data_mounts[0]
    if item.get("Source") != WEBUI_DIR or item.get("Type") != "bind":
        return "DATA_SOURCE_NOT_EXPECTED"
    if any(not isinstance(m, dict) or m.get("Destination") != WEBUI_DST for m in mounts):
        return "OTHER_PODMAN_MOUNTS_REVIEW"
    return "EXACT_WEBUI_DATA_BIND"


def podman_graph_root(info):
    if not isinstance(info, dict):
        return None
    store = info.get("store")
    if not isinstance(store, dict):
        return None
    path = store.get("graphRoot")
    return path if isinstance(path, str) and path.startswith("/") else None


def ollama_config(raw, active):
    if active is None or active.strip() != "active" or raw is None:
        return "UNVERIFIED"
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return "UNVERIFIED"
    matches = [s.partition("=")[2] for s in tokens if s.startswith("OLLAMA_MODELS=")]
    if len(matches) != 1:
        return "MODELS_LOCATION_UNVERIFIED"
    return "EXPECTED_MODELS_LOCATION" if matches[0] == MODELS_DIR else "OTHER_MODELS_LOCATION"


def podman_container_list(items):
    if not isinstance(items, list) or len(items) > 100:
        return "UNVERIFIED"
    if len(items) != 1 or not isinstance(items[0], dict):
        return "OTHER_OR_MISSING_CONTAINERS"
    names = items[0].get("Names")
    if names == ["open-webui"] or names == "open-webui":
        return "ONLY_OPEN_WEBUI"
    return "OTHER_OR_MISSING_CONTAINERS"


def podman_volume_list(items):
    if not isinstance(items, list) or len(items) > 100:
        return "UNVERIFIED"
    return "NONE" if not items else "ADDITIONAL_VOLUMES_REVIEW"


def main():
    status = query(["systemctl", "show", "ollama.service", "-p", "ActiveState", "--value"])
    env = query(["systemctl", "show", "ollama.service", "-p", "Environment", "--value"])
    model_setting = ollama_config(env, status)
    model_rootfs = rootfs_dir(MODELS_DIR) if model_setting == "EXPECTED_MODELS_LOCATION" else "UNVERIFIED"

    webui_bind = podman_webui(query_json(["podman", "inspect", "open-webui"]))
    webui_rootfs = rootfs_dir(WEBUI_DIR) if webui_bind == "EXACT_WEBUI_DATA_BIND" else "UNVERIFIED"

    info = query_json(["podman", "info", "--format", "json"])
    graph_path = podman_graph_root(info)
    graph_location = rootfs_dir(graph_path) if graph_path else "UNVERIFIED"
    container_state = podman_container_list(query_json(["podman", "ps", "--all", "--format", "json"]))
    volumes = podman_volume_list(query_json(["podman", "volume", "ls", "--format", "json"]))

    data_evidence = (
        model_setting == "EXPECTED_MODELS_LOCATION"
        and model_rootfs == "GUEST_ROOTFS"
        and webui_bind == "EXACT_WEBUI_DATA_BIND"
        and webui_rootfs == "GUEST_ROOTFS"
        and graph_location == "GUEST_ROOTFS"
        and container_state == "ONLY_OPEN_WEBUI"
        and volumes == "NONE"
    )
    return dict(
        AUDIT="READ_ONLY", CHANGED=False,
        STATUS="KNOWN_DATA_PATHS_IN_ROOTFS" if data_evidence else "REVIEW_REQUIRED",
        OLLAMA_CONFIG=model_setting, OLLAMA_MODELS_MOUNT=model_rootfs,
        WEBUI_PODMAN_BIND=webui_bind, WEBUI_DATA_MOUNT=webui_rootfs,
        PODMAN_GRAPH_MOUNT=graph_location, PODMAN_CONTAINERS=container_state,
        PODMAN_NAMED_VOLUMES=volumes,
        # This is a bounded evidence check, not a complete account of guest data.
        ALL_PERSISTENT_DATA_PROVEN=False,
        BACKUP_STARTED=False, BACKUP_AUTHORIZED=False, APPLY_AUTHORIZED=False,
        ROLLBACK_CLEARANCE="NOT_PROVEN", RESTORE_TEST="NOT_ATTESTED",
        NETWORK_CHANGES="NONE",
    )


def emit(result):
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        emit(main())
    except Exception:
        emit(dict(AUDIT="READ_ONLY", CHANGED=False, STATUS="UNVERIFIED",
                  OLLAMA_CONFIG="UNVERIFIED", OLLAMA_MODELS_MOUNT="UNVERIFIED",
                  WEBUI_PODMAN_BIND="UNVERIFIED", WEBUI_DATA_MOUNT="UNVERIFIED",
                  PODMAN_GRAPH_MOUNT="UNVERIFIED", PODMAN_CONTAINERS="UNVERIFIED",
                  PODMAN_NAMED_VOLUMES="UNVERIFIED",
                  ALL_PERSISTENT_DATA_PROVEN=False,
                  BACKUP_STARTED=False, BACKUP_AUTHORIZED=False,
                  APPLY_AUTHORIZED=False, ROLLBACK_CLEARANCE="NOT_PROVEN",
                  RESTORE_TEST="NOT_ATTESTED", NETWORK_CHANGES="NONE"))
