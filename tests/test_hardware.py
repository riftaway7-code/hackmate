import sys
import unittest
import json
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hardware


class OpenCorePlatformDetectionTests(unittest.TestCase):
    def test_linux_11th_gen_desktop_is_rocket_lake(self):
        profile = hardware.HardwareProfile()
        cpuinfo = "vendor_id : GenuineIntel\nmodel name : Intel(R) Core(TM) i7-11700 CPU"

        with patch.object(hardware, "_run", side_effect=[cpuinfo, "", "", "", "", ""]):
            hardware._detect_cpu_linux(profile)
            hardware._detect_platform_linux(profile)
        hardware._detect_oc_platform(profile)

        self.assertEqual(profile.platform, "desktop")
        self.assertEqual(profile.oc_platform, "Rocket Lake")

    def test_windows_11th_gen_laptop_is_tiger_lake(self):
        profile = hardware.HardwareProfile()
        responses = iter(["Intel(R) Core(TM) i7-1165G7", "4", "8", "10", "0", "0"])

        with patch.object(hardware, "_ps", side_effect=lambda query: next(responses)):
            hardware._detect_cpu_windows(profile)
            hardware._detect_platform_windows(profile)
        hardware._detect_oc_platform(profile)

        self.assertEqual(profile.platform, "laptop")
        self.assertEqual(profile.oc_platform, "Tiger Lake")

    def test_device_id_platform_is_not_overwritten(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="intel", cpu_generation=11, platform="desktop",
            oc_platform="Device ID platform",
        )

        hardware._detect_oc_platform(profile)

        self.assertEqual(profile.oc_platform, "Device ID platform")

    def test_coffee_lake_is_unchanged(self):
        for generation in (8, 9):
            with self.subTest(generation=generation):
                profile = hardware.HardwareProfile(
                    cpu_vendor="intel", cpu_generation=generation, platform="desktop"
                )
                hardware._detect_oc_platform(profile)
                self.assertEqual(profile.oc_platform, "Coffee Lake")


class LinuxAudioDetectionTests(unittest.TestCase):
    def test_audio_controller_pci_device_and_function_are_captured(self):
        profile = hardware.HardwareProfile(raw_pci=[
            "0000:14.3 Audio device [0403]: Advanced Micro Devices, Inc. "
            "Family 17h HD Audio Controller [1022:1457]",
        ])

        with patch.object(hardware, "_get_hda_codec_linux", return_value="ALC1220"):
            hardware._detect_audio_linux(profile)

        self.assertEqual(profile.audio_pci_device, 0x14)
        self.assertEqual(profile.audio_pci_function, 0x3)

    def test_onboard_audio_is_preferred_over_later_nvidia_hdmi_audio(self):
        profile = hardware.HardwareProfile(raw_pci=[
            "00:1f.3 Audio device [0403]: Intel Corporation "
            "HD Audio Controller [8086:a348]",
            "01:00.1 Audio device [0403]: NVIDIA Corporation "
            "HDMI Audio Controller [10de:10f9]",
        ])

        with patch.object(hardware, "_get_hda_codec_linux", return_value="ALC1220"):
            hardware._detect_audio_linux(profile)

        self.assertIn("Intel Corporation", profile.audio_name)
        self.assertNotIn("NVIDIA", profile.audio_name)
        self.assertEqual(profile.audio_pci_device, 0x1f)
        self.assertEqual(profile.audio_pci_function, 0x3)


class LinuxNetworkDetectionTests(unittest.TestCase):
    def test_i225_ethernet_is_identified(self):
        profile = hardware.HardwareProfile(raw_pci=[
            "04:06.1 Ethernet controller: Intel Corporation "
            "Ethernet Controller I225-V (rev 03)",
        ])

        hardware._detect_network_linux(profile)

        self.assertEqual(profile.ethernet_chipset, "i225")
        self.assertEqual(profile.ethernet_pci_device, 0x06)
        self.assertEqual(profile.ethernet_pci_function, 0x1)

    def test_i226_ethernet_is_identified(self):
        profile = hardware.HardwareProfile(raw_pci=[
            "0000:04:00.0 Ethernet controller: Intel Corporation "
            "Ethernet Controller I226-V (rev 04)",
        ])

        hardware._detect_network_linux(profile)

        self.assertEqual(profile.ethernet_chipset, "i226")


