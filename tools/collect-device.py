#!/usr/bin/env python3
"""Read-only Android inventory. Does not use root, push files, reboot or flash."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys

PROPERTIES = (
    "ro.product.model", "ro.product.device", "ro.product.vendor.device",
    "ro.soc.model", "ro.board.platform", "ro.build.fingerprint",
    "ro.boot.slot_suffix", "ro.boot.flash.locked", "ro.boot.verifiedbootstate",
    "ro.crypto.state", "ro.crypto.type", "ro.crypto.metadata.enabled",
)
QUERIES = {
    "cpuinfo": ["cat", "/proc/cpuinfo"],
    "memory": ["cat", "/proc/meminfo"],
    "input_devices": ["cat", "/proc/bus/input/devices"],
    "input_capabilities": ["getevent", "-lp"],
    "partitions": ["cat", "/proc/partitions"],
    "partition_names": ["ls", "-l", "/dev/block/by-name"],
    "mounts": ["cat", "/proc/mounts"],
    "storage_free": ["df", "-k", "/data"],
    "device_tree_model": ["cat", "/sys/firmware/devicetree/base/model"],
    "device_tree_compatible": ["cat", "/sys/firmware/devicetree/base/compatible"],
    "soc_id": ["cat", "/sys/devices/soc0/soc_id"],
    "soc_machine": ["cat", "/sys/devices/soc0/machine"],
    "soc_family": ["cat", "/sys/devices/soc0/family"],
    "spi_devices": ["ls", "-l", "/sys/bus/spi/devices"],
    "touch_spi_driver": ["ls", "-l", "/sys/bus/spi/devices/spi4.0/driver"],
    "touch_modules": ["ls", "/vendor_dlkm/lib/modules"],
    "touch_firmware_names": ["ls", "/odm/firmware/o10u"],
    "touch_host_processing_config": ["cat", "/odm/firmware/o10u_nova_csot_thp_config.ini"],
    "i2c_devices": ["ls", "-l", "/sys/bus/i2c/devices"],
    "dsu_status": ["gsi_tool", "status"],
}


def run(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=20)
        return {"returncode": p.returncode, "stdout": p.stdout.replace("\x00", "\n"), "stderr": p.stderr}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "query timed out"}
    except FileNotFoundError:
        sys.exit(f"Executable not found: {args[0]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--serial")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    inventory = run([args.adb, "devices"])
    if inventory["returncode"]:
        sys.exit(inventory["stderr"])
    devices = [line.split()[0] for line in inventory["stdout"].splitlines()
               if len(line.split()) == 2 and line.split()[1] == "device"]
    if args.serial:
        if args.serial not in devices:
            sys.exit("Requested device is not connected and authorized. No device commands sent.")
        serial = args.serial
    elif len(devices) == 1:
        serial = devices[0]
    else:
        sys.exit("Connect one authorized Android device, or select it with --serial. No device commands sent.")
    prefix = [args.adb, "-s", serial, "shell"]
    props = {key: run(prefix + ["getprop", key]) for key in PROPERTIES}
    codes = [props[k]["stdout"].strip() for k in ("ro.product.device", "ro.product.vendor.device")]
    now = datetime.datetime.now(datetime.timezone.utc)
    report = {
        "created_utc": now.isoformat(), "serial": serial,
        "properties": props,
        "android_properties_identify_onyx": any(code in ("onyx", "onyx_global") for code in codes),
        "identity_note": "Read-only capture; OxygenOS may spoof properties. Verify hardware before any boot image use.",
        "queries": {name: run(prefix + query) for name, query in QUERIES.items()},
    }
    output = args.output or Path("reports") / ("onyx-" + now.strftime("%Y%m%dT%H%M%SZ") + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Read-only inventory saved to {output}. Keep private: includes device serial and build details.")


if __name__ == "__main__":
    main()
