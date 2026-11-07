import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


stock = module("stock", "tools/inspect-stock.py")
unpack = module("unpack", "tools/safe-unpack-dmg.py")
kernel = module("kernel", "tools/prepare-kernel.py")
recovery = module("recovery", "tools/repair-ios26-systemos.py")
verification = module("verification", "tools/verify-kernel.py")


def minimal_fdt():
    names = b"compatible\0reg\0"
    content = struct.pack(">I", 1) + bytes(4)
    value = b"qcom,tuna\0"
    content += struct.pack(">III", 3, len(value), 0) + value
    content += bytes((-len(content)) % 4)
    content += struct.pack(">IIII", 3, 4, 11, 0)
    content += struct.pack(">II", 2, 9)
    strings_at = 56 + len(content)
    header = struct.pack(">10I", stock.FDT_MAGIC, strings_at + len(names), 56,
                         strings_at, 40, 17, 16, 0, len(names), len(content))
    return header + bytes(16) + content + names


class FirmwareParserTests(unittest.TestCase):
    def test_zero_cell_is_numeric(self):
        self.assertEqual(stock.describe(bytes(8)), ["0x0", "0x0"])
        self.assertEqual(stock.describe(struct.pack(">III", 55, 78, 0)), ["0x37", "0x4e", "0x0"])

    def test_fdt_parser_and_concatenated_trees(self):
        tree = minimal_fdt()
        nodes = stock.fdt_nodes(tree)
        self.assertEqual(nodes["/"]["compatible"], b"qcom,tuna\0")
        self.assertEqual(len(list(stock.dtb_sequence(tree + tree))), 2)

    def test_out_of_bounds_tree_is_rejected(self):
        tree = bytearray(minimal_fdt())
        struct.pack_into(">I", tree, 8, len(tree) + 100)
        with self.assertRaises(ValueError):
            stock.fdt_nodes(tree)

    def test_dtbo_payload_cannot_escape_file(self):
        header = struct.pack(">8I", stock.DTBO_MAGIC, 64, 32, 32, 1, 32, 4096, 0)
        entry = struct.pack(">8I", 40, 4096, 0, 0, 0, 0, 0, 0)
        with self.assertRaises(ValueError):
            list(stock.dtbo_entries(header + entry))


class ExtractionBoundaryTests(unittest.TestCase):
    def test_recovery_pattern_matches_only_requested_paths(self):
        import re
        paths = ["System/Library/A.bundle/Info.plist", "System/Library/A.bundle/A", "usr/lib/libstdc++.dylib"]
        pattern = re.compile(recovery.path_pattern(paths))
        for path in paths:
            self.assertTrue(pattern.search("root/" + path))
        for path in ("usr/lib/libstdcXX.dylib", "System/Library/A.bundle/Info.plist.bak", "System/Library/B.bundle/A"):
            self.assertFalse(pattern.search("root/" + path))

    def test_relative_framework_link_stays_inside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = "System/Library/Frameworks/AVFoundation.framework/Frameworks/AVFAudio.framework"
            self.assertEqual(unpack.contained_link(root, path, "../../AVFAudio.framework"), root.resolve() / path)

    def test_absolute_and_escaping_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, target in (("../escape", "file"), ("file", "../../escape"), ("file", "/etc/passwd")):
                with self.subTest(name=name, target=target), self.assertRaises(ValueError):
                    unpack.contained_link(root, name, target)


class TouchGatingTests(unittest.TestCase):
    def test_reference_transport_cannot_be_enabled_by_boot_args(self):
        source = (ROOT / "upstream/hakios-onyx-reference/xnu/files/bsd/dev/onyx_touch.c").read_text()
        result = kernel.touch_source(source)
        thread = result[result.index("onyx_touch_probe_thread(__unused"):]
        returned = thread.index("return;", thread.index("iOS26 passive build"))
        for call in ("onyx_touch_bridge_run(bridge_pa)", "onyx_touch_bitbang_run()", "onyx_gpi_probe()",
                     "onyx_touch_gpi_run()", "onyx_touch_run()", "ml_io_map(ONYX_TLMM_PHYS"):
            self.assertLess(returned, thread.index(call))


class KernelArtifactTests(unittest.TestCase):
    def test_arm64_artifact_cannot_pass_as_arm64e(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kernel"
            path.write_bytes(struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0))
            with self.assertRaises(ValueError):
                verification.verify(path)
            path.write_bytes(struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0x80000002, 2, 0, 0, 0, 0))
            result = verification.verify(path)
            self.assertEqual(result["architecture"], "arm64e")
            self.assertFalse(result["hardware_boot_tested"])


if __name__ == "__main__":
    unittest.main()
