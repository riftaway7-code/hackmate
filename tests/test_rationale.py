import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rationale
from hardware import HardwareProfile


def _profile(**overrides):
    defaults = dict(cpu_vendor="intel", cpu_generation=8, platform="desktop")
    defaults.update(overrides)
    return HardwareProfile(**defaults)


class ExplainShapeTests(unittest.TestCase):
    def test_every_decision_is_well_formed(self):
        decisions = rationale.explain(_profile(), macos_major=13)
        self.assertTrue(decisions)
        for d in decisions:
            self.assertTrue(d.section)
            self.assertTrue(d.setting)
            self.assertTrue(d.reason)

    def test_rows_round_trip_keys(self):
        rows = rationale.to_rows(rationale.explain(_profile()))
        for row in rows:
            self.assertEqual(
                set(row), {"section", "setting", "value", "reason", "doc"}
            )

    def test_render_is_grouped_text(self):
        text = rationale.render(rationale.explain(_profile(), macos_major=13))
        self.assertIn("== macOS ==", text)
        self.assertIn("== Kexts ==", text)


class HardwareDrivenTests(unittest.TestCase):
    def test_amd_points_at_amd_vanilla_and_disables_cfglock(self):
        decisions = rationale.explain(
            _profile(cpu_vendor="amd", cpu_generation=0, cpu_codename="Zen 3",
                     core_count=6, cpu_name="AMD Ryzen 5 5600X")
        )
        settings = {(d.section, d.setting): d for d in decisions}
        self.assertIn(("Kernel", "Patch"), settings)
        self.assertEqual(settings[("Kernel", "Quirks/AppleXcpmCfgLock")].value, "off")
        self.assertTrue(
            any("AMD_Vanilla" in d.doc for d in decisions if d.section == "Kernel")
        )

    def test_sandy_bridge_gets_dummy_power_management(self):
        decisions = rationale.explain(_profile(cpu_generation=2, cpu_name="Intel Core i5-2500K"))
        self.assertTrue(
            any(d.setting == "Emulate/DummyPowerManagement" for d in decisions)
        )

    def test_pentium_is_capped_at_monterey(self):
        decisions = rationale.explain(_profile(cpu_generation=9, cpu_name="Intel Pentium Gold G5400"))
        ceilings = [d for d in decisions if d.section == "macOS" and d.setting == "ceiling"]
        self.assertEqual(len(ceilings), 1)
        self.assertEqual(ceilings[0].value, "Monterey")

    def test_laptop_igpu_gets_agdpmod_bootarg(self):
        decisions = rationale.explain(
            _profile(platform="laptop", gpu_vendor="intel", gpu_name="UHD 620",
                     cpu_generation=8, oc_platform="Kaby Lake-R")
        )
        self.assertTrue(any(d.setting == "agdpmod=vit9696" for d in decisions))

    def test_no_audio_codec_means_no_alcid(self):
        decisions = rationale.explain(_profile(audio_codec=""))
        self.assertFalse(any(d.setting == "alcid" for d in decisions))


if __name__ == "__main__":
    unittest.main()
