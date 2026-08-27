import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config_gen
import config_editor
import efi_check
import kexts
import log_checker
from hardware import HardwareProfile
from smbios import SMBIOSData


class InstallerAudioSafetyTests(unittest.TestCase):
    def _selected_names(self, codec: str) -> set[str]:
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=8,
            platform="desktop",
            audio_codec=codec,
        )
        with (
            patch.object(kexts, "_dmi", return_value=""),
            patch.object(kexts, "_has_card_reader", return_value=False),
        ):
            return {entry.name for entry in kexts.select_kexts(profile)}

    def test_supported_codec_uses_applealc(self):
        names = self._selected_names("Realtek ALC257")

        self.assertIn("AppleALC", names)
        self.assertNotIn("VoodooHDA", names)

    def test_unknown_codec_does_not_inject_voodoohda(self):
        names = self._selected_names("Conexant CX20751")

        self.assertNotIn("AppleALC", names)
        self.assertNotIn("VoodooHDA", names)

    def test_missing_codec_keeps_safe_applealc_default(self):
        names = self._selected_names("")

        self.assertIn("AppleALC", names)
        self.assertNotIn("VoodooHDA", names)

    def test_disabled_installer_audio_omits_layout_and_boot_arg(self):
        profile = HardwareProfile(cpu_vendor="intel", platform="desktop")

        properties = config_gen._device_properties(profile, 1, audio_enabled=False)
        nvram = config_gen._nvram_section(profile, 1, audio_enabled=False)
        boot_args = nvram["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"]

        self.assertNotIn("PciRoot(0x0)/Pci(0x1f,0x3)", properties["Add"])
        self.assertNotIn("alcid=", boot_args)

    def test_detected_amd_audio_controller_uses_its_pci_path(self):
        profile = HardwareProfile(
            audio_pci_device=0x14,
            audio_pci_function=0x3,
        )

        properties = config_gen._device_properties(profile, 7)

        self.assertIn("PciRoot(0x0)/Pci(0x14,0x3)", properties["Add"])
        self.assertNotIn("PciRoot(0x0)/Pci(0x1f,0x3)", properties["Add"])

    def test_unknown_audio_controller_keeps_intel_pch_fallback(self):
        profile = HardwareProfile()

        properties = config_gen._device_properties(profile, 7)

        self.assertIn("PciRoot(0x0)/Pci(0x1f,0x3)", properties["Add"])

    def test_log_checker_recognizes_voodoohda_prelink_failure(self):
        log = (
            "OpenCore 1.0.7\n"
            "OC: Prelinked injection VoodooHDA.kext "
            "(fallback audio for unsupported codecs) - Invalid Parameter\n"
            "[EB|#LOG:EXITBS:START]\n"
        )

        titles = {finding.title for finding in log_checker.analyze(log)}

        self.assertIn("VoodooHDA cannot be injected from this installer EFI", titles)


class UefiOutputSafetyTests(unittest.TestCase):
    def test_gpu_less_amd_desktop_enables_gop_passthrough(self):
        profile = HardwareProfile(
            cpu_vendor="amd",
            platform="desktop",
            gpu_vendor="",
            dgpu_vendor="nvidia",
        )

        output = config_gen._uefi_section(profile)["Output"]

        self.assertEqual(output["GopPassThrough"], "Enabled")

    def test_supported_amd_dgpu_keeps_gop_passthrough_disabled(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=12,
            platform="desktop",
            gpu_vendor="intel",
            dgpu_vendor="amd",
        )

        output = config_gen._uefi_section(profile)["Output"]

        self.assertEqual(output["GopPassThrough"], "Disabled")

    def test_supported_intel_igpu_keeps_gop_passthrough_disabled(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=10,
            platform="desktop",
            gpu_vendor="intel",
        )

        output = config_gen._uefi_section(profile)["Output"]

        self.assertEqual(output["GopPassThrough"], "Disabled")


