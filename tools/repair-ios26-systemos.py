#!/usr/bin/env python3
"""Recover unsupported SystemOS files using ipsw's decoder, with size checks."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def path_pattern(paths):
    trie = {}
    for path in paths:
        node = trie
        for character in path:
            node = node.setdefault(character, {})
        node[None] = {}

    def render(node):
        branches = [re.escape(key) + render(value) for key, value in node.items() if key is not None]
        text = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
        if not branches:
            text = ""
        return "(?:" + text + ")?" if None in node and branches else text
    return "(?:^|/)" + render(trie) + "$"


def repair(ipsw, ios, reuse_decoded=False):
    root = ios / "cryptex"
    image = ios / "23G90__iPhone18,1/094-97238-092.dmg"
    results = json.loads((root / ".onyx-sevenzip-result.json").read_text())
    paths, links = [], []
    for error in results["stderr"]:
        if error.startswith("ERROR: Unsupported Method : "):
            paths.append(error.removeprefix("ERROR: Unsupported Method : "))
        else:
            match = re.fullmatch(r"ERROR: Dangerous (?:symbolic link path|link via another link) was ignored : (.+) : (.+)", error)
            if not match:
                raise ValueError("Unresolved archive error: " + error)
            links.append(match.groups())
    if not paths:
        raise ValueError("No unsupported-file list to repair")
    spec = importlib.util.spec_from_file_location("safe_unpack", Path(__file__).with_name("safe-unpack-dmg.py"))
    safe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(safe)
    for name in paths:
        safe.contained_link(root, name, ".")
    listing = subprocess.check_output([os.environ.get("SEVEN_ZIP", "7z"), "l", "-slt", str(image)], text=True)
    sizes = {}
    for record in listing.split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in record.splitlines() if " = " in line)
        if "Path" in fields and fields.get("Size", "").isdigit():
            sizes[fields["Path"]] = int(fields["Size"])
    if any(name not in sizes for name in paths):
        raise ValueError("Archive size metadata is missing for a requested file")
    pattern = path_pattern(paths)
    if len(pattern.encode()) > 120000:
        raise ValueError("Recovery pattern exceeds a safe command-argument size")
    output = ios / "systemos-recovery"
    output.mkdir(exist_ok=True)
    log = output / "extract.log"
    command = ["ipsw", "extract", "--files", "--pattern", pattern, "--device", "iPhone18,1", "--output", str(output), str(ipsw)]
    print(f"Recovering {len(paths)} unsupported SystemOS files with ipsw", flush=True)
    if not reuse_decoded:
        with log.open("w") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    source_root = output / "23G90__iPhone18,1/root"
    validated = []
    for name in paths:
        source = source_root / name
        target = safe.contained_link(root, name, ".")
        if not source.is_file() or not source.resolve().is_relative_to(source_root.resolve()) or source.stat().st_size != sizes[name]:
            raise ValueError("Missing or size-mismatched decoded file: " + name)
        if target.is_symlink():
            raise ValueError("Refusing to replace a symlink with decoded file: " + name)
        validated.append((source, target))
    # Copy only after all recovered files pass the archive size checks.
    for source, target in validated:
        shutil.copyfile(source, target)
    for name, target in links:
        link = safe.contained_link(root, name, target)
        if link.is_symlink() and os.readlink(link) == target:
            continue
        # 7-Zip can leave a refused symlink as a small file containing its target.
        # Replace only that exact, archive-declared placeholder in generated output.
        if link.is_file() and not link.is_symlink() and link.stat().st_size <= len(target.encode()) + 1:
            if link.read_bytes() in (b"", target.encode(), target.encode() + b"\n"):
                link.unlink()
        if link.exists() or link.is_symlink():
            raise ValueError("Refusing to replace existing symlink location: " + name)
        link.symlink_to(target)
    report = {"image": str(image), "recovered_files": len(validated), "all_recovered_sizes_match_archive": True,
              "restored_relative_links": [{"path": name, "target": target} for name, target in links],
              "decoder": "ipsw extract --files", "hardware_validated": False}
    (root / ".onyx-extraction-complete").write_text(json.dumps(report, indent=2) + "\n")
    print(f"SystemOS extraction complete: {len(validated)} files recovered and size-checked")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipsw", type=Path)
    parser.add_argument("ios", type=Path)
    parser.add_argument("--reuse-decoded", action="store_true", help="Revalidate existing decoder output instead of extracting again")
    args = parser.parse_args()
    try:
        repair(args.ipsw, args.ios, args.reuse_decoded)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"SystemOS recovery incomplete: {error}\n")


if __name__ == "__main__":
    main()
