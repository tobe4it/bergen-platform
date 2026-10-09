#!/usr/bin/env python3
"""Print reviewed, strictly offline CHLAUTH fixture commands. No MQ access."""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ansible"))
from module_utils.bergen_mq_chlauth import LAB, make_plan  # noqa: E402


def main():
    # Only the reserved offline fixture ID; production run IDs are generated
    # elsewhere. This preview never passes commands to a shell or MQ.
    prefix = "AUDIT.A1B2C3D"
    nodes = {side: {"host": attrs["host"], "qmgr": attrs["qmgr"], "port": 1414}
             for side, attrs in LAB.items()}
    plan = make_plan(prefix, nodes)
    for side in ("a", "b"):
        entry = plan[side]
        print("=== %s: %s ===" % (entry["qmgr"], entry["receiver"]))
        print("PRECONDITIONS (read only):")
        for statement in entry["preflight"]:
            print("  " + statement)
        print("PROPOSED WRITES (NOT EXECUTED):")
        for statement in entry["apply_order"]:
            print("  " + statement)
        print("RUNCHECK CASES (NOT EXECUTED):")
        for case in entry["cases"]:
            print("  %s / %s: %s" % (
                case["name"], case["expect"], case["command"]))
        print("CLEANUP ORDER (NOT EXECUTED):")
        for statement in entry["cleanup"]:
            print("  " + statement)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
