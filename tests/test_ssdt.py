import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ssdt

_ACPI0007_DSDT = (
    b"DSDT\x00\x00\x00\x00...Device (C000)\n"
    b"{\n    Name (_HID, \"ACPI0007\")\n}\n"
)
_LEGACY_DSDT = b"DSDT\x00\x00\x00\x00...Processor (PR00, 0x00, 0x00000410, 0x06)\n"


class Acpi0007DetectionTests(unittest.TestCase):
    def _inspect(self, raw: bytes) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".aml") as f:
            f.write(raw)
            f.flush()
            return ssdt._inspect_dsdt(Path(f.name))

    def test_detects_acpi0007_cpu_objects(self):
        self.assertTrue(self._inspect(_ACPI0007_DSDT)["has_acpi0007"])

    def test_legacy_dsdt_without_acpi0007_is_not_flagged(self):
        self.assertFalse(self._inspect(_LEGACY_DSDT)["has_acpi0007"])


class Acpi0007PlugFallbackTests(unittest.TestCase):
    def setUp(self):
        self.acpi_dir = Path(tempfile.mkdtemp(prefix="hackmate-test-acpi-"))
        self.dsdt_file = Path(tempfile.mkdtemp(prefix="hackmate-test-dsdt-")) / "DSDT.aml"

    def tearDown(self):
        shutil.rmtree(self.acpi_dir, ignore_errors=True)
        shutil.rmtree(self.dsdt_file.parent, ignore_errors=True)

    def _generate(self, dsdt_bytes: bytes) -> dict:
        self.dsdt_file.write_bytes(dsdt_bytes)
        with (
            patch.object(ssdt, "_ensure_ssdttime", side_effect=Exception("SSDTTime unavailable")),
            patch.object(ssdt, "get_dsdt", return_value=self.dsdt_file),
        ):
            return ssdt.generate(
                needed=["SSDT-PLUG"],
                acpi_dir=self.acpi_dir,
                tmp=self.dsdt_file.parent,
                cpu_generation=8,
            )

    def test_acpi0007_with_no_ssdttime_reports_error_not_a_silent_wrong_ssdt(self):
        results = self._generate(_ACPI0007_DSDT)

        self.assertTrue(results["SSDT-PLUG"].startswith("ERROR"))
        self.assertIn("ACPI0007", results["SSDT-PLUG"])
        self.assertFalse((self.acpi_dir / "SSDT-PLUG.aml").exists())

    def test_legacy_dsdt_still_gets_a_template_generated_ssdt_plug(self):
        results = self._generate(_LEGACY_DSDT)

        self.assertFalse(results["SSDT-PLUG"].startswith("ERROR"))


_I2C_HID_DSDT_STRING = b"DSDT\x00\x00\x00\x00...Device (TPD0)\n{ Name (_HID, \"ACPI0C50\") }\n"
# _HID EisaId("PNP0C50") compresses to the four bytes 41 D0 0C 50
_I2C_HID_DSDT_EISAID = b"DSDT\x00\x00\x00\x00...Device (TPL1)\n\x08_HID\x0c\x41\xd0\x0c\x50\n"
_NO_TRACKPAD_DSDT = b"DSDT\x00\x00\x00\x00...Device (PS2K)\n{ Name (_HID, \"PNP0303\") }\n"


class I2cHidDsdtDetectionTests(unittest.TestCase):
    def _inspect(self, raw: bytes) -> dict:
        f = tempfile.NamedTemporaryFile(suffix=".aml", delete=False)
        try:
            f.write(raw)
            f.close()
            return ssdt._inspect_dsdt(Path(f.name))
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_acpi0c50_string_id_is_detected(self):
        self.assertTrue(self._inspect(_I2C_HID_DSDT_STRING)["has_i2c_hid"])

    def test_compressed_pnp0c50_eisaid_is_detected(self):
        self.assertTrue(self._inspect(_I2C_HID_DSDT_EISAID)["has_i2c_hid"])

    def test_ps2_only_dsdt_is_not_flagged(self):
        self.assertFalse(self._inspect(_NO_TRACKPAD_DSDT)["has_i2c_hid"])