class EthernetDevicePropertySafetyTests(unittest.TestCase):
    def test_detected_i225_uses_its_pci_path_for_spoof(self):
        profile = HardwareProfile(
            ethernet_chipset="i225",
            ethernet_pci_device=0x06,
            ethernet_pci_function=0x1,
        )

        properties = config_gen._device_properties(profile, 1)["Add"]

        self.assertIn("PciRoot(0x0)/Pci(0x6,0x1)", properties)
        self.assertNotIn("PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)", properties)
        self.assertEqual(
            properties["PciRoot(0x0)/Pci(0x6,0x1)"]["device-id"],
            bytes([0xF2, 0x15, 0x00, 0x00]),
        )

    def test_unknown_i225_path_keeps_legacy_fallback(self):
        profile = HardwareProfile(ethernet_chipset="i225")

        properties = config_gen._device_properties(profile, 1)["Add"]

        self.assertIn("PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)", properties)

    def test_detected_realtek_uses_its_pci_path_for_built_in(self):
        profile = HardwareProfile(
            ethernet_chipset="rtl8125",
            ethernet_pci_device=0x07,
            ethernet_pci_function=0x2,
        )

        properties = config_gen._device_properties(profile, 1)["Add"]

        self.assertEqual(
            properties["PciRoot(0x0)/Pci(0x7,0x2)"]["built-in"], bytes([0x01])
        )
        self.assertNotIn("PciRoot(0x0)/Pci(0x1C,0x0)/Pci(0x0,0x0)", properties)


class NvmeDevicePropertySafetyTests(unittest.TestCase):
    def test_detected_nvme_uses_its_pci_path_for_built_in(self):
        profile = HardwareProfile(
            nvme_present=True,
            nvme_pci_device=0x08,
            nvme_pci_function=0x1,
        )

        properties = config_gen._device_properties(profile, 1)["Add"]

        self.assertEqual(
            properties["PciRoot(0x0)/Pci(0x8,0x1)"]["built-in"], bytes([0x01])
        )
        self.assertNotIn("PciRoot(0x0)/Pci(0x1D,0x0)", properties)

    def test_unknown_nvme_path_keeps_legacy_fallback(self):
        profile = HardwareProfile(nvme_present=True)

        properties = config_gen._device_properties(profile, 1)["Add"]

        self.assertEqual(
            properties["PciRoot(0x0)/Pci(0x1D,0x0)"]["built-in"], bytes([0x01])
        )


class RequiredSsdtSafetyTests(unittest.TestCase):
    def test_skylake_plus_desktop_gets_standalone_usbx(self):
        profile = HardwareProfile(cpu_generation=8, platform="desktop")

        self.assertIn("SSDT-USBX", config_gen._required_ssdts(profile, []))

    def test_pre_skylake_desktop_does_not_need_usbx(self):
        profile = HardwareProfile(cpu_generation=4, platform="desktop")

        self.assertNotIn("SSDT-USBX", config_gen._required_ssdts(profile, []))

    def test_laptop_gets_bundled_ec_usbx_not_a_duplicate_standalone_one(self):
        profile = HardwareProfile(cpu_generation=8, platform="laptop")

        ssdts = config_gen._required_ssdts(profile, [])

        self.assertIn("SSDT-EC-USBX", ssdts)
        self.assertNotIn("SSDT-USBX", ssdts)

    def test_i2c_trackpad_from_scan_gets_gpi0_even_without_a_voodooi2c_kext(self):
        # kext auto-selection can miss the trackpad when the USB is built from
        # another machine; the scan's touchpad_type must still pull in SSDT-GPI0.
        profile = HardwareProfile(
            cpu_generation=8, platform="laptop", touchpad_type="i2c"
        )

        ssdts = config_gen._required_ssdts(profile, [])

        self.assertIn("SSDT-GPI0", ssdts)
        self.assertIn("SSDT-XOSI", ssdts)

    def test_ps2_laptop_does_not_get_gpi0(self):
        profile = HardwareProfile(
            cpu_generation=8, platform="laptop", touchpad_type="ps2"
        )

        self.assertNotIn("SSDT-GPI0", config_gen._required_ssdts(profile, []))

    def test_modern_amd_desktop_does_not_get_intel_chipset_ssdts(self):
        for generation in (11, 12):
            with self.subTest(generation=generation):
                profile = HardwareProfile(
                    cpu_vendor="amd",
                    cpu_generation=generation,
                    platform="desktop",
                )

                ssdts = config_gen._required_ssdts(profile, [])

                self.assertNotIn("SSDT-AWAC", ssdts)
                self.assertNotIn("SSDT-PMC", ssdts)

    def test_modern_intel_desktop_still_gets_intel_chipset_ssdts(self):
        for generation in (11, 12):
            with self.subTest(generation=generation):
                profile = HardwareProfile(
                    cpu_vendor="intel",
                    cpu_generation=generation,
                    platform="desktop",
                )

                ssdts = config_gen._required_ssdts(profile, [])

                self.assertIn("SSDT-AWAC", ssdts)
                self.assertIn("SSDT-PMC", ssdts)


