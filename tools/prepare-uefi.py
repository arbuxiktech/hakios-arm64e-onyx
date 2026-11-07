#!/usr/bin/env python3
"""Prepare pinned Mu-Silicium for an embedded diagnostic EFI, without storage DXE.

This edits a host source checkout only. Proprietary platform blobs still require
hardware validation; a successful build does not establish safe phone operation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "8471e47f5248ebbffc2e6196b683204163efe155"
GUID = "40CCE213-62E6-4D71-86C1-D690911E39B7"
DENIED = ("UFSDxe", "SdccDxe", "UsbMsdDxe", "UsbMassStorageDxe",
          "DiskIoDxe", "PartitionDxe", "EnhancedFatDxe", "CapsuleRuntimeDxe")


def git(tree, *args):
    return subprocess.check_output(["git", "-C", str(tree), *args])


def filter_modules(text, usb_logs=False):
    removed = []
    lines = []
    denied = DENIED + (("XhciDxe", "XhciPciEmulationDxe", "UsbBusDxe", "UsbKbDxe") if usb_logs else ())
    for line in text.splitlines(True):
        if re.match(r"\s*INF\s", line) and any(name in line for name in denied):
            removed.append(line.strip())
        else:
            lines.append(line)
    return "".join(lines), removed


def put(tree, name, content, original=None):
    path = tree / name
    if path.exists():
        current = path.read_bytes()
        if current != content and (original is None or current != original):
            raise ValueError(f"Unrelated local changes in {name}; left untouched")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def prepare(tree, usb_logs=False, usb_probe=False):
    if git(tree, "rev-parse", "HEAD").decode().strip() != REVISION:
        raise ValueError("Unexpected Mu-Silicium revision")
    # Verify that the selected application really is AArch64 UEFI PE32+.
    loader = (ROOT / "out/onyx-loader/loader-onyx-diagnostics.efi").read_bytes()
    pe = struct.unpack_from("<I", loader, 0x3c)[0]
    if (loader[:2] != b"MZ" or loader[pe:pe+4] != b"PE\0\0" or
            struct.unpack_from("<H", loader, pe+4)[0] != 0xaa64 or
            struct.unpack_from("<H", loader, pe+24)[0] != 0x20b or
            struct.unpack_from("<H", loader, pe+24+68)[0] != 10):
        raise ValueError("Expected an AArch64 EFI application")
    if b"ONYX DIAGNOSTICS ONLY" not in loader:
        raise ValueError("Diagnostic marker absent")
    removed = []
    for name in ("Platforms/Xiaomi/onyxPkg/Include/DXE.inc", "Platforms/Xiaomi/onyxPkg/Include/APRIORI.inc"):
        original = git(tree, "show", "HEAD:" + name)
        text, entries = filter_modules(original.decode(), usb_logs)
        removed.extend(entries)
        put(tree, name, text.encode(), original)
    name = "Platforms/Xiaomi/onyxPkg/onyx.fdf"
    original = git(tree, "show", "HEAD:" + name)
    application = ("  INF onyxPkg/Applications/UsbDiagnostics/UsbDiagnostics.inf" if usb_logs else f'''  # Only this application is included; no menu, update or mass-storage apps.
  FILE APPLICATION = {GUID} {{
    SECTION PE32 = Resources/OnyxDiagnostics.efi
    SECTION UI = "Onyx RAM diagnostics"
  }}''')
    text = original.decode().replace("  !include QcomPkg/Extra.fdf.inc", application)
    if text == original.decode():
        raise ValueError("Onyx application integration point changed")
    put(tree, name, text.encode(), original)
    name = "Platforms/Xiaomi/onyxPkg/onyx.dsc"
    original = git(tree, "show", "HEAD:" + name)
    text = original.decode().replace("[LibraryClasses]\n", "[LibraryClasses]\n  PlatformBootManagerLib|onyxPkg/Library/DiagnosticsBootManagerLib/BootManagerLib.inf\n")
    if usb_logs:
        text = text.replace("[Components]\n", "[Components]\n  onyxPkg/Applications/UsbDiagnostics/UsbDiagnostics.inf\n")
    put(tree, name, text.encode(), original)
    for name in ("BootManager.c", "BootManagerLib.inf"):
        put(tree, "Platforms/Xiaomi/onyxPkg/Library/DiagnosticsBootManagerLib/" + name,
            (ROOT / "firmware/onyx-diagnostics" / name).read_text().encode())
    put(tree, "Resources/OnyxDiagnostics.efi", loader)
    if usb_logs:
        for name in ("UsbDiagnostics.c", "UsbDiagnostics.inf"):
            content = (ROOT / "firmware/onyx-diagnostics" / name).read_text().encode()
            original = None
            if name == "UsbDiagnostics.c":
                probe_content = content.replace(b"#define CONTROLLER_PROBE 0", b"#define CONTROLLER_PROBE 1")
                if usb_probe:
                    content, original = probe_content, content
                else:
                    original = probe_content
            put(tree, "Platforms/Xiaomi/onyxPkg/Applications/UsbDiagnostics/" + name,
                content, original)
    mode = "USB controller probe" if usb_probe else ("USB diagnostics" if usb_logs else "embedded diagnostics only")
    report = {"mu_commit": REVISION, "mode": mode, "usb_controller_probe": usb_probe,
              "excluded_modules": removed, "diagnostic_sha256": None if usb_logs else hashlib.sha256(loader).hexdigest(),
              "hardware_boot_tested": False, "safe_to_flash": False}
    report["excluded_guids"] = {}
    for entry in sorted(set(removed)):
        name = entry.split()[1]
        candidates = [tree / prefix / name for prefix in
                      ("", "Mu_Basecore", "Common/Mu", "Common/Mu_OEM_Sample", "Silicon/Qualcomm", "Silicon/Silicium")]
        found = [p for p in candidates if p.is_file()]
        if len(found) != 1:
            raise ValueError(f"Cannot resolve excluded module {name}")
        match = re.search(r"^\s*FILE_GUID\s*=\s*([0-9a-fA-F-]{36})", found[0].read_text(), re.M)
        if match is None:
            raise ValueError(f"No GUID in excluded module {name}")
        report["excluded_guids"][name] = match[1].lower()
    output = ROOT / "out/onyx-uefi"
    output.mkdir(parents=True, exist_ok=True)
    (output / "preparation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tree", type=Path)
    parser.add_argument("--usb-logs", action="store_true")
    parser.add_argument("--usb-probe", action="store_true")
    args = parser.parse_args()
    prepare(args.tree, args.usb_logs or args.usb_probe, args.usb_probe)
