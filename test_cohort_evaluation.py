import copy
import unittest
from unittest.mock import patch

import numpy as np

from cohort_evaluation import cohort_intervals, cohort_metrics
from event_evaluation import episode_metrics


def record(recording_id, cluster_id, truth, alarms):
    return {"recording_id": recording_id, "cluster_id": cluster_id,
            "metrics": episode_metrics(truth, alarms, 1)}


def grouped_records():
    return [
        record("r1", "a", [0, 1, 1, 1, 0], [0, 0, 1, 1, 0]),
        record("r2", "a", [0]*5, [1, 0, 1, 0, 0]),
        record("r3", "b", [1, 1, 1, 0, 1, 1, 1], [0, 0, 1, 0, 0, 0, 0]),
        record("r4", "c", [1, 1, 1, 1, 0], [0, 0, 0, 1, 0]),
    ]


class CohortMetricTests(unittest.TestCase):
    def test_pool_counts_not_mean_ratios(self):
        records = [record("r1", "a", [1], [1]),
                   record("r2", "b", [1, 0]*9, [0]*18)]
        result = cohort_metrics(records)
        self.assertEqual(result["event_recall"], 0.1)
        self.assertNotEqual(result["event_recall"], 0.5)
        self.assertEqual(result["fire_episodes"], 10)
        self.assertEqual(result["detected_fire_episodes"], 1)
        self.assertEqual(result["missed_fire_episodes"], 9)
        self.assertEqual(result["n_records"], 2)
        self.assertEqual(result["n_clusters"], 2)

    def test_detected_only_pooled_delays(self):
        records = [record("r1", "a", [1], [1]),
                   record("r2", "b", [1]*3, [0, 0, 1]),
                   record("r3", "c", [1]*9, [0]*8 + [1]),
                   record("r4", "d", [1]*10, [0]*10)]
        result = cohort_metrics(records)
        self.assertEqual(result["detected_delays_s"], [0, 2, 8])
        self.assertEqual(result["detected_delay_p50_s"], 2)
        self.assertEqual(result["detected_delay_p90_s"], 8)
        self.assertEqual(result["missed_fire_episodes"], 1)

    def test_manual_cluster_draws(self):
        draws = np.array([[0, 0, 0], [0, 1, 2], [1, 1, 2], [2, 2, 2]])
        with patch("cohort_evaluation.np.random.default_rng") as generator:
            generator.return_value.integers.return_value = draws
            result = cohort_intervals(grouped_records(), seed=17, replicates=4)
            generator.assert_called_once_with(17)
            generator.return_value.integers.assert_called_once_with(0, 3, size=(4, 3))
        self.assertEqual(result["cluster_ids"], ["a", "b", "c"])
        np.testing.assert_array_equal(result["draws"], draws)
        expected = {
            "event_recall": (0.75, 0.61125, 1.0),
            "alarm_precision": (0.6, 53/150, 1.0),
            "false_alarms_per_nonfire_hour": (800, 0, 7080/7),
            "detected_delay_p50_s": (2, 1.075, 2.925),
            "detected_delay_p90_s": (3, 1.15, 3),
        }
        for metric, values in expected.items():
            row = result["intervals"][metric]
            for name, expected_value in zip(("estimate", "ci_95_low", "ci_95_high"), values):
                self.assertAlmostEqual(row[name], expected_value, delta=1e-12)
            self.assertEqual(row["informative_clusters"], 3)
            self.assertEqual(row["valid_bootstrap_draws"], 4)
            self.assertEqual(row["ci_status"], "cluster_bootstrap")

    def test_seeded_reproducibility_and_row_order(self):
        first = cohort_intervals(grouped_records(), seed=9)
        second = cohort_intervals(list(reversed(grouped_records())), seed=9)
        self.assertEqual(first["intervals"], second["intervals"])
        self.assertEqual(first["aggregate"], second["aggregate"])
        np.testing.assert_array_equal(first["draws"], second["draws"])

    def test_minimum_informative_clusters(self):
        records = [record("r1", "a", [1], [1]), record("r2", "a", [0], [0])]
        result = cohort_intervals(records)
        self.assertEqual(result["aggregate"]["n_clusters"], 1)
        for row in result["intervals"].values():
            self.assertEqual(row["ci_status"], "insufficient_clusters")
            self.assertIsNone(row["ci_95_low"])
            self.assertIsNone(row["ci_95_high"])
        records[1]["cluster_id"] = "b"
        second = cohort_intervals(records)
        self.assertEqual(second["aggregate"]["n_clusters"], 2)
        self.assertEqual(second["intervals"]["event_recall"]["informative_clusters"], 1)
        self.assertEqual(second["intervals"]["event_recall"]["ci_status"], "insufficient_clusters")
        self.assertTrue(0 < second["intervals"]["event_recall"]["valid_bootstrap_draws"] < 1000)

    def test_undefined_and_invalid_metrics(self):
        result = cohort_intervals([record("r1", "a", [0, 0], [0, 0])])
        for metric in ("event_recall", "alarm_precision", "detected_delay_p50_s", "detected_delay_p90_s"):
            row = result["intervals"][metric]
            self.assertEqual(row["ci_status"], "undefined")
            self.assertIsNone(row["estimate"])
            self.assertEqual(row["valid_bootstrap_draws"], 0)
        original = grouped_records()
        for key, value in (("fire_episodes", -1), ("alarm_episodes", 1.5),
                           ("nonfire_exposure_s", float("nan")), ("sampled_exposure_s", float("inf")),
                           ("n_samples", True), ("event_recall", 0.99)):
            records = copy.deepcopy(original)
            records[0]["metrics"][key] = value
            with self.assertRaises(ValueError):
                cohort_metrics(records)

    def test_input_identity_and_seed_guards(self):
        with self.assertRaises(ValueError):
            cohort_metrics([])
        records = grouped_records()
        with self.assertRaises(ValueError):
            cohort_metrics(records + [records[0]])
        for seed in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                cohort_intervals(records, seed=seed)
        for replicates in (0, True, 1.5, 10001):
            with self.assertRaises(ValueError):
                cohort_intervals(records, replicates=replicates)

    def test_no_defined_draws_fail_loud(self):
        records = [record("r1", "a", [1], [1]), record("r2", "b", [1], [1]),
                   record("r3", "c", [0], [0])]
        with patch("cohort_evaluation.np.random.default_rng") as generator:
            generator.return_value.integers.return_value = np.array([[2, 2, 2]])
            with self.assertRaisesRegex(ValueError, "No defined bootstrap draws"):
                cohort_intervals(records, replicates=1)


if __name__ == "__main__":
    unittest.main()
