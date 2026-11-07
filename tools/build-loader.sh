#!/bin/bash
# Build only a diagnostics EFI; does not contact a phone or package a flash image.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
python3 "$ROOT/tools/prepare-loader.py"
cd "$ROOT/out/onyx-loader"
clang --target=aarch64-unknown-windows -ffreestanding -fno-builtin \
  -fno-stack-protector -fshort-wchar -mgeneral-regs-only -O1 -Wall -Wextra \
  -Wno-unused-parameter -DONYX_PORT=1 -DPAYLOAD_BASE=0xA8000000ULL \
  -DPAYLOAD_MAX_SIZE=0x10000000ULL -c loader.c -o loader-onyx-diagnostics.obj
lld-link /subsystem:efi_application /entry:efi_main /nodefaultlib \
  /base:0xA1000000 /out:loader-onyx-diagnostics.efi loader-onyx-diagnostics.obj
echo "Built $PWD/loader-onyx-diagnostics.efi (diagnostics only; not an Android boot image)"