class XhciUnsupportedChipsetTests(unittest.TestCase):
    def _selected_names(self, board_name: str, cpu_generation: int = 8) -> set[str]:
        profile = HardwareProfile(
            cpu_vendor="intel", cpu_generation=cpu_generation, platform="desktop",
        )
        with (
            patch.object(kexts, "_dmi", side_effect=lambda field: board_name if field == "board_name" else ""),
            patch.object(kexts, "_has_card_reader", return_value=False),
        ):
            return {entry.name for entry in kexts.select_kexts(profile)}

    def test_h370_board_gets_xhci_unsupported_despite_modern_cpu(self):
        names = self._selected_names("asus prime h370-a")
        self.assertIn("XHCI-unsupported", names)

    def test_b360_board_gets_xhci_unsupported(self):
        names = self._selected_names("msi b360m pro-vdh")
        self.assertIn("XHCI-unsupported", names)

    def test_x99_hedt_board_gets_xhci_unsupported_regardless_of_cpu_name(self):
        names = self._selected_names("asrock x99 taichi")
        self.assertIn("XHCI-unsupported", names)

    def test_ordinary_z370_board_does_not_get_it(self):
        names = self._selected_names("asus rog strix z370-e gaming")
        self.assertNotIn("XHCI-unsupported", names)

    def test_amd_system_never_gets_it_even_on_a_matching_board_name(self):
        profile = HardwareProfile(cpu_vendor="amd", cpu_generation=11, platform="desktop")
        with (
            patch.object(kexts, "_dmi", side_effect=lambda field: "b360" if field == "board_name" else ""),
            patch.object(kexts, "_has_card_reader", return_value=False),
        ):
            names = {entry.name for entry in kexts.select_kexts(profile)}
        self.assertNotIn("XHCI-unsupported", names)


class LegacyCpuPowerManagementSafetyTests(unittest.TestCase):
    def _selected_names(self, cpu_generation: int) -> set[str]:
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=cpu_generation,
            platform="laptop",
        )
        with (
            patch.object(kexts, "_dmi", return_value=""),
            patch.object(kexts, "_has_card_reader", return_value=False),
        ):
            return {entry.name for entry in kexts.select_kexts(profile)}

    def test_legacy_pre_sandy_bridge_gets_nullcpupowermanagement_not_cpufriend(self):
        names = self._selected_names(1)

        self.assertIn("NullCPUPowerManagement", names)
        self.assertNotIn("CPUFriend", names)

    def test_modern_cpu_gets_cpufriend_not_nullcpupowermanagement(self):
        names = self._selected_names(8)

        self.assertIn("CPUFriend", names)
        self.assertNotIn("NullCPUPowerManagement", names)


