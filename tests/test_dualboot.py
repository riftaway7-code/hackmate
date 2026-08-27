import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dualboot
from dualboot import PartitionInfo, DiskInfo, BootloaderInfo


def _proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _part(**overrides):
    defaults = dict(device="/dev/sda1", size="512 MB", fs_type="vfat",
                     label="EFI", mount="", is_efi=True)
    defaults.update(overrides)
    return PartitionInfo(**defaults)


def _disk(**overrides):
    defaults = dict(device="/dev/sda", model="Test Disk", size="1 TB",
                     transport="SATA", is_gpt=True, partitions=[])
    defaults.update(overrides)
    return DiskInfo(**defaults)


class BytesToHumanTests(unittest.TestCase):
    def test_bytes_stay_as_bytes_below_1024(self):
        self.assertEqual(dualboot._bytes_to_human(512), "512 B")

    def test_converts_to_kb(self):
        self.assertEqual(dualboot._bytes_to_human(2048), "2 KB")

    def test_converts_to_gb(self):
        self.assertEqual(dualboot._bytes_to_human(5 * 1024 ** 3), "5 GB")

    def test_converts_to_tb(self):
        self.assertEqual(dualboot._bytes_to_human(2 * 1024 ** 4), "2 TB")


class ScanLinuxTests(unittest.TestCase):
    def _lsblk(self, blockdevices):
        return json.dumps({"blockdevices": blockdevices})

    def test_parses_disk_and_efi_partition_by_parttype_guid(self):
        data = self._lsblk([{
            "name": "sda", "type": "disk", "size": "1000000000000",
            "model": "Samsung SSD", "tran": "sata", "pttype": "gpt",
            "children": [{
                "name": "sda1", "type": "part", "size": "536870912",
                "fstype": "vfat", "label": "EFI", "mountpoint": "",
                "parttype": dualboot._EFI_GUID,
            }],
        }])
        with patch.object(dualboot.subprocess, "run", return_value=_proc(stdout=data)):
            disks = dualboot._scan_linux()

        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0].device, "/dev/sda")
        self.assertTrue(disks[0].is_gpt)
        self.assertEqual(len(disks[0].partitions), 1)
        self.assertTrue(disks[0].partitions[0].is_efi)

    def test_detects_efi_by_label_when_parttype_missing(self):
        data = self._lsblk([{
            "name": "sda", "type": "disk", "size": "1000000000000", "children": [{
                "name": "sda1", "type": "part", "size": "536870912",
                "fstype": "vfat", "label": "ESP", "mountpoint": "", "parttype": "",
            }],
        }])
        with patch.object(dualboot.subprocess, "run", return_value=_proc(stdout=data)):
            disks = dualboot._scan_linux()
        self.assertTrue(disks[0].partitions[0].is_efi)

    def test_non_vfat_partition_with_esp_label_is_not_efi(self):
        data = self._lsblk([{
            "name": "sda", "type": "disk", "size": "1000000000000", "children": [{
                "name": "sda1", "type": "part", "size": "536870912",
                "fstype": "ext4", "label": "ESP", "mountpoint": "", "parttype": "",
            }],
        }])
        with patch.object(dualboot.subprocess, "run", return_value=_proc(stdout=data)):
            disks = dualboot._scan_linux()
        self.assertFalse(disks[0].partitions[0].is_efi)

    def test_skips_virtual_and_zero_size_devices(self):
        data = self._lsblk([
            {"name": "zram0", "type": "disk", "size": "1000000000"},
            {"name": "loop0", "type": "disk", "size": "1000000000"},
            {"name": "sdb", "type": "disk", "size": "0"},
        ])
        with patch.object(dualboot.subprocess, "run", return_value=_proc(stdout=data)):
            disks = dualboot._scan_linux()
        self.assertEqual(disks, [])

    def test_returns_empty_list_when_lsblk_unavailable(self):
        with patch.object(dualboot.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(dualboot._scan_linux(), [])

    def test_returns_empty_list_on_malformed_json(self):
        with patch.object(dualboot.subprocess, "run", return_value=_proc(stdout="not json")):
            self.assertEqual(dualboot._scan_linux(), [])


class ScanWindowsTests(unittest.TestCase):
    def test_parses_single_disk_dict_form(self):
        payload = json.dumps({
            "device": "Disk0", "model": "NVMe SSD", "size": "1000000000000",
            "transport": "NVMe", "is_gpt": True,
            "partitions": [{
                "name": "Disk0p1", "size": "536870912", "fs": "FAT32",
                "label": "SYSTEM", "mount": "", "is_esp": True,
            }],
        })
        with patch.object(dualboot.subprocess, "run", return_value=_proc(stdout=payload)):
            disks = dualboot._scan_windows()

        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0].device, "Disk0")
        self.assertTrue(disks[0].partitions[0].is_efi)
        self.assertEqual(disks[0].partitions[0].fs_type, "fat32")

    def test_parses_multiple_disks_list_form(self):
        payload = json.dumps([
            {"device": "Disk0", "model": "A", "size": "1", "transport": "SATA",
             "is_gpt": True, "partitions": []},
            {"device": "Disk1", "model": "B", "size": "1", "transport": "USB",
             "is_gpt": False, "partitions": []},
        ])
        with patch.object(dualboot.subprocess, "run", return_value=_proc(stdout=payload)):
            disks = dualboot._scan_windows()
        self.assertEqual(len(disks), 2)
        self.assertFalse(disks[1].is_gpt)

    def test_returns_empty_list_on_powershell_failure(self):
        with patch.object(dualboot.subprocess, "run", side_effect=OSError()):
            self.assertEqual(dualboot._scan_windows(), [])


