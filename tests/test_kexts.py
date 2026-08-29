import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config_gen
import kexts
from kexts import DB, check_kext_sources, alc_layout_is_known, get_alc_layout, fetch_opencore, OPENCORE_FALLBACK_URL
from hardware import HardwareProfile

_AIRPORTITLWM_ASSETS = [
    {"name": "AirportItlwm_v2.3.0_stable_Sonoma14.4.kext.zip"},
    {"name": "AirportItlwm_v2.3.0_stable_Ventura.kext.zip"},
    {"name": "itlwm_v2.3.0_stable.kext.zip"},
]


class CpuTopologyRebuildSelectionTests(unittest.TestCase):
    def test_amd_zen4_does_not_get_intel_topology_kext(self):
        profile = HardwareProfile(
            cpu_vendor="amd",
            cpu_generation=12,
            cpu_codename="Zen 4",
            platform="desktop",
        )
        with (
            patch.object(kexts, "_dmi", return_value=""),
            patch.object(kexts, "_has_card_reader", return_value=False),
        ):
            names = {entry.name for entry in kexts.select_kexts(profile)}

        self.assertNotIn("CpuTopologyRebuild", names)


class AmdGpuKextSelectionTests(unittest.TestCase):
    def _selected_names(self, profile: HardwareProfile) -> set[str]:
        with (
            patch.object(kexts, "_dmi", return_value=""),
            patch.object(kexts, "_has_card_reader", return_value=False),
        ):
            return {entry.name for entry in kexts.select_kexts(profile)}

    def test_intel_igpu_with_navi2x_dgpu_gets_navi_and_sensor_kexts(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=9,
            platform="desktop",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 630",
            dgpu_vendor="amd",
            dgpu_name="AMD Radeon RX 6600",
        )

        names = self._selected_names(profile)

        self.assertIn("NootRX", names)
        self.assertIn("RadeonSensor", names)
        self.assertIn("SMCRadeonGPU", names)

    def test_navi2x_dgpu_device_id_is_recognized(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=9,
            platform="desktop",
            gpu_vendor="intel",
            gpu_name="Intel UHD Graphics 630",
            dgpu_vendor="amd",
            dgpu_name="AMD Radeon GPU",
            dgpu_device_id="1002:73ff",
        )

        self.assertIn("NootRX", self._selected_names(profile))

    def test_amd_primary_navi2x_behavior_is_preserved(self):
        profile = HardwareProfile(
            cpu_vendor="intel",
            platform="desktop",
            gpu_vendor="amd",
            gpu_name="AMD Radeon RX 6800",
        )

        names = self._selected_names(profile)

        self.assertIn("NootRX", names)
        self.assertIn("RadeonSensor", names)
        self.assertIn("SMCRadeonGPU", names)

    def test_amd_apu_only_gets_neither_navi_nor_sensor_kexts(self):
        profile = HardwareProfile(
            cpu_vendor="amd",
            platform="desktop",
            gpu_vendor="amd",
            gpu_name="AMD Radeon Graphics",
        )

        names = self._selected_names(profile)

        self.assertNotIn("NootRX", names)
        self.assertNotIn("RadeonSensor", names)
        self.assertNotIn("SMCRadeonGPU", names)

    def test_modern_780m_graphics_is_recognized_as_amd_apu(self):
        profile = HardwareProfile(
            cpu_vendor="amd",
            gpu_vendor="amd",
            gpu_name="AMD Radeon 780M Graphics",
        )

        self.assertTrue(kexts._is_amd_apu(profile))


class AirportItlwmSourceCheckTests(unittest.TestCase):
    def _check(self, macos_version: str) -> str:
        with patch("kexts._get_latest_release", return_value={"assets": _AIRPORTITLWM_ASSETS}):
            results, _ = check_kext_sources([DB["AirportItlwm"]], macos_version=macos_version)
        return results["AirportItlwm"]

    def test_sonoma_build_is_available(self):
        self.assertEqual(self._check("14"), "OK")

    def test_tahoe_has_no_build_and_is_reported_as_an_error_not_ok(self):
        result = self._check("26")

        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("itlwm", result)

    def test_sequoia_has_no_build_and_is_reported_as_an_error_not_ok(self):
        result = self._check("15")

        self.assertTrue(result.startswith("ERROR"))

    def test_missing_macos_version_argument_does_not_silently_pass(self):
        result = self._check("")

        self.assertTrue(result.startswith("ERROR"))


class AlcLayoutConfidenceTests(unittest.TestCase):
    def test_known_codec_is_confirmed(self):
        self.assertTrue(alc_layout_is_known("ALC897"))

    def test_generic_realtek_string_is_not_confirmed(self):
        self.assertFalse(alc_layout_is_known("Realtek"))
        self.assertEqual(get_alc_layout("Realtek"), 1)

    def test_unrecognized_alc_model_is_not_confirmed(self):
        self.assertFalse(alc_layout_is_known("ALC1200"))


