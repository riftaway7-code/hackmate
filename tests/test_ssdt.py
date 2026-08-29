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
_CPU0_PROCESSOR_DSDT = b"DSDT\x00\x00\x00\x00...Processor (CPU0, 0x00, 0x00000410, 0x06)\n"
_NEITHER_PR00_NOR_CPU0_DSDT = b"DSDT\x00\x00\x00\x00...totally unrelated ACPI content\n"


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


class LegacyCpuScopeDetectionTests(unittest.TestCase):
    """Regression coverage for the \\_PR.CPU0 legacy Processor()-object gap:
    a DSDT that declares neither PR00 nor CPUS must not silently fall back
    to a guessed \\_SB.PR00 SSDT-PLUG that references a device that isn't
    actually there."""

    def _inspect(self, raw: bytes) -> dict:
        # NamedTemporaryFile(delete=False) + explicit close: on Windows a
        # second handle can't read the file while the writer's handle is
        # still open, unlike POSIX.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DSDT.aml"
            path.write_bytes(raw)
            return ssdt._inspect_dsdt(path)

    def test_modern_pr00_dsdt_is_confident(self):
        info = self._inspect(_LEGACY_DSDT)  # contains literal "PR00"
        self.assertTrue(info["cpu_path_confident"])
        self.assertEqual(info["cpu_path"], r"\_SB.PR00")

    def test_cpus_nested_dsdt_is_confident(self):
        info = self._inspect(b"...CPUS...no pr zero zero here...")
        self.assertTrue(info["cpu_path_confident"])
        self.assertEqual(info["cpu_path"], r"\_SB.CPUS.PR00")

    def test_legacy_cpu0_processor_object_is_not_confident(self):
        info = self._inspect(_CPU0_PROCESSOR_DSDT)
        self.assertFalse(info["cpu_path_confident"])
        self.assertEqual(info["cpu_path"], r"\_PR.CPU0")

    def test_neither_form_present_is_not_confident(self):
        info = self._inspect(_NEITHER_PR00_NOR_CPU0_DSDT)
        self.assertFalse(info["cpu_path_confident"])


class LegacyCpuScopePlugFallbackTests(unittest.TestCase):
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

    def test_legacy_cpu0_dsdt_reports_error_not_a_silently_wrong_ssdt(self):
        results = self._generate(_CPU0_PROCESSOR_DSDT)

        self.assertTrue(results["SSDT-PLUG"].startswith("ERROR"))
        self.assertFalse((self.acpi_dir / "SSDT-PLUG.aml").exists())

    def test_modern_pr00_dsdt_still_gets_a_template_generated_ssdt_plug(self):
        results = self._generate(_LEGACY_DSDT)  # contains literal "PR00"
        self.assertFalse(results["SSDT-PLUG"].startswith("ERROR"))


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


_DSL_NESTED_CONTROLLER = """\
DefinitionBlock ("", "DSDT", 2, "OEM", "OEMDSDT", 0x1)
{
    Scope (\\_SB)
    {
        Device (PCI0)
        {
            Device (SBUS)
            {
                Device (GPI0)
                {
                    Name (_HID, "INT344B")
                    Name (_CID, "INT344B")
                }
            }
            Device (I2C1)
            {
                Device (TPD0)
                {
                    Name (_HID, "PNP0C50")
                    Name (_CRS, ResourceTemplate ()
                    {
                        GpioInt (Level, ActiveLow, Exclusive, PullUp, 0x0000,
                            "\\_SB.PCI0.SBUS.GPI0", 0x00, ResourceConsumer, ,)
                        { 0x005B }
                    })
                }
            }
        }
    }
}
"""

_DSL_PLAIN_GPIO_NO_TOUCHPAD = """\
DefinitionBlock ("", "DSDT", 2, "OEM", "OEMDSDT", 0x1)
{
    Scope (\\_SB.PCI0)
    {
        Device (GPIO)
        {
            Name (_HID, "INT3450")
        }
    }
}
"""


class GpioPathDiscoveryTests(unittest.TestCase):
    def test_controller_path_is_fully_qualified_from_nesting(self):
        self.assertEqual(
            ssdt._gpio_controller_path(_DSL_NESTED_CONTROLLER),
            "\\_SB.PCI0.SBUS.GPI0",
        )

    def test_touchpad_crs_resource_source_wins(self):
        self.assertEqual(
            ssdt._touchpad_gpio_source(_DSL_NESTED_CONTROLLER),
            "\\_SB.PCI0.SBUS.GPI0",
        )

    def test_plain_gpio_device_without_touchpad(self):
        self.assertEqual(
            ssdt._gpio_controller_path(_DSL_PLAIN_GPIO_NO_TOUCHPAD),
            "\\_SB.PCI0.GPIO",
        )
        self.assertIsNone(ssdt._touchpad_gpio_source(_DSL_PLAIN_GPIO_NO_TOUCHPAD))

    def test_build_falls_back_to_byte_grep_when_decompile_unavailable(self):
        with tempfile.NamedTemporaryFile(suffix=".aml", delete=False) as f:
            f.write(b"....Device (GPI0)....")
            aml = Path(f.name)
        try:
            with tempfile.TemporaryDirectory() as out, \
                 patch.object(ssdt, "_decompile_dsdt", return_value=None), \
                 patch.object(ssdt, "find_iasl", return_value=None), \
                 patch.object(ssdt, "_compile_dsl", return_value=True) as compile_dsl:
                ok = ssdt._build_gpio_ssdt(aml, Path(out), Path("x"))
            self.assertTrue(ok)
            rendered = compile_dsl.call_args.args[0]
            self.assertIn("\\_SB.PCI0.GPI0", rendered)
        finally:
            aml.unlink(missing_ok=True)

    def test_build_uses_the_real_path_from_the_dsl(self):
        with tempfile.NamedTemporaryFile(suffix=".aml", delete=False) as f:
            f.write(b"....Device (GPI0)....")
            aml = Path(f.name)
        try:
            with tempfile.TemporaryDirectory() as out, \
                 patch.object(ssdt, "_decompile_dsdt", return_value=_DSL_NESTED_CONTROLLER), \
                 patch.object(ssdt, "find_iasl", return_value="iasl"), \
                 patch.object(ssdt, "_compile_dsl", return_value=True) as compile_dsl:
                ssdt._build_gpio_ssdt(aml, Path(out), Path("x"))
            rendered = compile_dsl.call_args.args[0]
            self.assertIn("\\_SB.PCI0.SBUS.GPI0", rendered)
            self.assertNotIn("Scope (\\_SB.PCI0.GPI0)\n", rendered)
        finally:
            aml.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
