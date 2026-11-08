import csv
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from robustness import paired_interval, response_counts, run_robustness, scenario_grid


class PairedIntervalTests(unittest.TestCase):
    def test_paired_delta_is_event_weighted(self):
        estimate, _, _ = paired_interval([1, 0], [0, 0], [1, 100], seed=42)
        self.assertAlmostEqual(estimate, 100 / 101)

    def test_pairing_preserves_zero_difference(self):
        self.assertEqual(paired_interval([1, 70, 0], [1, 70, 0], [1, 100, 3], seed=42),
                         (0.0, 0.0, 0.0))

    def test_paired_resampling_matches_manual_draws(self):
        candidate = np.array([1, 7, 5])
        reference = np.array([0, 9, 2])
        totals = np.array([1, 10, 8])
        draws = np.random.default_rng(42).integers(0, 3, (100, 3))
        ratios = []
        for indices in draws:
            numerator = sum(candidate[i] - reference[i] for i in indices)
            denominator = sum(totals[i] for i in indices)
            ratios.append(100 * numerator / denominator)
        low, high = np.quantile(ratios, [0.025, 0.975])
        actual = paired_interval(candidate, reference, totals, seed=42, replicates=100)
        for expected, observed in zip((200 / 19, low, high), actual):
            self.assertAlmostEqual(expected, observed, places=12)

    def test_invalid_counts_fail(self):
        for candidate, reference, totals in (
            ([1], [0, 1], [1]), ([0.5], [0], [1]), ([-1], [0], [1]),
            ([2], [0], [1]), ([0], [2], [1]), ([0], [0], [math.nan]),
            ([0], [0], [math.inf]), ([], [], []), ([[1]], [[0]], [[1]]),
        ):
            with self.subTest(candidate=candidate, reference=reference, totals=totals):
                with self.assertRaises(ValueError):
                    paired_interval(candidate, reference, totals, seed=42)
        for replicates in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                paired_interval([1], [0], [1], seed=42, replicates=replicates)

    def test_empty_denominator_is_not_success(self):
        self.assertEqual(paired_interval([0, 0], [0, 0], [0, 0], seed=42),
                         (None, None, None))
        self.assertEqual(paired_interval([1], [0], [2], seed=42), (50.0, None, None))
        estimate, low, high = paired_interval([1, 0], [0, 0], [1, 0], seed=42)
        self.assertEqual((estimate, low, high), (100.0, 100.0, 100.0))


class ResponseAccountingTests(unittest.TestCase):
    def test_response_accounting_keeps_rejections(self):
        self.assertEqual(response_counts([900, 901, math.inf]), {
            "real_alerts": 3, "within_15min": 1, "rejected": 1, "served_late": 1,
        })
        self.assertEqual(response_counts([]), {
            "real_alerts": 0, "within_15min": 0, "rejected": 0, "served_late": 0,
        })

    def test_invalid_responses_fail(self):
        for responses in ([math.nan], [-1], [-math.inf], [[1]]):
            with self.assertRaises(ValueError):
                response_counts(responses)


class RobustnessStudyTests(unittest.TestCase):
    def test_protocol_grid(self):
        protocol = json.loads(Path(__file__).with_name("robustness_protocol.json").read_text())
        scenarios = scenario_grid(protocol)
        self.assertEqual(len(scenarios), 20)
        self.assertEqual(len({s["scenario"] for s in scenarios}), 20)
        self.assertEqual({s["n_bases"] for s in scenarios}, {9, 25})
        for scenario in scenarios:
            self.assertEqual(scenario["airspeed_mps"], 18.0)
            if scenario["condition"] == "reference":
                self.assertEqual((scenario["endurance_min"], scenario["reserve_fraction"],
                                  scenario["launch_latency_s"]), (46.0, 0.25, 60.0))
            if scenario["condition"] == "combined":
                self.assertEqual((scenario["endurance_min"], scenario["reserve_fraction"],
                                  scenario["launch_latency_s"]), (34.5, 0.35, 180.0))

    def test_repeated_runs_match_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first", Path(directory) / "second"
            self.assertEqual(run_robustness(first, seasons=2, seed=42),
                             run_robustness(second, seasons=2, seed=42))
            for name in ("summary.csv", "seasons.csv", "comparisons.csv"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            for name in ("alerts.npz", "responses.npz"):
                with np.load(first / name, allow_pickle=False) as a:
                    with np.load(second / name, allow_pickle=False) as b:
                        self.assertEqual(a.files, b.files)
                        for key in a.files:
                            np.testing.assert_array_equal(a[key], b[key])
            with self.assertRaises(FileExistsError):
                run_robustness(first, seasons=2, seed=42)
            for seasons, seed in ((1, 42), (True, 42), (2.5, 42), (2, -1), (2, True)):
                invalid = Path(directory) / "invalid"
                with self.assertRaises(ValueError):
                    run_robustness(invalid, seasons=seasons, seed=seed)
                self.assertFalse(invalid.exists())

    def test_capture_and_manifest_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture"
            summary = run_robustness(output, seasons=2, seed=123)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["seasons"], 2)
            for name, expected in manifest["artifact_sha256"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), expected)
            with np.load(output / "alerts.npz", allow_pickle=False) as alerts:
                self.assertEqual(len(alerts["offsets"]), 3)
                self.assertEqual(alerts["offsets"][-1], len(alerts["times"]))
                real_total = int(alerts["is_real"].sum())
            with np.load(output / "responses.npz", allow_pickle=False) as responses:
                self.assertEqual(len(responses.files), 21)
                for row in summary:
                    values = responses[row["scenario"]]
                    self.assertEqual(len(values), real_total)
                    self.assertEqual(response_counts(values), {
                        key: row[key] for key in
                        ("real_alerts", "within_15min", "rejected", "served_late")
                    })
                    ordered = np.sort(values)
                    p90 = ordered[math.ceil(0.9 * real_total) - 1]
                    self.assertEqual(row["p90_unreachable"], math.isinf(p90))
                    self.assertEqual(row["p90_s"], None if math.isinf(p90) else p90)
            with (output / "seasons.csv").open() as handle:
                seasons = list(csv.DictReader(handle))
            self.assertEqual(len(seasons), 40)
            for row in seasons:
                self.assertEqual(int(row["real_alerts"]), sum(int(row[k]) for k in
                                 ("within_15min", "rejected", "served_late")))
            with (output / "comparisons.csv").open() as handle:
                contrasts = list(csv.DictReader(handle))
            self.assertEqual(len(contrasts), 26)
            self.assertEqual(sum(row["kind"] == "stress" for row in contrasts), 16)
            by_id = {row["scenario"]: row for row in summary}
            for row in contrasts:
                candidate, reference = by_id[row["candidate"]], by_id[row["reference"]]
                expected = 100 * (candidate["within_15min"] - reference["within_15min"]) / real_total
                self.assertAlmostEqual(float(row["delta_within_15min_pp"]), expected)


if __name__ == "__main__":
    unittest.main()
