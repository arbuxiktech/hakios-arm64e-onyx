#!/usr/bin/env python3
"""Verify the linked artifact is an ARM64E executable; this is not a boot test."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def verify(path):
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise ValueError("Truncated Mach-O header")
        magic, cpu, subtype, filetype, *_ = struct.unpack("<8I", header)
        if magic != 0xFEEDFACF or cpu != 0x0100000C or subtype & 0x00FFFFFF != 2 or filetype != 2:
            raise ValueError("Expected an ARM64E Mach-O executable")
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"format": "Mach-O 64", "architecture": "arm64e", "cpu_subtype": hex(subtype),
            "bytes": path.stat().st_size, "sha256": digest, "linked": True, "hardware_boot_tested": False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("kernel", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        result = verify(args.kernel)
    except (OSError, ValueError) as error:
        ap.exit(1, f"Kernel validation failed: {error}\n")
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
