#!/bin/bash
# Extract Ubuntu's Clang 19 packages into the private build directory; no sudo.
set -euo pipefail
WORK=${ONYX_BUILD_ROOT:-$HOME/ios-26-onyx-build}
LLVM=$WORK/llvm19
mkdir -p "$LLVM/packages"
cd "$LLVM/packages"
apt-get download clang-19 libclang-cpp19 libllvm19 libclang-common-19-dev libclang1-19
for package in ./*.deb; do
    dpkg-deb -x "$package" "$LLVM"
done
LD_LIBRARY_PATH="$LLVM/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$LLVM/usr/lib/llvm-19/bin/clang" --version
