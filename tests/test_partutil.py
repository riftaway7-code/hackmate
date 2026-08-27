import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import partutil
from partutil import PartEntry


def _proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _entry(**overrides):
    defaults = dict(
        number=1, start_bytes=1_048_576, end_bytes=100_000_000_000,
        size_bytes=100_000_000_000 - 1_048_576, fs_type="ntfs",
        label="Data", disk="/dev/sda",
    )
    defaults.update(overrides)
    return PartEntry(**defaults)


class PartEntryDeviceNamingTests(unittest.TestCase):
    def test_plain_disk_appends_number_directly(self):
        self.assertEqual(_entry(disk="/dev/sda", number=2).device, "/dev/sda2")

    def test_nvme_disk_gets_p_separator(self):
        self.assertEqual(_entry(disk="/dev/nvme0n1", number=3).device, "/dev/nvme0n1p3")

    def test_mmcblk_disk_gets_p_separator(self):
        self.assertEqual(_entry(disk="/dev/mmcblk0", number=1).device, "/dev/mmcblk0p1")


class PartEntrySizeGbTests(unittest.TestCase):
    def test_size_gb_converts_from_bytes(self):
        entry = _entry(size_bytes=10 * 1024 ** 3)
        self.assertAlmostEqual(entry.size_gb, 10.0)


class ParseSizeInputTests(unittest.TestCase):
    def test_parses_gb_with_space(self):
        self.assertEqual(partutil.parse_size_input("50 GB"), 50 * 1024 ** 3)

    def test_parses_g_shorthand(self):
        self.assertEqual(partutil.parse_size_input("100G"), 100 * 1024 ** 3)

    def test_parses_megabytes(self):
        self.assertEqual(partutil.parse_size_input("500M"), 500 * 1024 ** 2)

    def test_parses_terabytes(self):
        self.assertEqual(partutil.parse_size_input("1T"), 1024 ** 4)

    def test_parses_plain_bytes(self):
        self.assertEqual(partutil.parse_size_input("2048"), 2048)

    def test_parses_fractional_size(self):
        self.assertEqual(partutil.parse_size_input("1.5G"), int(1.5 * 1024 ** 3))

    def test_rejects_garbage_input(self):
        self.assertIsNone(partutil.parse_size_input("not a size"))

    def test_rejects_empty_input(self):
        self.assertIsNone(partutil.parse_size_input(""))


