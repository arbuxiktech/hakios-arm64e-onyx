# iOS 26 bring-up on POCO F7 / Onyx

Scope: boot, framebuffer and touch first; sound and other peripherals later.
**This is an incomplete port, not a flashable ROM. iOS and touch have not booted on this phone.**

## Hardware confirmed so far

The connected device identifies its vendor device as `onyx` and SoC as `SM8735`.
The CPU reports `paca` and `pacg`. Android model/fingerprint and lock-state properties
are spoofed by the installed ROM and are not evidence of the physical model or unlock state.

POCO F7 uses Snapdragon **8s Gen 4**, not the 8 Elite used by Xiaomi 15 / Dada.
Project Silicium already supplies an Onyx platform. Its published status lists display,
storage and USB device mode, but does not claim Linux or Windows boot.

The phone's active input is `NVTCapacitiveTouchScreen`; `spi4.0` binds to `NVT-ts`,
and `nt38771_touch.ko` is installed. Xiaomi's stock Onyx device tree identifies
Novatek SPI touch on SE4, 19.2 MHz, IRQ GPIO78. The reset-GPIO entry is commented
out: GPIO14 must not be toggled without further evidence. Panel variants include CSOT and TM.

The live touch configuration enables host processing of raw frames, with 18 x 39
sensor nodes and 100x coordinate resolution. The input device is virtual. Replacing
Dada's Synaptics register addresses will not provide this touch stack. NT38771
firmware initialization, SPI transport and frame-to-contact processing still need
implementation or a verified controller mode that reports contacts directly.

## What is implemented

- Pinned source checkouts under `upstream/`; origins and commits in `sources.lock.json`.
- Onyx board facts in `devices/onyx.json`, separating unknown values from evidence.
- Reproducible HakiOS loader patch with explicit Onyx selection. Dada and Onyx share
  framebuffer address `0xFC800000`, so framebuffer-only selection is ambiguous.
- Onyx GIC addresses `0x17100000` / `0x17180000`, with `0x40000` redistributor stride.
- Diagnostics EFI entry that prints CPU/GOP information and returns to UEFI before
  kernel handoff, block operations, exception hooks or watchdog SMC calls.
- Three upstream EFI BlockIO write calls replaced by an access-denied function;
  persistent `logdump` logging disabled in the prepared source.
- Read-only, serial-selected ADB inventory that works with spoofed ROM properties.
- Local IPSW BuildManifest inspection.
- Stock vendor_boot/DTBO inspection and bounded FDT parsing; the supplied stock
  images confirm the GIC/CPU/SPI values. See `docs/bringup-2026-11-07.md`.
- XNU 12377 source preparation with an Onyx passive touch object that compiles
  against generated kernel headers. Legacy transport code is retained behind
  compile-time exclusions and cannot be activated with boot arguments.
- Private WSL Clang 19 build environment, support-library compatibility patches,
  and local iOS 26 extraction tools.
- A linked arm64e XNU kernel built with Xcode 26.6 on GitHub Actions. The downloaded
  artifact passed the local architecture and SHA-256 checks. Touch is passive;
  Dada Wi-Fi/WLAN/Bluetooth transport is excluded from this initial build.
- An Onyx Mu-Silicium diagnostic boot container with the EFI checker embedded
  in RAM and selected storage/update modules excluded. The host build and package
  checks pass. A revised gzip container reached visible UEFI diagnostics, and
  the diagnostic application reached USB startup. USB log capture is still in
  bring-up; see [diagnostic firmware](docs/onyx-uefi-diagnostics.md). The first
  container was rejected and must not be retried.

Build from Windows using the installed WSL distribution:

```powershell
wsl -d Ubuntu-24.04 -- bash /mnt/c/path/to/ios-26-onyx/tools/build-loader.sh
python tools/collect-device.py
python -m unittest discover -s tests -v
```

Output: `out/onyx-loader/loader-onyx-diagnostics.efi`. This is an AArch64 EFI
application, **not** an Android `boot.img`; do not pass it to fastboot as a boot image.
The build does not package or start firmware on the phone. The application has
been cross-compiled and linked, but has not run on hardware.

## iOS input files

The Dada launcher `base/tools/dada-ios.sh` explicitly references `23G90__iPhone18,1`.
Use **iOS 26.6.2, build 23G90, iPhone 17 Pro (`iPhone18,1`)** as the initial userland
candidate to reproduce that fork. The kernel patch is based on Apple tag
`xnu-12377.121.6`. These facts do not establish that this exact stock IPSW kernel
matches that source tag, nor guarantee ABI compatibility on Onyx.

