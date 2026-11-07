#!/usr/bin/env python3
"""Prepare a pinned HakiOS loader with an Onyx diagnostics entry and write barriers."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "upstream/hakios-arm64e-dada"
REVISION = "f1ae906fcc43ba8f763663257724ba938fb820ab"


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Source changed: expected exactly one occurrence of {old[:75]!r}")
    return text.replace(old, new, 1)


def transform(original, board):
    text = original
    # This object is referenced by file-scope assembly even when the diagnostic
    # entry makes the C handoff code unreachable to the optimizer.
    text = once(text, "} other_cpu_start __attribute__((aligned(64)));",
                "} other_cpu_start __attribute__((used, aligned(64)));")
    # Match every existing direct EFI BlockIO write. Unknown new call sites fail closed below.
    text, writes = re.subn(r"\b(bio|data)->write_blocks\(\1,", "onyx_deny_storage_write(", text)
    if writes != 3 or re.search(r"->\s*write_blocks\s*\(", text):
        raise ValueError("Storage write call sites changed; review required")
    barrier = '''
/* Onyx bring-up: no persistent writes through this application's BlockIO paths.
 * This does not constrain firmware drivers or a future kernel's native UFS driver. */
static efi_status
onyx_deny_storage_write(uint32_t media_id, uint64_t lba, uint64_t size, void *buffer)
{
    (void)media_id; (void)lba; (void)size; (void)buffer;
    return EFI_ERROR_BIT | 15; /* EFI_ACCESS_DENIED */
}
'''
    text = once(text, '#include "efi.h"', '#include "efi.h"\n' + barrier)
    # Do not enumerate the logdump partition just to report diagnostics.
    text = once(text, "efi_block_io *bio = find_log_partition();", "efi_block_io *bio = NULL; /* Onyx: USB/console logs only */")
    platform = '''
#ifdef ONYX_PORT
/* Project-Silicium onyx.dts and onyxPkg MemoryMapLib, pinned in sources.lock.json.
 * Do not select by framebuffer: dada uses the same framebuffer reservation. */
static const struct platform platform_onyx = {
    .name = "onyx",
    .io_base = 0x00400000, .io_size = 0x3FC00000,
    .gic_dist = GIC_DIST, .gic_redist = GIC_REDIST,
    .gic_redist_size = GIC_SIZE, .gic_redist_stride = GIC_STRIDE,
    .uart = 0, .log_other_cpu = 0,
    .cores = 8, .core_shift = 8, .small_cores = 0,
    .fb_base = 0xFC800000,
};
#endif
'''
    for key, field in (("GIC_DIST", "gic_dist"), ("GIC_REDIST", "gic_redist"),
                       ("GIC_SIZE", "gic_redist_size"), ("GIC_STRIDE", "gic_redist_stride")):
        platform = platform.replace(key, board[field])
    text = once(text, "static const struct platform *const platforms[] = {", platform + "\nstatic const struct platform *const platforms[] = {")
    text = once(text, "\tPLAT = &platform_qemu_virt;", '''#ifdef ONYX_PORT
    PLAT = &platform_onyx;
#else
    PLAT = &platform_qemu_virt;
#endif''')
    start = "\t\tfor (unsigned i = 0; i < sizeof(platforms) / sizeof(platforms[0]); i++)"
    end = "\t\t\tramfb_phone_screen();"
    first, last = text.index(start), text.index(end) + len(end)
    text = text[:first] + "#ifndef ONYX_PORT\n" + text[first:last] + "\n#endif" + text[last:]
    text = once(text, '\tprint("platform %s\\n", PLAT->name);', '''\tprint("platform %s\\n", PLAT->name);
#ifdef ONYX_PORT
    print("ONYX DIAGNOSTICS ONLY: XNU has not been started\\n");
    print("GICD=%x GICR=%x stride=%x\\n", PLAT->gic_dist, PLAT->gic_redist, PLAT->gic_redist_stride);
    print("MPIDR=%x ISAR1=%x ISAR2=%x PFR0=%x\\n", READ_SYSREG(MPIDR_EL1),
        READ_SYSREG(ID_AA64ISAR1_EL1), READ_SYSREG(ID_AA64ISAR2_EL1), READ_SYSREG(ID_AA64PFR0_EL1));
    print("No disk operations, watchdog SMCs or kernel handoff in this entry.\\n");
    print("Returning to UEFI in 15 seconds.\\n");
    BS->stall(15000000);
    return 0;
#endif''')
    return text


def main():
    revision = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise SystemExit("Unexpected HakiOS revision; review the port against the new source first")
    loader = SOURCE / "base/xnuloader/loader.c"
    original = subprocess.check_output(["git", "-C", str(SOURCE), "show", "HEAD:base/xnuloader/loader.c"]).decode()
    if loader.read_text(encoding="utf-8") != original:
        raise SystemExit("Upstream loader has local changes; refusing to ignore them")
    board = json.loads((ROOT / "devices/onyx.json").read_text())
    result = transform(original, board)
    output = ROOT / "out/onyx-loader"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("efi.h", "identity.h"):
        (output / name).write_bytes((loader.parent / name).read_bytes())
    (output / "loader.c").write_text(result, encoding="utf-8", newline="\n")
    patch = "".join(difflib.unified_diff(original.splitlines(True), result.splitlines(True),
                     fromfile="a/base/xnuloader/loader.c", tofile="b/base/xnuloader/loader.c"))
    (ROOT / "patches").mkdir(exist_ok=True)
    (ROOT / "patches/onyx-loader.patch").write_text(patch, encoding="utf-8", newline="\n")
    (output / "source.json").write_text(json.dumps({"upstream_commit": revision,
        "upstream_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "prepared_sha256": hashlib.sha256(result.encode()).hexdigest(),
        "mode": "diagnostics-only", "hardware_validated": False}, indent=2) + "\n")
    print(f"Prepared Onyx diagnostics source in {output}")


if __name__ == "__main__":
    main()