class BooterQuirkSafetyTests(unittest.TestCase):
    def _quirks(self, profile: HardwareProfile, board: str = "") -> dict:
        with patch.object(config_gen, "dmi_field", return_value=board):
            return config_gen._booter_section(profile)["Quirks"]

    def test_skylake_keeps_old_firmware_memory_map_combo(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            cpu_codename="Skylake",
            platform="desktop",
        )

        quirks = self._quirks(profile)

        self.assertTrue(quirks["EnableWriteUnprotector"])
        self.assertFalse(quirks["RebuildAppleMemoryMap"])
        self.assertFalse(quirks["SyncRuntimePermissions"])
        self.assertTrue(quirks["SetupVirtualMap"])
        self.assertFalse(quirks["DevirtualiseMmio"])
        self.assertFalse(quirks["ProtectUefiServices"])

    def test_comet_lake_uses_its_required_memory_map_quirks(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=10,
            cpu_codename="Comet Lake",
            oc_platform="Comet Lake",
            platform="desktop",
        )

        quirks = self._quirks(profile)

        self.assertFalse(quirks["EnableWriteUnprotector"])
        self.assertTrue(quirks["RebuildAppleMemoryMap"])
        self.assertTrue(quirks["SyncRuntimePermissions"])
        self.assertFalse(quirks["SetupVirtualMap"])
        self.assertTrue(quirks["DevirtualiseMmio"])
        self.assertTrue(quirks["ProtectUefiServices"])

    def test_ryzen_uses_modern_memory_map_without_broad_mmio_quirks(self):
        profile = HardwareProfile(
            cpu_vendor="amd",
            cpu_generation=11,
            cpu_codename="Zen 3",
            oc_platform="Ryzen",
            platform="desktop",
        )

        quirks = self._quirks(profile, board="B450 TOMAHAWK")

        self.assertFalse(quirks["EnableWriteUnprotector"])
        self.assertTrue(quirks["RebuildAppleMemoryMap"])
        self.assertTrue(quirks["SyncRuntimePermissions"])
        self.assertTrue(quirks["SetupVirtualMap"])
        self.assertFalse(quirks["DevirtualiseMmio"])
        self.assertFalse(quirks["ProtectUefiServices"])

    def test_b550_disables_setup_virtual_map(self):
        profile = HardwareProfile(
            cpu_vendor="amd",
            cpu_generation=11,
            cpu_codename="Zen 3",
            platform="desktop",
        )

        quirks = self._quirks(profile, board="MAG B550 TOMAHAWK")

        self.assertFalse(quirks["SetupVirtualMap"])


class OpenCoreSchemaSafetyTests(unittest.TestCase):
    def test_generated_config_contains_opencore_107_required_fields(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=8,
            cpu_codename="Coffee Lake",
            oc_platform="Coffee Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 630",
            platform="desktop",
            smbios_model="iMac19,1",
        )
        smbios = SMBIOSData(
            model="iMac19,1",
            serial="C02TEST00001",
            board_serial="C02TESTMLB000001",
            system_uuid="00000000-0000-4000-8000-000000000001",
            rom="001122334455",
        )

        with (
            patch.object(config_gen, "select_kexts", return_value=[]),
            patch.object(config_gen, "dmi_field", return_value=""),
            patch.object(config_gen, "dmi_vendor", return_value=""),
        ):
            config = config_gen.generate(profile, smbios)

        kernel_quirks = config["Kernel"]["Quirks"]
        self.assertTrue({
            "AppleXcpmExtraMsrs",
            "AppleXcpmForceBoost",
            "CustomPciSerialDevice",
            "DisableIoMapperMapping",
            "ExternalDiskIcons",
            "ForceAquantiaEthernet",
            "ForceSecureBootScheme",
            "ThirdPartyDrives",
        }.issubset(kernel_quirks))
        self.assertIn("ClearTaskSwitchBit", config["Booter"]["Quirks"])
        self.assertTrue({
            "HibernateSkipsPicker",
            "InstanceIdentifier",
        }.issubset(config["Misc"]["Boot"]))
        self.assertTrue({
            "LegacyOverwrite",
            "LegacySchema",
        }.issubset(config["NVRAM"]))

        uefi = config["UEFI"]
        self.assertIn("AppleInput", uefi)
        self.assertIn("Unload", uefi)
        self.assertTrue({
            "DisconnectHda",
            "MaximumGain",
            "MinimumAssistGain",
            "MinimumAudibleGain",
            "ResetTrafficClass",
        }.issubset(uefi["Audio"]))
        self.assertTrue({"ConsoleFont", "GopBurstMode"}.issubset(uefi["Output"]))
        self.assertTrue({
            "ResizeUsePciRbIo",
            "ShimRetainProtocol",
        }.issubset(uefi["Quirks"]))

    def test_amd_uses_complete_vanilla_patch_set_with_physical_core_count(self):
        profile = HardwareProfile(
            cpu_vendor="amd",
            cpu_generation=11,
            cpu_codename="Zen 3",
            oc_platform="Ryzen",
            core_count=12,
            gpu_vendor="amd",
            gpu_name="AMD Radeon RX 6600",
            platform="desktop",
        )

        with patch.object(config_gen, "dmi_vendor", return_value=""):
            kernel = config_gen._kernel_section(profile, [])

        patches = kernel["Patch"]
        core_patches = [
            entry for entry in patches
            if "Force cpuid_cores_per_package" in entry["Comment"]
        ]

        self.assertTrue(kernel["Quirks"]["ProvideCurrentCpuInfo"])
        self.assertEqual(len(patches), 25)
        self.assertEqual(len(core_patches), 4)
        self.assertTrue(all(entry["Replace"][1] == 12 for entry in core_patches))
        for entry in patches:
            with self.subTest(comment=entry["Comment"]):
                self.assertEqual(len(entry["Find"]), len(entry["Replace"]))

    def test_newer_intel_cpu_uses_documented_comet_lake_cpuid_spoof(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=12,
            cpu_codename="Alder Lake",
            oc_platform="Alder Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 770",
            dgpu_vendor="amd",
            platform="desktop",
        )

        with patch.object(config_gen, "dmi_vendor", return_value=""):
            kernel = config_gen._kernel_section(profile, [])

        emulate = kernel["Emulate"]
        self.assertEqual(
            emulate["Cpuid1Data"],
            bytes.fromhex("55060A00" + "00000000" * 3),
        )
        self.assertEqual(
            emulate["Cpuid1Mask"],
            bytes.fromhex("FFFFFFFF" + "00000000" * 3),
        )
        self.assertTrue(kernel["Quirks"]["ProvideCurrentCpuInfo"])


