#!/usr/bin/env python3
"""Read the Onyx UEFI diagnostic endpoint. No bootloader/storage commands."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def parse(text):
    values = {}
    for line in text.splitlines():
        line = re.sub(r"^\(bootloader\)\s*", "", line.strip())
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)=(.{1,128})", line)
        if match:
            if match[1] in values:
                raise ValueError(f"Duplicate diagnostic value: {match[1]}")
            values[match[1]] = match[2]
    if values.get("stage") != "onyx-uefi-usb-diagnostics-v1":
        raise ValueError("Expected Onyx UEFI diagnostic stage marker")
    for name in ("CurrentEL", "MIDR_EL1", "MPIDR_EL1", "ID_AA64ISAR1_EL1", "CNTFRQ_EL0"):
        if not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", values.get(name, "")):
            raise ValueError(f"Missing or invalid register: {name}")
    return values


def command(serial, *args):
    result = subprocess.run(["fastboot", "-s", serial, *args],
                            capture_output=True, text=True, timeout=15)
    output = result.stdout + result.stderr
    if result.returncode:
        raise ValueError(output.strip())
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="ONYXDIAG0001")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    product = command(args.serial, "getvar", "product")
    if not re.search(r"^product:\s*onyx-diag\s*$", product, re.M):
        raise SystemExit("Selected interface is not the read-only Onyx diagnostic endpoint")
    text = command(args.serial, "getvar", "onyx-diag")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".log").write_text(text)
    values = parse(text)
    args.output.write_text(json.dumps({"values": values, "source": "UEFI USB diagnostic endpoint",
                                     "xnu_started": False}, indent=2) + "\n")
    print(json.dumps(values, indent=2))
