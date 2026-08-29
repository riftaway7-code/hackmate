import sys
import unittest
from dataclasses import replace
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recovery import MACOS_VERSIONS, compatible_versions, macrecovery_args


class RecoveryCompatibilityTests(unittest.TestCase):
    def _versions(
        self,
        cpu_gen: int,
        cpu_vendor: str = "intel",
        cpu_codename: str = "",
        gpu_vendor: str = "amd",
        gpu_name: str = "",
    ) -> list[str]:
        return [
            version.version
            for version in compatible_versions(
                cpu_gen,
                gpu_vendor,
                cpu_vendor,
                cpu_codename,
                gpu_name,
            )
        ]

    def test_skylake_is_not_offered_pre_skylake_installers(self):
        versions = self._versions(6)

        self.assertIn("10.11", versions)
        self.assertNotIn("10.10", versions)

    def test_coffee_lake_starts_with_high_sierra(self):
        versions = self._versions(8)

        self.assertIn("10.13", versions)
        self.assertNotIn("10.12", versions)

    def test_comet_lake_starts_with_catalina(self):
        versions = self._versions(10)

        self.assertIn("10.15", versions)
        self.assertNotIn("10.14", versions)

    def test_spoofed_newer_intel_starts_with_big_sur(self):
        versions = self._versions(13)

        self.assertIn("11", versions)
        self.assertNotIn("10.15", versions)

    def test_zen_4_starts_with_ventura(self):
        versions = self._versions(12, "amd", "Zen 4")

        self.assertIn("13", versions)
        self.assertNotIn("12", versions)

    def test_unknown_modern_amd_uses_generation_fallback(self):
        versions = self._versions(12, "amd")

        self.assertIn("13", versions)
        self.assertNotIn("12", versions)

    def test_zen_5_starts_with_sequoia(self):
        versions = self._versions(12, "amd", "Zen 5")

        self.assertIn("15", versions)
        self.assertNotIn("14", versions)

    def test_pascal_nvidia_stops_at_high_sierra(self):
        versions = self._versions(
            8,
            gpu_vendor="nvidia",
            gpu_name="NVIDIA GeForce GTX 1080",
        )

        self.assertEqual(["10.13"], versions)

    def test_kepler_nvidia_stops_at_big_sur(self):
        versions = self._versions(
            4,
            gpu_vendor="nvidia",
            gpu_name="NVIDIA GeForce GTX 770",
        )

        self.assertIn("11", versions)
        self.assertNotIn("12", versions)

    def test_unknown_nvidia_stops_at_high_sierra(self):
        versions = self._versions(6, gpu_vendor="nvidia")

        self.assertIn("10.13", versions)
        self.assertNotIn("10.14", versions)

    def test_zen_3_with_unsupported_nvidia_uses_cpu_compatibility(self):
        versions = self._versions(
            5,
            cpu_vendor="amd",
            cpu_codename="Zen 3",
            gpu_vendor="nvidia",
            gpu_name="NVIDIA GeForce RTX 3050",
        )

        self.assertTrue(versions)
        self.assertIn("11", versions)
        self.assertNotIn("10.15", versions)

    def test_modern_amd_and_intel_gpus_use_the_same_cpu_filtering(self):
        amd_versions = self._versions(10, gpu_vendor="amd")
        intel_versions = self._versions(10, gpu_vendor="intel")

        self.assertEqual(amd_versions, intel_versions)
        self.assertIn("10.15", amd_versions)
        self.assertNotIn("10.14", amd_versions)

    def test_pentium_celeron_are_capped_at_monterey(self):
        versions = [
            v.version for v in compatible_versions(
                8, "intel", "intel", "", "", "Intel Pentium Gold G5400"
            )
        ]
        self.assertIn("12", versions)
        self.assertNotIn("13", versions)
        self.assertNotIn("26", versions)

    def test_ordinary_core_cpu_is_not_capped_at_monterey(self):
        versions = [
            v.version for v in compatible_versions(
                8, "intel", "intel", "", "", "Intel Core i5-8400"
            )
        ]
        self.assertIn("13", versions)


class RecoveryCommandTests(unittest.TestCase):
    def _version(self, version: str):
        return next(item for item in MACOS_VERSIONS if item.version == version)

    def test_only_tahoe_requests_the_latest_recovery(self):
        tahoe_args = macrecovery_args(self._version("26"))
        sequoia_args = macrecovery_args(self._version("15"))
        sonoma_args = macrecovery_args(self._version("14"))

        self.assertIn("-os", tahoe_args)
        self.assertIn("latest", tahoe_args)
        self.assertNotIn("-os", sequoia_args)
        self.assertNotIn("-os", sonoma_args)

    def test_shared_command_builder_includes_output_directory(self):
        args = macrecovery_args(self._version("15"), Path("/tmp/recovery"))

        self.assertEqual(
            [
                "-b", "Mac-7BA5B2D9E42DDD94",
                "-m", "00000000000000000",
                "download",
                "--outdir", "/tmp/recovery",
            ],
            args,
        )

    def test_recovery_identifiers_match_opencore_guide(self):
        expected = {
            "26": ("Mac-CFF7D910A743CAAF", "00000000000000000"),
            "15": ("Mac-7BA5B2D9E42DDD94", "00000000000000000"),
            "14": ("Mac-827FAC58A8FDFA22", "00000000000000000"),
            "13": ("Mac-B4831CEBD52A0C4C", "00000000000000000"),
            "12": ("Mac-E43C1C25D4880AD6", "00000000000000000"),
            "11": ("Mac-2BD1B31983FE1663", "00000000000000000"),
            "10.15": ("Mac-CFF7D910A743CAAF", "00000000000PHCD00"),
            "10.14": ("Mac-7BA5B2DFE22DDD8C", "00000000000KXPG00"),
            "10.13": ("Mac-7BA5B2D9E42DDD94", "00000000000J80300"),
            "10.12": ("Mac-77F17D7DA9285301", "00000000000J0DX00"),
            "10.11": ("Mac-FFE5EF870D7BA81A", "00000000000GQRX00"),
            "10.10": ("Mac-E43C1C25D4880AD6", "00000000000GDVW00"),
        }

        actual = {
            version.version: (version.board_id, version.mlb)
            for version in MACOS_VERSIONS
        }

        self.assertEqual(expected, actual)

    def test_cache_key_changes_with_apple_query(self):
        sequoia = self._version("15")
        incorrect_query = replace(sequoia, os_flag="-os latest")

        self.assertNotEqual(sequoia.cache_key, incorrect_query.cache_key)
        self.assertTrue(sequoia.cache_key.startswith("15-"))