class ListPartitionsParsingTests(unittest.TestCase):
    def test_parses_parted_machine_readable_output(self):
        parted_output = (
            "BYT;\n"
            "/dev/sda:100000000000B:scsi:512:512:gpt:ATA Disk;\n"
            "1:1048576B:538967551B:537919488B:fat32:EFI system partition:boot, esp;\n"
            "2:538968064B:99999999999B:99461031936B:ntfs:Data:;\n"
        )
        with patch.object(partutil.subprocess, "run", return_value=_proc(stdout=parted_output)):
            entries = partutil.list_partitions("/dev/sda")

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].number, 1)
        self.assertEqual(entries[0].fs_type, "fat32")
        self.assertEqual(entries[1].fs_type, "ntfs")
        self.assertEqual(entries[1].label, "Data")
        self.assertEqual(entries[1].size_bytes, 99461031936)

    def test_returns_empty_list_when_parted_unavailable(self):
        with patch.object(partutil.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(partutil.list_partitions("/dev/sda"), [])

    def test_ignores_unparseable_lines(self):
        with patch.object(partutil.subprocess, "run", return_value=_proc(stdout="garbage\nmore garbage\n")):
            self.assertEqual(partutil.list_partitions("/dev/sda"), [])


class CheckToolsTests(unittest.TestCase):
    def test_reports_which_tool_is_present(self):
        with patch.object(partutil.shutil, "which", side_effect=lambda t: "/usr/bin/" + t if t == "parted" else None):
            result = partutil.check_tools()
        self.assertTrue(result["parted"])
        self.assertFalse(result["ntfsresize"])


class GetMinNtfsSizeTests(unittest.TestCase):
    def test_parses_you_might_resize_message(self):
        stdout = "You might resize at 21474836480 bytes or 20 GB (freeing 1 GB).\n"
        with patch.object(partutil.subprocess, "run", return_value=_proc(stdout=stdout)):
            self.assertEqual(partutil.get_min_ntfs_size("/dev/sda2"), 21474836480)

    def test_parses_minimum_size_message(self):
        stdout = "minimum resize size: 5000000\n"
        with patch.object(partutil.subprocess, "run", return_value=_proc(stdout=stdout)):
            self.assertEqual(partutil.get_min_ntfs_size("/dev/sda2"), 5000000)

    def test_returns_none_when_output_unrecognized(self):
        with patch.object(partutil.subprocess, "run", return_value=_proc(stdout="nothing useful here")):
            self.assertIsNone(partutil.get_min_ntfs_size("/dev/sda2"))

    def test_returns_none_on_subprocess_failure(self):
        with patch.object(partutil.subprocess, "run", side_effect=OSError()):
            self.assertIsNone(partutil.get_min_ntfs_size("/dev/sda2"))


class ResizePartitionDispatchTests(unittest.TestCase):
    def test_refuses_to_grow_or_keep_same_size(self):
        entry = _entry(fs_type="ntfs", size_bytes=100)
        result = partutil.resize_partition(entry, new_size_bytes=100)
        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("smaller", result)

    def test_refuses_growth_beyond_current_size(self):
        entry = _entry(fs_type="ntfs", size_bytes=100)
        result = partutil.resize_partition(entry, new_size_bytes=200)
        self.assertTrue(result.startswith("ERROR"))

    def test_unsupported_filesystem_is_rejected(self):
        entry = _entry(fs_type="xfs", size_bytes=1000)
        result = partutil.resize_partition(entry, new_size_bytes=500)
        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("not supported", result)

    def test_ntfs_dispatches_to_ntfs_resize(self):
        entry = _entry(fs_type="ntfs", size_bytes=1000)
        with patch.object(partutil, "_resize_ntfs", return_value="OK") as mocked:
            result = partutil.resize_partition(entry, new_size_bytes=500)
        self.assertEqual(result, "OK")
        mocked.assert_called_once()

    def test_ext_family_dispatches_to_ext4_resize(self):
        for fs in ("ext2", "ext3", "ext4"):
            with self.subTest(fs=fs):
                entry = _entry(fs_type=fs, size_bytes=1000)
                with patch.object(partutil, "_resize_ext4", return_value="OK") as mocked:
                    result = partutil.resize_partition(entry, new_size_bytes=500)
                self.assertEqual(result, "OK")
                mocked.assert_called_once()

    def test_btrfs_dispatches_to_btrfs_resize(self):
        entry = _entry(fs_type="btrfs", size_bytes=1000)
        with patch.object(partutil, "_resize_btrfs", return_value="OK") as mocked:
            result = partutil.resize_partition(entry, new_size_bytes=500)
        self.assertEqual(result, "OK")
        mocked.assert_called_once()


class ParteedResizeTests(unittest.TestCase):
    def test_success_updates_table_and_notifies_kernel(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _proc(returncode=0)

        with patch.object(partutil.subprocess, "run", side_effect=fake_run):
            result = partutil._parted_resize("/dev/sda", 2, 999, log=lambda m: None)

        self.assertEqual(result, "OK")
        self.assertTrue(any(c[0] == "parted" for c in calls))
        self.assertTrue(any(c[0] == "partprobe" for c in calls))

    def test_failure_is_reported_without_calling_partprobe(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _proc(returncode=1, stderr="resizepart: partition busy")

        with patch.object(partutil.subprocess, "run", side_effect=fake_run):
            result = partutil._parted_resize("/dev/sda", 2, 999, log=lambda m: None)

        self.assertTrue(result.startswith("ERROR"))
        self.assertFalse(any(c[0] == "partprobe" for c in calls))


class ResizeNtfsTests(unittest.TestCase):
    def test_missing_tool_is_reported(self):
        with patch.object(partutil.shutil, "which", return_value=None):
            result = partutil._resize_ntfs("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)
        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("ntfsresize", result)

    def test_dry_run_failure_stops_before_touching_the_filesystem(self):
        with (
            patch.object(partutil.shutil, "which", return_value="/usr/bin/ntfsresize"),
            patch.object(partutil.subprocess, "run", return_value=_proc(returncode=1, stderr="bad geometry")) as run,
        ):
            result = partutil._resize_ntfs("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)

        self.assertTrue(result.startswith("ERROR"))
        run.assert_called_once()  # only the dry-run happened, never the real resize

    def test_full_success_path_resizes_fs_then_partition_table(self):
        responses = iter([
            _proc(returncode=0),  # dry-run
            _proc(returncode=0),  # actual resize
            _proc(returncode=0),  # parted resizepart
            _proc(returncode=0),  # partprobe
        ])
        with (
            patch.object(partutil.shutil, "which", return_value="/usr/bin/ntfsresize"),
            patch.object(partutil.subprocess, "run", side_effect=lambda *a, **k: next(responses)),
        ):
            result = partutil._resize_ntfs("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)

        self.assertEqual(result, "OK")

    def test_real_resize_failure_after_successful_dry_run_is_reported(self):
        responses = iter([
            _proc(returncode=0),               # dry-run passes
            _proc(returncode=1, stderr="I/O error"),  # real resize fails
        ])
        with (
            patch.object(partutil.shutil, "which", return_value="/usr/bin/ntfsresize"),
            patch.object(partutil.subprocess, "run", side_effect=lambda *a, **k: next(responses)),
        ):
            result = partutil._resize_ntfs("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)

        self.assertTrue(result.startswith("ERROR"))


class ResizeExt4Tests(unittest.TestCase):
    def test_refuses_to_resize_a_mounted_filesystem(self):
        with patch.object(Path, "read_text", return_value="/dev/sda2 / ext4 rw 0 0\n"):
            result = partutil._resize_ext4("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)
        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("mounted", result)

    def test_fsck_hard_failure_is_reported(self):
        with (
            patch.object(Path, "read_text", return_value=""),
            patch.object(partutil.subprocess, "run", return_value=_proc(returncode=4, stderr="filesystem corrupt")),
        ):
            result = partutil._resize_ext4("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)
        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("e2fsck", result)

    def test_fsck_return_code_1_meaning_errors_fixed_is_not_fatal(self):
        responses = iter([
            _proc(returncode=1),  # e2fsck: errors corrected, non-fatal per e2fsck's own exit code convention
            _proc(returncode=0),  # resize2fs
            _proc(returncode=0),  # parted resizepart
            _proc(returncode=0),  # partprobe
        ])
        with (
            patch.object(Path, "read_text", return_value=""),
            patch.object(partutil.subprocess, "run", side_effect=lambda *a, **k: next(responses)),
        ):
            result = partutil._resize_ext4("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)
        self.assertEqual(result, "OK")

    def test_resize2fs_failure_is_reported(self):
        responses = iter([
            _proc(returncode=0),                       # e2fsck clean
            _proc(returncode=1, stderr="bad blocks"),   # resize2fs fails
        ])
        with (
            patch.object(Path, "read_text", return_value=""),
            patch.object(partutil.subprocess, "run", side_effect=lambda *a, **k: next(responses)),
        ):
            result = partutil._resize_ext4("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)
        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("resize2fs", result)


class ResizeBtrfsTests(unittest.TestCase):
    def test_requires_the_filesystem_to_be_mounted(self):
        with patch.object(Path, "read_text", return_value=""):
            result = partutil._resize_btrfs("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)
        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("mounted", result)

    def test_success_path_resizes_at_the_mount_point(self):
        mounts = "/dev/sda2 /mnt/data btrfs rw 0 0\n"
        responses = iter([
            _proc(returncode=0),  # btrfs filesystem resize
            _proc(returncode=0),  # parted resizepart
            _proc(returncode=0),  # partprobe
        ])
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return next(responses)

        with (
            patch.object(Path, "read_text", return_value=mounts),
            patch.object(partutil.subprocess, "run", side_effect=fake_run),
        ):
            result = partutil._resize_btrfs("/dev/sda2", "/dev/sda", 2, 500, 999, log=lambda m: None)

        self.assertEqual(result, "OK")
        self.assertIn("/mnt/data", calls[0])


if __name__ == "__main__":
    unittest.main()
