# Onyx diagnostic firmware

The host build produced `out/onyx-uefi/onyx-uefi-diagnostics.img` (1,314,816 bytes).
SHA-256: `ca7be4f39e40926c9d2d4ab525dd1f1b543cd084ad3194a1d4c0b87b6ae8226f`.
The bootloader rejected its first RAM-boot attempt before execution. Do not retry
this candidate. It does not start XNU or iOS and cannot provide touch.

## Behavior

This uses Mu-Silicium commit `8471e47f5248ebbffc2e6196b683204163efe155`
with its pinned submodules and Onyx platform. An Onyx-specific boot-manager
library connects the remaining devices and launches the diagnostic EFI directly
from the RAM firmware volume. It never continues into the normal boot menu,
OS selection, recovery or firmware-update applications.

The screen should show the memory-map summary, CPU identification/features,
GOP resolution/framebuffer and reference GIC addresses. The GIC addresses printed
by the EFI checker are configuration values, not proof of functioning interrupts.
After the checker returns, firmware stays in a loop with its watchdog disabled.
Hold the power button to restart if it does not return normally; this recovery
behavior still needs confirmation on the actual device.

Excluded from the Onyx firmware volume: UFS, SDCC, USB mass-storage exposure,
USB mass-storage host support, DiskIO, partition, FAT and capsule-update drivers.
The normal extra applications are excluded. UEFI variables use upstream's
emulated RAM-backed variable store. Proprietary Qualcomm platform drivers remain;
these changes do not prove that all firmware behavior is harmless or write-free.

## Verified on the host

- Full firmware compilation and upstream validation of 50 PE images succeeded.
- The build report resolves `PlatformBootManagerLib` to our diagnostic library.
- The uncompressed FV contains the embedded application and 88 files overall.
- All eight excluded module GUIDs are absent from that FV.
- Android boot header v4, gzip content, boot shim, FD and appended Onyx DTB match
  the expected build outputs. The copied Windows image has the same SHA-256.
- The FD base/size agree with Onyx's memory map: `0xA7100000` / `0x00300000`.
- FV decompression allocates its destination from the DXE heap; it does not copy
  the 4.6 MB uncompressed FV into the unrelated 4 MB `FV_Region` reservation.

The verifier deliberately records `hardware_boot_tested: false` and
`safe_to_flash: false`. Do not install this image to a phone partition.

## Rebuild

In WSL, clone the pinned Mu-Silicium revision to
`/home/arbuxik/ios-26-onyx-build/mu-silicium` and initialize its submodules.
Create `mu-venv` alongside it and install the pinned repository's Python
requirements there. Build the diagnostic EFI with `tools/build-loader.sh`, then:

```sh
bash tools/build-uefi.sh
```

`ONYX_BUILD_ROOT` can select a different workspace containing those two folders.
Preparation refuses unrelated changes in files that it would overwrite. When
changing the diagnostic library, use a fresh prepared tree or deliberately update
only the generated files that belong to this port.

## First hardware test

The intended test is a one-time RAM boot through an unlocked Onyx bootloader,
with Android remaining on slot A. Before issuing any boot command, verify the
bootloader product, unlock state and current slot independently of spoofed Android
properties. Stop if they disagree, or if temporary boot is unsupported. Do not
substitute flashing, unlocking, erasing, formatting or changing slots.

The supplied OxygenOS port folder includes boot, vendor_boot, init_boot, DTBO,
vbmeta and OrangeFox images. These are recovery candidates, not a verified dump
of the current installed partitions or a backup of personal data. Its installer
flashes both slots, changes the active slot and offers formatting; it is not a
recovery command for this diagnostic test and has not been executed here.

## First RAM-boot result

The user authorized one RAM-only test. Fastboot independently reported product
`onyx`, unlocked `yes`, active slot `a` and userspace `no`. Image transfer succeeded,
but boot failed with `Failed to load/authenticate boot image: Invalid Parameter`.
There is no evidence that the diagnostic EFI or UEFI started.

A normal reboot returned to fastboot. Slot A then reported successful `yes`,
unbootable `yes`, and retry count `6`. The first preflight did not capture those
flags, so their earlier values are unknown. Do not attribute the flag transition
to a particular bootloader code path without further evidence.

With separate explicit user approval, `fastboot set_active a` reselected the
already active slot and cleared the unbootable flag. This was a persistent
boot-metadata change. No boot image was flashed, no slot B was selected, and no
format/erase command was issued. After reboot, ADB confirmed `sys.boot_completed=1`,
`dev.bootcomplete=1`, slot `_a`, and the same OxygenOS build
`CPH2745_16.0.10.601(EX01)`.

Private command records are in `reports/`. Future trials require a complete
baseline including slot bootability, success and retry flags. The read-only
`tools/fastboot-preflight.py` captures these and rejects unknown/mismatched
values, including unsupported queries that return a zero process exit status.
No automatic boot or boot-metadata recovery is built into that tool.

The following candidates investigate the boot-container rejection. A valid
Android header and successful compilation do not establish hardware acceptance.
Subsequent trials were authorized, including ongoing temporary RAM tests and
recovery on the already active slot A. Image flashing and data erasure remain
outside that scope.

## Second candidate: raw payload and Android boot profile

`out/onyx-uefi/onyx-uefi-diagnostics-v2-raw.img` is a 3,637,248-byte
candidate, SHA-256 `959b1b79dcec86287c7a87824dc7daff521b1393f8a71496cfe2444db4a42d92`.
It keeps the same diagnostic firmware and Onyx DTB and changes only the host
container/shim representation:

- The payload is raw ARM64 shim + FD + DTB, matching the supplied Android image's
  uncompressed representation. Gzip support in the installed ABL is not established.