class LinuxNvmeDetectionTests(unittest.TestCase):
    def test_nvme_controller_pci_device_and_function_are_captured(self):
        profile = hardware.HardwareProfile(raw_pci=[
            "09:05.1 Non-Volatile memory controller: Samsung Electronics Co Ltd "
            "NVMe SSD Controller",
        ])

        hardware._detect_nvme_linux(profile)

        self.assertEqual(profile.nvme_pci_device, 0x05)
        self.assertEqual(profile.nvme_pci_function, 0x1)


class DiscreteGpuPromptTests(unittest.TestCase):
    def test_optimus_laptop_gets_disable_choice(self):
        profile = hardware.HardwareProfile(
            gpu_vendor="intel",
            dgpu_vendor="nvidia",
            platform="laptop",
        )

        self.assertTrue(hardware.needs_dgpu_disable_prompt(profile))

    def test_desktop_nvidia_gets_disable_choice(self):
        profile = hardware.HardwareProfile(
            gpu_vendor="intel",
            dgpu_vendor="nvidia",
            platform="desktop",
        )

        self.assertTrue(hardware.needs_dgpu_disable_prompt(profile))

    def test_desktop_amd_stays_enabled_for_display_output(self):
        profile = hardware.HardwareProfile(
            gpu_vendor="intel",
            dgpu_vendor="amd",
            platform="desktop",
        )

        self.assertFalse(hardware.needs_dgpu_disable_prompt(profile))

    def test_amd_primary_with_nvidia_dgpu_on_desktop_still_gets_disable_choice(self):
        profile = hardware.HardwareProfile(
            gpu_vendor="amd",
            dgpu_vendor="nvidia",
            platform="desktop",
        )

        self.assertTrue(hardware.needs_dgpu_disable_prompt(profile))


class GpuClassificationTests(unittest.TestCase):
    def test_rx_vega_10_is_classified_as_integrated(self):
        name = "AMD Radeon(TM) RX Vega 10 Graphics"

        self.assertEqual(hardware._classify_gpus([name]), (name, "amd", "", ""))

    def test_rx_series_cards_remain_discrete(self):
        for name in ("AMD Radeon RX 580", "AMD Radeon RX 5700 XT", "AMD Radeon RX 6600"):
            with self.subTest(name=name):
                self.assertEqual(hardware._classify_gpus([name]), ("", "", name, "amd"))


class IntelGenerationInferenceTests(unittest.TestCase):
    def test_core_ultra_100_series_is_meteor_lake(self):
        profile = hardware.HardwareProfile(cpu_name="Intel Core Ultra 7 155H")

        hardware._infer_intel_gen_from_name(profile)

        self.assertGreaterEqual(profile.cpu_generation, 11)
        self.assertEqual(profile.cpu_codename, "Meteor Lake")
        self.assertEqual(profile.oc_platform, "Meteor Lake")

    def test_core_ultra_200_series_remains_arrow_lake(self):
        profile = hardware.HardwareProfile(cpu_name="Intel Core Ultra 9 285K")

        hardware._infer_intel_gen_from_name(profile)

        self.assertEqual(profile.cpu_generation, 15)
        self.assertEqual(profile.cpu_codename, "Arrow Lake")
        self.assertEqual(profile.oc_platform, "Arrow Lake")


class AmdGenerationInferenceTests(unittest.TestCase):
    def test_2000_and_3000_series_apu_generations(self):
        cases = (
            ("AMD Ryzen 5 2400G", 8, "Zen"),
            ("AMD Ryzen 5 3400G", 8, "Zen+"),
            ("AMD Ryzen 5 3500U", 8, "Zen+"),
            ("AMD Ryzen 5 2600", 8, "Zen+"),
            ("AMD Ryzen 5 3600", 10, "Zen 2"),
        )

        for cpu_name, generation, codename in cases:
            with self.subTest(cpu_name=cpu_name):
                profile = hardware.HardwareProfile(cpu_name=cpu_name)

                hardware._detect_amd_gen(profile)

                self.assertEqual(profile.cpu_generation, generation)
                self.assertEqual(profile.cpu_codename, codename)


