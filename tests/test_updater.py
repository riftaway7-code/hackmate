import json
import ssl
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import updater


def _http_response(payload):
    body = json.dumps(payload).encode()
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    cm.__exit__.return_value = False
    return cm


class GetTests(unittest.TestCase):
    def test_returns_parsed_json_on_success(self):
        with patch.object(updater.urllib.request, "urlopen", return_value=_http_response({"sha": "abc123"})):
            result = updater._get("https://example.invalid/api")
        self.assertEqual(result, {"sha": "abc123"})

    def test_falls_back_to_unverified_context_on_ssl_error(self):
        good_response = _http_response({"sha": "xyz"})
        with patch.object(
            updater.urllib.request, "urlopen",
            side_effect=[ssl.SSLError("cert failure"), good_response],
        ) as urlopen:
            result = updater._get("https://example.invalid/api")
        self.assertEqual(result, {"sha": "xyz"})
        self.assertEqual(urlopen.call_count, 2)

    def test_returns_none_on_total_failure(self):
        with patch.object(updater.urllib.request, "urlopen", side_effect=OSError("no network")):
            self.assertIsNone(updater._get("https://example.invalid/api"))


class RemoteShaTests(unittest.TestCase):
    def test_returns_sha_when_data_present(self):
        with patch.object(updater, "_get", return_value={"sha": "deadbeef"}):
            self.assertEqual(updater._get_remote_sha(), "deadbeef")

    def test_returns_none_when_request_failed(self):
        with patch.object(updater, "_get", return_value=None):
            self.assertIsNone(updater._get_remote_sha())


class LocalShaTests(unittest.TestCase):
    def test_reads_version_file_when_not_frozen(self):
        with (
            patch.object(updater, "_is_frozen", return_value=False),
            patch.object(updater.Path, "read_text", return_value="  abc123  \n"),
        ):
            self.assertEqual(updater._get_local_sha(), "abc123")

    def test_returns_none_when_version_file_missing(self):
        with (
            patch.object(updater, "_is_frozen", return_value=False),
            patch.object(updater.Path, "read_text", side_effect=FileNotFoundError()),
        ):
            self.assertIsNone(updater._get_local_sha())

    def test_reads_bundled_version_file_when_frozen(self):
        with (
            patch.object(updater, "_is_frozen", return_value=True),
            patch.object(updater.sys, "_MEIPASS", "/fake/meipass", create=True),
            patch.object(updater.Path, "read_text", return_value="frozen-sha\n"),
        ):
            self.assertEqual(updater._get_local_sha(), "frozen-sha")


class ChangelogTests(unittest.TestCase):
    def test_empty_base_sha_returns_no_commits(self):
        self.assertEqual(updater._get_changelog("", "headsha"), [])

    def test_extracts_first_line_of_each_commit_message_in_chronological_order(self):
        payload = {"commits": [
            {"commit": {"message": "fix: newest change\nlonger body"}},
            {"commit": {"message": "feat: add thing"}},
        ]}
        with patch.object(updater, "_get", return_value=payload):
            messages = updater._get_changelog("base", "head")
        # API returns newest-first; function reverses to chronological order.
        self.assertEqual(messages, ["feat: add thing", "fix: newest change"])

    def test_missing_commits_key_returns_empty_list(self):
        with patch.object(updater, "_get", return_value={"unexpected": "shape"}):
            self.assertEqual(updater._get_changelog("base", "head"), [])

    def test_none_response_returns_empty_list(self):
        with patch.object(updater, "_get", return_value=None):
            self.assertEqual(updater._get_changelog("base", "head"), [])

    def test_blank_commit_messages_are_skipped(self):
        payload = {"commits": [{"commit": {"message": "   \n"}}]}
        with patch.object(updater, "_get", return_value=payload):
            self.assertEqual(updater._get_changelog("base", "head"), [])


class IsFrozenAndExeNameTests(unittest.TestCase):
    def test_is_frozen_true_when_sys_frozen_set(self):
        with patch.object(updater.sys, "frozen", True, create=True):
            self.assertTrue(updater._is_frozen())

    def test_is_frozen_false_by_default(self):
        with patch.object(updater.sys, "frozen", False, create=True):
            self.assertFalse(updater._is_frozen())

    def test_exe_name_is_hackmate_when_not_frozen(self):
        with patch.object(updater, "_is_frozen", return_value=False):
            self.assertEqual(updater._current_exe_name(), "HackMate")

    def test_exe_name_comes_from_executable_stem_when_frozen(self):
        with (
            patch.object(updater, "_is_frozen", return_value=True),
            patch.object(updater.sys, "executable", "C:\\path\\HackMate-GUI.exe"),
        ):
            self.assertEqual(updater._current_exe_name(), "HackMate-GUI")


