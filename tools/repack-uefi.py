#!/usr/bin/env python3
"""Build a raw Onyx diagnostic candidate from a supplied Android v4 boot profile.

Host-only packaging. Does not reboot or contact a phone. No Android kernel,
ramdisk, boot signature or AVB footer is carried into the resulting candidate.
"""
import argparse
import hashlib
import gzip
import importlib.util
import json
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reference_header(data):
    if len(data) < 4096 or data[:8] != b"ANDROID!":
        raise ValueError("Expected an Android boot image")
    if struct.unpack_from("<I", data, 40)[0] != 4 or struct.unpack_from("<I", data, 20)[0] != 1584:
        raise ValueError("Expected Android header v4")
    if not struct.unpack_from("<I", data, 8)[0] or struct.unpack_from("<I", data, 12)[0]:
        raise ValueError("Reference must be a kernel-only boot image, not init_boot/recovery")
    if struct.unpack_from("<I", data, 1580)[0]:
        raise ValueError("Reference has a boot signature; review its packaging separately")
    if any(data[24:40]) or any(data[1584:4096]):
        raise ValueError("Reference reserved/header padding bytes are not zero")
    kernel = struct.unpack_from("<I", data, 8)[0]
    if kernel + 4096 > len(data):
        raise ValueError("Truncated reference kernel")
    return bytes(data[:4096])


def pack(header, shim, firmware, dtb, compression="none"):
    if len(shim) < 64 or shim[56:60] != b"ARM\x64":
        raise ValueError("Missing ARM64 shim header")
    if dtb[:4] != bytes.fromhex("d00dfeed"):
        raise ValueError("Missing Onyx DTB")
    if len(dtb) < 40 or struct.unpack_from(">I", dtb, 4)[0] != len(dtb):
        raise ValueError("DTB size mismatch")
    adjusted = bytearray(shim)
    # Linux ARM64 image_size covers its header and executable payload, not DTB.
    image_size = len(shim) + len(firmware)
    struct.pack_into("<Q", adjusted, 16, image_size)
    blob = bytes(adjusted) + firmware
    if compression not in ("none", "gzip"):
        raise ValueError("Unsupported payload compression")
    kernel = (gzip.compress(blob, mtime=0) if compression == "gzip" else blob) + dtb
    result = bytearray(header)
    struct.pack_into("<II", result, 8, len(kernel), 0)
    struct.pack_into("<I", result, 1580, 0)
    result.extend(kernel)
    result.extend(b"\0" * (-len(result) % 4096))
    return bytes(result), bytes(adjusted), image_size


def build(tree, reference, output, compression="none"):
    source = reference.read_bytes()
    header = reference_header(source)
    fv = tree / "Build/onyxPkg/RELEASE_CLANGPDB/FV"
    firmware = (fv / "SILICIUM_UEFI.fd").read_bytes()
    shim = (tree / "BootShim/BootShim.bin").read_bytes()
    dtb = (tree / "Resources/DTBs/onyx.dtb").read_bytes()
    if len(firmware) != 0x300000 or struct.unpack_from("<Q", shim, 8)[0] != 0xA7100000:
        raise ValueError("Unexpected Onyx FD size or shim text offset")
    spec = importlib.util.spec_from_file_location("verify_uefi", ROOT / "tools/verify-uefi.py")
    verify = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify)
    files = verify.fv_files((fv / "FVMAIN.Fv").read_bytes())
    prep = json.loads((ROOT / "out/onyx-uefi/preparation.json").read_text())
    if files.get(verify.DIAGNOSTIC_GUID) != 9:
        raise ValueError("Embedded diagnostic EFI absent")
    if any(guid in files for guid in prep["excluded_guids"].values()):
        raise ValueError("Excluded storage/update module found in FV")
    image, adjusted, image_size = pack(header, shim, firmware, dtb, compression)
    kernel = verify.boot_kernel(image)
    if compression == "gzip":
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        blob = decoder.decompress(kernel, 8 * 1024 * 1024)
        if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data != dtb:
            raise ValueError("Compressed payload/DTB mismatch")
    else:
        blob = kernel[:-len(dtb)]
        if kernel[-len(dtb):] != dtb:
            raise ValueError("Raw payload DTB mismatch")
    if blob != adjusted + firmware or image[16:1580] != header[16:1580]:
        raise ValueError("Candidate contents or preserved profile mismatch")
    if struct.unpack_from("<Q", blob, 16)[0] != len(adjusted) + len(firmware):
        raise ValueError("ARM64 image span mismatch")
    candidate = output.stem
    report = {"candidate": candidate, "bytes": len(image), "sha256": sha(image),
              "reference_boot_sha256": sha(source), "reference_os_version": hex(struct.unpack_from("<I", header, 16)[0]),
              "fd_sha256": sha(firmware), "original_shim_sha256": sha(shim),
              "adjusted_shim_sha256": sha(adjusted), "dtb_sha256": sha(dtb),
              "arm64_image_size_before": struct.unpack_from("<Q", shim, 16)[0],
              "arm64_image_size_after": image_size, "compression": compression, "ramdisk_bytes": 0,
              "boot_header_version": 4, "excluded_module_guids_absent": True,
              "hardware_attempted": False, "bootloader_acceptance_verified": False,
              "safe_to_flash": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_bytes() != image:
        raise ValueError("Refusing to overwrite a different candidate")
    output.write_bytes(image)
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--reference-boot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compression", choices=("none", "gzip"), default="none")
    args = parser.parse_args()
    build(args.tree, args.reference_boot, args.output, args.compression)
