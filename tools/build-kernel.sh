#!/bin/bash
# Linux/WSL build environment. No device commands or firmware writes.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${ONYX_BUILD_ROOT:-$HOME/ios-26-onyx-build}
BASE=$WORK/base
export XNU_SRC=$WORK/xnu12377
export XNU_ARCH=arm64e
export MACHINE=BCM2837
export RC_DARWIN_KERNEL_VERSION=12377.121.6
if [ -x "$WORK/llvm19/usr/lib/llvm-19/bin/clang" ]; then
    export ONYX_CLANG_ROOT=$WORK/llvm19/usr/lib/llvm-19/bin
    export PATH=$ONYX_CLANG_ROOT:$PATH
    export LD_LIBRARY_PATH="$WORK/llvm19/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [ ! -d "$XNU_SRC/.git" ]; then
    echo "First clone Apple xnu-12377.121.6 to $XNU_SRC and run tools/prepare-kernel.py against it." >&2
    exit 1
fi
if [ ! -f "$XNU_SRC/bsd/dev/onyx_touch.c" ]; then
    echo "The kernel lacks the Onyx overlay; run tools/prepare-kernel.py first." >&2
    exit 1
fi
if [ ! -e "$BASE" ]; then
    mkdir -p "$BASE"
    # Git archive reads LF-normalized blobs, avoiding Windows CRLF shell scripts.
    git -C "$ROOT/upstream/hakios-arm64e-dada" archive f1ae906fcc43ba8f763663257724ba938fb820ab base |
        tar -x --strip-components=1 -C "$BASE"
fi
for component in xnu-env.sh xnu-deps/host/bin/xnu-clang xnu-deps/setup.sh; do
    if git -C "$BASE" apply --include="$component" --check "$ROOT/patches/dada-linux-build.patch" 2>/dev/null; then
        git -C "$BASE" apply --include="$component" "$ROOT/patches/dada-linux-build.patch"
    elif ! git -C "$BASE" apply --include="$component" --reverse --check "$ROOT/patches/dada-linux-build.patch" 2>/dev/null; then
        echo "Linux build environment patch no longer matches: $component" >&2
        exit 1
    fi
done
cd "$BASE"
if [ "${1:-build}" != stage1 ]; then
    if git -C "$BASE/xnu-deps/libdispatch" apply --check "$ROOT/patches/firehose-xnu12377.patch" 2>/dev/null; then
        git -C "$BASE/xnu-deps/libdispatch" apply "$ROOT/patches/firehose-xnu12377.patch"
    elif ! git -C "$BASE/xnu-deps/libdispatch" apply --reverse --check "$ROOT/patches/firehose-xnu12377.patch" 2>/dev/null; then
        echo "Firehose compatibility patch no longer matches." >&2
        exit 1
    fi
fi
case "${1:-build}" in
    stage1) bash xnu-deps/setup.sh --stage1 ;;
    stage2) bash xnu-deps/setup.sh --stage2 ;;
    touch) python3 "$ROOT/tools/compile-touch.py" "$XNU_SRC" ;;
    build) bash xnu-build.sh -j"${JOBS:-8}" ;;
    *) echo "usage: $0 stage1|stage2|touch|build" >&2; exit 2 ;;
esac