class I2cHidForcesGpi0Tests(unittest.TestCase):
    def setUp(self):
        self.acpi_dir = Path(tempfile.mkdtemp(prefix="hackmate-test-acpi-"))
        self.dsdt_file = Path(tempfile.mkdtemp(prefix="hackmate-test-dsdt-")) / "DSDT.aml"

    def tearDown(self):
        shutil.rmtree(self.acpi_dir, ignore_errors=True)
        shutil.rmtree(self.dsdt_file.parent, ignore_errors=True)

    def _generate(self, dsdt_bytes: bytes, needed=("SSDT-PLUG",)) -> dict:
        self.dsdt_file.write_bytes(dsdt_bytes)
        with (
            patch.object(ssdt, "_ensure_ssdttime", side_effect=Exception("SSDTTime unavailable")),
            patch.object(ssdt, "get_dsdt", return_value=self.dsdt_file),
        ):
            return ssdt.generate(
                needed=list(needed),
                acpi_dir=self.acpi_dir,
                tmp=self.dsdt_file.parent,
                cpu_generation=8,
            )

    def test_i2c_hid_dsdt_pulls_in_gpi0_and_xosi_even_when_not_requested(self):
        results = self._generate(_I2C_HID_DSDT_STRING)

        self.assertEqual(results.get("SSDT-GPI0"), "OK")
        self.assertEqual(results.get("SSDT-XOSI"), "OK")
        self.assertTrue((self.acpi_dir / "SSDT-GPI0.aml").exists())
        self.assertTrue((self.acpi_dir / "SSDT-XOSI.aml").exists())

    def test_no_i2c_hid_dsdt_does_not_add_gpi0(self):
        results = self._generate(_NO_TRACKPAD_DSDT)

        self.assertNotIn("SSDT-GPI0", results)
        self.assertFalse((self.acpi_dir / "SSDT-GPI0.aml").exists())


class UnknownDsdtPlugSafetyTests(unittest.TestCase):
    def setUp(self):
        self.acpi_dir = Path(tempfile.mkdtemp(prefix="hackmate-test-acpi-"))
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="hackmate-test-tmp-"))

    def tearDown(self):
        shutil.rmtree(self.acpi_dir, ignore_errors=True)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_no_dsdt_at_all_reports_error_instead_of_guessing_ssdt_plug(self):
        with (
            patch.object(ssdt, "_ensure_ssdttime", side_effect=Exception("SSDTTime unavailable")),
            patch.object(ssdt, "get_dsdt", return_value=None),
        ):
            results = ssdt.generate(
                needed=["SSDT-PLUG"],
                acpi_dir=self.acpi_dir,
                tmp=self.tmp_dir,
                cpu_generation=8,
            )

        self.assertTrue(results["SSDT-PLUG"].startswith("ERROR"))
        self.assertFalse((self.acpi_dir / "SSDT-PLUG.aml").exists())


def _aml_device(name: str, adr: int) -> bytes:
    name_b = name.encode("ascii")
    body = b"\x08_ADR" + b"\x0c" + adr.to_bytes(4, "little")
    after_pkglen = name_b + body
    pkg_len = 1 + len(after_pkglen)
    return b"\x5b\x82" + bytes([pkg_len]) + after_pkglen


class DisableSsdtGenerationTests(unittest.TestCase):
    def setUp(self):
        self.acpi_dir = Path(tempfile.mkdtemp(prefix="hackmate-test-acpi-"))
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="hackmate-test-tmp-"))

    def tearDown(self):
        shutil.rmtree(self.acpi_dir, ignore_errors=True)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_no_dsdt_skips(self):
        with patch.object(ssdt, "get_dsdt", return_value=None):
            result = ssdt.generate_disable_ssdt(self.acpi_dir, self.tmp_dir, 0x1C, 0)
        self.assertTrue(result.startswith("SKIP"))

    def test_device_not_in_dsdt_skips(self):
        dsdt_file = self.tmp_dir / "DSDT.aml"
        dsdt_file.write_bytes(_aml_device("WIFI", 0x001D0000))
        with patch.object(ssdt, "get_dsdt", return_value=dsdt_file):
            result = ssdt.generate_disable_ssdt(self.acpi_dir, self.tmp_dir, 0x1C, 0)
        self.assertTrue(result.startswith("SKIP"))

    def test_matching_device_but_no_iasl_errors_not_silently_skips(self):
        dsdt_file = self.tmp_dir / "DSDT.aml"
        dsdt_file.write_bytes(_aml_device("WIFI", 0x001C0000))
        with (
            patch.object(ssdt, "get_dsdt", return_value=dsdt_file),
            patch.object(ssdt, "find_iasl", return_value=None),
        ):
            result = ssdt.generate_disable_ssdt(self.acpi_dir, self.tmp_dir, 0x1C, 0)
        self.assertTrue(result.startswith("ERROR"))
        self.assertFalse((self.acpi_dir / "SSDT-DSBL.aml").exists())


class FrozenAssetsPathTests(unittest.TestCase):
    def test_source_checkout_uses_the_real_assets_directory(self):
        with patch.object(sys, "frozen", False, create=True):
            path = ssdt._assets_dir()

        self.assertEqual(path, Path(ssdt.__file__).parent / "assets" / "acpi")
        self.assertTrue(path.exists(), "src/assets/acpi should exist in the repo")

    def test_frozen_exe_uses_meipass_not_file_parent(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", "/fake/meipass/dir", create=True),
        ):
            path = ssdt._assets_dir()

        self.assertEqual(path, Path("/fake/meipass/dir") / "assets" / "acpi")


if __name__ == "__main__":
    unittest.main()