class HardwareWarningTests(unittest.TestCase):
    def test_realtek_wifi_warns_no_macos_driver(self):
        profile = hardware.HardwareProfile(wifi_chipset="realtek")

        warnings = hardware.hardware_warnings(profile)

        self.assertTrue(any("Realtek PCI WiFi" in w for w in warnings))

    def test_tiger_lake_laptop_warns_that_internal_graphics_are_unusable(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=11,
            gpu_vendor="intel",
            gpu_name="Intel Iris Xe Graphics",
            platform="laptop",
        )

        warnings = hardware.hardware_warnings(profile)

        self.assertTrue(any("no macOS driver" in warning for warning in warnings))
        self.assertTrue(any("laptop internal displays" in warning for warning in warnings))

    def test_meteor_lake_laptop_warns_that_internal_graphics_are_unusable(self):
        profile = hardware.HardwareProfile(
            cpu_name="Intel Core Ultra 7 155H",
            cpu_vendor="intel",
            gpu_vendor="intel",
            gpu_name="Intel Arc Graphics",
            platform="laptop",
        )
        hardware._infer_intel_gen_from_name(profile)

        warnings = hardware.hardware_warnings(profile)

        self.assertGreaterEqual(profile.cpu_generation, 11)
        self.assertTrue(any("no macOS driver" in warning for warning in warnings))
        self.assertTrue(any("laptop internal displays" in warning for warning in warnings))

    def test_alder_lake_desktop_requires_supported_amd_graphics(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=12,
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 770",
            platform="desktop",
        )

        warnings = hardware.hardware_warnings(profile)

        self.assertTrue(any("supported AMD discrete GPU is required" in warning for warning in warnings))

    def test_newer_intel_desktop_with_amd_dgpu_gets_disable_igpu_guidance(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=13,
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 770",
            dgpu_vendor="amd",
            dgpu_name="AMD Radeon RX 6600",
            platform="desktop",
        )

        warnings = hardware.hardware_warnings(profile)

        self.assertTrue(any("disable it in BIOS" in warning for warning in warnings))

    def test_gpu_less_amd_desktop_warns_about_gop_and_headless_setup(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="amd",
            platform="desktop",
            gpu_vendor="",
            dgpu_vendor="nvidia",
        )

        warnings = hardware.hardware_warnings(profile)

        self.assertTrue(any("GOP passthrough" in warning for warning in warnings))
        self.assertTrue(any("Screen Sharing" in warning for warning in warnings))

    def test_supported_amd_dgpu_does_not_get_gpu_less_warning(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=12,
            platform="desktop",
            gpu_vendor="intel",
            dgpu_vendor="amd",
        )

        warnings = hardware.hardware_warnings(profile)

        self.assertFalse(any("GOP passthrough" in warning for warning in warnings))

    def test_supported_intel_igpu_does_not_get_gpu_less_warning(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=10,
            platform="desktop",
            gpu_vendor="intel",
        )

        warnings = hardware.hardware_warnings(profile)

        self.assertFalse(any("GOP passthrough" in warning for warning in warnings))


class IntelWifiWarningTests(unittest.TestCase):
    def test_intel_wifi_warning_notes_broadcom_also_needs_a_root_patch(self):
        profile = hardware.HardwareProfile(wifi_chipset="intel")

        warnings = hardware.hardware_warnings(profile)

        self.assertTrue(any("root patch" in warning for warning in warnings))
        self.assertFalse(any("BCM94360CD" in warning for warning in warnings))

    def test_broadcom_wifi_does_not_get_the_recommendation(self):
        profile = hardware.HardwareProfile(wifi_chipset="broadcom")

        warnings = hardware.hardware_warnings(profile)

        self.assertFalse(any("BCM94360CD" in warning for warning in warnings))


_REAL_SP_AIRPORT_NO_CARD = """Wi-Fi:

      Software Versions:
          CoreWLAN: 16.0 (1657)
          CoreWLANKit: 16.0 (1657)
          Menu Extra: 1.0 (19150.2)
          System Information: 15.0 (1502)
          IO80211 Family: 12.0 (1200.13.1)
          Diagnostics: 11.0 (1163)
          AirPort Utility: 6.3.9 (639.29)
"""

_REAL_SP_ETHERNET_I219 = """Ethernet:

    Intel I219-V Ethernet Connection:

      Bus: PCI
      Vendor ID: 0x8086
      Device ID: 0x15d7
      Subsystem Vendor ID: 0x17aa
      Subsystem ID: 0x2258
      Revision ID: 0x0021
      Driver: com.insanelymac.IntelMausiEthernet
      BSD Device Name: en0
      MAC Address: 98:fa:9b:23:b0:b6
      AVB Support: No
      Maximum Link Speed: 1 Gb/s
"""


