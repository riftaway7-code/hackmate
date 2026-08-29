import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_runner
from hardware import HardwareProfile
from recovery import MacOSVersion


class ProfileFromDictTests(unittest.TestCase):
    def test_known_fields_are_kept(self):
        profile = build_runner._profile_from_dict({"cpu_vendor": "intel", "platform": "laptop"})
        self.assertEqual(profile.cpu_vendor, "intel")
        self.assertEqual(profile.platform, "laptop")

    def test_unknown_fields_are_silently_dropped(self):
        profile = build_runner._profile_from_dict({"cpu_vendor": "amd", "totally_made_up": 123})
        self.assertEqual(profile.cpu_vendor, "amd")
        self.assertFalse(hasattr(profile, "totally_made_up"))

    def test_empty_dict_produces_default_profile(self):
        profile = build_runner._profile_from_dict({})
        self.assertEqual(profile, HardwareProfile())


class VersionFromDictTests(unittest.TestCase):
    def test_known_fields_are_kept(self):
        version = build_runner._version_from_dict({
            "name": "macOS Sonoma (14)", "version": "14", "board_id": "Mac-827FAC58A8FDFA22", "mlb": "0" * 17,
        })
        self.assertEqual(version.name, "macOS Sonoma (14)")
        self.assertEqual(version.version, "14")

    def test_unknown_fields_are_silently_dropped(self):
        version = build_runner._version_from_dict({
            "name": "macOS Sonoma (14)", "version": "14", "board_id": "x", "mlb": "0" * 17,
            "made_up_field": True,
        })
        self.assertFalse(hasattr(version, "made_up_field"))


class RunEarlyGuardTests(unittest.TestCase):
    """`run()` validates confirmation text and device connectivity before
    touching the filesystem or network — these guards are cheap to test in
    isolation without mocking the rest of the (very large) build pipeline."""

    def _base_params(self, **overrides):
        params = {
            "profile": {"cpu_vendor": "intel", "platform": "desktop"},
            "macos_version": {"name": "macOS Sonoma (14)", "version": "14", "board_id": "x", "mlb": "0" * 17},
            "device": "/dev/sdb",
            "confirm_phrase": "WRITE /dev/sdb",
        }
        params.update(overrides)
        return params

    def test_wrong_confirm_phrase_raises_before_touching_anything(self):
        params = self._base_params(confirm_phrase="wrong text")
        with patch.object(build_runner.compat, "get_usb_drives") as get_drives:
            with self.assertRaises(ValueError):
                build_runner.run(params, emit=lambda *a: None)
        get_drives.assert_not_called()

    def test_disconnected_device_is_rejected(self):
        params = self._base_params()
        with patch.object(build_runner.compat, "get_usb_drives", return_value=[]):
            with self.assertRaises(RuntimeError):
                build_runner.run(params, emit=lambda *a: None)

    def test_local_mode_skips_the_usb_connectivity_check(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = str(Path(tmp) / "out")
            params = self._base_params(device="local", confirm_phrase="WRITE local", local_output_path=out_dir)

            # Stop the run immediately after the USB-connectivity check point
            # (which local mode must skip) instead of letting the real
            # pipeline proceed into actual network downloads.
            with (
                patch.object(build_runner.compat, "get_usb_drives") as get_drives,
                patch.object(build_runner, "gen_smbios", side_effect=RuntimeError("stop-here")),
            ):
                with self.assertRaises(RuntimeError):
                    build_runner.run(params, emit=lambda *a: None)

            get_drives.assert_not_called()


class SmbiosRegenerationWarningTests(unittest.TestCase):
    """A full (non-repair) build over an EFI that already carries a real
    SMBIOS identity should warn before silently regenerating it — see
    build_runner.py's SMBIOS section. skip_format is what makes the old
    config.plist survive instead of the USB getting reformatted first."""

    def _run_up_to_smbios_check(self, existing_config_plist: bytes | None):
        import plistlib
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp) / "mount"
            oc_dir = mount / "EFI" / "OC"
            oc_dir.mkdir(parents=True)
            if existing_config_plist is not None:
                (oc_dir / "config.plist").write_bytes(existing_config_plist)

            # download_recovery is mocked below (no real network), but the
            # code still lists recovery_dest's contents afterward — give it
            # an empty directory to iterate instead of failing on a missing one.
            (Path(tmp) / "tmp" / "recovery").mkdir(parents=True)

            logs = []

            def emit(method, data):
                if method == "log":
                    logs.append(data)

            params = {
                "profile": {"cpu_vendor": "intel", "platform": "desktop"},
                "macos_version": {"name": "macOS Sonoma (14)", "version": "14", "board_id": "x", "mlb": "0" * 17},
                "device": "/dev/sdb",
                "confirm_phrase": "WRITE /dev/sdb",
                "skip_format": True,
            }

            with (
                patch.object(build_runner.compat, "get_usb_drives", return_value=[("/dev/sdb", "16 GB", "USB")]),
                patch.object(build_runner.compat, "get_mount_path", return_value=str(mount)),
                patch.object(build_runner.compat, "get_tmp_dir", return_value=str(Path(tmp) / "tmp")),
                patch.object(build_runner.compat, "mount_usb", return_value=True),
                # skip_format=True does NOT skip the recovery-download block
                # (only repair/local_mode do) — mock it so this test can't
                # reach real network code before hitting the stop point below.
                patch.object(build_runner, "download_recovery", return_value=(True, "mocked")),
                patch.object(build_runner, "gen_smbios", side_effect=RuntimeError("stop-here")),
            ):
                with self.assertRaises(RuntimeError):
                    build_runner.run(params, emit=emit)

            return logs

    def test_warns_when_existing_config_has_a_real_serial(self):
        import plistlib
        old_config = plistlib.dumps({"PlatformInfo": {"Generic": {"SystemSerialNumber": "C02XG2AWH7JY"}}})
        logs = self._run_up_to_smbios_check(old_config)
        warn_logs = [l for l in logs if l.get("level") == "warn"]
        self.assertTrue(any("real SMBIOS identity" in l["message"] for l in warn_logs))
        self.assertTrue(any("C02XG2AWH7JY" in l["message"] for l in warn_logs))

    def test_no_warning_when_existing_serial_is_a_placeholder(self):
        import plistlib
        old_config = plistlib.dumps({"PlatformInfo": {"Generic": {"SystemSerialNumber": "00000000"}}})
        logs = self._run_up_to_smbios_check(old_config)
        self.assertFalse(any("real SMBIOS identity" in l.get("message", "") for l in logs))

    def test_no_warning_when_no_prior_config_exists(self):
        logs = self._run_up_to_smbios_check(None)
        self.assertFalse(any("real SMBIOS identity" in l.get("message", "") for l in logs))


if __name__ == "__main__":
    unittest.main()
