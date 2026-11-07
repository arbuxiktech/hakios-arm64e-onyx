// SPDX-License-Identifier: BSD-2-Clause-Patent
// An intentionally small read-only fastboot-style diagnostic endpoint.
// Transport uses the firmware protocol; there is no controller MMIO or BlockIO.
#include <Uefi.h>
#include <IndustryStandard/Usb.h>
#include <Protocol/UsbIo.h>
// The legacy Qualcomm extension header redeclares two modern Mu descriptors
// and enum values. Give those private declarations distinct names; protocol
// structures and function pointer layouts remain the vendor's declarations.
#define USB_BOS_DESCRIPTOR QCOM_LEGACY_USB_BOS_DESCRIPTOR
#define EFI_USB_BOS_DESCRIPTOR QCOM_LEGACY_EFI_USB_BOS_DESCRIPTOR
#define USB_INTERFACE_ASSOCIATION_DESCRIPTOR QCOM_LEGACY_USB_INTERFACE_ASSOCIATION_DESCRIPTOR
#define USB_DESC_TYPE_INTERFACE_ASSOCIATION QCOM_LEGACY_USB_DESC_TYPE_INTERFACE_ASSOCIATION
#define USB_DESC_TYPE_BOS QCOM_LEGACY_USB_DESC_TYPE_BOS
#include <Protocol/EFIUsbDevice.h>
#include <Protocol/EFIUsbfnIo.h>
#undef USB_BOS_DESCRIPTOR
#undef EFI_USB_BOS_DESCRIPTOR
#undef USB_INTERFACE_ASSOCIATION_DESCRIPTOR
#undef USB_DESC_TYPE_INTERFACE_ASSOCIATION
#undef USB_DESC_TYPE_BOS
#include <Protocol/GraphicsOutput.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PrintLib.h>
#include <Library/UefiApplicationEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiRuntimeServicesTableLib.h>
#include <Library/UefiLib.h>

#define RX_EP 0x01
#define TX_EP 0x81
#define BUFFER_SIZE 4096
#define LOG_ROWS 32
#define LOG_WIDTH 61
#define CONTROLLER_PROBE 0

STATIC EFI_USB_DEVICE_PROTOCOL *mUsb;
STATIC UINT8 *mRx;
STATIC UINT8 *mTx;
STATIC CHAR8 mLogs[LOG_ROWS][LOG_WIDTH];
STATIC UINTN mLogCount;
STATIC UINTN mNextLog;
STATIC BOOLEAN mSendingLogs;
STATIC BOOLEAN mRxQueued;
STATIC BOOLEAN mResetAfterTx;
STATIC EFI_GUID mInitUsbControllerGuid = {
  0x1c0cffce, 0xfc8d, 0x4e44, { 0x8c, 0x78, 0x9c, 0x9e, 0x5b, 0x53, 0x0d, 0x36 }
};

STATIC VOID EFIAPI UsbInitNotify (EFI_EVENT Event, VOID *Context)
{
  (VOID)Event;
  (VOID)Context;
}