class MacOSNetworkDetectionTests(unittest.TestCase):
    def _sp_for(self, mapping: dict) -> callable:
        return lambda data_type: mapping.get(data_type, "")

    def test_working_i219_ethernet_is_identified_not_reported_as_none(self):
        profile = hardware.HardwareProfile()
        with patch.object(hardware, "_sp", side_effect=self._sp_for({
            "SPEthernetDataType": _REAL_SP_ETHERNET_I219,
            "SPAirPortDataType": _REAL_SP_AIRPORT_NO_CARD,
        })):
            hardware._detect_network_macos(profile)

        self.assertEqual(profile.ethernet_chipset, "i219")
        self.assertIn("I219", profile.ethernet_name)

    def test_no_wifi_card_present_correctly_reports_no_wifi(self):
        profile = hardware.HardwareProfile()
        with patch.object(hardware, "_sp", side_effect=self._sp_for({
            "SPEthernetDataType": _REAL_SP_ETHERNET_I219,
            "SPAirPortDataType": _REAL_SP_AIRPORT_NO_CARD,
        })):
            hardware._detect_network_macos(profile)

        self.assertEqual(profile.wifi_chipset, "")


class MacOSAudioDetectionTests(unittest.TestCase):
    def test_virtual_blackhole_device_does_not_override_real_codec(self):
        sp = (
            "Audio:\n"
            "\n"
            "    Devices:\n"
            "\n"
            "        Realtek ALC295:\n"
            "\n"
            "        BlackHole 2ch:\n"
            "\n"
            "          Manufacturer: Existential Audio Inc.\n"
        )
        profile = hardware.HardwareProfile()
        with patch.object(hardware, "_sp", return_value=sp):
            hardware._detect_audio_macos(profile)

        self.assertEqual(profile.audio_codec, "ALC295")

    def test_virtual_only_audio_falls_back_without_claiming_a_codec(self):
        sp = (
            "Audio:\n"
            "\n"
            "    Devices:\n"
            "\n"
            "        BlackHole 16ch:\n"
            "\n"
            "          Input Channels: 16\n"
            "          Manufacturer: Existential Audio Inc.\n"
            "          Output Channels: 16\n"
            "          Transport: Virtual\n"
            "\n"
            "        BlackHole 2ch:\n"
            "\n"
            "          Default Output Device: Yes\n"
            "          Input Channels: 2\n"
            "          Manufacturer: Existential Audio Inc.\n"
            "          Output Channels: 2\n"
            "          Transport: Virtual\n"
        )
        profile = hardware.HardwareProfile()
        with patch.object(hardware, "_sp", return_value=sp):
            hardware._detect_audio_macos(profile)

        self.assertEqual(profile.audio_codec, "")
        self.assertEqual(profile.audio_name, "")


_REAL_SP_PCI_T480S = """PCI:

    Intel UHD Graphics 620:

      Name: display
      Type: VGA compatible controller
      Driver Installed: Yes
      MSI: Yes
      Bus: PCI
      Slot: Internal@0,2,0
      Vendor ID: 0x8086
      Device ID: 0x5916
      Subsystem Vendor ID: 0x17aa
      Subsystem ID: 0x2258
      Revision ID: 0x0007
      Link Width: x0
      Link Status: Link up

    Sunrise Point-LP HD Audio:

      Name: pci8086,9d71
      Type: Audio device
      Driver Installed: No
      MSI: No
      Bus: PCI
      Slot: Internal@0,31,3
      Vendor ID: 0x8086
      Device ID: 0x9d71
      Subsystem Vendor ID: 0x17aa
      Subsystem ID: 0x2258
      Revision ID: 0x0021

    ExpressCard:

      Name: pci8086,15bf
      Type: System peripheral
      Driver Installed: Yes
      MSI: Yes
      Bus: PCI
      Slot: Internal@0,28,4/0,0/0,0/0,0
      Vendor ID: 0x8086
      Device ID: 0x15bf
      Subsystem Vendor ID: 0x2222
      Subsystem ID: 0x1111
      Revision ID: 0x0001
      Link Width: x4
      Link Speed: 2.5 GT/s
      Link Status: Link up

    ExpressCard:

      Name: pci8086,15c1
      Type: USB controller
      Driver Installed: Yes
      MSI: Yes
      Bus: PCI
      Slot: Internal@0,28,4/0,0/2,0/0,0
      Vendor ID: 0x8086
      Device ID: 0x15c1
      Subsystem Vendor ID: 0x2222
      Subsystem ID: 0x1111
      Revision ID: 0x0001
      Link Width: x4
      Link Speed: 2.5 GT/s
      Link Status: Link up
"""


