#!/usr/bin/env python3
"""Read-only inspection of one locally recorded CHLAUTH fixture journal.

Exit codes: 0 = CLEAN marker recorded (NOT live approval),
            2 = unresolved/manual review required,
            3 = unreadable, unsafe or malformed journal.
No MQSC, SSH, Ansible invocation or cleanup operation is implemented.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ansible"))
from module_utils.bergen_mq_chlauth_journal import (  # noqa: E402
    JournalError, recovery_report,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal", type=Path, help="Existing AUDIT.<7HEX>.jsonl file")
    args = parser.parse_args(argv)
    try:
        result = recovery_report(args.journal)
    except (JournalError, OSError, ValueError) as exc:
        print(json.dumps({
            "state": "INVALID_JOURNAL", "can_auto_cleanup": False,
            "can_authorize_live_apply": False,
            "error": str(exc),
        }, sort_keys=True))
        return 3
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["state"] == "CLEAN_RECORDED" else 2


if __name__ == "__main__":
    sys.exit(main())
