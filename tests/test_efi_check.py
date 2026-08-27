import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import efi_check
from hardware import HardwareProfile


def _profile(**overrides):
    defaults = dict(cpu_vendor="intel", cpu_generation=8, platform="desktop", gpu_vendor="intel")
    defaults.update(overrides)
    return HardwareProfile(**defaults)


class IsValidEfiTests(unittest.TestCase):
    def test_mz_header_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "OpenCore.efi"
            p.write_bytes(b"MZ" + b"\x00" * 100)
            self.assertTrue(efi_check._is_valid_efi(p))

    def test_missing_header_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "OpenCore.efi"
            p.write_bytes(b"garbage data with no header")
            self.assertFalse(efi_check._is_valid_efi(p))

    def test_missing_file_is_invalid(self):
        self.assertFalse(efi_check._is_valid_efi(Path("/nonexistent/OpenCore.efi")))


class KextStructureTests(unittest.TestCase):
    def _kext(self, tmp, exe_name=None, exe_bytes=b"\x00"):
        kext = Path(tmp) / "Lilu.kext"
        contents = kext / "Contents"
        contents.mkdir(parents=True)
        (contents / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": exe_name or "Lilu"}))
        if exe_name is not None:
            macos = contents / "MacOS"
            macos.mkdir()
            (macos / exe_name).write_bytes(exe_bytes)
        return kext

    def test_valid_kext_with_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext = self._kext(tmp, exe_name="Lilu")
            ok, reason = efi_check._kext_has_valid_structure(kext, "Contents/MacOS/Lilu")
            self.assertTrue(ok)

    def test_missing_info_plist_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext = Path(tmp) / "Empty.kext"
            kext.mkdir()
            ok, reason = efi_check._kext_has_valid_structure(kext, "")
            self.assertFalse(ok)
            self.assertIn("Info.plist", reason)

    def test_missing_expected_executable_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext = Path(tmp) / "Lilu.kext"
            (kext / "Contents").mkdir(parents=True)
            (kext / "Contents" / "Info.plist").write_bytes(plistlib.dumps({}))
            ok, reason = efi_check._kext_has_valid_structure(kext, "Contents/MacOS/Lilu")
            self.assertFalse(ok)
            self.assertIn("missing", reason)

    def test_zero_byte_executable_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext = self._kext(tmp, exe_name="Lilu", exe_bytes=b"")
            ok, reason = efi_check._kext_has_valid_structure(kext, "Contents/MacOS/Lilu")
            self.assertFalse(ok)
            self.assertIn("empty", reason)

    def test_plist_only_kext_with_no_expected_exec_path_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext = Path(tmp) / "UTBMap.kext"
            (kext / "Contents").mkdir(parents=True)
            (kext / "Contents" / "Info.plist").write_bytes(plistlib.dumps({}))
            ok, reason = efi_check._kext_has_valid_structure(kext, "")
            self.assertTrue(ok)


class SmbiosPlaceholderTests(unittest.TestCase):
    def test_empty_string_is_placeholder(self):
        self.assertTrue(efi_check._smbios_is_placeholder(""))

    def test_all_zero_serial_is_placeholder(self):
        self.assertTrue(efi_check._smbios_is_placeholder("00000000"))

    def test_zero_prefixed_mlb_is_placeholder(self):
        self.assertTrue(efi_check._smbios_is_placeholder("0000000000000000"))

    def test_real_looking_serial_is_not_placeholder(self):
        self.assertFalse(efi_check._smbios_is_placeholder("C02XG2AWH7JY"))


class FindDeviceKeyTests(unittest.TestCase):
    def test_finds_by_alias(self):
        dev_props = {"PciRoot(0x0)/Pci(0x2,0x0)": {"AAPL,ig-platform-id": b"\x00"}}
        # alias not present as key text, but pci path should match
        key = efi_check._find_device_key(dev_props, ("IGPU", "GFX0", "B0D2"), "PciRoot(0x0)/Pci(0x2,0x0)")
        self.assertEqual(key, "PciRoot(0x0)/Pci(0x2,0x0)")

    def test_finds_by_named_alias_key(self):
        dev_props = {"IGPU@2": {"AAPL,ig-platform-id": b"\x00"}}
        key = efi_check._find_device_key(dev_props, ("IGPU", "GFX0", "B0D2"), "PciRoot(0x0)/Pci(0x2,0x0)")
        self.assertEqual(key, "IGPU@2")

    def test_returns_none_when_not_present(self):
        dev_props = {"HDEF@1F,3": {}}
        key = efi_check._find_device_key(dev_props, ("IGPU", "GFX0", "B0D2"), "PciRoot(0x0)/Pci(0x2,0x0)")
        self.assertIsNone(key)


class CheckConflictsTests(unittest.TestCase):
    def test_itlwm_and_airportitlwm_conflict_detected(self):
        results = []
        efi_check._check_conflicts({"itlwm.kext", "AirportItlwm.kext"}, results)
        self.assertTrue(any(lvl == "error" for lvl, _ in results))

    def test_no_conflict_when_only_one_present(self):
        results = []
        efi_check._check_conflicts({"itlwm.kext"}, results)
        self.assertEqual(results, [])

    def test_virtualsmc_and_fakesmc_conflict_detected(self):
        results = []
        efi_check._check_conflicts({"VirtualSMC.kext", "FakeSMC.kext"}, results)
        self.assertTrue(any("VirtualSMC" in msg for _, msg in results))


class CheckConfigCompletenessTests(unittest.TestCase):
    def _cfg(self, sn="C02XG2AWH7JY", mlb="C02123456789ABCDE", uid="12345678-1234-1234-1234-123456789ABC"):
        return {
            "PlatformInfo": {"Generic": {
                "SystemSerialNumber": sn, "MLB": mlb, "SystemUUID": uid,
            }},
            "NVRAM": {"Add": {}},
            "Misc": {"Security": {}},
        }

    def test_complete_smbios_reports_ok(self):
        results = []
        efi_check._check_config_completeness(self._cfg(), results)
        levels = {lvl for lvl, _ in results}
        self.assertNotIn("error", levels)

    def test_placeholder_serial_is_an_error(self):
        results = []
        efi_check._check_config_completeness(self._cfg(sn=""), results)
        self.assertTrue(any(lvl == "error" and "SerialNumber" in msg for lvl, msg in results))

    def test_placeholder_mlb_is_an_error(self):
        results = []
        efi_check._check_config_completeness(self._cfg(mlb="0000000000000000"), results)
        self.assertTrue(any(lvl == "error" and "MLB" in msg for lvl, msg in results))

    def test_all_zero_uuid_is_an_error(self):
        results = []
        efi_check._check_config_completeness(self._cfg(uid="00000000-0000-0000-0000-000000000000"), results)
        self.assertTrue(any(lvl == "error" and "UUID" in msg for lvl, msg in results))

    def test_missing_verbose_boot_is_info_not_error(self):
        results = []
        efi_check._check_config_completeness(self._cfg(), results)
        info_msgs = [msg for lvl, msg in results if lvl == "info"]
        self.assertTrue(any("-v" in msg for msg in info_msgs))


class FullCheckIntegrationTests(unittest.TestCase):
    """End-to-end tests against a constructed on-disk EFI folder."""

    def _write_efi_binary(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MZ" + b"\x00" * 64)

    def _base_efi(self, tmp: Path, kernel_add=None, acpi_add=None):
        oc = tmp / "OC"
        boot = tmp / "BOOT"
        self._write_efi_binary(boot / "BOOTx64.efi")
        self._write_efi_binary(oc / "OpenCore.efi")
        (oc / "Drivers").mkdir(parents=True, exist_ok=True)
        self._write_efi_binary(oc / "Drivers" / "OpenRuntime.efi")
        self._write_efi_binary(oc / "Drivers" / "HfsPlus.efi")
        (oc / "Kexts").mkdir(parents=True, exist_ok=True)
        (oc / "ACPI").mkdir(parents=True, exist_ok=True)

        config = {
            "ACPI": {"Add": acpi_add or []},
            "Kernel": {"Add": kernel_add or []},
            "UEFI": {"Drivers": []},
            "PlatformInfo": {"Generic": {
                "SystemSerialNumber": "C02XG2AWH7JY",
                "MLB": "C02123456789ABCDE",
                "SystemUUID": "12345678-1234-1234-1234-123456789ABC",
                "SystemProductName": "iMac18,3",
            }},
            "NVRAM": {"Add": {}},
            "Misc": {"Security": {}},
            "DeviceProperties": {"Add": {}},
        }
        (oc / "config.plist").write_bytes(plistlib.dumps(config))
        return oc

    def _add_kext(self, oc: Path, name: str, exe: bool = True):
        kext = oc / "Kexts" / f"{name}.kext"
        (kext / "Contents").mkdir(parents=True)
        info = {"CFBundleExecutable": name} if exe else {}
        (kext / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
        if exe:
            (kext / "Contents" / "MacOS").mkdir()
            (kext / "Contents" / "MacOS" / name).write_bytes(b"\x00")

    def test_missing_bootx64_is_reported_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._base_efi(root)
            (root / "BOOT" / "BOOTx64.efi").unlink()
            results = efi_check.check(root, _profile())
        self.assertTrue(any(lvl == "error" and "BOOTx64.efi" in msg for lvl, msg in results))

    def test_corrupt_opencore_binary_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._base_efi(root)
            (root / "OC" / "OpenCore.efi").write_bytes(b"not an efi binary")
            results = efi_check.check(root, _profile())
        self.assertTrue(any(lvl == "error" and "not a valid EFI binary" in msg for lvl, msg in results))

    def test_kext_referenced_but_not_on_disk_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kernel_add = [{"BundlePath": "Lilu.kext", "ExecutablePath": "Contents/MacOS/Lilu", "Enabled": True}]
            oc = self._base_efi(root, kernel_add=kernel_add)
            # Deliberately never write Lilu.kext to Kexts/
            results = efi_check.check(root, _profile())
        self.assertTrue(any(lvl == "error" and "Lilu.kext" in msg and "not on the USB" in msg for lvl, msg in results))

    def test_lilu_dependent_loaded_before_lilu_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kernel_add = [
                {"BundlePath": "AppleALC.kext", "ExecutablePath": "Contents/MacOS/AppleALC", "Enabled": True},
                {"BundlePath": "Lilu.kext", "ExecutablePath": "Contents/MacOS/Lilu", "Enabled": True},
            ]
            oc = self._base_efi(root, kernel_add=kernel_add)
            self._add_kext(oc, "AppleALC")
            self._add_kext(oc, "Lilu")
            results = efi_check.check(root, _profile())
        self.assertTrue(any(lvl == "error" and "loaded before Lilu" in msg for lvl, msg in results))

    def test_valid_minimal_efi_reports_no_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kernel_add = [
                {"BundlePath": "Lilu.kext", "ExecutablePath": "Contents/MacOS/Lilu", "Enabled": True},
            ]
            oc = self._base_efi(root, kernel_add=kernel_add)
            self._add_kext(oc, "Lilu")
            results = efi_check.check(root, _profile(platform="desktop", gpu_vendor="intel"))
        errors = [msg for lvl, msg in results if lvl == "error"]
        self.assertEqual(errors, [])

    def test_missing_acpi_table_file_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acpi_add = [{"Path": "SSDT-PLUG.aml", "Enabled": True}]
            self._base_efi(root, acpi_add=acpi_add)
            # SSDT-PLUG.aml never written to ACPI/
            results = efi_check.check(root, _profile())
        self.assertTrue(any(lvl == "warn" and "SSDT-PLUG.aml" in msg for lvl, msg in results))

    def test_nvidia_gpu_is_flagged_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._base_efi(root)
            results = efi_check.check(root, _profile(gpu_vendor="nvidia"))
        self.assertTrue(any(lvl == "error" and "NVIDIA" in msg for lvl, msg in results))

    def test_amd_cpu_with_intel_igpu_only_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._base_efi(root)
            results = efi_check.check(root, _profile(cpu_vendor="amd", gpu_vendor="intel"))
        self.assertTrue(any(lvl == "error" and "AMD CPU" in msg for lvl, msg in results))


if __name__ == "__main__":
    unittest.main()
