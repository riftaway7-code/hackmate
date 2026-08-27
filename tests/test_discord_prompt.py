import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import discord_prompt


class ShownStateTests(unittest.TestCase):
    def test_not_shown_when_marker_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".hackmate" / "discord_prompt.json"
            with patch.object(discord_prompt, "_PROMPT_PATH", marker):
                self.assertFalse(discord_prompt.already_shown())

    def test_mark_shown_creates_the_marker_and_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".hackmate" / "discord_prompt.json"
            with patch.object(discord_prompt, "_PROMPT_PATH", marker):
                discord_prompt.mark_shown()
                self.assertTrue(marker.exists())
                self.assertTrue(discord_prompt.already_shown())

    def test_mark_shown_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".hackmate" / "discord_prompt.json"
            with patch.object(discord_prompt, "_PROMPT_PATH", marker):
                discord_prompt.mark_shown()
                discord_prompt.mark_shown()
                self.assertTrue(discord_prompt.already_shown())


class RealHomeTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "SUDO_USER path uses the Unix-only pwd module")
    def test_prefers_sudo_user_home_over_path_home(self):
        import pwd
        fake_pw = type("pw", (), {"pw_dir": "/home/realuser"})()
        with (
            patch.dict("os.environ", {"SUDO_USER": "realuser"}, clear=False),
            patch.object(pwd, "getpwnam", return_value=fake_pw),
        ):
            self.assertEqual(discord_prompt._real_home(), Path("/home/realuser"))

    def test_falls_back_to_path_home_without_sudo_user(self):
        env = {k: v for k, v in __import__("os").environ.items() if k != "SUDO_USER"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(discord_prompt._real_home(), Path.home())


if __name__ == "__main__":
    unittest.main()
