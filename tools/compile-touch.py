#!/usr/bin/env python3
"""Compile the Onyx touch translation unit with the kernel's generated flags."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tree", type=Path)
    args = parser.parse_args()
    tree = args.tree.resolve()
    directory = tree / "BUILD/obj/DEVELOPMENT_ARM64_BCM2837/bsd/DEVELOPMENT"
    raw_flags = shlex.split((directory / ".CFLAGS").read_text().rstrip("\x00\n"))
    # XNU's stamp drops shell quoting around parenthesized -D expressions.
    flags = []
    for flag in raw_flags:
        if flags and flags[-1].startswith("-D") and flags[-1].count("(") > flags[-1].count(")"):
            flags[-1] += " " + flag
        else:
            flags.append(flag)
    # xnu-env.sh normally provides this wrapper path to make.
    work = tree.parent
    environment = os.environ.copy()
    environment["PATH"] = str(work / "base/xnu-deps/host/bin") + os.pathsep + environment["PATH"]
    command = flags + ["-c", str(tree / "bsd/dev/onyx_touch.c"), "-o", "onyx_touch.o"]
    result = subprocess.run(command, cwd=directory, env=environment)
    if result.returncode:
        raise SystemExit(result.returncode)
    output = Path(__file__).resolve().parents[1] / "out/touch-compile.json"
    output.write_text(json.dumps({"source": str(tree / "bsd/dev/onyx_touch.c"),
        "object": str(directory / "onyx_touch.o"), "compiled": True,
        "linked_kernel": False, "hardware_validated": False, "mode": "passive"}, indent=2) + "\n")
    print(f"Compiled passive Onyx touch object: {directory / 'onyx_touch.o'}")


if __name__ == "__main__":
    main()
