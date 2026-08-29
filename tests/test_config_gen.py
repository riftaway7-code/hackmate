import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config_gen
from config_gen import KextEntry
from hardware import HardwareProfile
from smbios import SMBIOSData


def _profile(**overrides):
    defaults = dict(cpu_vendor="intel", cpu_generation=8, platform="desktop")
    defaults.update(overrides)
    return HardwareProfile(**defaults)


def _smbios(**overrides):
    defaults = dict(
        model="iMac18,3", serial="C02XXXXXXXXX", board_serial="C02XXXXXXXXXXXXXX",
        system_uuid="12345678-1234-1234-1234-123456789ABC", rom="001122334455",
    )
    defaults.update(overrides)
    return SMBIOSData(**defaults)


def _kext(name, note="", exe_name=""):
    return KextEntry(name=name, repo="", asset_pattern="", note=note, exe_name=exe_name)


class SortKextsTests(unittest.TestCase):
    def test_kexts_are_sorted_to_load_order(self):
        kexts_in = [_kext("AppleALC"), _kext("Lilu"), _kext("WhateverGreen")]
        sorted_names = [k.name for k in config_gen._sort_kexts(kexts_in)]
        self.assertEqual(sorted_names, ["Lilu", "WhateverGreen", "AppleALC"])

    def test_unknown_kext_sorts_after_all_known_kexts(self):
        kexts_in = [_kext("SomeThirdPartyKext"), _kext("Lilu")]
        sorted_names = [k.name for k in config_gen._sort_kexts(kexts_in)]
        self.assertEqual(sorted_names, ["Lilu", "SomeThirdPartyKext"])


class KextEntryDictTests(unittest.TestCase):
    def test_normal_kext_gets_an_executable_path(self):
        entry = config_gen._kext_entry(_kext("Lilu"))
        self.assertEqual(entry["ExecutablePath"], "Contents/MacOS/Lilu")
        self.assertEqual(entry["BundlePath"], "Lilu.kext")
        self.assertTrue(entry["Enabled"])

    def test_plist_only_kext_has_no_executable_path(self):
        entry = config_gen._kext_entry(_kext("UTBMap"))
        self.assertEqual(entry["ExecutablePath"], "")

    def test_custom_exe_name_is_respected(self):
        entry = config_gen._kext_entry(_kext("AirportItlwm", exe_name="itlwm"))
        self.assertEqual(entry["ExecutablePath"], "Contents/MacOS/itlwm")

    def test_kext_with_kernel_version_bounds_gets_them(self):
        entry = config_gen._kext_entry(_kext("CryptexFixup"))
        self.assertEqual(entry["MinKernel"], "22.0.0")
        self.assertEqual(entry["MaxKernel"], "")

    def test_disabled_flag_is_passed_through(self):
        entry = config_gen._kext_entry(_kext("UTBMap"), enabled=False)
        self.assertFalse(entry["Enabled"])


class AcpiAddTests(unittest.TestCase):
    def test_builds_one_entry_per_ssdt_all_enabled(self):
        entries = config_gen._acpi_add(["SSDT-PLUG", "SSDT-EC"])
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["Path"], "SSDT-PLUG.aml")
        self.assertTrue(all(e["Enabled"] for e in entries))