class MacOSThunderboltDetectionTests(unittest.TestCase):
    def test_alpine_ridge_controller_detected_from_pci_ids_not_name(self):
        profile = hardware.HardwareProfile()
        with (
            patch.object(hardware, "_sp", side_effect=lambda dt: (
                _REAL_SP_PCI_T480S if dt == "SPPCIDataType" else ""
            )),
            patch.object(hardware, "_run", return_value=""),
        ):
            hardware._detect_platform_macos(profile)

        self.assertTrue(profile.has_thunderbolt)

    def test_machine_without_a_thunderbolt_controller_is_not_a_false_positive(self):
        profile = hardware.HardwareProfile()
        with (
            patch.object(hardware, "_sp", side_effect=lambda dt: (
                _REAL_SP_ETHERNET_I219 if dt == "SPPCIDataType" else ""
            )),
            patch.object(hardware, "_run", return_value=""),
        ):
            hardware._detect_platform_macos(profile)

        self.assertFalse(profile.has_thunderbolt)


class MacOSPCIDetectionTests(unittest.TestCase):
    def test_uses_system_profiler_instead_of_lspci(self):
        output = "Intel UHD Graphics 630:\n    Vendor ID: 0x8086"

        with (
            patch("platform.system", return_value="Darwin"),
            patch.object(hardware, "_run", return_value=output) as run,
        ):
            lines = hardware._lspci()

        run.assert_called_once_with(["system_profiler", "SPPCIDataType"])
        self.assertEqual(lines, output.splitlines())

    def test_missing_system_profiler_does_not_crash(self):
        with (
            patch("platform.system", return_value="Darwin"),
            patch.object(hardware.subprocess, "run", side_effect=FileNotFoundError),
        ):
            self.assertEqual(hardware._lspci(), [])


class MacOSGpuDetectionTests(unittest.TestCase):
    def test_intel_igpu_remains_primary_when_amd_dgpu_is_also_present(self):
        output = """
Intel UHD Graphics 630:
    Chipset Model: Intel UHD Graphics 630
AMD Radeon RX 580:
    Chipset Model: AMD Radeon RX 580
"""
        profile = hardware.HardwareProfile()

        with patch.object(hardware, "_sp", return_value=output):
            hardware._detect_gpu_macos(profile)

        self.assertEqual(profile.gpu_name, "Intel UHD Graphics 630")
        self.assertEqual(profile.gpu_vendor, "intel")
        self.assertEqual(profile.dgpu_name, "AMD Radeon RX 580")
        self.assertEqual(profile.dgpu_vendor, "amd")

    def test_single_gpu_remains_primary(self):
        cases = (
            ("Chipset Model: Intel Iris Plus Graphics", "Intel Iris Plus Graphics", "intel"),
            ("Chipset Model: AMD Radeon RX 580", "AMD Radeon RX 580", "amd"),
            ("Chipset Model: NVIDIA GeForce GTX 1080", "NVIDIA GeForce GTX 1080", "nvidia"),
        )

        for output, expected_name, expected_vendor in cases:
            with self.subTest(vendor=expected_vendor):
                profile = hardware.HardwareProfile()
                with patch.object(hardware, "_sp", return_value=output):
                    hardware._detect_gpu_macos(profile)

                self.assertEqual(profile.gpu_name, expected_name)
                self.assertEqual(profile.gpu_vendor, expected_vendor)
                self.assertEqual(profile.dgpu_name, "")
                self.assertEqual(profile.dgpu_vendor, "")


