import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hwdb_submit
from hardware import HardwareProfile


class BuildLogContentTests(unittest.TestCase):
    def _profile(self) -> HardwareProfile:
        return HardwareProfile(
            cpu_name="Intel(R) Core(TM) i5-8500",
            cpu_brand="Intel",
            cpu_vendor="intel",
            cpu_generation=8,
            cpu_codename="Coffee Lake",
            cpu_family="desktop",
            core_count=6,
            thread_count=6,
            platform="desktop",
            oc_platform="Coffee Lake",
            gpu_name="Intel UHD Graphics 630",
            gpu_vendor="intel",
            gpu_device_id="3e9b",
            gpu_subsystem="17aa2258",
            dgpu_name="NVIDIA GeForce RTX 4070",
            dgpu_vendor="nvidia",
            resizable_bar=True,
            audio_name="Realtek High Definition Audio",
            audio_codec="ALC897",
            ethernet_name="Realtek Gaming 2.5GbE Family Controller",
            ethernet_chipset="rtl8125",
            wifi_name="Microsoft Wi-Fi Direct Virtual Adapter",
            wifi_chipset="",
            has_touchpad=False,
            nvme_present=True,
            has_thunderbolt=False,
            smbios_model="iMac19,1",
        )

    def test_every_hardware_field_is_present_in_the_log(self):
        log = hwdb_submit.build_log(
            self._profile(), "full", "Tahoe (26)",
            worked="build completed", issues="none",
            wifi_kext_mode="AirportItlwm",
        )

        for expected in (
            "cpu_brand: Intel", "cpu_family: desktop", "core_count: 6",
            "thread_count: 6", "oc_platform: Coffee Lake",
            "igpu_device_id: 3e9b", "igpu_subsystem: 17aa2258",
            "resizable_bar: yes", "wifi_kext_mode: AirportItlwm",
            "dgpu: NVIDIA GeForce RTX 4070 (nvidia)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, log)

    def test_missing_wifi_kext_mode_reports_na_not_blank(self):
        log = hwdb_submit.build_log(
            self._profile(), "full", "Tahoe (26)",
            worked="build completed", issues="none",
        )

        self.assertIn("wifi_kext_mode: n/a", log)

    def test_full_log_is_appended_when_provided(self):
        log = hwdb_submit.build_log(
            self._profile(), "full", "Tahoe (26)",
            worked="build failed", issues="disk write error",
            full_log="Scanning hardware...\nWriting EFI...\nFATAL: disk write error",
        )

        self.assertIn("--- full EFI generation log ---", log)
        self.assertIn("FATAL: disk write error", log)

    def test_no_full_log_section_when_not_provided(self):
        log = hwdb_submit.build_log(
            self._profile(), "full", "Tahoe (26)",
            worked="build completed", issues="none",
        )

        self.assertNotIn("--- full EFI generation log ---", log)


class RelayUrlOverrideTests(unittest.TestCase):
    """RELAY_URL supports an env-var override so forks/self-hosted
    deployments don't have to edit source, and an empty value disables
    submission the same way declining consent does."""

    def test_env_var_overrides_the_default_relay_url(self):
        import importlib
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"HACKMATE_HWDB_RELAY_URL": "https://example.invalid/relay"}):
            importlib.reload(hwdb_submit)
        try:
            self.assertEqual(hwdb_submit.RELAY_URL, "https://example.invalid/relay")
        finally:
            importlib.reload(hwdb_submit)  # restore the real default for later tests

    def test_no_env_var_keeps_the_default_relay_url(self):
        import importlib
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HACKMATE_HWDB_RELAY_URL", None)
            importlib.reload(hwdb_submit)
        self.assertEqual(hwdb_submit.RELAY_URL, "https://hackmate-hwdb-relay.riftaway7.workers.dev")

    def test_empty_relay_url_disables_submission_without_touching_the_network(self):
        from unittest.mock import patch

        with (
            patch.object(hwdb_submit, "RELAY_URL", ""),
            patch.object(hwdb_submit.urllib.request, "urlopen") as urlopen,
        ):
            hwdb_submit.submit_log(HardwareProfile(), "full", "some log text")

        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
