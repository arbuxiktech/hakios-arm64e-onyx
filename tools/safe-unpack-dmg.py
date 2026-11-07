#!/usr/bin/env python3
"""Extract a DMG with 7-Zip and restore only verified, contained relative links."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess


def contained_link(root, name, target):
    root = root.resolve()
    source = PurePosixPath(name)
    value = PurePosixPath(target)
    if source.is_absolute() or value.is_absolute() or ".." in source.parts or "\x00" in name + target:
        raise ValueError("Absolute or traversing link name/target refused")
    link = root.joinpath(*source.parts)
    # resolve also checks any existing parent symlinks, not just lexical '..'.
    if not link.parent.resolve().is_relative_to(root):
        raise ValueError("Link parent escapes extraction root")
    if not (link.parent / target).resolve().is_relative_to(root):
        raise ValueError("Link target escapes extraction root")
    return link


def extract(image, destination, resume=False, driverkit_cache=None):
    if destination.exists() and not resume:
        raise ValueError("Output exists; explicitly use --resume only for your own incomplete extraction")
    destination.mkdir(parents=True, exist_ok=resume)
    result = subprocess.run([os.environ.get("SEVEN_ZIP", "7z"), "x", "-y", "-bso0", "-bsp0", "-o" + str(destination), str(image)],
                            capture_output=True, text=True)
    errors = [line for line in result.stderr.splitlines() if line.strip()]
    (destination / ".onyx-sevenzip-result.json").write_text(json.dumps({"exit": result.returncode,
        "stderr": errors, "stdout": result.stdout}, indent=2) + "\n")
    links = []
    fallback_files = []
    pattern = r"ERROR: Dangerous symbolic link path was ignored : (.+) : (.+)"
    if result.returncode:
        if not errors:
            raise ValueError(f"7-Zip failed ({result.returncode}): {result.stdout[-2000:]}")
        for error in errors:
            unsupported = re.fullmatch(r"ERROR: Unsupported Method : (System/DriverKit/System/Library/dyld/(dyld_shared_cache_arm64e(?:\.symbols|\.atlas)?))", error)
            if driverkit_cache and unsupported:
                name, basename = unsupported.groups()
                source = driverkit_cache / basename
                target = contained_link(destination, name, ".")
                if not source.is_file() or source.stat().st_size == 0 or not source.resolve().is_relative_to(driverkit_cache.resolve()) or target.is_symlink():
                    raise ValueError("Invalid DriverKit fallback file: " + basename)
                fallback_files.append((source, target, name))
                continue
            match = re.fullmatch(pattern, error)
            if not match:
                raise ValueError("Unresolved 7-Zip error: " + error)
            name, target = match.groups()
            link = contained_link(destination, name, target)
            if link.exists() or link.is_symlink():
                raise ValueError("Refusing to replace an existing symlink path: " + name)
            links.append((link, name, target))
        # Validate every link before creating any, then recheck after each creation.
        for link, name, target in links:
            contained_link(destination, name, target)
            link.symlink_to(target)
        for source, target, name in fallback_files:
            contained_link(destination, name, ".")
            shutil.copyfile(source, target)
    report = {"image": str(image.resolve()), "seven_zip_exit": result.returncode,
              "restored_driverkit_files_from_ipsw_tool": [{"path": name, "bytes": source.stat().st_size} for source, _, name in fallback_files],
              "restored_contained_relative_links": [{"path": name, "target": target} for _, name, target in links]}
    (destination / ".onyx-extraction-complete").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Extracted {destination}; restored {len(links)} contained relative symlinks")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", type=Path)
    ap.add_argument("destination", type=Path)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--driverkit-cache", type=Path,
                    help="DriverKit caches extracted from this IPSW by ipsw --driverkit, as a fallback for 7-Zip")
    args = ap.parse_args()
    try:
        extract(args.image, args.destination, args.resume, args.driverkit_cache)
    except (OSError, ValueError) as error:
        ap.exit(1, f"Extraction incomplete: {error}\n")


if __name__ == "__main__":
    main()
