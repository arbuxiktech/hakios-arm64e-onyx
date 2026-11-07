#!/usr/bin/env python3
"""Read-only Onyx fastboot checks. Does not reboot, boot, flash or select a slot."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def value(name, output):
    # Some bootloaders return exit code 0 even for unsupported getvar queries.
    match = re.search(r"^" + re.escape(name) + r":\s*(\S+)\s*$", output, re.M)
    if match is None:
        raise ValueError(f"No definite value for {name}")
    return match[1]


def inspect(serial, slot):
    expected = {"product": "onyx", "unlocked": "yes", "current-slot": slot,
                "is-userspace": "no", f"slot-unbootable:{slot}": "no",
                f"slot-successful:{slot}": "yes"}
    names = list(expected) + [f"slot-retry-count:{slot}", "max-download-size"]
    records = {}
    errors = []
    for name in names:
        result = subprocess.run(["fastboot", "-s", serial, "getvar", name],
                                capture_output=True, text=True, timeout=8)
        output = result.stdout + result.stderr
        record = {"exit_code": result.returncode, "output": output}
        records[name] = record
        try:
            if result.returncode:
                raise ValueError(f"getvar failed: {name}")
            record["value"] = value(name, output)
            if name in expected and record["value"] != expected[name]:
                raise ValueError(f"{name}: expected {expected[name]}, got {record['value']}")
        except ValueError as error:
            errors.append(str(error))
    return {"variables": records, "errors": errors, "baseline_passed": not errors,
            "authorizes_boot": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--slot", choices=("a", "b"), default="a")
    parser.add_argument("--output", type=Path, default=Path("reports/fastboot-baseline.json"))
    args = parser.parse_args()
    report = inspect(args.serial, args.slot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["baseline_passed"] else 1)