STATIC EFI_USB_DEVICE_DESCRIPTOR mDevice = {
  18, 1, 0x0210, 0, 0, 0, 64, 0x18d1, 0xd00d, 0x0100, 1, 2, 3, 1
};
STATIC EFI_USB_DEVICE_DESCRIPTOR mSuperSpeedDevice = {
  18, 1, 0x0300, 0, 0, 0, 9, 0x18d1, 0xd00d, 0x0100, 1, 2, 3, 1
};
STATIC EFI_USB_DEVICE_QUALIFIER_DESCRIPTOR mQualifier = {
  10, 6, 0x0200, 0, 0, 0, 64, 1, 0
};
#pragma pack(1)
STATIC struct {
  EFI_USB_CONFIG_DESCRIPTOR Config;
  EFI_USB_INTERFACE_DESCRIPTOR Interface;
  EFI_USB_ENDPOINT_DESCRIPTOR In;
  EFI_USB_ENDPOINT_DESCRIPTOR Out;
} mConfig = {
  { 9, 2, 32, 1, 1, 0, 0x80, 0x10 },
  { 9, 4, 0, 0, 2, 0xff, 0x42, 0x03, 0 },
  { 7, 5, TX_EP, 2, 512, 0 },
  { 7, 5, RX_EP, 2, 512, 0 }
};
STATIC struct {
  EFI_USB_CONFIG_DESCRIPTOR Config;
  EFI_USB_INTERFACE_DESCRIPTOR Interface;
  EFI_USB_ENDPOINT_DESCRIPTOR In;
  EFI_USB_SS_ENDPOINT_COMPANION_DESCRIPTOR InCompanion;
  EFI_USB_ENDPOINT_DESCRIPTOR Out;
  EFI_USB_SS_ENDPOINT_COMPANION_DESCRIPTOR OutCompanion;
} mSuperSpeedConfig = {
  { 9, 2, 44, 1, 1, 0, 0x80, 0x10 },
  { 9, 4, 0, 0, 2, 0xff, 0x42, 0x03, 0 },
  { 7, 5, TX_EP, 2, 1024, 0 },
  { 6, 0x30, 0, 0, 0 },
  { 7, 5, RX_EP, 2, 1024, 0 },
  { 6, 0x30, 0, 0, 0 }
};
STATIC struct { UINT8 Length; UINT8 Type; UINT16 Language; } mLanguage = { 4, 3, 0x0409 };
STATIC struct { UINT8 Length; UINT8 Type; CHAR16 Text[4]; } mManufacturer = { 10, 3, L"Onyx" };
STATIC struct { UINT8 Length; UINT8 Type; CHAR16 Text[16]; } mProduct = { 34, 3, L"Onyx diagnostics" };
STATIC struct { UINT8 Length; UINT8 Type; CHAR16 Text[12]; } mSerial = { 26, 3, L"ONYXDIAG0001" };
#pragma pack()
STATIC VOID *mConfigs[] = { &mConfig };
STATIC VOID *mSuperSpeedConfigs[] = { &mSuperSpeedConfig };
STATIC UINT8 mBos[] = {
  5, 0x0f, 22, 0, 2,
  7, 0x10, 2, 2, 0, 0, 0,
  10, 0x10, 3, 0, 0x0e, 0, 1, 10, 0xff, 7
};
STATIC EFI_USB_STRING_DESCRIPTOR *mStrings[] = {
  (VOID *)&mLanguage, (VOID *)&mManufacturer, (VOID *)&mProduct, (VOID *)&mSerial
};
STATIC USB_DEVICE_DESCRIPTOR_SET mDescriptorSet = {
  &mDevice, mConfigs, &mSuperSpeedDevice, mSuperSpeedConfigs,
  &mQualifier, mBos, ARRAY_SIZE (mStrings), mStrings
};
STATIC_ASSERT (sizeof (mConfig) == 32, "USB2 descriptor layout");
STATIC_ASSERT (sizeof (mSuperSpeedConfig) == 44, "USB3 descriptor layout");

STATIC VOID LogValue (CONST CHAR8 *Name, UINT64 Value)
{
  if (mLogCount < LOG_ROWS) {
    AsciiSPrint (mLogs[mLogCount++], LOG_WIDTH, "%a=0x%Lx", Name, Value);
  }
}

