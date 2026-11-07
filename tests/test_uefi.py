import importlib.util
from pathlib import Path
import struct
import unittest
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_uefi", ROOT / "tools/verify-uefi.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
preflight_spec = importlib.util.spec_from_file_location("fastboot_preflight", ROOT / "tools/fastboot-preflight.py")
preflight = importlib.util.module_from_spec(preflight_spec)
preflight_spec.loader.exec_module(preflight)
repack_spec = importlib.util.spec_from_file_location("repack_uefi", ROOT / "tools/repack-uefi.py")
repack = importlib.util.module_from_spec(repack_spec)
repack_spec.loader.exec_module(repack)
usb_spec = importlib.util.spec_from_file_location("read_usb", ROOT / "tools/read-usb-diagnostics.py")
read_usb = importlib.util.module_from_spec(usb_spec)
usb_spec.loader.exec_module(read_usb)


class UsbLogTests(unittest.TestCase):
    def log(self):
        rows = ["stage=onyx-uefi-usb-diagnostics-v1"]
        rows.extend(name + "=0x123" for name in
                    ("CurrentEL", "MIDR_EL1", "MPIDR_EL1", "ID_AA64ISAR1_EL1", "CNTFRQ_EL0"))
        return "\n".join("(bootloader) " + row for row in rows)

    def test_accepts_complete_firmware_register_log(self):
        self.assertEqual(read_usb.parse(self.log())["CurrentEL"], "0x123")

    def test_rejects_bootloader_output_or_partial_log(self):
        with self.assertRaisesRegex(ValueError, "stage"):
            read_usb.parse("product: onyx\nFinished. Total time: 0.005s")
        with self.assertRaisesRegex(ValueError, "register"):
            read_usb.parse("(bootloader) stage=onyx-uefi-usb-diagnostics-v1")

    def test_rejects_duplicate_or_oversized_register(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            read_usb.parse(self.log() + "\n(bootloader) CurrentEL=0x4")
        with self.assertRaisesRegex(ValueError, "register"):
            read_usb.parse(self.log().replace("CurrentEL=0x123", "CurrentEL=0x" + "f" * 17))


class RawPackagingTests(unittest.TestCase):
    def reference(self):
        data = bytearray(8192)
        data[:8] = b"ANDROID!"
        struct.pack_into("<I", data, 8, 16)
        struct.pack_into("<I", data, 16, 0x200001a5)
        struct.pack_into("<I", data, 20, 1584)
        struct.pack_into("<I", data, 40, 4)
        data[4096:] = b"X" * 4096
        return data

    def test_size_covers_shim_and_firmware_without_copying_reference_kernel(self):
        header = repack.reference_header(self.reference())
        shim = bytearray(112)
        shim[56:60] = b"ARM\x64"
        firmware = b"F" * 32
        dtb = bytearray(40)
        dtb[:4] = bytes.fromhex("d00dfeed")
        struct.pack_into(">I", dtb, 4, 40)
        image, adjusted, size = repack.pack(header, bytes(shim), firmware, bytes(dtb))
        self.assertEqual(size, 144)
        self.assertEqual(struct.unpack_from("<Q", adjusted, 16)[0], size)
        self.assertEqual(verify.boot_kernel(image), adjusted + firmware + dtb)
        self.assertEqual(image[16:1580], header[16:1580])
        self.assertEqual(struct.unpack_from("<I", image, 12)[0], 0)
        self.assertNotIn(b"X" * 16, image)

    def test_rejects_init_boot_or_recovery_as_reference(self):
        reference = self.reference()
        struct.pack_into("<II", reference, 8, 0, 16)
        with self.assertRaisesRegex(ValueError, "kernel-only"):
            repack.reference_header(reference)

    def test_gzip_candidate_has_identical_firmware_and_appended_dtb(self):
        header = repack.reference_header(self.reference())
        shim = bytearray(112)
        shim[56:60] = b"ARM\x64"
        dtb = bytearray(40)
        dtb[:4] = bytes.fromhex("d00dfeed")
        struct.pack_into(">I", dtb, 4, len(dtb))
        image, adjusted, _ = repack.pack(header, bytes(shim), b"F" * 32, bytes(dtb), "gzip")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self.assertEqual(decoder.decompress(verify.boot_kernel(image)), adjusted + b"F" * 32)
        self.assertTrue(decoder.eof)
        self.assertEqual(decoder.unused_data, dtb)

    def test_rejects_signed_or_unknown_header_contents(self):
        reference = self.reference()
        struct.pack_into("<I", reference, 1580, 4096)
        with self.assertRaisesRegex(ValueError, "signature"):
            repack.reference_header(reference)
        struct.pack_into("<I", reference, 1580, 0)
        reference[2000] = 1
        with self.assertRaisesRegex(ValueError, "padding"):
            repack.reference_header(reference)

    def test_rejects_truncated_reference(self):
        with self.assertRaisesRegex(ValueError, "Truncated"):
            repack.reference_header(self.reference()[:4097])


class FirmwareBoundsTests(unittest.TestCase):
    def test_unsupported_getvar_cannot_pass_as_a_baseline(self):
        with self.assertRaises(ValueError):
            preflight.value("slot-unbootable:a", "getvar:slot-unbootable:a FAILED (remote: 'GetVar Variable Not found')\n")
        self.assertEqual(preflight.value("slot-unbootable:a", "slot-unbootable:a: no\nFinished. Total time: 0.005s\n"), "no")

    def volume(self):
        data = bytearray(b"\xff" * 128)
        struct.pack_into("<Q", data, 32, len(data))
        data[40:44] = b"_FVH"
        struct.pack_into("<H", data, 48, 72)
        data[72:88] = uuid.UUID(verify.DIAGNOSTIC_GUID).bytes_le
        data[90] = 9
        data[92:95] = (24).to_bytes(3, "little")
        return data

    def test_reads_application_guid(self):
        self.assertEqual(verify.fv_files(self.volume()), {verify.DIAGNOSTIC_GUID: 9})

    def test_rejects_ffs_outside_volume(self):
        data = self.volume()
        data[92:95] = (129).to_bytes(3, "little")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            verify.fv_files(data)

    def test_rejects_zero_length_file(self):
        data = self.volume()
        data[92:95] = b"\0\0\0"
        with self.assertRaises(ValueError):
            verify.fv_files(data)

    def test_rejects_volume_length_mismatch(self):
        with self.assertRaisesRegex(ValueError, "bounds"):
            verify.fv_files(self.volume()[:-1])

    def test_rejects_wrong_boot_version_and_truncated_kernel(self):
        data = bytearray(8192)
        data[:8] = b"ANDROID!"
        struct.pack_into("<I", data, 8, 1)
        struct.pack_into("<I", data, 20, 1584)
        struct.pack_into("<I", data, 40, 4)
        self.assertEqual(verify.boot_kernel(data), b"\0")
        struct.pack_into("<I", data, 40, 3)
        with self.assertRaises(ValueError):
            verify.boot_kernel(data)
        struct.pack_into("<I", data, 40, 4)
        struct.pack_into("<I", data, 8, 8193)
        with self.assertRaises(ValueError):
            verify.boot_kernel(data)


if __name__ == "__main__":
    unittest.main()
