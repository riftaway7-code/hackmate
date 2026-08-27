import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import log_checker
from log_checker import Finding
from hardware import HardwareProfile


class ExtractContextTests(unittest.TestCase):
    def test_marks_the_matched_line_with_an_arrow(self):
        lines = ["a", "b", "c", "d", "e"]
        ctx = log_checker._extract_context(lines, 2, radius=1)
        self.assertEqual(ctx, ["  b", "→ c", "  d"])

    def test_clamps_radius_at_start_of_file(self):
        lines = ["a", "b", "c"]
        ctx = log_checker._extract_context(lines, 0, radius=2)
        self.assertEqual(ctx, ["→ a", "  b", "  c"])

    def test_clamps_radius_at_end_of_file(self):
        lines = ["a", "b", "c"]
        ctx = log_checker._extract_context(lines, 2, radius=2)
        self.assertEqual(ctx, ["  a", "  b", "→ c"])

    def test_long_lines_are_truncated(self):
        lines = ["x" * 200]
        ctx = log_checker._extract_context(lines, 0, radius=0)
        self.assertEqual(len(ctx[0]), 122)  # "→ " prefix + 120 chars


class DetectLogTypeTests(unittest.TestCase):
    def test_kernel_panic_by_panic_header(self):
        text = "panic(cpu 0 caller 0xffffff): something bad happened"
        self.assertEqual(log_checker._detect_log_type(text), "kernel_panic")

    def test_kernel_panic_by_backtrace_marker(self):
        text = "some log text\nBacktrace (CPU 0), Frame : Return Address\n"
        self.assertEqual(log_checker._detect_log_type(text), "kernel_panic")

    def test_oc_log_by_oc_prefix(self):
        text = "OC: OpenCore booting...\nOCB: loaded config"
        self.assertEqual(log_checker._detect_log_type(text), "oc_log")

    def test_generic_fallback(self):
        text = "just some random boot output with nothing recognizable"
        self.assertEqual(log_checker._detect_log_type(text), "generic")


class AnalyzeOcLogTests(unittest.TestCase):
    def test_matches_a_known_pattern(self):
        text = "OC: booting\nStill waiting for root device\n"
        findings = log_checker._analyze_oc_log(text)
        titles = {f.title for f in findings}
        self.assertIn("USB ports not mapped — macOS cannot find the disk", titles)

    def test_matching_pattern_suppresses_its_declared_followups(self):
        """'Still waiting for root device' suppresses the usb-port-limit and
        usb-xhci tagged patterns, even when their own regex also matches —
        they're downstream noise once the root cause is already identified."""
        text = (
            "Still waiting for root device\n"
            "XhciPortLimit true\n"
            "AppleUSBXHCI reset\n"
        )
        findings = log_checker._analyze_oc_log(text)
        titles = {f.title for f in findings}
        self.assertIn("USB ports not mapped — macOS cannot find the disk", titles)
        self.assertNotIn("USB port limit patch active — causes panics on macOS 12+", titles)
        self.assertNotIn("USB controller (XHCI) reset loop", titles)

    def test_same_pattern_matching_multiple_lines_is_reported_once(self):
        text = "Still waiting for root device\nStill waiting for root device\n"
        findings = log_checker._analyze_oc_log(text)
        matches = [f for f in findings if "USB ports not mapped" in f.title]
        self.assertEqual(len(matches), 1)

    def test_no_matches_returns_empty_list(self):
        text = "totally unremarkable log output\n"
        self.assertEqual(log_checker._analyze_oc_log(text), [])


class AnalyzeKernelPanicTests(unittest.TestCase):
    def test_known_panic_reason_maps_to_specific_finding(self):
        text = 'panic(cpu 0 caller 0xffffff801234): "MSR_PKG_CST_CONFIG_CONTROL write failed"\n'
        findings = log_checker._analyze_kernel_panic(text)
        self.assertTrue(any("CFG Lock" in f.title for f in findings))

    def test_unrecognized_panic_reason_gets_generic_finding(self):
        text = 'panic(cpu 0 caller 0xffffff801234): "some totally novel panic string"\n'
        findings = log_checker._analyze_kernel_panic(text)
        self.assertTrue(any(f.category == "unknown" and f.confidence == "possible" for f in findings))

    def test_third_party_kext_at_top_of_backtrace_is_flagged_critical(self):
        text = (
            'panic(cpu 0 caller 0xffffff801234): "totally novel panic"\n'
            "Kernel Extensions in backtrace:\n"
            "com.example.SomeThirdPartyKext(1.0)[uuid]\n"
            "com.apple.driver.AppleACPIPlatform(1.0)[uuid]\n\n"
        )
        findings = log_checker._analyze_kernel_panic(text)
        self.assertTrue(any(
            f.category == "kext" and f.severity == "critical" and "SomeThirdPartyKext" in f.title
            for f in findings
        ))

    def test_apple_kext_at_top_of_backtrace_is_not_flagged(self):
        text = (
            'panic(cpu 0 caller 0xffffff801234): "totally novel panic"\n'
            "Kernel Extensions in backtrace:\n"
            "com.apple.driver.AppleACPIPlatform(1.0)[uuid]\n\n"
        )
        findings = log_checker._analyze_kernel_panic(text)
        self.assertFalse(any(f.category == "kext" and f.severity == "critical" for f in findings))