class AcpiPatchesTests(unittest.TestCase):
    def test_osi_to_xosi_only_emitted_when_ssdt_xosi_present(self):
        without = config_gen._acpi_patches(_profile(), ssdts=[])
        with_ = config_gen._acpi_patches(_profile(), ssdts=["SSDT-XOSI"])

        without_comments = {p["Comment"] for p in without}
        with_comments = {p["Comment"] for p in with_}

        self.assertNotIn("OSID to XSID", without_comments)
        self.assertNotIn("_OSI to XOSI", without_comments)
        self.assertIn("OSID to XSID", with_comments)
        self.assertIn("_OSI to XOSI", with_comments)

    def test_gprw_to_xgpr_requires_ssdt_gprw(self):
        without = config_gen._acpi_patches(_profile(), ssdts=[])
        with_ = config_gen._acpi_patches(_profile(), ssdts=["SSDT-GPRW"])

        self.assertNotIn("GPRW to XGPR", {p["Comment"] for p in without})
        self.assertIn("GPRW to XGPR", {p["Comment"] for p in with_})

    def test_patch_find_and_replace_are_correct_hex_bytes(self):
        patches = config_gen._acpi_patches(_profile(), ssdts=["SSDT-XOSI"])
        osi = next(p for p in patches if p["Comment"] == "_OSI to XOSI")
        self.assertEqual(osi["Find"], b"_OSI")
        self.assertEqual(osi["Replace"], b"XOSI")


class CpuNeedsSpoofTests(unittest.TestCase):
    def test_no_spoof_for_ordinary_supported_cpu(self):
        profile = _profile(cpu_vendor="intel", cpu_generation=8, cpu_name="Core i5-8400")
        self.assertIsNone(config_gen._cpu_needs_spoof(profile))

    def test_rocket_lake_and_newer_gets_comet_lake_spoof(self):
        profile = _profile(cpu_vendor="intel", cpu_generation=11, cpu_name="Core i7-11700K")
        spoof = config_gen._cpu_needs_spoof(profile)
        self.assertIsNotNone(spoof)
        data, mask = spoof
        self.assertEqual(data[:4], bytes.fromhex("55060A00"))
        self.assertEqual(mask[:4], bytes.fromhex("FFFFFFFF"))

    def test_pentium_gets_spoofed_regardless_of_generation(self):
        profile = _profile(cpu_vendor="intel", cpu_generation=6, cpu_name="Pentium G4560")
        self.assertIsNotNone(config_gen._cpu_needs_spoof(profile))

    def test_celeron_gets_spoofed(self):
        profile = _profile(cpu_vendor="intel", cpu_generation=7, cpu_name="Celeron G3930")
        self.assertIsNotNone(config_gen._cpu_needs_spoof(profile))

    def test_xeon_gets_spoofed(self):
        profile = _profile(cpu_vendor="intel", cpu_generation=4, cpu_name="Xeon E3-1275 v3")
        self.assertIsNotNone(config_gen._cpu_needs_spoof(profile))

    def test_amd_cpu_never_gets_intel_spoof(self):
        profile = _profile(cpu_vendor="amd", cpu_generation=12, cpu_name="Ryzen 9 5900X")
        self.assertIsNone(config_gen._cpu_needs_spoof(profile))


class AmdKernelPatchesTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        bundled = Path(config_gen.__file__).with_name("amd_patches.plist").read_bytes()
        p = patch.object(config_gen, "_amd_vanilla_raw", return_value=bundled)
        p.start()
        self.addCleanup(p.stop)

    def test_valid_core_count_is_written_into_the_patch(self):
        profile = _profile(cpu_vendor="amd", cpu_generation=12, core_count=6)
        patches = config_gen._amd_kernel_patches(profile)
        core_patches = [p for p in patches if "Force cpuid_cores_per_package" in p.get("Comment", "")]
        self.assertTrue(core_patches)
        for p in core_patches:
            self.assertEqual(p["Replace"][1], 6)

    def test_zero_core_count_falls_back_to_detected_core_count(self):
        from unittest.mock import patch
        profile = _profile(cpu_vendor="amd", cpu_generation=12, core_count=0)
        with patch.object(config_gen, "cpu_core_count", return_value=6):
            patches = config_gen._amd_kernel_patches(profile)
        core_patches = [p for p in patches if "Force cpuid_cores_per_package" in p.get("Comment", "")]
        for p in core_patches:
            self.assertEqual(p["Replace"][1], 6)

    def test_negative_core_count_is_rejected(self):
        profile = _profile(cpu_vendor="amd", cpu_generation=12, core_count=-1)
        with self.assertRaises(ValueError):
            config_gen._amd_kernel_patches(profile)

    def test_core_count_above_255_is_rejected(self):
        profile = _profile(cpu_vendor="amd", cpu_generation=12, core_count=256)
        with self.assertRaises(ValueError):
            config_gen._amd_kernel_patches(profile)


