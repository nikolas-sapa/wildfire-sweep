import csv
import hashlib
import json
from pathlib import Path
import unittest


class PublishedResultsTests(unittest.TestCase):
    def test_published_capture_matches_source_and_season_denominators(self):
        root = Path(__file__).parent
        capture = root / "research_results" / "2026-11-07-anchor"
        manifest = json.loads((capture / "manifest.json").read_text())
        self.assertEqual(manifest["seasons"], 200)
        for name, expected in manifest["source_sha256"].items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)
        with (capture / "summary.csv").open(newline="") as handle:
            summary = list(csv.DictReader(handle))
        with (capture / "seasons.csv").open(newline="") as handle:
            seasons = list(csv.DictReader(handle))
        self.assertEqual(len(summary), 36)
        self.assertEqual(len(seasons), 36 * 200)
        self.assertEqual(len({row["scenario"] for row in summary}), 36)
        for result in summary:
            records = [row for row in seasons if row["scenario"] == result["scenario"]]
            self.assertEqual({int(row["season"]) for row in records}, set(range(200)))
            totals = {key: sum(int(row[key]) for row in records)
                      for key in ("real_alerts", "within_15min", "rejected", "served_late")}
            self.assertEqual(totals["real_alerts"], 61538)
            self.assertEqual(totals["within_15min"] + totals["rejected"] + totals["served_late"],
                             totals["real_alerts"])
            for count, share in (("within_15min", "within_15min_share"),
                                 ("rejected", "rejected_share"), ("served_late", "served_late_share")):
                self.assertAlmostEqual(totals[count] / totals["real_alerts"], float(result[share]))
            self.assertEqual(result["p90_s"] == "", result["p90_unreachable"] == "True")
        per_season = {}
        for row in seasons:
            key = row["season"]
            if key in per_season:
                self.assertEqual(row["real_alerts"], per_season[key])
            per_season[key] = row["real_alerts"]


if __name__ == "__main__":
    unittest.main()