class GetLatestExeUrlTests(unittest.TestCase):
    def test_matches_asset_by_current_exe_name(self):
        data = {"assets": [
            {"name": "HackMate.exe", "browser_download_url": "http://x/HackMate.exe"},
            {"name": "HackMate-GUI.exe", "browser_download_url": "http://x/HackMate-GUI.exe"},
        ]}
        with (
            patch.object(updater, "_get", return_value=data),
            patch.object(updater, "_current_exe_name", return_value="HackMate-GUI"),
        ):
            url = updater._get_latest_exe_url()
        self.assertEqual(url, "http://x/HackMate-GUI.exe")

    def test_falls_back_to_first_exe_asset_when_no_name_match(self):
        data = {"assets": [{"name": "SomethingElse.exe", "browser_download_url": "http://x/other.exe"}]}
        with (
            patch.object(updater, "_get", return_value=data),
            patch.object(updater, "_current_exe_name", return_value="HackMate"),
        ):
            url = updater._get_latest_exe_url()
        self.assertEqual(url, "http://x/other.exe")

    def test_returns_none_when_no_exe_assets(self):
        data = {"assets": [{"name": "source.zip", "browser_download_url": "http://x/source.zip"}]}
        with patch.object(updater, "_get", return_value=data):
            self.assertIsNone(updater._get_latest_exe_url())

    def test_returns_none_when_request_failed(self):
        with patch.object(updater, "_get", return_value=None):
            self.assertIsNone(updater._get_latest_exe_url())


class CheckUpdateSilentTests(unittest.TestCase):
    def test_no_remote_sha_means_no_update(self):
        with patch.object(updater, "_get_remote_sha", return_value=None):
            self.assertEqual(updater.check_update_silent(), (False, "", []))

    def test_matching_shas_means_no_update(self):
        with (
            patch.object(updater, "_get_remote_sha", return_value="same"),
            patch.object(updater, "_get_local_sha", return_value="same"),
        ):
            self.assertEqual(updater.check_update_silent(), (False, "same", []))

    def test_different_shas_returns_update_and_changelog(self):
        with (
            patch.object(updater, "_get_remote_sha", return_value="new-sha"),
            patch.object(updater, "_get_local_sha", return_value="old-sha"),
            patch.object(updater, "_get_changelog", return_value=["fix: something"]),
        ):
            result = updater.check_update_silent()
        self.assertEqual(result, (True, "new-sha", ["fix: something"]))

    def test_no_local_sha_skips_changelog_fetch(self):
        with (
            patch.object(updater, "_get_remote_sha", return_value="new-sha"),
            patch.object(updater, "_get_local_sha", return_value=None),
            patch.object(updater, "_get_changelog") as changelog,
        ):
            result = updater.check_update_silent()
        changelog.assert_not_called()
        self.assertEqual(result, (True, "new-sha", []))


class CheckAndUpdateTests(unittest.TestCase):
    """Only the network-free early-return paths — anything that reaches
    _download_file or input() needs interactive/network mocking beyond what's
    worth maintaining here."""

    def test_offline_returns_false_without_prompting(self):
        with (
            patch.object(updater, "_ping_launch"),
            patch.object(updater, "_get_remote_sha", return_value=None),
            patch("builtins.input") as prompt,
        ):
            result = updater.check_and_update()
        self.assertFalse(result)
        prompt.assert_not_called()

    def test_frozen_and_up_to_date_returns_false_without_prompting(self):
        with (
            patch.object(updater, "_ping_launch"),
            patch.object(updater, "_get_remote_sha", return_value="same-sha"),
            patch.object(updater, "_get_local_sha", return_value="same-sha"),
            patch.object(updater, "_is_frozen", return_value=True),
            patch("builtins.input") as prompt,
        ):
            result = updater.check_and_update()
        self.assertFalse(result)
        prompt.assert_not_called()

    def test_non_frozen_up_to_date_with_no_missing_files_returns_false(self):
        with (
            patch.object(updater, "_ping_launch"),
            patch.object(updater, "_get_remote_sha", return_value="same-sha"),
            patch.object(updater, "_get_local_sha", return_value="same-sha"),
            patch.object(updater, "_is_frozen", return_value=False),
            patch.object(Path, "exists", return_value=True),
            patch("builtins.input") as prompt,
        ):
            result = updater.check_and_update()
        self.assertFalse(result)
        prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