STATIC VOID CollectLogs (VOID)
{
  UINT64 Value;
  EFI_STATUS Status;
  EFI_GRAPHICS_OUTPUT_PROTOCOL *Gop = NULL;
  EFI_MEMORY_DESCRIPTOR *Map;
  EFI_MEMORY_DESCRIPTOR *Entry;
  UINTN Size = 0, Capacity, Key, Stride = 0, Offset;
  UINT32 Version;
  UINT64 FreePages = 0;

  AsciiSPrint (mLogs[mLogCount++], LOG_WIDTH, "stage=onyx-uefi-usb-diagnostics-v1");
  AsciiSPrint (mLogs[mLogCount++], LOG_WIDTH, "xnu_started=no; storage_commands=disabled");
#define LOG_REGISTER(Name) do { \
  __asm__ volatile ("mrs %0, " #Name : "=r" (Value)); \
  LogValue (#Name, Value); \
} while (0)
  LOG_REGISTER (CurrentEL);
  LOG_REGISTER (MIDR_EL1);
  LOG_REGISTER (MPIDR_EL1);
  LOG_REGISTER (ID_AA64ISAR1_EL1);
  LOG_REGISTER (ID_AA64ISAR2_EL1);
  LOG_REGISTER (ID_AA64PFR0_EL1);
  LOG_REGISTER (ID_AA64MMFR0_EL1);
  LOG_REGISTER (CNTFRQ_EL0);
#undef LOG_REGISTER
  Status = gBS->LocateProtocol (&gEfiGraphicsOutputProtocolGuid, NULL, (VOID **)&Gop);
  LogValue ("gop_status", Status);
  if (!EFI_ERROR (Status) && Gop != NULL && Gop->Mode != NULL && Gop->Mode->Info != NULL) {
    LogValue ("display_width", Gop->Mode->Info->HorizontalResolution);
    LogValue ("display_height", Gop->Mode->Info->VerticalResolution);
    LogValue ("display_stride_pixels", Gop->Mode->Info->PixelsPerScanLine);
    LogValue ("display_pixel_format", Gop->Mode->Info->PixelFormat);
    LogValue ("framebuffer_base", Gop->Mode->FrameBufferBase);
    LogValue ("framebuffer_bytes", Gop->Mode->FrameBufferSize);
  }
  Status = gBS->GetMemoryMap (&Size, NULL, &Key, &Stride, &Version);
  if (Status == EFI_BUFFER_TOO_SMALL && Size < 1024 * 1024) {
    Capacity = Size + 4096;
    Map = AllocatePool (Capacity);
    if (Map != NULL) {
      Size = Capacity;
      Status = gBS->GetMemoryMap (&Size, Map, &Key, &Stride, &Version);
      LogValue ("memory_map_status", Status);
      if (!EFI_ERROR (Status) && Stride >= sizeof (*Map) && Size <= Capacity) {
        LogValue ("memory_map_entries", Size / Stride);
        for (Offset = 0; Offset + Stride <= Size; Offset += Stride) {
          Entry = (VOID *)((UINT8 *)Map + Offset);
          if (Entry->Type == EfiConventionalMemory) {
            FreePages += Entry->NumberOfPages;
          }
        }
        LogValue ("conventional_ram_mib", FreePages / 256);
      }
      FreePool (Map);
    }
  }
}

STATIC EFI_STATUS QueueRx (VOID)
{
  EFI_STATUS Status;
  if (mRxQueued) {
    return EFI_SUCCESS;
  }
  Status = mUsb->Send (RX_EP, BUFFER_SIZE - 1, mRx);
  mRxQueued = !EFI_ERROR (Status);
  return Status;
}

STATIC EFI_STATUS Reply (CONST CHAR8 *Code, CONST CHAR8 *Text)
{
  UINTN Length;
  // Fastboot responses have a four-byte code and at most 60 payload bytes.
  Length = AsciiSPrint ((CHAR8 *)mTx, 65, "%a%a", Code, Text);
  if (Length > 64) {
    return EFI_BAD_BUFFER_SIZE;
  }
  return mUsb->Send (TX_EP, Length, mTx);
}

STATIC EFI_STATUS NextLog (VOID)
{
  if (mNextLog < mLogCount) {
    return Reply ("INFO", mLogs[mNextLog++]);
  }
  mSendingLogs = FALSE;
  return Reply ("OKAY", "");
}

STATIC EFI_STATUS Command (UINTN Length)
{
  if (Length == 0 || Length >= BUFFER_SIZE || Length > 64 ||
      ScanMem8 (mRx, Length, 0) != NULL) {
    return Reply ("FAIL", "invalid diagnostic command");
  }
  mRx[Length] = 0;
  if (AsciiStrCmp ((CHAR8 *)mRx, "getvar:product") == 0) {
    return Reply ("OKAY", "onyx-diag");
  }
  if (AsciiStrCmp ((CHAR8 *)mRx, "getvar:serialno") == 0) {
    return Reply ("OKAY", "ONYXDIAG0001");
  }
  if (AsciiStrCmp ((CHAR8 *)mRx, "getvar:version") == 0) {
    return Reply ("OKAY", "0.4");
  }
  if (AsciiStrCmp ((CHAR8 *)mRx, "getvar:all") == 0 ||
      AsciiStrCmp ((CHAR8 *)mRx, "getvar:onyx-diag") == 0) {
    mNextLog = 0;
    mSendingLogs = TRUE;
    return NextLog ();
  }
  if (AsciiStrCmp ((CHAR8 *)mRx, "reboot") == 0) {
    mResetAfterTx = TRUE;
    return Reply ("OKAY", "");
  }
  // No download, boot, flash, erase, OEM, slot, or memory-access command exists.
  return Reply ("FAIL", "read-only diagnostics; command disabled");
}

EFI_STATUS EFIAPI DiagnosticsEntry (EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)
{
  EFI_STATUS Status;
  USB_DEVICE_EVENT Event;
  USB_DEVICE_EVENT_DATA Data;
  UINTN DataSize;
  UINTN Index;
  EFI_EVENT InitEvent;
  (VOID)ImageHandle;
  (VOID)SystemTable;

  gBS->SetWatchdogTimer (0, 0, 0, NULL);
  Print (L"Onyx USB diagnostic application entered.\r\n");
  CollectLogs ();
  for (Index = 0; Index < mLogCount; Index++) {
    Print (L"%a\r\n", mLogs[Index]);
  }
  Print (L"USB: signaling controller initialization.\r\n");
  Status = gBS->CreateEventEx (EVT_NOTIFY_SIGNAL, TPL_CALLBACK, UsbInitNotify,
                             NULL, &mInitUsbControllerGuid, &InitEvent);
  if (EFI_ERROR (Status)) {
    Print (L"USB init event failed: %r\r\n", Status);
    return Status;
  }
  gBS->SignalEvent (InitEvent);
  gBS->CloseEvent (InitEvent);
  Status = gBS->LocateProtocol (&gEfiUsbDeviceProtocolGuid, NULL, (VOID **)&mUsb);
  if (EFI_ERROR (Status)) {
    Print (L"USB device protocol unavailable: %r\r\n", Status);
    return Status;
  }
  if (CONTROLLER_PROBE) {
    EFI_USBFN_IO_PROTOCOL *Fn = NULL;
    Status = gBS->LocateProtocol (&gEfiUsbfnIoProtocolGuid, NULL, (VOID **)&Fn);
    Print (L"USB P0: function protocol = %r\r\n", Status);
    if (EFI_ERROR (Status)) {
      return Status;
    }
    Print (L"USB P1: StopController begin\r\n");
    Status = Fn->StopController (Fn);
    Print (L"USB P1: StopController returned %r\r\n", Status);
    if (EFI_ERROR (Status)) {
      return Status;
    }
    Print (L"USB P2: StartController begin\r\n");
    Status = Fn->StartController (Fn);
    Print (L"USB P2: StartController returned %r\r\n", Status);
    Print (L"USB P3: controller probe finished; no enumeration attempted\r\n");
    return Status;
  }
  Print (L"Starting read-only USB diagnostics: ONYXDIAG0001\r\n");
  Status = mUsb->StartEx (&mDescriptorSet);
  if (EFI_ERROR (Status)) {
    Print (L"USB start failed: %r\r\n", Status);
    return Status;
  }
  // Qualcomm's transport initializes its underlying UsbfnIo during Start.
  Status = mUsb->AllocateTransferBuffer (BUFFER_SIZE, (VOID **)&mRx);
  if (EFI_ERROR (Status)) {
    Print (L"USB RX allocation failed: %r\r\n", Status);
    mUsb->Stop ();
    return Status;
  }
  Status = mUsb->AllocateTransferBuffer (BUFFER_SIZE, (VOID **)&mTx);
  if (EFI_ERROR (Status)) {
    Print (L"USB TX allocation failed: %r\r\n", Status);
    mUsb->FreeTransferBuffer (mRx);
    mUsb->Stop ();
    return Status;
  }
  while (TRUE) {
    DataSize = sizeof (Data);
    Status = mUsb->HandleEvent (&Event, &DataSize, &Data);
    if (EFI_ERROR (Status)) {
      gBS->Stall (1000);
      continue;
    }
    if (Event == UsbDeviceEventDeviceStateChange) {
      if (Data.DeviceState == UsbDeviceStateConnected) {
        QueueRx ();
      } else {
        mRxQueued = FALSE;
        mSendingLogs = FALSE;
        mResetAfterTx = FALSE;
      }
    } else if (Event == UsbDeviceEventTransferNotification &&
               Data.TransferOutcome.Status == UsbDeviceTransferStatusCompleteOK) {
      if (Data.TransferOutcome.EndpointIndex == RX_EP && Data.TransferOutcome.DataBuffer == mRx) {
        mRxQueued = FALSE;
        Status = Command (Data.TransferOutcome.BytesCompleted);
        if (EFI_ERROR (Status)) {
          mSendingLogs = FALSE;
          mResetAfterTx = FALSE;
          QueueRx ();
        }
      } else if (Data.TransferOutcome.EndpointIndex == TX_EP && Data.TransferOutcome.DataBuffer == mTx) {
        if (mResetAfterTx) {
          mUsb->Stop ();
          gRT->ResetSystem (EfiResetCold, EFI_SUCCESS, 0, NULL);
          CpuDeadLoop ();
        } else if (mSendingLogs) {
          NextLog ();
        } else {
          QueueRx ();
        }
      }
    }
  }
}