Neither checkout includes an iOS 26 downloader. Old READMEs mention a 16.5 fetcher;
the current common repository has a local-IPSW unpacker hardcoded for iOS 16.5.
Do not run that unpacker on an iOS 26 image by merely overriding its size check.
The Dada build references `ios26/fetch.sh`, which is absent from this checkout.

With a locally acquired IPSW:

```powershell
python tools/check-ipsw.py C:\path\iPhone18,1_26.6.2_23G90_Restore.ipsw
```

This reads the manifest and component paths; it does not download, decrypt,
authenticate, extract the full filesystem or flash anything. Firmware and system
images remain local inputs and must not be committed.

The supplied `iPhone18,1_26.6.2_23G90_Restore.ipsw` passes this identity check.
Its root filesystem, SystemOS filesystem and arm64e dyld caches are now local
under `/home/arbuxik/ios-26-onyx-build/ios26` in WSL. The 1597 SystemOS files that
7-Zip could not decode were recovered with `ipsw` and checked against archive
size metadata. Image assembly and hardware boot validation remain separate.

## GitHub Actions build

A manual macOS/Xcode kernel workflow is prepared in
`.github/workflows/build-onyx-ios26.yml`; see [the CI instructions](docs/github-actions.md).
It requires the real IIG generator and validates the linked arm64e artifact.
The [first successful build](https://github.com/arbuxiktech/hakios-arm64e-onyx/actions/runs/42397012052)
produced a linked kernel at commit `92220b24cb53a2b1ae021900e222847a8576e300`.
This artifact is not a flashable image or evidence of an Onyx hardware boot.

## Preserve Android

**Do not flash an iOS/APFS image to `userdata`.** On this phone `userdata` maps to
`sda34` and `metadata` to `sda17`. Those are observations, not install targets.
Android reports both file and metadata encryption. The upstream userdata carving
tool describes a different, unencrypted layout and is not suitable as an Onyx recipe.

Initial boot work should use RAM and a model-verified temporary UEFI boot image.
No persistent boot selector, slot switch, boot-partition replacement, filesystem
resize or GPT modification is implemented here. Keeping Android as the default
and launching a temporary UEFI image is the intended first dual-boot workflow;
it is not yet verified on this device.

For later storage, an Android-managed DSU allocation is a candidate because the
Dada loader supports DSU extents. Allocation, encryption behavior, extent stability,
image size, slot identity and all write paths must be verified on this ROM first.
The upstream DSU installer and raw `oem dsu patch` writer are not authorized install
instructions for this port. No zero-risk preservation guarantee is possible for
experimental firmware. A host-side write barrier cannot constrain firmware or
an independently running kernel's native storage driver.

## Remaining bring-up

1. Verify actual bootloader unlock state independently of spoofed Android properties
   and obtain a recoverable backup. Stock boot/vendor_boot/dtbo inputs have been
   supplied and inspected; they are not a backup of the currently installed OxygenOS port.
2. Validate the built Onyx Mu-Silicium diagnostic payload on hardware: review
   firmware behavior and check GOP, live memory map and CPU feature registers.
3. Package the linked XNU 12377 arm64e kernel with a tiny RAM-only PID1 image. Verify
   interrupts, timer, page tables, PAC and return-to-loader before full userland.
4. Adapt iOS 26 extraction/image assembly using the selected IPSW, then validate
   launchd and framebuffer rendering with storage writes disabled.
5. Implement and validate NT38771 transport and contact processing; connect its
   events to HakiOS input. Confirm press, move, release, bounds and multitouch.
6. Only after these milestones, validate persistent storage and a boot selector.

## Sources and licensing

- [Dada iOS 26 port](https://github.com/superboyyy/hakios-arm64e-dada)
- [HakiOS common source](https://github.com/oosexgang/hakios-xnu-kernel)
- [Project Silicium](https://github.com/Project-Silicium/Mu-Silicium)
- [Official Onyx device tree](https://github.com/MiCode/kernel_devicetree/tree/onyx-v-oss)
- [Onyx reference port](https://github.com/Aymon-njz/hackios-xnu-kernel-Onyx)
- [POCO specifications](https://www.po.co/global/product/poco-f7/specs/)
- [Apple release listing](https://developer.apple.com/news/releases/?id=07072025c)

Upstream licenses and notices remain in their source trees. The loader patch
modifies HakiOS source and must retain its applicable upstream licensing and attribution.
No Apple or phone firmware binaries are redistributed by this project.
