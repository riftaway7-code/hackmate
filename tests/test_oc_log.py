import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import oc_log


class ParseLogPatternTests(unittest.TestCase):
    def _findings(self, text: str) -> list[tuple[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "opencore-0000.txt"
            log.write_text(text, encoding="utf-8")
            return oc_log.parse_log(log)

    def test_root_hash_error_maps_to_secure_boot_advice(self):
        findings = self._findings("OCB: LoadImage failed - Err(0xE) ... root_hash mismatch\n")
        self.assertEqual(findings[0][0], "error")
        self.assertIn("SecureBootModel", findings[0][1])

    def test_pattern_match_is_case_insensitive(self):
        findings = self._findings("some PANIC PRIOR TO INITIALIZATION of the kernel\n")
        self.assertTrue(any(level == "error" for level, _ in findings))
        self.assertIn("Kernel panic", findings[0][1])

    def test_each_explanation_is_only_reported_once(self):
        text = (
            "Could not load VoodooI2C.kext\n"
            "later on: Could not load Lilu.kext\n"
        )
        explanations = [msg for level, msg in self._findings(text) if level == "error"]
        self.assertEqual(len(explanations), len(set(explanations)))
        self.assertEqual(len(explanations), 1)

    def test_multiple_distinct_patterns_all_report(self):
        text = (
            "Err(0xE) EB.LD.OpenPartition failed\n"
            "OCABC: MMIO devirt ... stall detected\n"
        )
        errors = [msg for level, msg in self._findings(text) if level == "error"]
        self.assertEqual(len(errors), 2)

    def test_unknown_error_lines_fall_through_to_raw_warn_and_info(self):
        findings = self._findings("OC: Err(0x8000000000000009) doing something obscure\n")
        levels = [level for level, _ in findings]
        self.assertIn("warn", levels)
        self.assertIn("info", levels)
        raw = [msg for level, msg in findings if level == "info"]
        self.assertTrue(any("0x8000000000000009" in line for line in raw))

    def test_raw_line_context_is_capped_at_ten(self):
        text = "".join(f"line {i} panic here\n" for i in range(50))
        info_lines = [msg for level, msg in self._findings(text) if level == "info"]
        self.assertLessEqual(len(info_lines), 10)

    def test_clean_log_says_no_known_errors(self):
        findings = self._findings("OC: Everything booted fine, no problems at all\n")
        self.assertEqual(findings, [("info", "No known errors found in the OpenCore log.")])

    def test_unreadable_path_returns_a_single_error_tuple(self):
        missing = Path(tempfile.gettempdir()) / "hackmate-nope-does-not-exist-42.txt"
        findings = oc_log.parse_log(missing)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], "error")


class FindOcLogTests(unittest.TestCase):
    def test_returns_none_when_no_oc_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(oc_log.find_oc_log(Path(tmp)))

    def test_picks_the_most_recent_log_in_efi_oc(self):
        with tempfile.TemporaryDirectory() as tmp:
            oc_dir = Path(tmp) / "EFI" / "OC"
            oc_dir.mkdir(parents=True)
            (oc_dir / "opencore-0001.txt").write_text("old")
            (oc_dir / "opencore-0007.txt").write_text("new")
            self.assertEqual(oc_log.find_oc_log(Path(tmp)).name, "opencore-0007.txt")

    def test_falls_back_to_efi_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "EFI" / "OC").mkdir(parents=True)
            (Path(tmp) / "opencore-0003.txt").write_text("root log")
            self.assertEqual(oc_log.find_oc_log(Path(tmp)).name, "opencore-0003.txt")


class EnableOcLoggingTests(unittest.TestCase):
    def test_sets_the_debug_keys_and_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.plist"
            cfg.write_bytes(plistlib.dumps({"Misc": {}}))
            self.assertTrue(oc_log.enable_oc_logging(cfg))
            debug = plistlib.loads(cfg.read_bytes())["Misc"]["Debug"]
            self.assertIs(debug["AppleDebug"], True)
            self.assertIs(debug["ApplePanic"], True)
            self.assertIs(debug["DisableWatchDog"], True)
            self.assertEqual(debug["Target"], 67)

    def test_creates_misc_and_debug_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.plist"
            cfg.write_bytes(plistlib.dumps({}))
            self.assertTrue(oc_log.enable_oc_logging(cfg))
            self.assertIn("Debug", plistlib.loads(cfg.read_bytes())["Misc"])

    def test_missing_file_returns_false(self):
        missing = Path(tempfile.gettempdir()) / "hackmate-no-config-99.plist"
        self.assertFalse(oc_log.enable_oc_logging(missing))


if __name__ == "__main__":
    unittest.main()
