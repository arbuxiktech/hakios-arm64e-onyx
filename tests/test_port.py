import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


prepare = module("prepare_loader", "tools/prepare-loader.py")
ipsw = module("check_ipsw", "tools/check-ipsw.py")


class LoaderSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "upstream/hakios-arm64e-dada/base/xnuloader/loader.c").read_text()
        cls.board = json.loads((ROOT / "devices/onyx.json").read_text())

    def test_no_direct_blockio_write_survives(self):
        result = prepare.transform(self.source, self.board)
        self.assertNotRegex(result, r"->\s*write_blocks\s*\(")
        self.assertIn("return EFI_ERROR_BIT | 15;", result)
        self.assertIn("efi_block_io *bio = NULL; /* Onyx: USB/console logs only */", result)

    def test_unreviewed_write_site_is_rejected(self):
        changed = self.source + "\nvoid new_writer(void) { other->write_blocks(other, 0, 0, 0, 0); }\n"
        with self.assertRaisesRegex(ValueError, "write call sites changed"):
            prepare.transform(changed, self.board)

    def test_diagnostics_returns_before_hardware_handoff(self):
        result = prepare.transform(self.source, self.board)
        entry = result[result.index("efi_main(efi_handle"):]
        diagnostic = entry.index("ONYX DIAGNOSTICS ONLY")
        returned = entry.index("return 0;", diagnostic)
        for operation in ("install_exception_hook();", "wdt_arm();", "parse_payload(&pi, 0)", "run_kernel(0, 0);"):
            self.assertLess(returned, entry.index(operation))
        self.assertIn("PLAT = &platform_onyx;", entry)
        self.assertIn(".gic_dist = 0x17100000, .gic_redist = 0x17180000", result)


class IpswIdentityTests(unittest.TestCase):
    def check_manifest(self, manifest):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.ipsw"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("BuildManifest.plist", plistlib.dumps(manifest))
            return ipsw.inspect(path)

    def test_candidate_requires_version_build_and_model(self):
        manifest = {"ProductVersion": "26.6.2", "ProductBuildVersion": "23G90",
                    "SupportedProductTypes": ["iPhone18,1"]}
        self.assertTrue(self.check_manifest(manifest)["matches_dada_launcher_reference"])
        for field, wrong in (("ProductVersion", "26.0"), ("ProductBuildVersion", "23G91"),
                             ("SupportedProductTypes", ["iPhone18,2"])):
            changed = dict(manifest, **{field: wrong})
            self.assertFalse(self.check_manifest(changed)["matches_dada_launcher_reference"])

    def test_manifest_does_not_claim_abi_validation(self):
        self.assertFalse(self.check_manifest({})["kernel_abi_compatibility_verified"])


if __name__ == "__main__":
    unittest.main()
