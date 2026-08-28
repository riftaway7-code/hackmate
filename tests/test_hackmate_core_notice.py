import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hackmate_core_notice


class NoticeMarkerTests(unittest.TestCase):
    def test_not_shown_before_marking(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".hackmate" / "hackmate_core_notice.json"
            with patch.object(hackmate_core_notice, "_NOTICE_PATH", marker):
                self.assertFalse(hackmate_core_notice.already_shown())

    def test_mark_shown_creates_marker_and_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".hackmate" / "hackmate_core_notice.json"
            with patch.object(hackmate_core_notice, "_NOTICE_PATH", marker):
                hackmate_core_notice.mark_shown()
                self.assertTrue(marker.exists())
                self.assertTrue(hackmate_core_notice.already_shown())

    def test_mark_shown_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".hackmate" / "hackmate_core_notice.json"
            with patch.object(hackmate_core_notice, "_NOTICE_PATH", marker):
                hackmate_core_notice.mark_shown()
                hackmate_core_notice.mark_shown()
                self.assertTrue(hackmate_core_notice.already_shown())

    @unittest.skipUnless(sys.platform.startswith("linux"), "SUDO_USER path uses the Unix-only pwd module")
    def test_prefers_sudo_user_home(self):
        import os
        import pwd

        fake = type("pw", (), {"pw_dir": "/home/realuser"})()
        with (
            patch.dict(os.environ, {"SUDO_USER": "realuser"}, clear=False),
            patch.object(pwd, "getpwnam", return_value=fake),
        ):
            self.assertEqual(hackmate_core_notice._real_home(), Path("/home/realuser"))


class DefaultOnTests(unittest.TestCase):
    def test_generate_still_defaults_off_for_bare_calls(self):
        import config_gen
        from hardware import HardwareProfile
        from smbios import SMBIOSData

        prof = HardwareProfile(cpu_vendor="intel", cpu_generation=8, platform="desktop")
        smb = SMBIOSData(
            model="iMac18,3", serial="C02XXXXXXXXX", board_serial="C02XXXXXXXXXXXXXX",
            system_uuid="12345678-1234-1234-1234-123456789ABC", rom="001122334455",
        )
        self.assertEqual(config_gen.generate(prof, smb).get("Misc", {}).get("Boot", {}).get("PickerMode"), "Builtin")


if __name__ == "__main__":
    unittest.main()