class AmdVanillaSourceTests(unittest.TestCase):
    def _bundled(self):
        return Path(config_gen.__file__).with_name("amd_patches.plist").read_bytes()

    def test_fetch_failure_falls_back_to_bundled(self):
        from unittest.mock import patch
        with patch.object(config_gen, "_AMD_VANILLA_CACHE") as cache, \
             patch.object(config_gen, "http_get", side_effect=OSError("offline")):
            cache.exists.return_value = False
            raw = config_gen._amd_vanilla_raw()
        self.assertEqual(plistlib.loads(raw)["Kernel"]["Patch"][0].keys(),
                         plistlib.loads(self._bundled())["Kernel"]["Patch"][0].keys())

    def test_bad_payload_is_rejected_and_falls_back(self):
        from unittest.mock import patch
        with patch.object(config_gen, "_AMD_VANILLA_CACHE") as cache, \
             patch.object(config_gen, "http_get", return_value=b"not a plist"):
            cache.exists.return_value = False
            raw = config_gen._amd_vanilla_raw()
        self.assertIn(b"Kernel", raw)


class PlatformInfoTests(unittest.TestCase):
    def test_smbios_fields_are_mapped_into_generic_dict(self):
        smbios = _smbios(model="iMac18,3", serial="SERIAL123", board_serial="MLB123456789ABCDE",
                          system_uuid="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE", rom="AABBCCDDEEFF")
        info = config_gen._platform_info(smbios)
        generic = info["Generic"]
        self.assertEqual(generic["SystemProductName"], "iMac18,3")
        self.assertEqual(generic["SystemSerialNumber"], "SERIAL123")
        self.assertEqual(generic["MLB"], "MLB123456789ABCDE")
        self.assertEqual(generic["SystemUUID"], "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE")
        self.assertEqual(generic["ROM"], bytes.fromhex("AABBCCDDEEFF"))
        self.assertTrue(info["UpdateSMBIOS"])
        self.assertEqual(info["UpdateSMBIOSMode"], "Create")


