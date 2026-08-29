import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ocvalidate


class BinaryNameTests(unittest.TestCase):
    def test_name_is_platform_specific(self):
        self.assertIn(ocvalidate._binary_name(),
                      {"ocvalidate.exe", "ocvalidate", "ocvalidate.linux"})


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config = Path(self._tmp.name) / "config.plist"
        self.config.write_bytes(b"<plist></plist>")

    def test_missing_config_is_an_error(self):
        ok, lines = ocvalidate.validate(Path(self._tmp.name) / "nope.plist")
        self.assertFalse(ok)
        self.assertTrue(any("not found" in ln for ln in lines))

    def test_unavailable_binary_is_non_fatal(self):
        with patch.object(ocvalidate, "ensure_ocvalidate", return_value=None):
            ok, lines = ocvalidate.validate(self.config)
        self.assertTrue(ok)
        self.assertTrue(any("skipped" in ln for ln in lines))

    def test_clean_run_is_reported_ok(self):
        from unittest.mock import MagicMock
        proc = MagicMock(returncode=0, stdout="Completed validating without errors\n", stderr="")
        with patch.object(ocvalidate, "ensure_ocvalidate", return_value=Path("ocvalidate")), \
             patch.object(ocvalidate.subprocess, "run", return_value=proc):
            ok, lines = ocvalidate.validate(self.config)
        self.assertTrue(ok)
        self.assertIn("Completed validating without errors", lines)

    def test_nonzero_exit_is_reported_as_failure(self):
        from unittest.mock import MagicMock
        proc = MagicMock(returncode=1, stdout="Misc->Security->SecureBootModel is borked\n", stderr="")
        with patch.object(ocvalidate, "ensure_ocvalidate", return_value=Path("ocvalidate")), \
             patch.object(ocvalidate.subprocess, "run", return_value=proc):
            ok, lines = ocvalidate.validate(self.config)
        self.assertFalse(ok)
        self.assertTrue(lines)

    def test_subprocess_failure_is_swallowed_as_skip(self):
        with patch.object(ocvalidate, "ensure_ocvalidate", return_value=Path("ocvalidate")), \
             patch.object(ocvalidate.subprocess, "run", side_effect=OSError("boom")):
            ok, lines = ocvalidate.validate(self.config)
        self.assertTrue(ok)
        self.assertTrue(any("skipped" in ln for ln in lines))


class EnsureFromExtractTests(unittest.TestCase):
    def test_finds_binary_in_an_extracted_tree_and_caches_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            util = root / "Utilities" / "ocvalidate"
            util.mkdir(parents=True)
            binary = util / ocvalidate._binary_name()
            binary.write_bytes(b"x" * (11 * 1024))

            cache = root / "cache" / "ocvalidate"
            with patch.object(ocvalidate, "_CACHE_DIR", cache):
                found = ocvalidate.ensure_ocvalidate(oc_extract_dir=root)
            self.assertIsNotNone(found)
            self.assertEqual(Path(found).read_bytes(), b"x" * (11 * 1024))


if __name__ == "__main__":
    unittest.main()
