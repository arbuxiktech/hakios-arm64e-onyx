// SPDX-License-Identifier: BSD-2-Clause-Patent
// RAM-only diagnostic launch policy. Never enters the ordinary boot menu.
#include <Uefi.h>
#include <Pi/PiFirmwareFile.h>
#include <Library/BaseLib.h>
#include <Library/DevicePathLib.h>
#include <Library/DxeServicesLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PlatformBootManagerLib.h>
#include <Library/UefiBootManagerLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>
#include <Protocol/GraphicsOutput.h>

STATIC CONST EFI_GUID mDiagnosticsGuid =
  { 0x40cce213, 0x62e6, 0x4d71, { 0x86, 0xc1, 0xd6, 0x90, 0x91, 0x1e, 0x39, 0xb7 } };

STATIC VOID PrintMemorySummary (VOID)
{
  UINTN Size = 0;
  UINTN Capacity;
  UINTN Key;
  UINTN Stride = 0;
  UINTN Offset;
  UINT32 Version;
  EFI_MEMORY_DESCRIPTOR *Map;
  EFI_MEMORY_DESCRIPTOR *Entry;
  UINT64 FreePages = 0;
  EFI_STATUS Status;

  Status = gBS->GetMemoryMap (&Size, NULL, &Key, &Stride, &Version);
  if (Status != EFI_BUFFER_TOO_SMALL || Size > 1024 * 1024) {
    Print (L"Memory map size query failed: %r\r\n", Status);
    return;
  }
  Capacity = Size + 4096;
  Map = AllocatePool (Capacity);
  if (Map == NULL) {
    return;
  }
  Size = Capacity;
  Status = gBS->GetMemoryMap (&Size, Map, &Key, &Stride, &Version);
  if (!EFI_ERROR (Status) && Stride >= sizeof (*Map) && Size <= Capacity) {
    for (Offset = 0; Offset + Stride <= Size; Offset += Stride) {
      Entry = (EFI_MEMORY_DESCRIPTOR *)((UINT8 *)Map + Offset);
      if (Entry->Type == EfiConventionalMemory) {
        FreePages += Entry->NumberOfPages;
      }
    }
    Print (L"Live memory map: %u entries, %Lu MiB conventional RAM\r\n",
           (UINT32)(Size / Stride), FreePages / 256);
  } else {
    Print (L"Memory map read failed: %r\r\n", Status);
  }
  FreePool (Map);
}

VOID EFIAPI PlatformBootManagerBeforeConsole (VOID)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0;
  UINTN Index;
  EFI_DEVICE_PATH_PROTOCOL *Path;

  // The prepared FV excludes storage drivers. Connect its remaining devices.
  EfiBootManagerConnectAll ();
  if (!EFI_ERROR (gBS->LocateHandleBuffer (ByProtocol,
        &gEfiGraphicsOutputProtocolGuid, NULL, &Count, &Handles))) {
    for (Index = 0; Index < Count; Index++) {
      Path = DevicePathFromHandle (Handles[Index]);
      if (Path != NULL) {
        // Nv variables use upstream's emulated, RAM-backed variable store.
        EfiBootManagerUpdateConsoleVariable (ConOut, Path, NULL);
        EfiBootManagerUpdateConsoleVariable (ErrOut, Path, NULL);
      }
    }
    FreePool (Handles);
  }
}

VOID EFIAPI PlatformBootManagerAfterConsole (VOID)
{
  VOID *Buffer = NULL;
  UINTN Size = 0;
  EFI_HANDLE Image = NULL;
  EFI_STATUS Status;

  gBS->SetWatchdogTimer (0, 0, 0, NULL);
  Print (L"Onyx RAM diagnostics: Android storage drivers excluded.\r\n");
  PrintMemorySummary ();
  Status = GetSectionFromAnyFv (&mDiagnosticsGuid, EFI_SECTION_PE32, 0, &Buffer, &Size);
  if (!EFI_ERROR (Status)) {
    Status = gBS->LoadImage (FALSE, gImageHandle, NULL, Buffer, Size, &Image);
    FreePool (Buffer);
    if (!EFI_ERROR (Status)) {
      Status = gBS->StartImage (Image, NULL, NULL);
      gBS->UnloadImage (Image);
    }
  }
  Print (L"Diagnostics finished: %r. No OS selected. Hold power to restart.\r\n", Status);
  // Do not fall through into BDS boot selection, recovery or firmware updates.
  CpuDeadLoop ();
}

VOID EFIAPI PlatformBootManagerBdsEntry (VOID) {}
VOID EFIAPI PlatformBootManagerOnDemandConInConnect (VOID) {}
VOID EFIAPI PlatformBootManagerProcessBootCompletion (IN EFI_BOOT_MANAGER_LOAD_OPTION *BootOption) { (VOID)BootOption; }
VOID EFIAPI PlatformBootManagerPriorityBoot (UINT16 **BootNext) { (VOID)BootNext; }
VOID EFIAPI PlatformBootManagerWaitCallback (UINT16 TimeoutRemain) { (VOID)TimeoutRemain; }
VOID EFIAPI PlatformBootManagerUnableToBoot (VOID) { CpuDeadLoop (); }
VOID EFIAPI PlatformBootManagerDeadloop (VOID) { CpuDeadLoop (); }
