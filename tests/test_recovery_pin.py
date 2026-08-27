import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import recovery


class MacrecoveryUrlPinTests(unittest.TestCase):
    """Regression guard: MACRECOVERY_URL must stay pinned to a specific
    OpenCorePkg release tag, not `master` — see the comment above the
    constant for why (it runs unreviewed on end-user machines)."""

    def test_url_is_not_tracking_master_branch(self):
        self.assertNotIn("/master/", recovery.MACRECOVERY_URL)

    def test_url_points_at_a_pinned_release_tag(self):
        # e.g. ".../OpenCorePkg/1.0.7/Utilities/..." — a dotted version
        # string in the ref position, not a branch name.
        import re
        self.assertRegex(
            recovery.MACRECOVERY_URL,
            r"OpenCorePkg/\d+\.\d+\.\d+/Utilities/macrecovery/macrecovery\.py$",
        )


if __name__ == "__main__":
    unittest.main()
