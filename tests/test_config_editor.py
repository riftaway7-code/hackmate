import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config_editor


def _cfg_with_kexts():
    return {
        "Kernel": {
            "Add": [
                {"BundlePath": "Lilu.kext", "Enabled": True},
                {"BundlePath": "WhateverGreen.kext", "Enabled": True},
                {"BundlePath": "UTBMap.kext", "Enabled": False},
            ]
        }
    }


def _cfg_with_acpi():
    return {
        "ACPI": {
            "Add": [
                {"Path": "SSDT-PLUG.aml", "Enabled": True},
                {"Path": "SSDT-EC.aml", "Enabled": True},
            ]
        }
    }


class KextEntryTests(unittest.TestCase):
    def test_lists_all_kexts_with_enabled_state(self):
        entries = config_editor.get_kext_entries(_cfg_with_kexts())
        self.assertIn(("Lilu", True), entries)
        self.assertIn(("UTBMap", False), entries)

    def test_set_kext_enabled_toggles_the_right_entry(self):
        cfg = _cfg_with_kexts()
        found = config_editor.set_kext_enabled(cfg, "UTBMap", True)
        self.assertTrue(found)
        entries = dict(config_editor.get_kext_entries(cfg))
        self.assertTrue(entries["UTBMap"])
        self.assertTrue(entries["Lilu"])

    def test_set_kext_enabled_unknown_name_returns_false(self):
        cfg = _cfg_with_kexts()
        self.assertFalse(config_editor.set_kext_enabled(cfg, "DoesNotExist", True))

    def test_empty_config_returns_empty_list_not_a_crash(self):
        self.assertEqual(config_editor.get_kext_entries({}), [])


class AcpiEntryTests(unittest.TestCase):
    def test_lists_all_acpi_adds_with_enabled_state(self):
        entries = config_editor.get_acpi_entries(_cfg_with_acpi())
        self.assertIn(("SSDT-PLUG", True), entries)
        self.assertIn(("SSDT-EC", True), entries)

    def test_set_acpi_entry_enabled_toggles_the_right_entry(self):
        cfg = _cfg_with_acpi()
        found = config_editor.set_acpi_entry_enabled(cfg, "SSDT-PLUG", False)
        self.assertTrue(found)
        entries = dict(config_editor.get_acpi_entries(cfg))
        self.assertFalse(entries["SSDT-PLUG"])
        self.assertTrue(entries["SSDT-EC"])

    def test_set_acpi_entry_enabled_unknown_name_returns_false(self):
        cfg = _cfg_with_acpi()
        self.assertFalse(config_editor.set_acpi_entry_enabled(cfg, "SSDT-GHOST", False))


class SerialInfoTests(unittest.TestCase):
    def test_reads_serial_mlb_uuid_rom(self):
        cfg = {
            "PlatformInfo": {
                "Generic": {
                    "SystemSerialNumber": "C02ABC123XYZ",
                    "MLB": "C02ABC123XYZ12345",
                    "SystemUUID": "12345678-1234-1234-1234-123456789012",
                    "ROM": bytes.fromhex("001122334455"),
                }
            }
        }
        info = config_editor.get_serial_info(cfg)
        self.assertEqual(info["serial"], "C02ABC123XYZ")
        self.assertEqual(info["mlb"], "C02ABC123XYZ12345")
        self.assertEqual(info["rom"], "001122334455")

    def test_missing_platform_info_returns_empty_strings_not_a_crash(self):
        info = config_editor.get_serial_info({})
        self.assertEqual(info["serial"], "")
        self.assertEqual(info["rom"], "")

    def test_set_serial_info_writes_all_fields(self):
        cfg = {}
        config_editor.set_serial_info(
            cfg, serial="NEWSERIAL123", mlb="NEWMLB123456789", uuid="ABCDEF00-0000-0000-0000-000000000000",
            rom="aabbccddeeff",
        )
        info = config_editor.get_serial_info(cfg)
        self.assertEqual(info["serial"], "NEWSERIAL123")
        self.assertEqual(info["mlb"], "NEWMLB123456789")
        self.assertEqual(info["rom"], "aabbccddeeff")

    def test_set_serial_info_partial_update_does_not_clear_other_fields(self):
        cfg = {"PlatformInfo": {"Generic": {"SystemSerialNumber": "KEEPME", "MLB": "KEEPTOO"}}}
        config_editor.set_serial_info(cfg, uuid="ABCDEF00-0000-0000-0000-000000000000")
        info = config_editor.get_serial_info(cfg)
        self.assertEqual(info["serial"], "KEEPME")
        self.assertEqual(info["mlb"], "KEEPTOO")
        self.assertEqual(info["uuid"], "ABCDEF00-0000-0000-0000-000000000000")

    def test_set_serial_info_accepts_colon_separated_rom(self):
        cfg = {}
        config_editor.set_serial_info(cfg, rom="aa:bb:cc:dd:ee:ff")
        self.assertEqual(config_editor.get_serial_info(cfg)["rom"], "aabbccddeeff")