class OpenCoreDebugBuildTests(unittest.TestCase):
    def test_fallback_url_points_at_debug_not_release(self):
        self.assertIn("DEBUG", OPENCORE_FALLBACK_URL)
        self.assertNotIn("RELEASE", OPENCORE_FALLBACK_URL)

    def test_picks_the_debug_asset_from_the_release_list(self):
        assets = [
            {"name": "OpenCore-1.0.7-RELEASE.zip", "browser_download_url": "http://x/release.zip", "size": 1000},
            {"name": "OpenCore-1.0.7-DEBUG.zip", "browser_download_url": "http://x/debug.zip", "size": 15},
        ]
        with (
            patch.object(kexts, "_github_headers", return_value={}),
            patch("kexts.http_get") as http_get,
        ):
            import json as _json
            http_get.side_effect = [
                _json.dumps({"assets": assets}).encode(),
                b"debug-zip-bytes",
            ]
            path = fetch_opencore(Path("/tmp"))

        try:
            second_call_url = http_get.call_args_list[1].args[0]
            self.assertIn("debug.zip", second_call_url)
        finally:
            path.unlink(missing_ok=True)
            cached = kexts._CACHE_ROOT / "opencore" / "OpenCore-1.0.7-DEBUG.zip"
            cached.unlink(missing_ok=True)


class TouchpadKextSelectionTests(unittest.TestCase):
    """select_kexts() used to re-detect the touchpad live on whatever machine
    HackMate happened to be running on, ignoring profile.touchpad_type
    entirely — so a manually-entered profile (built for different hardware
    than the one running HackMate) silently got the wrong touchpad kext, and
    a laptop's compat.detect_touchpad_type() diagnostic could disagree with
    what was actually injected. select_kexts must trust the profile."""

    def _selected_names(self, touchpad_type: str) -> set[str]:
        profile = HardwareProfile(
            cpu_vendor="intel",
            cpu_generation=8,
            platform="laptop",
            touchpad_type=touchpad_type,
        )
        with (
            patch.object(kexts, "_dmi", return_value=""),
            patch.object(kexts, "_has_card_reader", return_value=False),
        ):
            return {entry.name for entry in kexts.select_kexts(profile)}

    def test_manual_i2c_elan_profile_gets_the_elan_satellite_not_ps2(self):
        names = self._selected_names("i2c_elan")

        self.assertIn("VoodooI2C", names)
        self.assertIn("VoodooI2CELAN", names)
        self.assertNotIn("VoodooI2CSynaptics", names)

    def test_manual_rmi_profile_gets_voodoormi_not_i2c(self):
        names = self._selected_names("rmi")

        self.assertIn("VoodooRMI", names)
        self.assertNotIn("VoodooI2C", names)

    def test_manual_i2c_alps_profile_gets_alpshid(self):
        names = self._selected_names("i2c_alps")

        self.assertIn("AlpsHID", names)
        self.assertIn("VoodooI2C", names)

    def test_plain_ps2_profile_gets_no_i2c_kexts(self):
        names = self._selected_names("ps2")

        self.assertNotIn("VoodooI2C", names)
        self.assertNotIn("VoodooRMI", names)
        self.assertIn("VoodooPS2Controller", names)


class LoadOrderCompletenessTests(unittest.TestCase):
    """A kext missing from config_gen.LOAD_ORDER silently sorts to the very end
    of Kernel->Add (see _sort_kexts's order.get(name, 999) fallback) instead of
    raising anything — the exact "ignores load order" failure mode reported
    against generated EFIs. Every kext in the DB must have an explicit
    position so this can't happen unnoticed again."""

    def test_every_kext_in_db_has_an_explicit_load_order_position(self):
        missing = sorted(set(DB) - set(config_gen.LOAD_ORDER))
        self.assertEqual(
            missing, [],
            f"kexts missing from LOAD_ORDER (they will sort last, silently): {missing}"
        )

    def test_load_order_has_no_duplicate_entries(self):
        seen = set()
        duplicates = sorted({
            name for name in config_gen.LOAD_ORDER
            if name in seen or seen.add(name)
        })
        self.assertEqual(duplicates, [], f"duplicate LOAD_ORDER entries: {duplicates}")


