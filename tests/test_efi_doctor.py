import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import efi_doctor


class FindEfiCandidatesTests(unittest.TestCase):
    def test_returns_a_list_and_does_not_raise(self):
        result = efi_doctor.find_efi_candidates()
        self.assertIsInstance(result, list)


class MainArgHandlingTests(unittest.TestCase):
    def _run(self, argv, **patches):
        with (
            patch.object(efi_doctor, "find_efi_candidates", return_value=patches.get("candidates", [])),
            patch.object(efi_doctor, "audit", return_value=patches.get("findings", [])),
            patch.object(efi_doctor, "format_report", return_value=""),
            patch.object(efi_doctor, "summarise", return_value={"critical": patches.get("critical", 0)}),
        ):
            return efi_doctor.main(argv)

    def test_nonexistent_path_returns_1(self):
        code = self._run(["hackmate.py", "--doctor", "/definitely/not/here/xyz"])
        self.assertEqual(code, 1)

    def test_no_path_and_no_candidates_returns_1(self):
        self.assertEqual(self._run(["hackmate.py", "--doctor"]), 1)

    def test_no_path_with_ambiguous_candidates_returns_2(self):
        code = self._run(
            ["hackmate.py", "--doctor"],
            candidates=[Path("/Volumes/EFI"), Path("/Volumes/EFI2")],
        )
        self.assertEqual(code, 2)

    def test_clean_efi_folder_returns_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "OC").mkdir()
            self.assertEqual(
                self._run(["hackmate.py", "--doctor", tmp], critical=0), 0
            )

    def test_efi_with_critical_findings_returns_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "OC").mkdir()
            self.assertEqual(
                self._run(["hackmate.py", "--doctor", tmp], critical=3), 1
            )

    def test_accepts_the_volume_and_descends_into_EFI(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "EFI" / "OC").mkdir(parents=True)
            captured = {}
            with (
                patch.object(efi_doctor, "find_efi_candidates", return_value=[]),
                patch.object(efi_doctor, "audit", side_effect=lambda p: captured.setdefault("path", p) or []),
                patch.object(efi_doctor, "format_report", return_value=""),
                patch.object(efi_doctor, "summarise", return_value={"critical": 0}),
            ):
                efi_doctor.main(["hackmate.py", "--doctor", tmp])
            self.assertEqual(captured["path"].name, "EFI")


if __name__ == "__main__":
    unittest.main()