class WindowsAudioDetectionTests(unittest.TestCase):
    def test_generic_realtek_device_name_resolves_to_real_codec_via_registry(self):
        profile = hardware.HardwareProfile()
        responses = iter([
            "Realtek High Definition Audio",
            r"HDAUDIO\FUNC_01&VEN_10EC&DEV_0897&SUBSYS_10438694\4&2E4E0D6&0&0001",
        ])
        with patch.object(hardware, "_ps", side_effect=lambda *a, **k: next(responses)):
            hardware._detect_audio_windows(profile)

        self.assertEqual(profile.audio_codec, "ALC897")

    def test_no_realtek_pnp_entry_falls_back_to_generic_label(self):
        profile = hardware.HardwareProfile()
        responses = iter(["Realtek High Definition Audio", ""])
        with patch.object(hardware, "_ps", side_effect=lambda *a, **k: next(responses)):
            hardware._detect_audio_windows(profile)

        self.assertEqual(profile.audio_codec, "Realtek")


class WindowsNetworkDetectionTests(unittest.TestCase):
    def test_ethernet_query_selects_physical_adapter_without_name_blacklist(self):
        queries = []

        with patch.object(hardware, "_ps", side_effect=lambda query: queries.append(query) or ""):
            hardware._detect_network_windows(hardware.HardwareProfile())

        ethernet_query = queries[0]
        self.assertIn("Get-NetAdapter -Physical -ErrorAction Stop", ethernet_query)
        self.assertIn("$_.InterfaceDescription -notmatch", ethernet_query)
        self.assertNotIn("Win32_NetworkAdapter", ethernet_query)
        self.assertNotIn("$_.Name -notmatch", ethernet_query)
        for virtual_adapter_term in ("Virtual", "TAP", "VPN", "Loopback"):
            self.assertNotIn(virtual_adapter_term, ethernet_query)


class WindowsGpuDetectionTests(unittest.TestCase):
    def test_primary_gpu_pci_device_and_function_are_captured(self):
        controllers = [{
            "Name": "NVIDIA GeForce RTX 4070",
            "PNPDeviceID": r"PCI\VEN_10DE&DEV_2786&SUBSYS_00000000",
            "BusNumber": 1,
            "Address": (0x1A << 16) | 3,
        }]
        profile = hardware.HardwareProfile()

        with patch.object(hardware, "_ps", return_value=json.dumps(controllers)):
            hardware._detect_gpu_windows(profile)

        self.assertEqual(profile.gpu_vendor, "nvidia")
        self.assertEqual(profile.gpu_pci_device, 0x1A)
        self.assertEqual(profile.gpu_pci_function, 3)

    def test_pci_address_follows_the_selected_primary_gpu(self):
        controllers = [
            {
                "Name": "NVIDIA GeForce GTX 1050",
                "PNPDeviceID": r"PCI\VEN_10DE&DEV_1C8D&SUBSYS_00000000",
                "BusNumber": 1,
                "Address": (0x1B << 16),
            },
            {
                "Name": "Intel(R) HD Graphics 630",
                "PNPDeviceID": r"PCI\VEN_8086&DEV_591B&SUBSYS_00000000",
                "BusNumber": 0,
                "Address": (0x02 << 16),
            },
        ]
        profile = hardware.HardwareProfile()

        with patch.object(hardware, "_ps", return_value=json.dumps(controllers)):
            hardware._detect_gpu_windows(profile)

        self.assertEqual(profile.gpu_vendor, "intel")
        self.assertEqual(profile.gpu_pci_device, 0x02)
        self.assertEqual(profile.gpu_pci_function, 0)

    def test_invalid_windows_pci_address_is_rejected(self):
        for address in (None, 0xFFFFFFFF, (0x20 << 16), (0x01 << 16) | 8):
            with self.subTest(address=address):
                self.assertEqual(
                    hardware._decode_windows_pci_address(address), (-1, -1)
                )

    def test_gpu_pci_fields_default_to_unknown(self):
        profile = hardware.HardwareProfile()

        self.assertEqual(profile.gpu_pci_device, -1)
        self.assertEqual(profile.gpu_pci_function, -1)

    def test_intel_device_id_follows_selected_igpu_when_dgpu_is_listed_first(self):
        controllers = [
            {
                "Name": "NVIDIA GeForce GTX 1050",
                "PNPDeviceID": r"PCI\VEN_10DE&DEV_1C8D&SUBSYS_00000000",
            },
            {
                "Name": "Intel(R) HD Graphics 630",
                "PNPDeviceID": r"PCI\VEN_8086&DEV_591B&SUBSYS_00000000",
            },
        ]
        profile = hardware.HardwareProfile()

        with patch.object(hardware, "_ps", return_value=json.dumps(controllers)):
            hardware._detect_gpu_windows(profile)

        self.assertEqual(profile.gpu_name, "Intel(R) HD Graphics 630")
        self.assertEqual(profile.gpu_vendor, "intel")
        self.assertEqual(profile.gpu_device_id, "591B")
        self.assertEqual(profile.dgpu_name, "NVIDIA GeForce GTX 1050")
        self.assertEqual(profile.dgpu_vendor, "nvidia")

    def test_gpu_names_fall_back_when_powershell_json_is_unavailable(self):
        profile = hardware.HardwareProfile()

        with patch.object(
            hardware,
            "_ps",
            side_effect=["not-json", "Intel(R) UHD Graphics 620||NVIDIA GeForce MX150"],
        ):
            hardware._detect_gpu_windows(profile)

        self.assertEqual(profile.gpu_name, "Intel(R) UHD Graphics 620")
        self.assertEqual(profile.gpu_vendor, "intel")
        self.assertEqual(profile.dgpu_name, "NVIDIA GeForce MX150")
        self.assertEqual(profile.dgpu_vendor, "nvidia")

    def test_amd_and_nvidia_discrete_with_no_igpu_puts_amd_in_primary_slot(self):
        controllers = [
            {
                "Name": "NVIDIA GeForce RTX 4070",
                "PNPDeviceID": r"PCI\VEN_10DE&DEV_2786&SUBSYS_00000000",
            },
            {
                "Name": "AMD Radeon RX 570 Series",
                "PNPDeviceID": r"PCI\VEN_1002&DEV_67DF&SUBSYS_00000000",
            },
        ]
        profile = hardware.HardwareProfile()

        with patch.object(hardware, "_ps", return_value=json.dumps(controllers)):
            hardware._detect_gpu_windows(profile)

        self.assertEqual(profile.gpu_name, "AMD Radeon RX 570 Series")
        self.assertEqual(profile.gpu_vendor, "amd")
        self.assertEqual(profile.dgpu_name, "NVIDIA GeForce RTX 4070")
        self.assertEqual(profile.dgpu_vendor, "nvidia")

    def test_driverless_gpu_with_blank_wmi_name_is_resolved_via_pci_ids(self):
        controllers = [
            {
                "Name": "",
                "PNPDeviceID": r"PCI\VEN_8086&DEV_591B&SUBSYS_00000000",
            },
        ]
        profile = hardware.HardwareProfile()

        with patch.object(hardware, "_ps", return_value=json.dumps(controllers)):
            hardware._detect_gpu_windows(profile)

        self.assertIn("HD Graphics 630", profile.gpu_name)
        self.assertEqual(profile.gpu_vendor, "intel")