class ScanEfiDirTests(unittest.TestCase):
    def _mkdir(self, root: Path, *parts):
        p = root.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def test_detects_windows_bootmgr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boot = self._mkdir(root, "EFI", "Microsoft", "Boot")
            (boot / "bootmgfw.efi").write_bytes(b"")
            info = BootloaderInfo(partition="/dev/sda1")
            dualboot._scan_efi_dir(root, info)
        self.assertTrue(info.windows)

    def test_microsoft_dir_without_bootmgfw_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._mkdir(root, "EFI", "Microsoft", "Boot")
            info = BootloaderInfo(partition="/dev/sda1")
            dualboot._scan_efi_dir(root, info)
        self.assertFalse(info.windows)

    def test_detects_grub_linux_distro(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ubuntu = self._mkdir(root, "EFI", "ubuntu")
            (ubuntu / "grubx64.efi").write_bytes(b"")
            info = BootloaderInfo(partition="/dev/sda1")
            dualboot._scan_efi_dir(root, info)
        self.assertTrue(info.linux_grub)

    def test_detects_opencore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oc = self._mkdir(root, "EFI", "OC")
            (oc / "OpenCore.efi").write_bytes(b"")
            info = BootloaderInfo(partition="/dev/sda1")
            dualboot._scan_efi_dir(root, info)
        self.assertTrue(info.opencore)

    def test_detects_refind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            refind = self._mkdir(root, "EFI", "refind")
            (refind / "refind_x64.efi").write_bytes(b"")
            info = BootloaderInfo(partition="/dev/sda1")
            dualboot._scan_efi_dir(root, info)
        self.assertTrue(info.refind)

    def test_unknown_directory_is_recorded_as_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._mkdir(root, "EFI", "SomeVendorTool")
            info = BootloaderInfo(partition="/dev/sda1")
            dualboot._scan_efi_dir(root, info)
        self.assertIn("SomeVendorTool", info.other)

    def test_missing_efi_directory_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info = BootloaderInfo(partition="/dev/sda1")
            dualboot._scan_efi_dir(root, info)  # no EFI/ subdir at all
        self.assertFalse(info.windows)
        self.assertEqual(info.other, [])


class DetectBootloadersTests(unittest.TestCase):
    def test_non_efi_partition_returns_none(self):
        part = _part(is_efi=False)
        self.assertIsNone(dualboot.detect_bootloaders(part))

    def test_already_mounted_partition_is_scanned_directly_without_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oc = root / "EFI" / "OC"
            oc.mkdir(parents=True)
            (oc / "OpenCore.efi").write_bytes(b"")

            part = _part(mount=str(root))
            with patch.object(dualboot.subprocess, "run") as run:
                info = dualboot.detect_bootloaders(part)
            run.assert_not_called()
        self.assertIsNotNone(info)
        self.assertTrue(info.opencore)

    def test_windows_with_no_mount_returns_none(self):
        part = _part(mount="")
        with patch.object(dualboot, "IS_WINDOWS", True):
            self.assertIsNone(dualboot.detect_bootloaders(part))

    def test_linux_mounts_temporarily_then_unmounts_cleanly(self):
        part = _part(mount="")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "mount":
                return _proc(returncode=0)
            return _proc(returncode=0)

        with (
            patch.object(dualboot, "IS_WINDOWS", False),
            patch.object(dualboot.subprocess, "run", side_effect=fake_run),
        ):
            info = dualboot.detect_bootloaders(part)

        self.assertIsNotNone(info)
        self.assertEqual(calls[0][0], "mount")
        self.assertEqual(calls[1][0], "umount")
        self.assertEqual(len(calls), 2)  # no lazy-umount retry needed on clean unmount

    def test_failed_mount_returns_none(self):
        part = _part(mount="")
        with (
            patch.object(dualboot, "IS_WINDOWS", False),
            patch.object(dualboot.subprocess, "run", return_value=_proc(returncode=1)),
        ):
            self.assertIsNone(dualboot.detect_bootloaders(part))

    def test_failed_umount_retries_with_lazy_flag(self):
        """Regression test: a failed `umount` used to be silently ignored,
        leaking the temp mountpoint for the process lifetime."""
        part = _part(mount="")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "mount":
                return _proc(returncode=0)
            if cmd[0] == "umount" and "-l" not in cmd:
                return _proc(returncode=1, stderr="target is busy")
            return _proc(returncode=0)

        with (
            patch.object(dualboot, "IS_WINDOWS", False),
            patch.object(dualboot.subprocess, "run", side_effect=fake_run),
        ):
            dualboot.detect_bootloaders(part)

        umount_calls = [c for c in calls if c[0] == "umount"]
        self.assertEqual(len(umount_calls), 2)
        self.assertNotIn("-l", umount_calls[0])
        self.assertIn("-l", umount_calls[1])


class CheckConflictsTests(unittest.TestCase):
    def test_multiple_internal_opencore_installs_are_flagged(self):
        disks = [_disk(device="/dev/sda", transport="SATA",
                        partitions=[_part(device="/dev/sda1")]),
                 _disk(device="/dev/sdb", transport="SATA",
                        partitions=[_part(device="/dev/sdb1")])]
        bootloaders = {
            "/dev/sda1": BootloaderInfo(partition="/dev/sda1", opencore=True),
            "/dev/sdb1": BootloaderInfo(partition="/dev/sdb1", opencore=True),
        }
        warnings = dualboot.check_conflicts(disks, bootloaders)
        self.assertTrue(any("OpenCore" in w for w in warnings))

    def test_opencore_on_usb_installer_is_not_counted(self):
        disks = [_disk(device="/dev/sda", transport="SATA",
                        partitions=[_part(device="/dev/sda1")]),
                 _disk(device="/dev/sdb", transport="USB",
                        partitions=[_part(device="/dev/sdb1")])]
        bootloaders = {
            "/dev/sda1": BootloaderInfo(partition="/dev/sda1", opencore=True),
            "/dev/sdb1": BootloaderInfo(partition="/dev/sdb1", opencore=True),
        }
        warnings = dualboot.check_conflicts(disks, bootloaders)
        self.assertFalse(any("OpenCore" in w for w in warnings))

    def test_mbr_internal_disk_is_flagged(self):
        disks = [_disk(device="/dev/sda", transport="SATA", is_gpt=False)]
        warnings = dualboot.check_conflicts(disks, {})
        self.assertTrue(any("MBR" in w for w in warnings))

    def test_mbr_usb_disk_is_not_flagged(self):
        disks = [_disk(device="/dev/sdb", transport="USB", is_gpt=False)]
        warnings = dualboot.check_conflicts(disks, {})
        self.assertFalse(any("MBR" in w for w in warnings))

    def test_clean_single_gpt_disk_has_no_warnings(self):
        disks = [_disk(device="/dev/sda", transport="SATA", is_gpt=True,
                        partitions=[_part(device="/dev/sda1")])]
        bootloaders = {"/dev/sda1": BootloaderInfo(partition="/dev/sda1", opencore=True)}
        self.assertEqual(dualboot.check_conflicts(disks, bootloaders), [])


class BuildDiskTreeTests(unittest.TestCase):
    def test_empty_disk_list_message(self):
        self.assertEqual(dualboot.build_disk_tree([], {}), "  No disks found.")

    def test_includes_disk_and_partition_lines(self):
        disks = [_disk(device="/dev/sda", model="Test Disk", partitions=[_part(device="/dev/sda1", label="EFI")])]
        tree = dualboot.build_disk_tree(disks, {})
        self.assertIn("/dev/sda", tree)
        self.assertIn("/dev/sda1", tree)
        self.assertIn("EFI", tree)

    def test_mbr_disk_is_marked(self):
        disks = [_disk(is_gpt=False)]
        tree = dualboot.build_disk_tree(disks, {})
        self.assertIn("MBR", tree)


class FixMacosBootTests(unittest.TestCase):
    def test_copies_oc_directory_and_bootloader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            (src / "OC").mkdir(parents=True)
            (src / "OC" / "config.plist").write_bytes(b"fake")
            (src / "BOOT").mkdir(parents=True)
            (src / "BOOT" / "BOOTx64.efi").write_bytes(b"fake")

            mount = root / "mount"
            mount.mkdir()

            result = dualboot.fix_macos_boot(src, str(mount))

            self.assertEqual(result, "OK")
            self.assertTrue((mount / "EFI" / "OC" / "config.plist").exists())
            self.assertTrue((mount / "EFI" / "BOOT" / "BOOTx64.efi").exists())

    def test_replaces_existing_oc_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            (src / "OC").mkdir(parents=True)
            (src / "OC" / "new.plist").write_bytes(b"new")
            (src / "BOOT").mkdir(parents=True)

            mount = root / "mount"
            old_oc = mount / "EFI" / "OC"
            old_oc.mkdir(parents=True)
            (old_oc / "old.plist").write_bytes(b"old")

            dualboot.fix_macos_boot(src, str(mount))

            self.assertFalse((mount / "EFI" / "OC" / "old.plist").exists())
            self.assertTrue((mount / "EFI" / "OC" / "new.plist").exists())

    def test_missing_source_returns_error_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mount = root / "mount"
            mount.mkdir()
            result = dualboot.fix_macos_boot(root / "nonexistent", str(mount))
        self.assertTrue(result.startswith("ERROR"))


if __name__ == "__main__":
    unittest.main()
