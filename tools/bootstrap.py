#!/usr/bin/env python3
"""Fetch the pinned public sources. Never flashes, builds or updates an existing checkout."""
import json
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-only", action="store_true", help="Fetch only Dada and the Onyx reference needed for kernel preparation")
    args = parser.parse_args()
    sources = json.loads((ROOT / "sources.lock.json").read_text())
    for source in sources["repositories"]:
        if args.kernel_only and source["path"] not in ("upstream/hakios-arm64e-dada", "upstream/hakios-onyx-reference"):
            continue
        destination = ROOT / source["path"]
        if destination.exists():
            revision = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
            if revision != source["commit"]:
                raise SystemExit(f"{destination}: unexpected revision {revision}; left unchanged")
            print(f"Verified {source['path']}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(destination)], check=True)
        subprocess.run(["git", "-C", str(destination), "remote", "add", "origin", source["url"]], check=True)
        subprocess.run(["git", "-C", str(destination), "fetch", "--depth", "1", "--filter=blob:none", "origin", source["commit"]], check=True)
        # Some Linux trees contain Windows-reserved filenames; keep these sources
        # as Git objects until the needed files are extracted or a Linux worktree is used.
        if source.get("objects_only"):
            subprocess.run(["git", "-C", str(destination), "reset", "--soft", "FETCH_HEAD"], check=True)
        else:
            subprocess.run(["git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"], check=True)


if __name__ == "__main__":
    main()
