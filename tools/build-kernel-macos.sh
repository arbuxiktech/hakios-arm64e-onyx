#!/bin/bash
# Run on a macOS/Xcode CI host. Produces artifacts only; no device access.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${ONYX_BUILD_ROOT:-$HOME/ios-26-onyx-build-macos}
BASE=$WORK/base
ARTIFACTS=$ROOT/out/macos-ci
export XNU_SRC=$WORK/xnu12377
export XNU_ARCH=arm64e MACHINE=BCM2837 RC_DARWIN_KERNEL_VERSION=12377.121.6
if [ "$(uname -s)" != Darwin ]; then
    echo 'This build needs a macOS host with Xcode.' >&2
    exit 1
fi
export DEVELOPER_DIR=${DEVELOPER_DIR:-$(xcode-select -p)}
export XNU_SDK_VERSION=$(/usr/bin/xcrun --sdk iphoneos --show-sdk-version)
test -x "$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/iig"
test -f "$XNU_SRC/bsd/dev/onyx_touch.c"
mkdir -p "$ARTIFACTS"
if [ ! -e "$BASE" ]; then
    mkdir -p "$BASE"
    git -C "$ROOT/upstream/hakios-arm64e-dada" archive f1ae906fcc43ba8f763663257724ba938fb820ab base |
        tar -x --strip-components=1 -C "$BASE"
fi
if git -C "$BASE" apply --check "$ROOT/patches/dada-macos-build.patch" 2>/dev/null; then
    git -C "$BASE" apply "$ROOT/patches/dada-macos-build.patch"
elif ! git -C "$BASE" apply --reverse --check "$ROOT/patches/dada-macos-build.patch" 2>/dev/null; then
    echo 'macOS build environment patch no longer matches.' >&2
    exit 1
fi
export PATH="$(brew --prefix bison)/bin:$(brew --prefix flex)/bin:$PATH"
cd "$BASE"
bash xnu-deps/setup.sh --stage1 2>&1 | tee "$ARTIFACTS/setup-stage1.log"
if git -C "$BASE/xnu-deps/libdispatch" apply --check "$ROOT/patches/firehose-xnu12377.patch" 2>/dev/null; then
    git -C "$BASE/xnu-deps/libdispatch" apply "$ROOT/patches/firehose-xnu12377.patch"
elif ! git -C "$BASE/xnu-deps/libdispatch" apply --reverse --check "$ROOT/patches/firehose-xnu12377.patch" 2>/dev/null; then
    echo 'Firehose compatibility patch no longer matches.' >&2
    exit 1
fi
bash xnu-deps/setup.sh --stage2 2>&1 | tee "$ARTIFACTS/setup-stage2.log"
bash xnu-build.sh -j"${JOBS:-3}" 2>&1 | tee "$ARTIFACTS/kernel-build.log"
kernel=$(find "$XNU_SRC/BUILD/obj" -type f -name mach.development.bcm2837 -print -quit)
test -n "$kernel" && test -s "$kernel"
python3 "$ROOT/tools/verify-kernel.py" "$kernel" --output "$ARTIFACTS/kernel-verification.json"
strings -a "$kernel" | grep -F 'iOS26 passive build' > "$ARTIFACTS/onyx-diagnostic-string.txt"
cp "$kernel" "$ARTIFACTS/mach.development.bcm2837"
shasum -a 256 "$ARTIFACTS/mach.development.bcm2837" > "$ARTIFACTS/kernel.sha256"