class EnrichRootHashTests(unittest.TestCase):
    def _finding(self):
        return Finding(
            severity="critical", category="boot",
            title="Recovery image root hash check failed",
            explanation="original", fix_steps=["original step"],
        )

    def test_rewrites_when_secure_boot_model_is_disabled(self):
        f = self._finding()
        log_checker._enrich_root_hash([f], "Disabled")
        self.assertIn("very likely benign", f.explanation)
        self.assertEqual(f.confidence, "possible")

    def test_case_insensitive_match(self):
        f = self._finding()
        log_checker._enrich_root_hash([f], "disabled")
        self.assertIn("very likely benign", f.explanation)

    def test_no_change_when_secure_boot_model_is_none(self):
        f = self._finding()
        log_checker._enrich_root_hash([f], None)
        self.assertEqual(f.explanation, "original")

    def test_no_change_when_secure_boot_model_is_not_disabled(self):
        f = self._finding()
        log_checker._enrich_root_hash([f], "Default")
        self.assertEqual(f.explanation, "original")

    def test_other_findings_are_untouched(self):
        f = Finding(severity="warning", category="usb", title="Some other finding",
                     explanation="original", fix_steps=[])
        log_checker._enrich_root_hash([f], "Disabled")
        self.assertEqual(f.explanation, "original")


class EnrichTests(unittest.TestCase):
    def test_audio_finding_gets_codec_appended(self):
        f = Finding(severity="critical", category="audio", title="x", explanation="base", fix_steps=[])
        profile = HardwareProfile(audio_codec="ALC256")
        log_checker._enrich([f], profile)
        self.assertIn("ALC256", f.explanation)
        self.assertIn("ALC256", f.fix_steps[0])

    def test_gpu_finding_gets_device_id_appended(self):
        f = Finding(severity="warning", category="gpu", title="x", explanation="base", fix_steps=[])
        profile = HardwareProfile(gpu_device_id="0x1912")
        log_checker._enrich([f], profile)
        self.assertIn("0x1912", f.explanation)

    def test_amd_cfg_lock_note_is_appended(self):
        f = Finding(severity="critical", category="cpu", title="CFG Lock is on — MSR 0xE2 is write-protected",
                     explanation="base", fix_steps=[])
        profile = HardwareProfile(cpu_vendor="amd")
        log_checker._enrich([f], profile)
        self.assertTrue(any("AMD CPUs don't have CFG Lock" in step for step in f.fix_steps))

    def test_intel_cpu_does_not_get_amd_cfg_lock_note(self):
        f = Finding(severity="critical", category="cpu", title="CFG Lock is on — MSR 0xE2 is write-protected",
                     explanation="base", fix_steps=[])
        profile = HardwareProfile(cpu_vendor="intel")
        log_checker._enrich([f], profile)
        self.assertFalse(any("AMD CPUs don't have CFG Lock" in step for step in f.fix_steps))

    def test_laptop_usb_finding_gets_extra_note(self):
        f = Finding(severity="critical", category="usb", title="x", explanation="base",
                     fix_steps=["Run USBToolBox to map your ports."])
        profile = HardwareProfile(platform="laptop")
        log_checker._enrich([f], profile)
        self.assertTrue(any("USB 2.0 ports during install" in step for step in f.fix_steps))

    def test_desktop_usb_finding_does_not_get_laptop_note(self):
        f = Finding(severity="critical", category="usb", title="x", explanation="base",
                     fix_steps=["Run USBToolBox to map your ports."])
        profile = HardwareProfile(platform="desktop")
        log_checker._enrich([f], profile)
        self.assertFalse(any("USB 2.0 ports during install" in step for step in f.fix_steps))