if __name__ == "__main__":
    unittest.main()


class BootArgsTests(unittest.TestCase):
    def test_parse_splits_flags_and_key_values(self):
        parsed = config_editor.parse_boot_args("-v keepsyms=1 debug=0x100 -no_compat_check")
        self.assertEqual(parsed["-v"], True)
        self.assertEqual(parsed["keepsyms"], "1")
        self.assertEqual(parsed["debug"], "0x100")
        self.assertEqual(parsed["-no_compat_check"], True)

    def test_serialize_drops_false_and_empty_keeps_flags(self):
        out = config_editor.serialize_boot_args({"-v": True, "debug": "0x100", "off": False, "blank": ""})
        self.assertIn("-v", out.split())
        self.assertIn("debug=0x100", out.split())
        self.assertNotIn("off", out)
        self.assertNotIn("blank", out)

    def test_round_trips_through_a_config(self):
        cfg = {}
        config_editor.set_boot_args(cfg, {"-v": True, "alcid": "11"})
        self.assertEqual(config_editor.get_boot_args(cfg), {"-v": True, "alcid": "11"})

    def test_get_boot_args_on_empty_config_is_empty_dict(self):
        self.assertEqual(config_editor.get_boot_args({}), {})


class ResolvePathTests(unittest.TestCase):
    def test_get_and_set_walk_dotted_path(self):
        cfg = {"Misc": {"Boot": {"Timeout": 5}}}
        self.assertEqual(config_editor.get_value(cfg, "Misc.Boot.Timeout"), 5)
        config_editor.set_value(cfg, "Misc.Boot.Timeout", 10)
        self.assertEqual(cfg["Misc"]["Boot"]["Timeout"], 10)

    def test_missing_intermediate_key_raises_keyerror(self):
        with self.assertRaises(KeyError):
            config_editor.get_value({}, "Misc.Boot.Timeout")


class SipTests(unittest.TestCase):
    def test_all_zero_csr_reads_as_enabled(self):
        cfg = {"NVRAM": {"Add": {config_editor._NVRAM_KEY: {"csr-active-config": bytes(4)}}}}
        self.assertTrue(config_editor.get_sip_enabled(cfg))

    def test_nonzero_csr_reads_as_disabled(self):
        cfg = {"NVRAM": {"Add": {config_editor._NVRAM_KEY: {"csr-active-config": bytes([3, 0, 0, 0])}}}}
        self.assertFalse(config_editor.get_sip_enabled(cfg))

    def test_missing_csr_defaults_to_enabled(self):
        self.assertTrue(config_editor.get_sip_enabled({}))

    def test_set_sip_round_trips_both_ways(self):
        cfg = {}
        config_editor.set_sip(cfg, False)
        self.assertFalse(config_editor.get_sip_enabled(cfg))
        config_editor.set_sip(cfg, True)
        self.assertTrue(config_editor.get_sip_enabled(cfg))


