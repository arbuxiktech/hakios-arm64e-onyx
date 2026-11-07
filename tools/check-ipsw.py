#!/usr/bin/env python3
"""Inspect a local IPSW manifest without extracting or installing the system."""
import argparse
import json
from pathlib import Path
import plistlib
import zipfile


def inspect(path):
    with zipfile.ZipFile(path) as archive:
        member = archive.getinfo("BuildManifest.plist")
        if member.file_size > 16 * 1024 * 1024:
            raise ValueError("Unexpectedly large BuildManifest.plist")
        manifest = plistlib.loads(archive.read(member))
    version = manifest.get("ProductVersion")
    build = manifest.get("ProductBuildVersion")
    devices = manifest.get("SupportedProductTypes", [])
    candidate = version == "26.6.2" and build == "23G90" and "iPhone18,1" in devices
    identities = []
    for identity in manifest.get("BuildIdentities", []):
        info = identity.get("Info", {})
        identities.append({
            "device_class": info.get("DeviceClass"),
            "variant": info.get("Variant"),
            "components": {name: component.get("Info", {}).get("Path")
                           for name, component in identity.get("Manifest", {}).items()
                           if name in ("OS", "Cryptex1,SystemOS", "Cryptex1,AppOS", "KernelCache", "DeviceTree")},
        })
    return {"product_version": version, "build": build, "devices": devices,
            "matches_dada_launcher_reference": candidate,
            "kernel_abi_compatibility_verified": False,
            "note": "Manifest identity is not an authenticity check or proof of Onyx boot support.",
            "identities": identities}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipsw", type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args.ipsw)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, plistlib.InvalidFileException) as error:
        parser.exit(1, f"IPSW check failed: {error}\n")
    print(json.dumps(result, indent=2))
    if not result["matches_dada_launcher_reference"]:
        parser.exit(2, "This archive is not the 23G90 / iPhone18,1 userland referenced by the Dada launcher.\n")


if __name__ == "__main__":
    main()