class LoadOrderDependencyTests(unittest.TestCase):
    """Base patcher / satellite relationships the Dortania guide requires:
    Lilu-dependent plugins must load after Lilu, and I2C touchpad satellites
    must load after the VoodooI2C base kext they attach to."""

    def _position(self, name: str) -> int:
        return config_gen.LOAD_ORDER.index(name)

    def test_lilu_loads_before_its_plugins(self):
        lilu_plugins = [
            "WhateverGreen", "AppleALC", "RestrictEvents", "FeatureUnlock",
            "CPUFriend", "NVMeFix", "DebugEnhancer", "CryptexFixup",
            "NootedRed", "NootRX", "HibernationFixup",
        ]
        lilu_pos = self._position("Lilu")
        for plugin in lilu_plugins:
            with self.subTest(plugin=plugin):
                self.assertLess(lilu_pos, self._position(plugin))

    def test_i2c_satellites_load_after_their_base_kext(self):
        base_pos = self._position("VoodooI2C")
        satellites = [
            "VoodooI2CHID", "VoodooI2CSynaptics", "VoodooI2CELAN",
            "VoodooI2CAtmel", "VoodooI2CFTE", "VoodooI2CGoodix", "AlpsHID",
        ]
        for satellite in satellites:
            with self.subTest(satellite=satellite):
                self.assertLess(base_pos, self._position(satellite))


class ZipExtractionSafetyTests(unittest.TestCase):
    def test_member_path_escaping_extract_dir_is_skipped(self):
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "evil.zip"
            extract_dir = tmp_path / "extract"
            extract_dir.mkdir()

            with zipfile.ZipFile(zip_path, "w") as z:
                z.writestr("Good.kext/Contents/Info.plist", "<plist/>")
                z.writestr("../../evil.txt", "should not escape extract_dir")

            kexts._extract_zip(zip_path, extract_dir)

            self.assertTrue((extract_dir / "Good.kext" / "Contents" / "Info.plist").exists())
            self.assertFalse((tmp_path.parent / "evil.txt").exists())
            self.assertFalse((tmp_path / "evil.txt").exists())


class GithubTokenTests(unittest.TestCase):
    def setUp(self):
        kexts._GH_TOKEN_CACHE.clear()
        self.addCleanup(kexts._GH_TOKEN_CACHE.clear)

    def test_gh_token_env_var_is_picked_up(self):
        with patch.dict("os.environ", {"GH_TOKEN": "ghp_fromenv", "GITHUB_TOKEN": ""}, clear=False):
            self.assertEqual(kexts._github_token(), "ghp_fromenv")
        self.assertEqual(kexts._github_headers()["Authorization"], "Bearer ghp_fromenv")

    def test_falls_back_to_gh_cli(self):
        from unittest.mock import MagicMock
        result = MagicMock(returncode=0, stdout="ghp_fromcli\n")
        with patch.dict("os.environ", {"GH_TOKEN": "", "GITHUB_TOKEN": ""}, clear=False), \
             patch.object(kexts.subprocess, "run", return_value=result) as run:
            self.assertEqual(kexts._github_token(), "ghp_fromcli")
            run.assert_called_once()

    def test_no_token_means_no_auth_header(self):
        with patch.dict("os.environ", {"GH_TOKEN": "", "GITHUB_TOKEN": ""}, clear=False), \
             patch.object(kexts.subprocess, "run", side_effect=FileNotFoundError):
            self.assertNotIn("Authorization", kexts._github_headers())


class ReleaseMetaCacheTests(unittest.TestCase):
    def _redirect_cache(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(kexts, "_CACHE_ROOT", Path(self._tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_fresh_cache_hit_skips_the_network(self):
        self._redirect_cache()
        path = kexts._release_cache_path("acme/widget")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"tag_name": "v9"}', encoding="utf-8")
        with patch.object(kexts, "_get_latest_release_uncached", side_effect=AssertionError("network hit")) as net:
            self.assertEqual(kexts._get_latest_release("acme/widget"), {"tag_name": "v9"})
            net.assert_not_called()

    def test_rate_limit_falls_back_to_stale_cache(self):
        self._redirect_cache()
        path = kexts._release_cache_path("acme/widget")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"tag_name": "old"}', encoding="utf-8")
        old = time.time() - kexts._RELEASE_META_TTL - 10
        os.utime(path, (old, old))
        with patch.object(kexts, "_get_latest_release_uncached", side_effect=RuntimeError("rate limit")):
            self.assertEqual(kexts._get_latest_release("acme/widget"), {"tag_name": "old"})

    def test_successful_fetch_writes_the_cache(self):
        self._redirect_cache()
        with patch.object(kexts, "_get_latest_release_uncached", return_value={"tag_name": "v2"}):
            kexts._get_latest_release("acme/widget")
        self.assertEqual(
            json.loads(kexts._release_cache_path("acme/widget").read_text(encoding="utf-8")),
            {"tag_name": "v2"},
        )


if __name__ == "__main__":
    unittest.main()
