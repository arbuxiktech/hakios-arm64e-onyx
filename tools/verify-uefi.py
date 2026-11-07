#!/usr/bin/env python3
"""Check the diagnostic FV contents and Android boot container; never boots a device."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC_GUID = "40cce213-62e6-4d71-86c1-d690911e39b7"


def fv_files(data):
    if len(data) < 56 or data[40:44] != b"_FVH":
        raise ValueError("Missing firmware volume header")
    length = struct.unpack_from("<Q", data, 32)[0]
    header = struct.unpack_from("<H", data, 48)[0]
    if length != len(data) or header < 56 or header > length:
        raise ValueError("Firmware volume bounds mismatch")
    offset = (header + 7) & ~7
    files = {}
    while offset < length:
        if data[offset:] == b"\xff" * (length - offset):
            break
        if offset + 24 > length:
            raise ValueError("Truncated FFS header")
        size = int.from_bytes(data[offset+20:offset+23], "little")
        minimum = 24
        if size == 0xffffff:
            if offset + 32 > length:
                raise ValueError("Truncated extended FFS header")
            size = struct.unpack_from("<Q", data, offset+24)[0]
            minimum = 32
        if size < minimum or offset + size > length:
            raise ValueError("FFS file exceeds firmware volume")
        guid = str(uuid.UUID(bytes_le=bytes(data[offset:offset+16])))
        if guid in files:
            raise ValueError("Duplicate FFS file GUID")
        files[guid] = data[offset+18]
        offset = (offset + size + 7) & ~7
    return files


def boot_kernel(data):
    if len(data) < 4096 or data[:8] != b"ANDROID!":
        raise ValueError("Missing Android boot header")
    kernel, ramdisk = struct.unpack_from("<II", data, 8)
    header = struct.unpack_from("<I", data, 20)[0]
    version = struct.unpack_from("<I", data, 40)[0]
    if version != 4 or header != 1584 or not kernel or 4096 + kernel > len(data):
        raise ValueError("Unexpected or truncated Android v4 boot image")
    ramdisk_start = (4096 + kernel + 4095) & ~4095
    if ramdisk_start + ramdisk > len(data):
        raise ValueError("Truncated boot ramdisk")
    return data[4096:4096+kernel]


def verify(tree, image, output=None):
    prep = json.loads((ROOT / "out/onyx-uefi/preparation.json").read_text())
    fv = tree / "Build/onyxPkg/RELEASE_CLANGPDB/FV"
    # FvMain is the uncompressed volume embedded in the final compact FD.
    volume = fv / "FVMAIN.Fv"
    if not volume.exists():
        volume = fv / "FVMAIN.fv"
    files = fv_files(volume.read_bytes())
    if files.get(DIAGNOSTIC_GUID) != 9:
        raise ValueError("Embedded diagnostic application absent")
    bad = {name: guid for name, guid in prep["excluded_guids"].items() if guid in files}
    if bad:
        raise ValueError(f"Excluded storage/update modules remain in FV: {bad}")
    kernel = boot_kernel(image.read_bytes())
    compressed = zlib.decompressobj(16 + zlib.MAX_WBITS)
    content = compressed.decompress(kernel, 8 * 1024 * 1024)
    expected = (tree / "BootShim/BootShim.bin").read_bytes() + (fv / "SILICIUM_UEFI.fd").read_bytes()
    if not compressed.eof or compressed.unconsumed_tail or content != expected:
        raise ValueError("Packaged boot shim/FD mismatch")
    if compressed.unused_data != (tree / "Resources/DTBs/onyx.dtb").read_bytes():
        raise ValueError("Packaged Onyx DTB mismatch")
    report = {"image": str(image.resolve()), "bytes": image.stat().st_size,
              "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
              "fv_files": len(files), "excluded_module_guids_absent": True,
              "boot_header_version": 4, "embedded_diagnostics": True,
              "hardware_boot_tested": False, "safe_to_flash": False}
    (output or ROOT / "out/onyx-uefi/verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tree", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    verify(args.tree, args.image, args.output)
