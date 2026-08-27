import plistlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import offline_installer as oi


_CATALOG = plistlib.dumps({
    "Products": {
        "071-EOLD": {  # older Sequoia point release
            "PostDate": "2024-09-16T00:00:00Z",
            "Packages": [
                {"URL": "https://swcdn.apple.com/.../071-EOLD/InstallAssistant.pkg",
                 "Size": 12345678},
            ],
            "Distributions": {"English": "https://swcdn.apple.com/.../seq-15.0.english.dist"},
        },
        "072-NEWR": {  # newer Sequoia point release — should win
            "PostDate": "2024-11-19T00:00:00Z",
            "Packages": [
                {"URL": "https://swcdn.apple.com/.../072-NEWR/InstallAssistant.pkg",
                 "Size": 13000000000},
            ],
            "Distributions": {"English": "https://swcdn.apple.com/.../seq-15.1.1.english.dist"},
        },
        "099-SONO": {  # Sonoma — different major, must be ignored for major "15"
            "PostDate": "2024-10-01T00:00:00Z",
            "Packages": [
                {"URL": "https://swcdn.apple.com/.../099-SONO/InstallAssistant.pkg",
                 "Size": 12000000000},
            ],
            "Distributions": {"English": "https://swcdn.apple.com/.../son-14.7.dist"},
        },
        "010-RCVY": {  # a recovery-only product, no InstallAssistant.pkg
            "PostDate": "2024-11-01T00:00:00Z",
            "Packages": [{"URL": "https://swcdn.apple.com/.../BaseSystem.dmg", "Size": 700000000}],
        },
    }
})

_DISTS = {
    "https://swcdn.apple.com/.../seq-15.0.english.dist":
        b"<installer-gui-script><title>Install macOS Sequoia</title>"
        b"<key>VERSION</key><string>15.0</string><key>BUILD</key><string>24A335</string>"
        b"</installer-gui-script>",
    "https://swcdn.apple.com/.../seq-15.1.1.english.dist":
        b"<installer-gui-script><title>Install macOS Sequoia</title>"
        b"<key>VERSION</key><string>15.1.1</string><key>BUILD</key><string>24B2091</string>"
        b"</installer-gui-script>",
    "https://swcdn.apple.com/.../son-14.7.dist":
        b"<installer-gui-script><title>Install macOS Sonoma</title>"
        b"<key>VERSION</key><string>14.7</string><key>BUILD</key><string>23H124</string>"
        b"</installer-gui-script>",
}


def _fake_http_bytes(url, timeout=60):
    if url == "CATALOG":
        return _CATALOG
    if url in _DISTS:
        return _DISTS[url]
    raise AssertionError(f"unexpected URL {url}")


class ResolveFullInstallerTests(unittest.TestCase):
    def test_picks_the_newest_point_release_for_the_requested_major(self):
        with patch.object(oi, "_http_bytes", side_effect=_fake_http_bytes):
            fi = oi.resolve_full_installer("15", catalog_url="CATALOG")

        self.assertEqual(fi.version, "15.1.1")
        self.assertEqual(fi.build, "24B2091")
        self.assertEqual(fi.size, 13000000000)
        self.assertTrue(fi.url.endswith("072-NEWR/InstallAssistant.pkg"))
        self.assertEqual(fi.title, "Install macOS Sequoia")

    def test_other_majors_are_ignored(self):
        with patch.object(oi, "_http_bytes", side_effect=_fake_http_bytes):
            fi = oi.resolve_full_installer("14", catalog_url="CATALOG")
        self.assertEqual(fi.version, "14.7")

    def test_unsupported_major_raises_before_any_network(self):
        with self.assertRaises(ValueError):
            oi.resolve_full_installer("12", catalog_url="CATALOG")

    def test_missing_major_raises(self):
        with patch.object(oi, "_http_bytes", side_effect=_fake_http_bytes):
            with self.assertRaises(RuntimeError):
                oi.resolve_full_installer("26", catalog_url="CATALOG")


class ExfatCommandTests(unittest.TestCase):
    def test_macos_uses_diskutil_erasedisk(self):
        with patch.object(oi, "IS_MACOS", True), patch.object(oi, "IS_WINDOWS", False):
            cmds = oi.exfat_format_commands("/dev/disk4", "INSTALLER")
        self.assertEqual(cmds, [["diskutil", "eraseDisk", "ExFAT", "INSTALLER", "MBR", "/dev/disk4"]])

    def test_windows_emits_a_diskpart_script(self):
        with patch.object(oi, "IS_MACOS", False), patch.object(oi, "IS_WINDOWS", True):
            cmds = oi.exfat_format_commands("3", "INSTALLER")
        self.assertEqual(cmds[0][0], "diskpart-script")
        self.assertIn("select disk 3", cmds[0])
        self.assertIn("format fs=exfat quick label=INSTALLER", cmds[0])

    def test_linux_wipes_and_mkfs_exfat_the_first_partition(self):
        with patch.object(oi, "IS_MACOS", False), patch.object(oi, "IS_WINDOWS", False):
            cmds = oi.exfat_format_commands("/dev/sdb", "INSTALLER")
        self.assertIn(["wipefs", "-a", "/dev/sdb"], cmds)
        self.assertIn(["mkfs.exfat", "-n", "INSTALLER", "/dev/sdb1"], cmds)


class WholeDiskTests(unittest.TestCase):
    def test_strips_partition_suffixes(self):
        self.assertEqual(oi.whole_disk("/dev/sdb1"), "/dev/sdb")
        self.assertEqual(oi.whole_disk("/dev/nvme0n1p3"), "/dev/nvme0n1")
        self.assertEqual(oi.whole_disk("/dev/mmcblk0p1"), "/dev/mmcblk0")

    def test_leaves_a_whole_disk_alone(self):
        self.assertEqual(oi.whole_disk("/dev/sdb"), "/dev/sdb")
        self.assertEqual(oi.whole_disk("/dev/disk4"), "/dev/disk4")


if __name__ == "__main__":
    unittest.main()