class XcpmExtraMsrsSafetyTests(unittest.TestCase):
    def _quirk(self, profile: HardwareProfile) -> bool:
        with patch.object(config_gen, "dmi_vendor", return_value=""):
            return config_gen._kernel_section(profile, [])["Quirks"]["AppleXcpmExtraMsrs"]

    def test_pentium_enables_the_quirk(self):
        profile = HardwareProfile(
            cpu_vendor="intel", cpu_name="Intel(R) Pentium(R) CPU G4560",
            cpu_generation=7, platform="desktop",
        )
        self.assertTrue(self._quirk(profile))

    def test_xeon_enables_the_quirk(self):
        profile = HardwareProfile(
            cpu_vendor="intel", cpu_name="Intel(R) Xeon(R) CPU E5-2680 v4",
            cpu_generation=5, platform="desktop",
        )
        self.assertTrue(self._quirk(profile))

    def test_ordinary_core_i_cpu_does_not_enable_the_quirk(self):
        profile = HardwareProfile(
            cpu_vendor="intel", cpu_name="Intel(R) Core(TM) i7-8700K CPU",
            cpu_generation=8, platform="desktop",
        )
        self.assertFalse(self._quirk(profile))


class IntelGraphicsSafetyTests(unittest.TestCase):
    def test_sandy_bridge_laptop_uses_snb_platform_id_without_dvmt_patch(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=2,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 3000",
            platform="laptop",
        )

        properties = config_gen._device_properties(profile, 1)
        igpu = properties["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]

        self.assertEqual(igpu["AAPL,snb-platform-id"], bytes.fromhex("00000100"))
        self.assertNotIn("AAPL,ig-platform-id", igpu)
        self.assertNotIn("framebuffer-patch-enable", igpu)

    def test_ivy_bridge_laptop_does_not_get_newer_dvmt_patch(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=3,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 4000",
            platform="laptop",
        )

        properties = config_gen._device_properties(profile, 1)
        igpu = properties["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]

        self.assertEqual(igpu["AAPL,ig-platform-id"], bytes.fromhex("03006601"))
        self.assertNotIn("framebuffer-patch-enable", igpu)

    def test_sandy_bridge_desktop_uses_display_and_headless_values(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=2,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 3000",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("10000300"), bytes.fromhex("26010000")),
        )
        self.assertEqual(
            config_gen._igpu_config(profile, headless=True),
            (bytes.fromhex("00000500"), bytes.fromhex("02010000")),
        )

    def test_ivy_bridge_desktop_uses_display_and_headless_values(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=3,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 4000",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("0A006601"), None),
        )
        self.assertEqual(
            config_gen._igpu_config(profile, headless=True),
            (bytes.fromhex("07006201"), None),
        )

    def test_haswell_hd4600_laptop_uses_supported_spoof_and_cursor_patch(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=4,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 4600",
            platform="laptop",
        )

        properties = config_gen._device_properties(profile, 1)
        igpu = properties["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]

        self.assertEqual(igpu["AAPL,ig-platform-id"], bytes.fromhex("0600260A"))
        self.assertEqual(igpu["device-id"], bytes.fromhex("12040000"))
        self.assertEqual(igpu["framebuffer-patch-enable"], bytes.fromhex("01000000"))
        self.assertEqual(igpu["framebuffer-cursormem"], bytes.fromhex("00009000"))
        self.assertNotIn("framebuffer-stolenmem", igpu)

    def test_haswell_iris_laptop_uses_mobile_iris_framebuffer_without_spoof(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=4,
            gpu_vendor="intel",
            gpu_name="Intel Iris Pro Graphics 5200",
            platform="laptop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("0500260A"), None),
        )

    def test_haswell_hd5000_laptop_uses_mobile_iris_framebuffer_without_spoof(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=4,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 5000",
            platform="laptop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("0500260A"), None),
        )

    def test_haswell_desktop_uses_display_and_headless_framebuffers(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=4,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 4600",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("0300220D"), None),
        )
        self.assertEqual(
            config_gen._igpu_config(profile, headless=True),
            (bytes.fromhex("04001204"), None),
        )

    def test_haswell_hd4400_desktop_uses_supported_device_spoof(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=4,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 4400",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("0300220D"), bytes.fromhex("12040000")),
        )

    def test_broadwell_uses_documented_mobile_and_desktop_framebuffers(self):
        laptop = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=5,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 5500",
            platform="laptop",
        )
        desktop = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=5,
            gpu_vendor="intel",
            gpu_name="Intel Iris Pro Graphics 6200",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(laptop),
            (bytes.fromhex("06002616"), None),
        )
        self.assertEqual(
            config_gen._igpu_config(desktop),
            (bytes.fromhex("07002216"), None),
        )
        self.assertEqual(
            config_gen._igpu_config(desktop, headless=True),
            (bytes.fromhex("07002216"), None),
        )

    def test_skylake_hd530_laptop_uses_mobile_framebuffer(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 530",
            platform="laptop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("00001619"), None),
        )

    def test_skylake_desktop_uses_display_and_headless_framebuffers(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 530",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("00001219"), None),
        )
        self.assertEqual(
            config_gen._igpu_config(profile, headless=True),
            (bytes.fromhex("01001219"), None),
        )

    def test_skylake_is_spoofed_as_matching_kaby_lake_gpu_on_ventura(self):
        hd520 = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 520",
            platform="laptop",
        )
        hd530 = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 530",
            platform="laptop",
        )
        desktop = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 530",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(hd520, macos_major=13),
            (bytes.fromhex("00001659"), bytes.fromhex("16590000")),
        )
        self.assertEqual(
            config_gen._igpu_config(hd530, macos_major=13),
            (bytes.fromhex("00001B59"), bytes.fromhex("1B590000")),
        )
        self.assertEqual(
            config_gen._igpu_config(desktop, macos_major=13),
            (bytes.fromhex("00001259"), bytes.fromhex("12590000")),
        )
        self.assertEqual(
            config_gen._igpu_config(desktop, headless=True, macos_major=13),
            (bytes.fromhex("03001259"), bytes.fromhex("12590000")),
        )

    def test_skylake_ventura_properties_include_graphics_tile_fix(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 530",
            platform="laptop",
        )

        properties = config_gen._device_properties(
            profile,
            1,
            macos_major=13,
        )
        igpu = properties["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]

        self.assertEqual(igpu["AAPL,ig-platform-id"], bytes.fromhex("00001B59"))
        self.assertEqual(igpu["device-id"], bytes.fromhex("1B590000"))
        self.assertEqual(igpu["AAPL,GfxYTile"], bytes.fromhex("01000000"))

    def test_efi_checker_accepts_native_and_ventura_skylake_framebuffers(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 530",
            platform="laptop",
        )

        for platform_id in ("00001619", "00001B59"):
            with self.subTest(platform_id=platform_id):
                config = {
                    "DeviceProperties": {
                        "Add": {
                            "PciRoot(0x0)/Pci(0x2,0x0)": {
                                "AAPL,ig-platform-id": bytes.fromhex(platform_id),
                            },
                        },
                    },
                    "Kernel": {"Add": []},
                    "PlatformInfo": {"Generic": {}},
                }
                results = []

                efi_check._check_hardware_mismatch(config, profile, results)

                self.assertFalse(any(
                    level == "warn" and "ig-platform-id" in message
                    for level, message in results
                ))

    def test_skylake_unsupported_variants_use_documented_device_spoofs(self):
        hd510 = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 510",
            platform="laptop",
        )
        p530 = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=6,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics P530",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(hd510),
            (bytes.fromhex("00001B19"), bytes.fromhex("02190000")),
        )
        self.assertEqual(
            config_gen._igpu_config(p530),
            (bytes.fromhex("00001219"), bytes.fromhex("1B190000")),
        )

    def test_intel_xe_igpu_is_not_given_a_fake_framebuffer(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=12,
            cpu_codename="Alder Lake",
            oc_platform="Alder Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 770",
            dgpu_vendor="amd",
            platform="desktop",
        )

        self.assertEqual(config_gen._igpu_config(profile), (b"", None))

        properties = config_gen._device_properties(profile, 1)

        self.assertNotIn(
            "PciRoot(0x0)/Pci(0x2,0x0)",
            properties["Add"],
        )

    def test_kaby_lake_hd630_laptop_uses_mobile_framebuffer(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=7,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 630",
            platform="laptop",
        )

        properties = config_gen._device_properties(profile, 1)
        igpu = properties["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]

        self.assertEqual(igpu["AAPL,ig-platform-id"], bytes.fromhex("00001B59"))
        self.assertEqual(igpu["framebuffer-stolenmem"], bytes.fromhex("00003001"))
        self.assertEqual(igpu["framebuffer-fbmem"], bytes.fromhex("00009000"))

    def test_laptop_dgpu_does_not_force_headless_or_disable_before_user_choice(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=7,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 630",
            dgpu_vendor="nvidia",
            platform="laptop",
        )

        properties = config_gen._device_properties(profile, 1)
        igpu = properties["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]

        self.assertEqual(igpu["AAPL,ig-platform-id"], bytes.fromhex("00001B59"))
        self.assertNotIn("disable-external-gpu", igpu)

    def test_optimus_laptop_disables_nvidia_via_boot_arg(self):
        profile = HardwareProfile(
            gpu_vendor="intel",
            dgpu_vendor="nvidia",
            platform="laptop",
        )

        nvram = config_gen._nvram_section(profile, 1)
        boot_args = nvram["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"]

        self.assertIn("nv_disable=1", boot_args.split())

    def test_intel_only_laptop_does_not_get_nvidia_disable_boot_arg(self):
        profile = HardwareProfile(
            gpu_vendor="intel",
            platform="laptop",
        )

        nvram = config_gen._nvram_section(profile, 1)
        boot_args = nvram["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"]

        self.assertNotIn("nv_disable=1", boot_args.split())

    def test_dgpu_choice_uses_stable_igpu_property_and_can_be_reversed(self):
        config = {
            "DeviceProperties": {
                "Add": {
                    "PciRoot(0x0)/Pci(0x2,0x0)": {
                        "AAPL,ig-platform-id": bytes.fromhex("00001B59"),
                    },
                },
            },
        }

        config_editor.set_dgpu_disabled(config, True)

        igpu = config["DeviceProperties"]["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]
        self.assertEqual(igpu["disable-external-gpu"], bytes.fromhex("01000000"))
        self.assertTrue(config_editor.get_dgpu_disabled(config))

        config_editor.set_dgpu_disabled(config, False)

        self.assertNotIn("disable-external-gpu", igpu)
        self.assertFalse(config_editor.get_dgpu_disabled(config))

    def test_amd_desktop_dgpu_keeps_acceleration_and_uses_headless_igpu(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=8,
            cpu_codename="Coffee Lake",
            oc_platform="Coffee Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 630",
            dgpu_vendor="amd",
            dgpu_name="AMD Radeon RX 580",
            platform="desktop",
        )

        properties = config_gen._device_properties(profile, 1)
        nvram = config_gen._nvram_section(profile, 1)
        igpu = properties["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]
        boot_args = nvram["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"]

        self.assertEqual(igpu["AAPL,ig-platform-id"], bytes.fromhex("0300913E"))
        self.assertNotIn("disable-external-gpu", igpu)
        self.assertNotIn("-radvesa", boot_args)

    def test_kaby_lake_hd630_desktop_keeps_display_and_headless_variants(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=7,
            gpu_vendor="intel",
            gpu_name="Intel HD Graphics 630",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("00001259"), None),
        )
        self.assertEqual(
            config_gen._igpu_config(profile, headless=True),
            (bytes.fromhex("03001259"), None),
        )

    def test_kaby_lake_r_uhd620_uses_amber_lake_framebuffer_and_spoof(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=8,
            cpu_codename="Kaby Lake-R",
            oc_platform="Kaby Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 620",
            platform="laptop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("0000C087"), bytes.fromhex("16590000")),
        )

    def test_whiskey_lake_uhd620_uses_coffee_lake_mobile_values(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=8,
            cpu_codename="Whiskey Lake",
            oc_platform="Coffee Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 620",
            platform="laptop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("00009B3E"), bytes.fromhex("9B3E0000")),
        )

    def test_coffee_lake_uhd630_uses_mobile_framebuffer(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=8,
            cpu_codename="Coffee Lake-H",
            oc_platform="Coffee Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 630",
            platform="laptop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("0900A53E"), bytes.fromhex("9B3E0000")),
        )

    def test_coffee_lake_desktop_uses_documented_display_and_headless_ids(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=8,
            cpu_codename="Coffee Lake",
            oc_platform="Coffee Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 630",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("07009B3E"), None),
        )
        self.assertEqual(
            config_gen._igpu_config(profile, headless=True),
            (bytes.fromhex("0300913E"), None),
        )

    def test_comet_lake_desktop_uses_documented_display_and_headless_ids(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=10,
            cpu_codename="Comet Lake",
            oc_platform="Comet Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 630",
            platform="desktop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("07009B3E"), None),
        )
        self.assertEqual(
            config_gen._igpu_config(profile, headless=True),
            (bytes.fromhex("0300C89B"), None),
        )

    def test_comet_lake_uhd620_uses_supported_mobile_spoof(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=10,
            cpu_codename="Comet Lake-H",
            oc_platform="Comet Lake",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 620",
            platform="laptop",
        )

        self.assertEqual(
            config_gen._igpu_config(profile),
            (bytes.fromhex("00009B3E"), bytes.fromhex("9B3E0000")),
        )

    def test_config_editor_suggests_current_mobile_framebuffers(self):
        expected = {
            "0116": "00000100",
            "0126": "00000100",
            "0162": "0a006601",
            "0416": "0600260a",
            "0412": "0300220d",
            "0d26": "0500260a",
            "1616": "06002616",
            "1626": "06002616",
            "191b": "00001619",
            "1912": "00001219",
            "1926": "00001619",
            "5916": "00001b59",
            "5917": "0000c087",
            "3ea0": "00009b3e",
            "3ea9": "00009b3e",
            "9bc4": "0900a53e",
            "9bca": "00009b3e",
        }

        for device_id, platform_id in expected.items():
            with self.subTest(device_id=device_id):
                suggestions = config_editor.suggest_framebuffers(device_id)
                self.assertTrue(suggestions)
                self.assertEqual(suggestions[0][0], platform_id)

    def test_config_editor_reads_and_updates_sandy_bridge_platform_key(self):
        config = {
            "DeviceProperties": {
                "Add": {
                    "PciRoot(0x0)/Pci(0x2,0x0)": {
                        "AAPL,snb-platform-id": bytes.fromhex("00000100"),
                    },
                },
            },
        }

        self.assertEqual(config_editor.get_igpu_platform_id(config), "00000100")

        config_editor.set_igpu_platform_id(config, "10000300")

        igpu = config["DeviceProperties"]["Add"]["PciRoot(0x0)/Pci(0x2,0x0)"]
        self.assertEqual(igpu["AAPL,snb-platform-id"], bytes.fromhex("10000300"))
        self.assertNotIn("AAPL,ig-platform-id", igpu)


if __name__ == "__main__":
    unittest.main()
