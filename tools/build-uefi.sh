#!/bin/bash
# Local host build only. This script never invokes adb, fastboot or a device writer.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${ONYX_BUILD_ROOT:-/home/arbuxik/ios-26-onyx-build}
TREE=$WORK/mu-silicium
ARTIFACTS=${ONYX_UEFI_ARTIFACTS:-$ROOT/out/onyx-uefi}
export PATH="$WORK/mu-venv/bin:$PATH"
export CLANGPDB_AARCH64_PREFIX=aarch64-linux-gnu-
mkdir -p "$ARTIFACTS"
test -x "$WORK/mu-venv/bin/python"
test -d "$TREE/Mu_Basecore/MdePkg"
prepare_args=()
if [ "${ONYX_USB_LOGS:-0}" = 1 ]; then
    prepare_args+=(--usb-logs)
fi
if [ "${ONYX_USB_PROBE:-0}" = 1 ]; then
    prepare_args+=(--usb-probe)
fi
python "$ROOT/tools/prepare-uefi.py" "$TREE" "${prepare_args[@]}" > "$ARTIFACTS/preparation.log"
cp "$ROOT/out/onyx-uefi/preparation.json" "$ARTIFACTS/preparation-record.json"
cd "$TREE"
python Platforms/Xiaomi/onyxPkg/DeviceBuild.py --setup -t RELEASE 2>&1 | tee "$ARTIFACTS/setup.log"
python Platforms/Xiaomi/onyxPkg/DeviceBuild.py --update -t RELEASE 2>&1 | tee "$ARTIFACTS/update.log"
python build_uefi.py -d onyx 2>&1 | tee "$ARTIFACTS/build.log"
python "$ROOT/tools/verify-uefi.py" "$TREE" "$TREE/Mu-onyx.img" --output "$ARTIFACTS/verification.json"
cp "$TREE/Mu-onyx.img" "$ARTIFACTS/upstream-container.img"
if [ -n "${ONYX_REFERENCE_BOOT:-}" ]; then
    python "$ROOT/tools/repack-uefi.py" --tree "$TREE" --reference-boot "$ONYX_REFERENCE_BOOT" \
        --compression gzip --output "$ARTIFACTS/onyx-uefi-diagnostics-profile.img"
    sha256sum "$ARTIFACTS/onyx-uefi-diagnostics-profile.img" > "$ARTIFACTS/image.sha256"
else
    echo 'Built upstream container only. Use repack-uefi.py with the matching Android boot profile before a trial.'
fi