class MiscBootGettersTests(unittest.TestCase):
    def test_defaults_when_unset(self):
        self.assertTrue(config_editor.get_hide_auxiliary({}))
        self.assertEqual(config_editor.get_timeout({}), 5)
        self.assertFalse(config_editor.get_oc_logging({}))
        self.assertEqual(config_editor.get_secure_boot_model({}), "Disabled")
        self.assertEqual(config_editor.get_smbios({}), "")

    def test_timeout_coerces_and_falls_back_on_garbage(self):
        self.assertEqual(config_editor.get_timeout({"Misc": {"Boot": {"Timeout": "12"}}}), 12)
        self.assertEqual(config_editor.get_timeout({"Misc": {"Boot": {"Timeout": "nope"}}}), 5)

    def test_oc_logging_setter_flips_the_debug_block(self):
        cfg = {}
        config_editor.set_oc_logging(cfg, True)
        dbg = cfg["Misc"]["Debug"]
        self.assertEqual(dbg["Target"], 67)
        self.assertTrue(dbg["AppleDebug"] and dbg["ApplePanic"] and dbg["DisableWatchDog"])
        config_editor.set_oc_logging(cfg, False)
        self.assertEqual(cfg["Misc"]["Debug"]["Target"], 0)

    def test_smbios_and_secure_boot_round_trip(self):
        cfg = {}
        config_editor.set_smbios(cfg, "MacBookPro15,2")
        config_editor.set_secure_boot_model(cfg, "j137")
        self.assertEqual(config_editor.get_smbios(cfg), "MacBookPro15,2")
        self.assertEqual(config_editor.get_secure_boot_model(cfg), "j137")


class IgpuPlatformIdTests(unittest.TestCase):
    def test_round_trips_ig_platform_id_as_hex(self):
        cfg = {}
        config_editor.set_igpu_platform_id(cfg, "0000923e")
        self.assertEqual(config_editor.get_igpu_platform_id(cfg), "0000923e")
        stored = cfg["DeviceProperties"]["Add"][config_editor._IGPU_PATH]["AAPL,ig-platform-id"]
        self.assertEqual(stored, bytes.fromhex("0000923e"))

    def test_empty_hex_is_a_no_op(self):
        cfg = {}
        config_editor.set_igpu_platform_id(cfg, "")
        self.assertEqual(cfg, {})

    def test_missing_returns_empty_string(self):
        self.assertEqual(config_editor.get_igpu_platform_id({}), "")


class SuggestionTableTests(unittest.TestCase):
    def test_audio_layouts_match_by_substring_case_insensitive(self):
        self.assertEqual(
            config_editor.suggest_audio_layouts("realtek alc257"),
            config_editor.AUDIO_LAYOUTS["ALC257"],
        )

    def test_unknown_codec_returns_empty(self):
        self.assertEqual(config_editor.suggest_audio_layouts("Cirrus Logic"), [])

    def test_framebuffer_lookup_is_case_insensitive(self):
        known = next(iter(config_editor.IGPU_FRAMEBUFFERS))
        self.assertEqual(
            config_editor.suggest_framebuffers(known.upper()),
            config_editor.IGPU_FRAMEBUFFERS[known],
        )
        self.assertEqual(config_editor.suggest_framebuffers("dead:beef"), [])


class CoerceValueTests(unittest.TestCase):
    def test_bool_truthy_and_falsy_strings(self):
        for s in ("true", "Yes", "1", "on"):
            self.assertTrue(config_editor.coerce_value(s, "bool"))
        for s in ("false", "no", "0", "", "off"):
            self.assertFalse(config_editor.coerce_value(s, "bool"))

    def test_int_and_data_and_default_string(self):
        self.assertEqual(config_editor.coerce_value("42", "int"), 42)
        self.assertEqual(config_editor.coerce_value("de ad be ef", "data"), bytes.fromhex("deadbeef"))
        self.assertEqual(config_editor.coerce_value("hello", "str"), "hello")


class LoadSaveConfigTests(unittest.TestCase):
    def test_save_then_load_round_trips_a_plist(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.plist"
            original = {"Misc": {"Boot": {"Timeout": 3}}, "flag": True}
            config_editor.save_config(p, original)
            self.assertEqual(config_editor.load_config(p), original)