class SyncExecutablePathsTests(unittest.TestCase):
    def _write_kext(self, kext_dir: Path, bundle: str, exe: str | None):
        kext_path = kext_dir / bundle / "Contents"
        kext_path.mkdir(parents=True)
        info = {"CFBundleExecutable": exe} if exe else {}
        (kext_path / "Info.plist").write_bytes(plistlib.dumps(info))
        if exe:
            macos = kext_path / "MacOS"
            macos.mkdir()
            (macos / exe).write_bytes(b"\x00")

    def test_wrong_executable_path_is_corrected_from_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext_dir = Path(tmp)
            self._write_kext(kext_dir, "itlwm.kext", "itlwm")
            config = {"Kernel": {"Add": [
                {"BundlePath": "itlwm.kext", "ExecutablePath": "Contents/MacOS/WrongName"}
            ]}}
            fixed = config_gen.sync_executable_paths(config, kext_dir)
            self.assertEqual(fixed, ["itlwm.kext"])
            self.assertEqual(config["Kernel"]["Add"][0]["ExecutablePath"], "Contents/MacOS/itlwm")

    def test_already_correct_path_is_not_reported_as_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext_dir = Path(tmp)
            self._write_kext(kext_dir, "Lilu.kext", "Lilu")
            config = {"Kernel": {"Add": [
                {"BundlePath": "Lilu.kext", "ExecutablePath": "Contents/MacOS/Lilu"}
            ]}}
            fixed = config_gen.sync_executable_paths(config, kext_dir)
            self.assertEqual(fixed, [])

    def test_plist_only_bundle_gets_empty_executable_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext_dir = Path(tmp)
            self._write_kext(kext_dir, "UTBMap.kext", None)
            config = {"Kernel": {"Add": [
                {"BundlePath": "UTBMap.kext", "ExecutablePath": "Contents/MacOS/stale"}
            ]}}
            fixed = config_gen.sync_executable_paths(config, kext_dir)
            self.assertEqual(fixed, ["UTBMap.kext"])
            self.assertEqual(config["Kernel"]["Add"][0]["ExecutablePath"], "")

    def test_missing_bundle_on_disk_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext_dir = Path(tmp)
            config = {"Kernel": {"Add": [
                {"BundlePath": "NeverDownloaded.kext", "ExecutablePath": "Contents/MacOS/Foo"}
            ]}}
            fixed = config_gen.sync_executable_paths(config, kext_dir)
            self.assertEqual(fixed, [])
            self.assertEqual(config["Kernel"]["Add"][0]["ExecutablePath"], "Contents/MacOS/Foo")

    def test_claimed_executable_that_does_not_exist_on_disk_clears_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            kext_dir = Path(tmp)
            kext_path = kext_dir / "Broken.kext" / "Contents"
            kext_path.mkdir(parents=True)
            (kext_path / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "Broken"}))
            # No Contents/MacOS/Broken file actually written — bundle is incomplete.
            config = {"Kernel": {"Add": [
                {"BundlePath": "Broken.kext", "ExecutablePath": "Contents/MacOS/Broken"}
            ]}}
            fixed = config_gen.sync_executable_paths(config, kext_dir)
            self.assertEqual(fixed, ["Broken.kext"])
            self.assertEqual(config["Kernel"]["Add"][0]["ExecutablePath"], "")


class StripMissingSsdtsTests(unittest.TestCase):
    def _config(self):
        return {
            "ACPI": {
                "Add": [
                    {"Path": "SSDT-PLUG.aml"},
                    {"Path": "SSDT-XOSI.aml"},
                ],
                "Patch": [
                    {"Comment": "_OSI to XOSI"},
                    {"Comment": "OSID to XSID"},
                ],
            }
        }

    def test_no_missing_ssdts_is_a_no_op(self):
        config = self._config()
        removed = config_gen.strip_missing_ssdts(config, [])
        self.assertEqual(removed, (0, 0))
        self.assertEqual(len(config["ACPI"]["Add"]), 2)

    def test_missing_ssdt_removes_its_table_and_dependent_patch(self):
        config = self._config()
        removed_tables, removed_patches = config_gen.strip_missing_ssdts(config, ["SSDT-XOSI"])

        self.assertEqual(removed_tables, 1)
        self.assertEqual(removed_patches, 2)  # both renames require SSDT-XOSI
        remaining_paths = {e["Path"] for e in config["ACPI"]["Add"]}
        self.assertEqual(remaining_paths, {"SSDT-PLUG.aml"})
        self.assertEqual(config["ACPI"]["Patch"], [])

    def test_missing_ssdt_not_referenced_by_any_patch_only_drops_the_table(self):
        config = self._config()
        removed_tables, removed_patches = config_gen.strip_missing_ssdts(config, ["SSDT-PLUG"])

        self.assertEqual(removed_tables, 1)
        self.assertEqual(removed_patches, 0)
        self.assertEqual(len(config["ACPI"]["Patch"]), 2)


class WritePlistTests(unittest.TestCase):
    def test_writes_a_valid_binary_plist_and_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "dir" / "config.plist"
            config_gen.write_plist({"Key": "Value"}, path)

            self.assertTrue(path.exists())
            roundtrip = plistlib.loads(path.read_bytes())
            self.assertEqual(roundtrip, {"Key": "Value"})


if __name__ == "__main__":
    unittest.main()
