import re
import sys
import tempfile
import unittest
import uuid as uuid_module
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import smbios
from hardware import HardwareProfile

_tmp_dir = None
_original_seen_file = None


def setUpModule():
    # generate_serial/generate_mlb persist a local dedup file — redirect it
    # to a throwaway temp path so the test suite never writes into the real
    # user's ~/.hackmate directory.
    global _tmp_dir, _original_seen_file
    _tmp_dir = tempfile.TemporaryDirectory()
    _original_seen_file = smbios._SEEN_FILE
    smbios._SEEN_FILE = Path(_tmp_dir.name) / "used_smbios.json"


def tearDownModule():
    smbios._SEEN_FILE = _original_seen_file
    _tmp_dir.cleanup()


class GenerateSerialTests(unittest.TestCase):
    def test_known_model_uses_its_own_suffix_list(self):
        for _ in range(50):
            serial = smbios.generate_serial("MacBookPro15,2")
            suffix = next(s for s in smbios.MODEL_SUFFIXES["MacBookPro15,2"] if serial.endswith(s))
            self.assertIsNotNone(suffix)

    def test_serial_starts_with_a_known_factory_code(self):
        for _ in range(50):
            serial = smbios.generate_serial("MacBookPro15,2")
            factory = next((f for f in smbios.FACTORIES if serial.startswith(f)), None)
            self.assertIsNotNone(factory)

    def test_unknown_model_falls_back_to_default_suffixes(self):
        fallback_suffixes = ["DH2", "GF1", "K05"]
        for _ in range(50):
            serial = smbios.generate_serial("SomeUnknownModel99,1")
            self.assertTrue(any(serial.endswith(s) for s in fallback_suffixes))

    def test_serial_length_is_consistent_for_a_given_model(self):
        lengths = {len(smbios.generate_serial("MacBookPro15,2")) for _ in range(50)}
        self.assertEqual(len(lengths), 1)  # factory+year+week+unique+suffix are all fixed-width per call


class GenerateMlbTests(unittest.TestCase):
    def test_mlb_is_always_17_characters(self):
        for model in ("MacBookPro15,2", "iMac18,3", "SomeUnknownModel", ""):
            for _ in range(20):
                self.assertEqual(len(smbios.generate_mlb(model)), smbios.MLB_LENGTH)

    def test_known_model_uses_one_of_its_prefixes(self):
        for _ in range(30):
            mlb = smbios.generate_mlb("iMac18,3")
            prefix = next((p for p in smbios.MLB_PREFIXES["iMac18,3"] if mlb.startswith(p)), None)
            self.assertIsNotNone(prefix)

    def test_unknown_model_uses_generic_fallback_pattern(self):
        mlb = smbios.generate_mlb("TotallyUnknownModel")
        self.assertTrue(mlb.startswith("C02"))
        self.assertIn("HACD", mlb)
        self.assertEqual(len(mlb), smbios.MLB_LENGTH)


class GenerateUuidTests(unittest.TestCase):
    def test_uuid_is_valid_and_uppercase(self):
        value = smbios.generate_uuid()
        parsed = uuid_module.UUID(value)  # raises if malformed
        self.assertEqual(value, value.upper())
        self.assertEqual(str(parsed).upper(), value)

    def test_repeated_calls_are_not_all_identical(self):
        values = {smbios.generate_uuid() for _ in range(20)}
        self.assertGreater(len(values), 1)


class GenerateRomTests(unittest.TestCase):
    def test_rom_is_twelve_hex_characters(self):
        for _ in range(30):
            rom = smbios.generate_rom()
            self.assertEqual(len(rom), 12)
            self.assertTrue(re.fullmatch(r"[0-9A-F]{12}", rom))

    def test_rom_starts_with_a_known_apple_oui(self):
        apple_ouis = ["0017F2", "28CFE9", "3C0754", "8C8590", "ACDE48", "F0DBE2"]
        for _ in range(30):
            rom = smbios.generate_rom()
            self.assertTrue(any(rom.startswith(oui) for oui in apple_ouis))


class GenerateTests(unittest.TestCase):
    def test_uses_profile_smbios_model_when_set(self):
        profile = HardwareProfile(smbios_model="iMac18,3")
        data = smbios.generate(profile)
        self.assertEqual(data.model, "iMac18,3")

    def test_falls_back_to_default_model_when_unset(self):
        profile = HardwareProfile(smbios_model="")
        data = smbios.generate(profile)
        self.assertEqual(data.model, "MacBookPro15,2")

    def test_all_fields_are_populated(self):
        profile = HardwareProfile(smbios_model="MacBookPro16,1")
        data = smbios.generate(profile)
        self.assertTrue(data.serial)
        self.assertTrue(data.board_serial)
        self.assertTrue(data.system_uuid)
        self.assertTrue(data.rom)
        self.assertEqual(len(data.board_serial), smbios.MLB_LENGTH)

    def test_serial_and_mlb_match_the_generated_model(self):
        profile = HardwareProfile(smbios_model="iMac18,3")
        data = smbios.generate(profile)
        suffix_match = any(data.serial.endswith(s) for s in smbios.MODEL_SUFFIXES["iMac18,3"])
        prefix_match = any(data.board_serial.startswith(p) for p in smbios.MLB_PREFIXES["iMac18,3"])
        self.assertTrue(suffix_match)
        self.assertTrue(prefix_match)


class LocalDedupTests(unittest.TestCase):
    """Regression coverage for the local serial/MLB dedup added after
    GenSMBIOS's own issue tracker documented cross-run duplicate serials."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._original = smbios._SEEN_FILE
        smbios._SEEN_FILE = Path(self._tmp.name) / "used_smbios.json"

    def tearDown(self):
        smbios._SEEN_FILE = self._original
        self._tmp.cleanup()

    def test_forced_collision_retries_until_a_new_value_is_produced(self):
        calls = iter(["DUPLICATE", "DUPLICATE", "FRESH-VALUE"])
        smbios._remember("serials", "DUPLICATE")

        result = smbios._unique("serials", lambda: next(calls))

        self.assertEqual(result, "FRESH-VALUE")

    def test_chosen_value_is_persisted_for_future_calls(self):
        smbios._unique("serials", lambda: "ONLY-OPTION")
        seen = smbios._load_seen()
        self.assertIn("ONLY-OPTION", seen["serials"])

    def test_corrupt_seen_file_is_treated_as_empty(self):
        smbios._SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        smbios._SEEN_FILE.write_text("not valid json{{{")
        seen = smbios._load_seen()
        self.assertEqual(seen, {"serials": set(), "mlbs": set()})

    def test_missing_seen_file_is_treated_as_empty(self):
        seen = smbios._load_seen()
        self.assertEqual(seen, {"serials": set(), "mlbs": set()})

    def test_generate_serial_avoids_a_value_already_recorded(self):
        smbios._remember("serials", "IMPOSSIBLE-SEED-VALUE")
        with patch.object(smbios, "_generate_serial_once",
                          side_effect=["IMPOSSIBLE-SEED-VALUE", "REAL-SERIAL"]):
            result = smbios.generate_serial("MacBookPro15,2")
        self.assertEqual(result, "REAL-SERIAL")

    def test_gives_up_after_max_attempts_rather_than_looping_forever(self):
        # Every attempt collides — the space is exhausted for this test, so
        # it must still return promptly instead of retrying indefinitely.
        smbios._remember("serials", "ALWAYS-THE-SAME")
        result = smbios._unique("serials", lambda: "ALWAYS-THE-SAME")
        self.assertEqual(result, "ALWAYS-THE-SAME")


if __name__ == "__main__":
    unittest.main()