class SortTests(unittest.TestCase):
    def test_critical_sorts_before_warning_before_info(self):
        findings = [
            Finding(severity="info", category="a", title="i", explanation="", fix_steps=[]),
            Finding(severity="critical", category="z", title="c", explanation="", fix_steps=[]),
            Finding(severity="warning", category="m", title="w", explanation="", fix_steps=[]),
        ]
        result = log_checker._sort(findings)
        self.assertEqual([f.severity for f in result], ["critical", "warning", "info"])

    def test_same_severity_sorts_by_category(self):
        findings = [
            Finding(severity="critical", category="usb", title="a", explanation="", fix_steps=[]),
            Finding(severity="critical", category="boot", title="b", explanation="", fix_steps=[]),
        ]
        result = log_checker._sort(findings)
        self.assertEqual([f.category for f in result], ["boot", "usb"])


class AnalyzeEndToEndTests(unittest.TestCase):
    def test_dispatches_to_kernel_panic_analyzer(self):
        text = 'panic(cpu 0 caller 0xffffff801234): "MSR_PKG_CST_CONFIG_CONTROL write failed"\n'
        findings = log_checker.analyze(text)
        self.assertTrue(any("CFG Lock" in f.title for f in findings))

    def test_dispatches_to_oc_log_analyzer(self):
        text = "OC: booting\nStill waiting for root device\n"
        findings = log_checker.analyze(text)
        self.assertTrue(any("USB ports not mapped" in f.title for f in findings))

    def test_clean_log_returns_no_known_issues_finding(self):
        findings = log_checker.analyze("nothing interesting here at all\n")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].title, "No known issues detected")

    def test_profile_enrichment_is_applied_end_to_end(self):
        text = "OC: booting\nPrelinked injection VoodooHDA.kext ... Invalid Parameter\n"
        profile = HardwareProfile(audio_codec="ALC1220")
        findings = log_checker.analyze(text, profile=profile)
        audio_findings = [f for f in findings if f.category == "audio"]
        self.assertTrue(audio_findings)
        self.assertIn("ALC1220", audio_findings[0].explanation)

    def test_secure_boot_model_enrichment_is_applied_end_to_end(self):
        text = "OC: booting\nErr(0xE) something root_hash failed\n"
        findings = log_checker.analyze(text, secure_boot_model="Disabled")
        root_hash = next(f for f in findings if f.title == "Recovery image root hash check failed")
        self.assertIn("very likely benign", root_hash.explanation)

    def test_results_are_sorted_by_severity(self):
        text = "OC: booting\nStill waiting for root device\n"
        findings = log_checker.analyze(text)
        severities = [log_checker._SEV.get(f.severity, 9) for f in findings]
        self.assertEqual(severities, sorted(severities))


class FindConfigPlistTests(unittest.TestCase):
    def test_finds_config_plist_next_to_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "opencore-log.txt"
            log_path.write_text("log")
            (root / "config.plist").write_bytes(plistlib.dumps({}))

            found = log_checker._find_config_plist(log_path)
        self.assertEqual(found.name, "config.plist")

    def test_finds_config_plist_in_oc_subdir_of_grandparent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "misc" / "logs"
            log_dir.mkdir(parents=True)
            log_path = log_dir / "opencore-log.txt"
            log_path.write_text("log")
            oc_dir = root / "misc" / "OC"
            oc_dir.mkdir(parents=True)
            (oc_dir / "config.plist").write_bytes(plistlib.dumps({}))

            found = log_checker._find_config_plist(log_path)
        self.assertEqual(found.name, "config.plist")

    def test_returns_none_when_no_config_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "opencore-log.txt"
            log_path.write_text("log")
            self.assertIsNone(log_checker._find_config_plist(log_path))


class AnalyzeFileTests(unittest.TestCase):
    def test_unreadable_file_returns_critical_finding(self):
        findings = log_checker.analyze_file("/definitely/does/not/exist.txt")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "critical")
        self.assertEqual(findings[0].title, "Could not read log file")

    def test_reads_real_file_and_picks_up_secure_boot_model_from_sibling_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "opencore-log.txt"
            log_path.write_text("OC: booting\nErr(0xE) something root_hash failed\n")
            config = {"Misc": {"Security": {"SecureBootModel": "Disabled"}}}
            (root / "config.plist").write_bytes(plistlib.dumps(config))

            findings = log_checker.analyze_file(log_path)

        root_hash = next(f for f in findings if f.title == "Recovery image root hash check failed")
        self.assertIn("very likely benign", root_hash.explanation)


if __name__ == "__main__":
    unittest.main()
