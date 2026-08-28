import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hackmate_core as hc


class ThemeAssetTests(unittest.TestCase):
    def test_resources_exist(self):
        self.assertTrue(hc.available())
        root = hc.RESOURCES
        for sub in ("Font", "Label", "Image/HackMate/Core"):
            self.assertTrue((root / sub).is_dir(), sub)

    def test_mandatory_icons_present(self):
        core = hc.RESOURCES / "Image" / "HackMate" / "Core"
        for name in ("Background", "Cursor", "Selected", "Selector",
                     "SetDefault", "Left", "Right", "HardDrive"):
            self.assertTrue((core / f"{name}.icns").is_file(), name)

    def test_background_is_a_valid_icns_wrapping_png(self):
        d = (hc.RESOURCES / "Image" / "HackMate" / "Core" / "Background.icns").read_bytes()
        self.assertEqual(d[:4], b"icns")
        self.assertEqual(struct.unpack(">I", d[4:8])[0], len(d))
        off = 8
        seen = []
        while off < len(d):
            tag = d[off:off + 4]
            ln = struct.unpack(">I", d[off + 4:off + 8])[0]
            payload = d[off + 8:off + ln]
            self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n", tag)
            w, h = struct.unpack(">II", payload[16:24])
            seen.append((tag.decode(), w, h))
            off += ln
        self.assertTrue(any(w >= 1920 and h >= 1080 for _, w, h in seen), seen)

    def test_labels_have_both_scales(self):
        label = hc.RESOURCES / "Label"
        stems = {p.stem for p in label.glob("*.lbl")}
        for stem in stems:
            self.assertTrue((label / f"{stem}.l2x").is_file(), stem)


class ConfigPatchTests(unittest.TestCase):
    def _base(self):
        return {
            "Misc": {"Boot": {"PickerAttributes": 1, "PickerMode": "Builtin", "PickerVariant": "Auto"}},
            "UEFI": {"Drivers": [{"Path": "OpenRuntime.efi", "Enabled": True}], "Output": {"Resolution": "Max"}},
        }

    def test_sets_external_picker_and_variant(self):
        c = self._base()
        hc.apply_to_config(c)
        self.assertEqual(c["Misc"]["Boot"]["PickerMode"], "External")
        self.assertEqual(c["Misc"]["Boot"]["PickerVariant"], "HackMate\\Core")

    def test_picker_attributes_keeps_existing_bits_and_adds_flavour_pointer(self):
        c = self._base()
        c["Misc"]["Boot"]["PickerAttributes"] = 0x02
        hc.apply_to_config(c)
        attr = c["Misc"]["Boot"]["PickerAttributes"]
        self.assertTrue(attr & 0x02)
        self.assertTrue(attr & 0x0010)
        self.assertTrue(attr & 0x0080)

    def test_adds_opencanopy_driver_once(self):
        c = self._base()
        hc.apply_to_config(c)
        hc.apply_to_config(c)
        paths = [d["Path"] for d in c["UEFI"]["Drivers"]]
        self.assertEqual(paths.count("OpenCanopy.efi"), 1)
        self.assertIn("OpenRuntime.efi", paths)

    def test_forces_console_gop(self):
        c = self._base()
        hc.apply_to_config(c)
        self.assertIs(c["UEFI"]["Output"]["ProvideConsoleGop"], True)

    def test_minimal_style_sets_minimal_ui_bit(self):
        full = self._base()
        minimal = self._base()
        hc.apply_to_config(full, style="full")
        hc.apply_to_config(minimal, style="minimal")
        self.assertFalse(full["Misc"]["Boot"]["PickerAttributes"] & 0x0040)
        self.assertTrue(minimal["Misc"]["Boot"]["PickerAttributes"] & 0x0040)

    def test_unknown_style_falls_back_to_full(self):
        c = self._base()
        hc.apply_to_config(c, style="nonsense")
        self.assertEqual(
            c["Misc"]["Boot"]["PickerAttributes"] & ~1, hc.PICKER_ATTRIBUTES & ~1
        )


class BackgroundPickTests(unittest.TestCase):
    def _stage(self, tmp):
        import shutil

        core = Path(tmp) / "Image" / "HackMate" / "Core"
        core.mkdir(parents=True)
        src = hc.RESOURCES / "Image" / "HackMate" / "Core"
        for n in ("Background.icns", "Background_1440p.icns", "Background_2160p.icns"):
            shutil.copy(src / n, core / n)
        return core

    def _bg_height(self, path):
        d = path.read_bytes()
        i = d.index(b"\x89PNG\r\n\x1a\n")
        assert d[i + 12:i + 16] == b"IHDR", d[i + 12:i + 16]
        return struct.unpack(">I", d[i + 20:i + 24])[0]

    def test_swaps_to_1440p_for_a_1440p_display(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            core = self._stage(tmp)
            hc._pick_background(core, "2560x1440", lambda *a: None)
            self.assertEqual(self._bg_height(core / "Background.icns"), 1440)

    def test_swaps_to_2160p_for_4k(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            core = self._stage(tmp)
            hc._pick_background(core, "3840x2160", lambda *a: None)
            self.assertEqual(self._bg_height(core / "Background.icns"), 2160)

    def test_leaves_1080p_for_max_or_unknown(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            core = self._stage(tmp)
            hc._pick_background(core, "Max", lambda *a: None)
            self.assertEqual(self._bg_height(core / "Background.icns"), 1080)


class GenerateHookTests(unittest.TestCase):
    def test_generate_flag_enables_the_picker(self):
        import config_gen
        from hardware import HardwareProfile
        from smbios import SMBIOSData

        prof = HardwareProfile(cpu_vendor="intel", cpu_generation=8, platform="desktop")
        smb = SMBIOSData(
            model="iMac18,3", serial="C02XXXXXXXXX", board_serial="C02XXXXXXXXXXXXXX",
            system_uuid="12345678-1234-1234-1234-123456789ABC", rom="001122334455",
        )
        plain = config_gen.generate(prof, smb, macos_major=20)
        themed = config_gen.generate(prof, smb, macos_major=20, hackmate_core=True)
        self.assertEqual(plain["Misc"]["Boot"]["PickerMode"], "Builtin")
        self.assertEqual(themed["Misc"]["Boot"]["PickerMode"], "External")
        self.assertIn("OpenCanopy.efi", [d["Path"] for d in themed["UEFI"]["Drivers"]])


if __name__ == "__main__":
    unittest.main()
