#!/bin/bash
# Pinned official 7-Zip binary, kept in the private build folder.
set -euo pipefail
WORK=${ONYX_BUILD_ROOT:-$HOME/ios-26-onyx-build}
DEST=$WORK/7zip-26.06
mkdir -p "$DEST"
curl --fail --location --output "$DEST/7z2606-linux-x64.tar.xz" \
    https://github.com/ip7z/7zip/releases/download/26.06/7z2606-linux-x64.tar.xz
tar -xJf "$DEST/7z2606-linux-x64.tar.xz" -C "$DEST"
"$DEST/7zz" i | head -6