- The boot ramdisk is empty rather than Silicium's five-byte placeholder. The
  supplied boot image also has an empty ramdisk and a separate `init_boot`.
- The Android header's OS-version field (`0x200001a5`) and command line are copied
  from the supplied OxygenOS `boot.img`; its original kernel, AVB footer and
  boot signature are not copied. This is a reference profile, not an installed dump.
- The ARM64 `image_size` includes the 112-byte shim: `0x300070` rather than
  `0x300000`. The FD base, copy length, executable instructions and firmware bytes
  remain unchanged. The appended DTB is outside that ARM64 image span.

`tools/repack-uefi.py` creates and checks the candidate without phone access.
The JSON alongside it records source hashes and explicitly leaves bootloader
acceptance unverified. These differences are hypotheses for another controlled
test; they do not identify the proven cause of the earlier authentication error.

Offline inspection also extracted the ABL EFI application from the supplied
OxygenOS package. Its error string is referenced by the fastboot boot path, but
the installed ABL has not been dumped and cannot be claimed byte-identical.
No ABL modification or signature bypass is part of this candidate.

The separately approved v2 trial returned transfer and `Booting` OKAY. The screen
remained blank and ABL continued answering `getvar product` as `onyx`. This does
not prove UEFI entry. All captured slot-A flags matched the healthy baseline:
successful `yes`, unbootable `no`, retries `6`. A normal reboot returned to
Android and `sys.boot_completed=1`; no metadata reset was needed for this trial.

## Third candidate: compression comparison

`out/onyx-uefi/onyx-uefi-diagnostics-v3-gzip.img` is 1,306,624 bytes, SHA-256
`bc6a36a3119549877575dee153f8aa289add12ee55cb7f75ee6b26b0f0c0da63`.
It differs from v2 only by gzip-compressing the adjusted shim + FD before the
same appended DTB, and the resulting Android kernel-size field/padding. Its
decompressed payload, reference header profile and empty ramdisk match v2.
Use `tools/repack-uefi.py --compression gzip` to reproduce it. Host verification
and 25 tests pass. Hardware acceptance and UEFI startup remain unverified.

The v3 trial was accepted by ABL and USB disappeared from fastboot. The user
reported diagnostic text. Exact register values were not transcribed. The user
then requested USB capture rather than manually typing the diagnostic screen.
Android was restarted manually and its completed boot was checked before v4.

## USB diagnostics

`firmware/onyx-diagnostics/UsbDiagnostics.c` uses Qualcomm's UEFI USB-device
protocol, not controller MMIO. Preparation with `--usb-logs` embeds it instead
of the original HakiOS checker, retaining the same diagnostic application GUID.

The intended interface uses VID/PID `18d1:d00d`, serial `ONYXDIAG0001` and product
response `onyx-diag`. It implements `getvar:onyx-diag`, `getvar:all`, product,
serial and version queries, plus a cold `reboot`. Unknown commands fail. There
is no download, flash, erase, OEM, slot, kernel-boot or memory-access handler.
Diagnostics are kept in RAM. The same eight storage/update modules stay excluded.

`tools/read-usb-diagnostics.py --output reports/uefi-usb.json` checks the diagnostic
product, reads the log and validates its stage marker and register fields before
writing a structured record. It never sends a bootloader write command.

The first USB builds compiled and passed package verification but did not
enumerate. The initialization sequence was revised to signal the published USB
controller-init event and start the controller before allocating transfer buffers.
The user then specifically reported `Starting read-only USB diagnostics`, which
is printed by the logger application after collecting its register/GOP/memory
summary and immediately before calling the USB start method. This establishes
that the diagnostic application ran; USB transport still has not been verified.

The next candidate uses `StartEx` and complete USB 2/3 descriptors instead of the
legacy start method. Candidate v6 is
`out/onyx-uefi-usb-v6/onyx-uefi-diagnostics-v6-usb.img`, SHA-256
`255d70ce4857ecc2649ba79212ff776dad76e53ddca64846a739fc9f2f02417a`.
Host firmware/package checks and 28 tests pass. Its USB capture is untested.

V6 still did not enumerate; the user reported it remained at the USB-start line.
V7 excluded XHCI, its PCI emulation, USB bus and USB keyboard drivers as a
device-only comparison. Its FV contains 84 files and all twelve excluded module
GUIDs are absent. It also did not enumerate on the PC.

V8 is a controller probe rather than a transport build. It calls the same
underlying UsbfnIo StopController and StartController methods in order, printing
P1/P2 progress and returned statuses. It does not attempt enumeration. This is
intended to identify the blocking call before more USB transport changes.
The candidate is `out/onyx-uefi-usb-v8/onyx-uefi-diagnostics-v8-probe.img`, SHA-256
`3c2a4d41f9560124e164844dd48ca6da4cbfcf1514c1d73370a48a2b7c19ca42`.

Rebuild USB diagnostics with `ONYX_USB_LOGS=1`, or the controller probe with
`ONYX_USB_PROBE=1`. `ONYX_UEFI_ARTIFACTS` selects a distinct output directory.
Supply `ONYX_REFERENCE_BOOT` to automatically package the corrected gzip profile.
Without that reference, the build leaves an `upstream-container.img` for inspection
and asks for explicit profile repacking; it is not a validated hardware candidate.

References:

- [Android generic boot architecture](https://source.android.com/docs/core/architecture/partitions/generic-boot)
- [ARM64 image header and boot protocol](https://docs.kernel.org/arch/arm64/booting.html)
- [Manufacturer-published Qualcomm loader reference source](https://github.com/SHIFTPHONES/android_bootable_bootloader_edk2/blob/sos-3.x/QcomModulePkg/Library/FastbootLib/FastbootCmds.c)
