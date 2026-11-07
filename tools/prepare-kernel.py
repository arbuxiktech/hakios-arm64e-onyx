#!/usr/bin/env python3
"""Apply the pinned iOS 26 base and passive Onyx touch overlay to pristine XNU.

Run in Linux/WSL against a fresh clone of Apple xnu-12377.121.6. This prepares
source only. Experimental MMIO/GPI transport from the reference stays unreachable.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
APPLE_COMMIT = "ac9718fb1af618d5ce8678d0dc6e8a58f252216f"
REFERENCE_COMMIT = "1a1f3d3510ccf3f1a92afd7238ac406dd9d6897a"


def run(tree, *args, **kwargs):
    return subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True, **kwargs).stdout


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected one integration point: {old[:70]!r}")
    return text.replace(old, new, 1)


def touch_source(source):
    # Preserve provenance and staged reference code, but keep its active transport
    # unreachable in the initial port. No boot argument can bypass this return.
    marker = '\tif (PE_parse_boot_argn("onyx_touch_shared_pa", &bridge_pa, sizeof(bridge_pa)) && bridge_pa != 0) {'
    source = replace_once(source, "struct onyx_touch_bridge {", "#if 0 /* Legacy transport retained for review; not compiled in the passive iOS 26 build. */\nstruct onyx_touch_bridge {")
    source = replace_once(source, "static void\nonyx_touch_probe_thread(__unused", "#endif\n\nstatic void\nonyx_touch_probe_thread(__unused")
    source = replace_once(source, marker, '''
    /* Onyx iOS 26 port: passive bring-up only. The reference's GPI/SMMU,
     * GPIO, FIFO and bridge paths need separate review against stock firmware.
     * In particular, no boot argument may enable them in this build. */
    printf("onyx-touch: iOS26 passive build; hardware transport withheld\\n");
    return;
#if 0 /* No runtime argument can enable unported transport code. */
''' + marker)
    return replace_once(source, "}\n\nvoid\nonyx_touch_init(void)", "#endif\n}\n\nvoid\nonyx_touch_init(void)")


def prepare(tree):
    if run(tree, "rev-parse", "HEAD").decode().strip() != APPLE_COMMIT:
        raise ValueError("Kernel must be at the pinned Apple xnu-12377.121.6 commit")
    if run(tree, "status", "--porcelain").strip():
        raise ValueError("Kernel tree must be pristine; existing changes are left untouched")
    reference = ROOT / "upstream/hakios-onyx-reference"
    if run(reference, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Unexpected Onyx reference revision")
    # Read Git objects to avoid Windows checkout CRLF conversion in patches/C.
    dada = ROOT / "upstream/hakios-arm64e-dada"
    lock = json.loads((ROOT / "sources.lock.json").read_text())
    dada_commit = next(s["commit"] for s in lock["repositories"] if s["path"] == "upstream/hakios-arm64e-dada")
    patch = run(dada, "show", f"{dada_commit}:kernel/xnu-12377.121.6-dada.patch")
    source = run(reference, "show", f"{REFERENCE_COMMIT}:xnu/files/bsd/dev/onyx_touch.c").decode()
    source = touch_source(source)
    run(tree, "apply", "--check", "-", input=patch)
    run(tree, "apply", "--whitespace=nowarn", "-", input=patch)
    apply_overlay(tree, source)
    report = {"apple_commit": APPLE_COMMIT, "dada_commit": dada_commit, "onyx_reference_commit": REFERENCE_COMMIT,
              "base_patch_sha256": hashlib.sha256(patch).hexdigest(), "kernel_tree": str(tree.resolve()),
              "touch_mode": "passive diagnostics only", "compiled": False, "hardware_validated": False}
    output = ROOT / "out/kernel-preparation.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Prepared iOS 26 kernel with passive Onyx touch integration: {tree}")


def apply_overlay(tree, source):
    modifications = {}
    path = "bsd/conf/files"
    before = (tree / path).read_text()
    after = replace_once(before, "bsd/dev/redwood_goodix.c\tstandard\n", "")
    modifications[path] = (before, after + "\nbsd/dev/onyx_touch.c\t\tstandard\n")
    path = "bsd/sys/redwood_input.h"
    before = (tree / path).read_text()
    modifications[path] = (before, replace_once(before, "void redwood_input_init(void);",
        "void onyx_touch_init(void); /* onyx_touch_probe=1: passive diagnostics only */\nvoid redwood_input_init(void);"))
    path = "bsd/dev/redwood_input.c"
    before = (tree / path).read_text()
    modifications[path] = (before, replace_once(before, "\tredwood_goodix_init();",
        "\tonyx_touch_init(); /* Onyx does not use Redwood Goodix/FocalTech */"))
    modifications["bsd/dev/onyx_touch.c"] = ("", source)
    overlay = []
    for name, (before, after) in modifications.items():
        (tree / name).write_text(after, encoding="utf-8", newline="\n")
        overlay.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
            fromfile="a/" + name if before else "/dev/null", tofile="b/" + name))
    (ROOT / "patches/onyx-xnu12377-touch-passive.patch").write_text("".join(overlay), encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tree", type=Path)
    args = ap.parse_args()
    try:
        prepare(args.tree)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            ap.exit(1, error.stderr.decode(errors="replace"))
        ap.exit(1, f"Kernel preparation failed: {error}\n")


if __name__ == "__main__":
    main()