class LinuxGpuFallbackNameTests(unittest.TestCase):
    def test_generic_lspci_name_is_resolved_via_bundled_pci_ids(self):
        profile = hardware.HardwareProfile()
        profile.raw_pci = [
            "00:02.0 VGA compatible controller [0300]: Device [8086:591b]",
        ]

        hardware._detect_gpu_linux(profile)

        self.assertIn("HD Graphics 630", profile.gpu_name)
        self.assertEqual(profile.gpu_vendor, "intel")


class SmbiosGenerationMatchTests(unittest.TestCase):
    def test_zen_2_laptop_uses_amd_smbios(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="amd", cpu_generation=10, platform="laptop"
        )

        hardware.detect_smbios(profile)

        self.assertEqual(profile.smbios_model, "MacBookPro15,2")

    def test_zen_4_or_5_laptop_uses_amd_smbios(self):
        profile = hardware.HardwareProfile(
            cpu_vendor="amd", cpu_generation=12, platform="laptop"
        )

        hardware.detect_smbios(profile)

        self.assertEqual(profile.smbios_model, "MacBookPro15,2")

    def test_kaby_lake_laptop_gets_a_genuine_kaby_lake_smbios(self):
        profile = hardware.HardwareProfile(cpu_generation=7, platform="laptop")

        hardware.detect_smbios(profile)

        self.assertEqual(profile.smbios_model, "MacBookPro14,1")

    def test_coffee_lake_laptop_smbios_unaffected(self):
        profile = hardware.HardwareProfile(cpu_generation=8, platform="laptop")

        hardware.detect_smbios(profile)

        self.assertEqual(profile.smbios_model, "MacBookPro15,2")


if __name__ == "__main__":
    unittest.main()
