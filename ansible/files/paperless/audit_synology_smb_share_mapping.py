#!/usr/bin/env python3
"""READ ONLY verify DSM share-to-real-site-root mapping before SMB2 probes.

synoshare --get never changes a share. Treat all output as untrusted and
suppress paths and identities in status logs. No files, ACLs or users touched.
"""
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

SHARES = {
    "homes": "/volume1/homes",
    "paperless-scan": "/volume1/paperless-scan",
}
PATH_FIELD = re.compile(r"^\s*Path\s*\.+\s*\[([^\]\r\n]+)\]\s*$")


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def parse_share_path(output, share):
    require(isinstance(output, str) and len(output) <= 65536,
            "SHARE_DUMP_UNSAFE")
    matches = []
    for line in output.splitlines():
        if "Path" not in line:
            continue
        m = PATH_FIELD.fullmatch(line)
        if m:
            matches.append(m.group(1))
        elif line.lstrip().startswith("Path"):
            raise RuntimeError("UNPARSEABLE_SHARE_PATH")
    require(len(matches) == 1, "MISSING_OR_DUPLICATED_SHARE_PATH")
    path = matches[0]
    require(share in SHARES and path == SHARES[share],
            "SHARE_MAP_UNEXPECTED")
    return path


def check_share(tool, share):
    require(share in SHARES, "UNEXPECTED_SHARE")
    expected = Path(SHARES[share])
    st = expected.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == 0,
            "UNTRUSTED_SITE_ROOT")
    result = subprocess.run([str(tool), "--get", share],
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            timeout=15, check=False)
    require(result.returncode == 0 and result.stderr.strip() == "",
            "SYNO_SHARE_LOOKUP_FAILED")
    parsed = parse_share_path(result.stdout, share)
    require(parsed == str(expected), "UNEXPECTED_SHARE_PATH")
    return True


def audit():
    require(os.geteuid() == 0, "NAS_ROOT_REQUIRED")
    tools = (Path("/usr/syno/sbin/synoshare"),
             Path("/usr/syno/bin/synoshare"))
    available = [p for p in tools if p.is_file() and os.access(p, os.X_OK)]
    require(len(available) >= 1, "SYNO_SHARE_TOOL_MISSING")
    tool = available[0]
    for share in ("homes", "paperless-scan"):
        check_share(tool, share)
        print("NAS_SMB_SHARE_REAL_ROOT_VERIFIED", share, flush=True)
    print("NAS_SMB_SHARE_MAPPING_VERIFIED 2")
    print("SMB_NEGATIVE_RIGHTS_NOT_TESTED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    try:
        audit()
    except Exception:
        print("NAS_SMB_SHARE_MAPPING_BLOCKED", file=sys.stderr)
        raise SystemExit(2)
