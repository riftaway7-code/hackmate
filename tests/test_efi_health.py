import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import efi_check
import efi_health


class LiluDependentsSharedConstantTests(unittest.TestCase):
    """Regression test for the drift bug: efi_health.py used to carry its own,
    smaller copy of the Lilu-plugin list and silently missed load-order
    violations for NootedRed/NootedBlue/FeatureUnlock/CryptexFixup."""

    def test_efi_health_and_efi_check_share_the_same_lilu_dependents_set(self):
        self.assertIs(efi_health.LILU_DEPENDENTS, efi_check.LILU_DEPENDENTS)

    def test_previously_missing_kexts_are_in_the_shared_set(self):
        for kext in ("NootedRed.kext", "NootedBlue.kext", "FeatureUnlock.kext", "CryptexFixup.kext"):
            self.assertIn(kext, efi_health.LILU_DEPENDENTS)


class EfiHealthLiluOrderDetectionTests(unittest.TestCase):
    def test_nooted_red_loaded_before_lilu_is_flagged_as_critical(self):
        cfg = {
            "Kernel": {
                "Add": [
                    {"BundlePath": "NootedRed.kext/Contents/Info.plist",
                     "ExecutablePath": "Contents/MacOS/NootedRed", "Enabled": True},
                    {"BundlePath": "Lilu.kext/Contents/Info.plist", "Enabled": True},
                ]
            }
        }
        out = []
        efi_health._check_kexts(cfg, kext_dir=None, out=out)

        order_findings = [f for f in out if f[1] == "Lilu loads after its plugins"]
        self.assertEqual(len(order_findings), 1)
        self.assertIn("NootedRed.kext", order_findings[0][2])

    def test_lilu_before_its_plugins_is_not_flagged(self):
        cfg = {
            "Kernel": {
                "Add": [
                    {"BundlePath": "Lilu.kext/Contents/Info.plist", "Enabled": True},
                    {"BundlePath": "NootedRed.kext/Contents/Info.plist",
                     "ExecutablePath": "Contents/MacOS/NootedRed", "Enabled": True},
                ]
            }
        }
        out = []
        efi_health._check_kexts(cfg, kext_dir=None, out=out)

        order_findings = [f for f in out if f[1] == "Lilu loads after its plugins"]
        self.assertEqual(order_findings, [])


if __name__ == "__main__":
    unittest.main()
