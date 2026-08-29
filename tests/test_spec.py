import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hardware
from hardware import HardwareProfile


def _profile(**overrides):
    defaults = dict(
        cpu_vendor="intel", cpu_generation=8, platform="laptop",
        cpu_name="Intel Core i7-8650U", cpu_codename="Kaby Lake-R",
        gpu_vendor="intel", gpu_name="UHD 620", audio_codec="ALC256",
        smbios_model="MacBookPro15,2", raw_pci=["00:02.0 VGA compatible controller: Intel"],
    )
    defaults.update(overrides)
    return HardwareProfile(**defaults)


class SpecRoundTripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "my-pc.json"

    def test_save_then_load_reproduces_the_profile(self):
        original = _profile()
        hardware.save_spec(original, self.path, macos_major=13)
        loaded, major = hardware.load_spec(self.path)
        self.assertEqual(loaded, original)
        self.assertEqual(major, 13)

    def test_spec_file_is_readable_json_with_an_envelope(self):
        hardware.save_spec(_profile(), self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["hackmate_spec"], hardware.SPEC_VERSION)
        self.assertIn("profile", data)
        self.assertEqual(data["profile"]["cpu_name"], "Intel Core i7-8650U")

    def test_unknown_keys_in_a_spec_are_ignored(self):
        payload = {
            "hackmate_spec": 1,
            "profile": {"cpu_name": "x", "cpu_generation": 9, "not_a_field": 1},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        loaded, _ = hardware.load_spec(self.path)
        self.assertEqual(loaded.cpu_generation, 9)

    def test_a_bare_profile_dict_without_envelope_still_loads(self):
        self.path.write_text(json.dumps({"cpu_name": "y", "cpu_generation": 7}), encoding="utf-8")
        loaded, major = hardware.load_spec(self.path)
        self.assertEqual(loaded.cpu_name, "y")
        self.assertEqual(major, 0)

    def test_raw_pci_is_coerced_to_a_list(self):
        loaded = hardware.profile_from_dict({"raw_pci": ("a", "b")})
        self.assertEqual(loaded.raw_pci, ["a", "b"])


class DetectBoardTests(unittest.TestCase):
    def _chipset(self, board, vendor="", cpu_vendor="intel"):
        from unittest.mock import patch
        p = HardwareProfile(cpu_vendor=cpu_vendor)
        fields = {"board_name": board, "board_vendor": vendor, "sys_vendor": vendor, "product_name": board}
        with patch("compat.dmi_field", side_effect=lambda f: fields.get(f, "")):
            hardware._detect_board(p)
        return p.chipset

    def test_intel_z390_board(self):
        self.assertEqual(self._chipset("PRIME Z390-A"), "Z390")

    def test_intel_laptop_hm370(self):
        self.assertEqual(self._chipset("HM370 Chipset - ThinkPad"), "HM370")

    def test_amd_b550_board(self):
        self.assertEqual(self._chipset("ROG STRIX B550-F GAMING", cpu_vendor="amd"), "B550")

    def test_hedt_x299(self):
        self.assertEqual(self._chipset("X299 AORUS MASTER"), "X299")

    def test_no_recognisable_chipset_is_left_blank(self):
        self.assertEqual(self._chipset("Default string"), "")


if __name__ == "__main__":
    unittest.main()
