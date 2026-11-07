#!/bin/bash
# Local IPSW extraction only; no device commands. Requires ipsw and 7-Zip 23+.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
IPSW=${1:?usage: extract-ios26.sh /path/to/iPhone18,1_26.6.2_23G90_Restore.ipsw}
WORK=${ONYX_BUILD_ROOT:-$HOME/ios-26-onyx-build}
IOS=$WORK/ios26
CACHE=$IOS/23G90__iPhone18,1
if [ -x "$WORK/7zip-26.06/7zz" ]; then export SEVEN_ZIP=$WORK/7zip-26.06/7zz; fi
python3 "$ROOT/tools/check-ipsw.py" "$IPSW" > /dev/null
mkdir -p "$IOS"
for kind in fs sys; do
    if [ "$kind" = fs ]; then member=094-95416-090; destination=rootfs; else member=094-97238-092; destination=cryptex; fi
    if [ ! -f "$CACHE/$member.dmg.aea" ]; then
        ipsw extract --dmg "$kind" --device iPhone18,1 --output "$IOS" "$IPSW"
    fi
    if [ ! -f "$CACHE/$member.dmg" ]; then
        ipsw fw aea --output "$CACHE" "$CACHE/$member.dmg.aea"
    fi
    fallback=()
    if [ "$kind" = sys ]; then
        DKCACHE=$IOS/driverkit-cache/23G90__iPhone18,1
        if [ ! -f "$DKCACHE/dyld_shared_cache_arm64e.symbols" ]; then
            ipsw extract --dyld --driverkit --dyld-arch arm64e --device iPhone18,1 --output "$IOS/driverkit-cache" "$IPSW"
        fi
        fallback=(--driverkit-cache "$DKCACHE")
    fi
    if [ ! -e "$IOS/$destination" ]; then
        if ! python3 "$ROOT/tools/safe-unpack-dmg.py" "$CACHE/$member.dmg" "$IOS/$destination" "${fallback[@]}"; then
            if [ "$kind" = sys ]; then
                python3 "$ROOT/tools/repair-ios26-systemos.py" "$IPSW" "$IOS"
            else
                exit 1
            fi
        fi
    elif [ ! -f "$IOS/$destination/.onyx-extraction-complete" ]; then
        if [ "$kind" = sys ] && [ -f "$IOS/$destination/.onyx-sevenzip-result.json" ]; then
            python3 "$ROOT/tools/repair-ios26-systemos.py" "$IPSW" "$IOS"
        else
            echo "Incomplete existing $IOS/$destination; inspect it before retrying." >&2
            exit 1
        fi
    fi
done
if [ ! -f "$CACHE/dyld_shared_cache_arm64e" ]; then
    ipsw extract --dyld --dyld-arch arm64e --device iPhone18,1 --output "$IOS" "$IPSW"
fi
echo "Extracted local system/cryptex and arm64e caches in $IOS. Image assembly remains separate."
