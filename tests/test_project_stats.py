import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import project_stats


class BarTests(unittest.TestCase):
    def test_zero_progress_is_all_empty(self):
        bar = project_stats._bar(0, 100, width=10)
        self.assertEqual(bar.count("█"), 0)
        self.assertEqual(bar.count("░"), 10)

    def test_half_progress(self):
        self.assertEqual(project_stats._bar(50, 100, width=10).count("█"), 5)

    def test_overshoot_is_clamped_to_width(self):
        bar = project_stats._bar(999, 100, width=10)
        self.assertEqual(bar.count("█"), 10)
        self.assertEqual(bar.count("░"), 0)

    def test_zero_total_does_not_divide_by_zero(self):
        bar = project_stats._bar(5, 0, width=10)
        self.assertEqual(bar.count("█"), 0)


class FormatStatsPanelTests(unittest.TestCase):
    def test_none_data_renders_unavailable(self):
        out = project_stats.format_stats_panel(None)
        self.assertIn("stats unavailable", out)

    def test_numbers_are_thousands_separated_and_tag_shown(self):
        out = project_stats.format_stats_panel({
            "stars": 1234, "total_downloads": 56789,
            "open_issues": 7, "latest_tag": "v1.4.0",
        })
        self.assertIn("1,234", out)
        self.assertIn("56,789", out)
        self.assertIn("v1.4.0", out)

    def test_missing_tag_falls_back_to_question_mark(self):
        out = project_stats.format_stats_panel({
            "stars": 10, "total_downloads": 0, "open_issues": 0, "latest_tag": None,
        })
        self.assertIn("[#cccccc]?[/]", out)

    def test_star_milestone_step_is_50_below_500_and_100_above(self):
        below = project_stats.format_stats_panel({
            "stars": 120, "total_downloads": 0, "open_issues": 0, "latest_tag": "x",
        })
        self.assertIn("120/150", below)
        above = project_stats.format_stats_panel({
            "stars": 640, "total_downloads": 0, "open_issues": 0, "latest_tag": "x",
        })
        self.assertIn("640/700", above)


class FetchProjectStatsTests(unittest.TestCase):
    def test_merges_repo_over_stats_json_and_reads_latest_tag(self):
        def fake(url, timeout=6):
            if url.endswith("/releases"):
                return [{"tag_name": "v2.0.0"}, {"tag_name": "v1.9.0"}]
            if "api.github.com" in url:
                return {"stargazers_count": 300, "open_issues_count": 9}
            return {"stars": 111, "total_downloads": 42000}

        with patch.object(project_stats, "_fetch_json", side_effect=fake):
            data = project_stats.fetch_project_stats()

        self.assertEqual(data["stars"], 300)
        self.assertEqual(data["total_downloads"], 42000)
        self.assertEqual(data["open_issues"], 9)
        self.assertEqual(data["latest_tag"], "v2.0.0")

    def test_returns_none_when_both_sources_fail(self):
        with patch.object(project_stats, "_fetch_json", side_effect=Exception("boom")):
            self.assertIsNone(project_stats.fetch_project_stats())

    def test_stats_json_alone_still_yields_a_dict(self):
        def fake(url, timeout=6):
            if "api.github.com" in url:
                raise Exception("api down")
            return {"stars": 88, "total_downloads": 5000}

        with patch.object(project_stats, "_fetch_json", side_effect=fake):
            data = project_stats.fetch_project_stats()

        self.assertEqual(data["stars"], 88)
        self.assertEqual(data["total_downloads"], 5000)
        self.assertIsNone(data["latest_tag"])


if __name__ == "__main__":
    unittest.main()
