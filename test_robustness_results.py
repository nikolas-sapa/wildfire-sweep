import csv
import hashlib
import json
import math
from pathlib import Path
import unittest

import numpy as np


CAPTURE = Path(__file__).parent / "research_results" / "2026-11-08-robustness"


def read_rows(name):
    with (CAPTURE / name).open() as handle:
        return list(csv.DictReader(handle))


class PublishedRobustnessTests(unittest.TestCase):
    def test_frozen_manifest_and_artifact_hashes(self):
        manifest = json.loads((CAPTURE / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["seasons"], 200)
        self.assertEqual(manifest["seed"], 20261108)
        self.assertEqual(manifest["real_alerts_per_scenario"], 61084)
        self.assertEqual(set(manifest["artifact_sha256"]), {
            "alerts.npz", "responses.npz", "summary.csv", "seasons.csv", "comparisons.csv",
        })
        for name, digest in manifest["artifact_sha256"].items():
            self.assertEqual(hashlib.sha256((CAPTURE / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(len(read_rows("summary.csv")), 20)
        self.assertEqual(len(read_rows("seasons.csv")), 4000)
        self.assertEqual(len(read_rows("comparisons.csv")), 26)

    def test_shared_alerts_and_response_accounting(self):
        summary = read_rows("summary.csv")
        with np.load(CAPTURE / "alerts.npz", allow_pickle=False) as alerts:
            self.assertEqual(len(alerts["offsets"]), 201)
            self.assertEqual(alerts["offsets"][-1], len(alerts["times"]))
            self.assertEqual(alerts["is_real"].dtype, np.bool_)
            totals = [int(alerts["is_real"][a:b].sum()) for a, b in
                      zip(alerts["offsets"][:-1], alerts["offsets"][1:])]
        self.assertEqual(sum(totals), 61084)
        seasons = read_rows("seasons.csv")
        with np.load(CAPTURE / "responses.npz", allow_pickle=False) as capture:
            np.testing.assert_array_equal(capture["offsets"], np.cumsum([0] + totals))
            self.assertEqual(set(capture.files), {"offsets"} | {r["scenario"] for r in summary})
            for row in summary:
                identifier = row["scenario"]
                values = capture[identifier]
                self.assertEqual(len(values), 61084)
                self.assertFalse(np.isnan(values).any())
                self.assertTrue((values >= 0).all())
                timely = int((values <= 900).sum())
                rejected = int(np.isposinf(values).sum())
                late = int((np.isfinite(values) & (values > 900)).sum())
                self.assertEqual((timely, rejected, late),
                                 tuple(int(row[k]) for k in ("within_15min", "rejected", "served_late")))
                self.assertEqual(timely + rejected + late, 61084)
                self.assertAlmostEqual(float(row["within_15min_share"]), timely / 61084)
                self.assertAlmostEqual(float(row["rejected_share"]), rejected / 61084)
                self.assertAlmostEqual(float(row["served_late_share"]), late / 61084)
                p90 = np.sort(values)[math.ceil(0.9 * len(values)) - 1]
                self.assertEqual(row["p90_unreachable"] == "True", math.isinf(p90))
                self.assertEqual(row["p90_s"], "" if math.isinf(p90) else str(p90))
                season_rows = sorted((r for r in seasons if r["scenario"] == identifier),
                                     key=lambda r: int(r["season"]))
                self.assertEqual([int(r["season"]) for r in season_rows], list(range(200)))
                for season, (a, b) in enumerate(zip(capture["offsets"][:-1], capture["offsets"][1:])):
                    raw = values[a:b]
                    self.assertEqual(int(season_rows[season]["real_alerts"]), totals[season])
                    self.assertEqual(int(season_rows[season]["within_15min"]), int((raw <= 900).sum()))
                    self.assertEqual(int(season_rows[season]["rejected"]), int(np.isposinf(raw).sum()))

    def test_paired_contrasts_and_intervals_match_captured_seasons(self):
        seasons = read_rows("seasons.csv")
        identifiers = {r["scenario"] for r in seasons}
        counts = {
            identifier: np.array([int(r["within_15min"]) for r in sorted(
                (row for row in seasons if row["scenario"] == identifier),
                key=lambda row: int(row["season"]),
            )]) for identifier in identifiers
        }
        totals = np.array([int(r["real_alerts"]) for r in sorted(
            (row for row in seasons if row["scenario"] == "b9-w8-reference"),
            key=lambda row: int(row["season"]),
        )])
        draws = np.random.default_rng([1, 20261108]).integers(0, 200, (1000, 200))
        denominators = totals[draws].sum(axis=1)
        contrasts = read_rows("comparisons.csv")
        self.assertEqual(len({row["comparison"] for row in contrasts}), 26)
        self.assertEqual(sum(row["kind"] == "density" for row in contrasts), 10)
        for row in contrasts:
            difference = counts[row["candidate"]] - counts[row["reference"]]
            point = 100 * difference.sum() / totals.sum()
            bootstrap = 100 * difference[draws].sum(axis=1) / denominators
            low, high = np.quantile(bootstrap, [0.025, 0.975])
            for key, expected in (
                ("delta_within_15min_pp", point), ("mc_95ci_low_pp", low), ("mc_95ci_high_pp", high),
            ):
                self.assertAlmostEqual(float(row[key]), expected, places=12)
        for row in read_rows("summary.csv"):
            bootstrap = counts[row["scenario"]][draws].sum(axis=1) / denominators
            low, high = np.quantile(bootstrap, [0.025, 0.975])
            self.assertAlmostEqual(float(row["mc_95ci_low"]), low, places=12)
            self.assertAlmostEqual(float(row["mc_95ci_high"]), high, places=12)


if __name__ == "__main__":
    unittest.main()
