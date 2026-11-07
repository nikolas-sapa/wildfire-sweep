import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from sweep import CONFIG, dispatch
from research import MissionConfig, dispatch_physical, flight_times, nearest_rank, run_study, success_interval


class FlightTests(unittest.TestCase):
    def test_tailwind_and_return_are_asymmetric(self):
        out, back = flight_times(np.array([[1.0, 0.0]]), 20.0, (5.0, 0.0))
        self.assertAlmostEqual(out[0], 40.0)
        self.assertAlmostEqual(back[0], 1000.0 / 15.0)

    def test_crosswind_requires_crabbing(self):
        out, back = flight_times(np.array([[0.0, 1.0]]), 20.0, (5.0, 0.0))
        expected = 1000.0 / math.sqrt(375.0)
        self.assertAlmostEqual(out[0], expected)
        self.assertAlmostEqual(back[0], expected)

    def test_zero_distance_is_zero_even_without_headway(self):
        out, back = flight_times(np.array([[0.0, 0.0], [1.0, 0.0]]), 20.0, (20.0, 0.0))
        self.assertEqual(out[0], 0.0)
        self.assertEqual(back[0], 0.0)
        self.assertTrue(math.isinf(back[1]))

    def test_reversing_track_swaps_legs(self):
        out, back = flight_times(np.array([[1.0, 2.0], [-1.0, -2.0]]), 20.0, (3.0, 4.0))
        np.testing.assert_allclose(out, back[::-1])

    def test_invalid_physics_fails(self):
        for kwargs in ({"airspeed_mps": 0}, {"reserve_fraction": 1},
                       {"endurance_min": float("nan")}, {"wind_mps": (float("inf"), 0)}):
            with self.assertRaises(ValueError):
                MissionConfig(**kwargs)


class DispatchTests(unittest.TestCase):
    def test_zero_wind_matches_legacy_when_budget_does_not_bind(self):
        times = np.array([0.0, 1.0, 1000.0])
        points = np.array([[1.0, 0.0], [0.0, 1.0], [2.0, 2.0]])
        bases = np.array([[0.0, 0.0], [3.0, 3.0]])
        cfg = MissionConfig(airspeed_mps=CONFIG["cruise_mps"], endurance_min=1000)
        old, _ = dispatch(times, points, bases, 1, 30.0, CONFIG)
        result = dispatch_physical(times, points, bases, 1, 30.0, CONFIG, cfg)
        np.testing.assert_allclose(result["response_s"], old)
        self.assertEqual(result["status"], ["served"] * 3)

    def test_queue_uses_round_trip_not_twice_outbound(self):
        cfg = dict(CONFIG, dwell_s=20.0, turnaround_s=30.0)
        result = dispatch_physical(
            np.array([0.0, 1.0]), np.array([[1.0, 0.0], [1.0, 0.0]]),
            np.array([[0.0, 0.0]]), 1, 10.0, cfg,
            MissionConfig(airspeed_mps=20, wind_mps=(5.0, 0.0)),
        )
        self.assertAlmostEqual(result["response_s"][0], 50.0)
        self.assertAlmostEqual(result["response_s"][1], 10 + 40 + 1000 / 15 + 20 + 30 + 10 + 40 - 1)

    def test_rejected_mission_never_locks_aircraft(self):
        cfg = dict(CONFIG, dwell_s=0.0)
        result = dispatch_physical(
            np.array([0.0, 1.0]), np.array([[1.0, 0.0], [0.01, 0.0]]),
            np.array([[0.0, 0.0]]), 1, 0.0, cfg,
            MissionConfig(endurance_min=0.5, reserve_fraction=0),
        )
        self.assertEqual(result["status"], ["battery_rejected", "served"])
        self.assertTrue(np.isinf(result["response_s"][0]))
        self.assertAlmostEqual(result["response_s"][1], 0.5)

    def test_reserve_boundary_is_inclusive(self):
        cfg = dict(CONFIG, dwell_s=0.0)
        result = dispatch_physical(
            np.array([0.0]), np.array([[0.3, 0.0]]), np.array([[0.0, 0.0]]),
            1, 0, cfg, MissionConfig(endurance_min=1, reserve_fraction=0.5),
        )
        self.assertEqual(result["status"], ["served"])

    def test_weather_gate_rejects_all_alerts(self):
        result = dispatch_physical(
            np.array([0.0]), np.array([[0.0, 0.0]]), np.array([[0.0, 0.0]]),
            1, 0, CONFIG, MissionConfig(wind_mps=(12.01, 0)),
        )
        self.assertEqual(result["status"], ["weather_rejected"])
        self.assertEqual(result["utilisation"], 0)

    def test_calm_weather_does_not_allow_unsafe_distant_fallback(self):
        cfg = dict(CONFIG, dwell_s=60.0, turnaround_s=600.0)
        times = np.array([0.0, 1.0])
        points = np.zeros((2, 2))
        bases = np.array([[0.0, 0.0], [10.0, 0.0]])
        legacy, _ = dispatch(times, points, bases, 1, 0, cfg)
        physical = dispatch_physical(times, points, bases, 1, 0, cfg,
                                     MissionConfig(endurance_min=2, reserve_fraction=0))
        self.assertEqual(legacy[1], 500.0)
        self.assertEqual(physical["response_s"][1], 659.0)
        self.assertEqual(physical["status"], ["served", "served"])

    def test_unsorted_times_and_empty_fleet_fail(self):
        for times, bases in ((np.array([1.0, 0.0]), np.array([[0.0, 0.0]])),
                             (np.array([0.0, 1.0]), np.empty((0, 2)))):
            with self.assertRaises(ValueError):
                dispatch_physical(times, np.zeros((2, 2)), bases, 1, 0, CONFIG, MissionConfig())


class MetricsTests(unittest.TestCase):
    def test_quantile_preserves_rejections(self):
        self.assertTrue(math.isinf(nearest_rank([1.0, 2.0, math.inf], 0.9)))
        self.assertIsNone(nearest_rank([], 0.9))
        self.assertEqual(nearest_rank([1.0, 2.0, 3.0], 0.5), 2.0)

    def test_success_is_event_weighted(self):
        estimate, low, high = success_interval(np.array([1, 0]), np.array([1, 100]), seed=42)
        self.assertAlmostEqual(estimate, 1 / 101)
        self.assertLessEqual(low, estimate)
        self.assertGreaterEqual(high, estimate)

    def test_no_fires_has_no_estimate(self):
        self.assertEqual(success_interval(np.array([0, 0]), np.array([0, 0]), seed=42),
                         (None, None, None))

    def test_bootstrap_repeats_exactly(self):
        args = (np.array([8, 9, 7]), np.array([10, 10, 10]))
        self.assertEqual(success_interval(*args, seed=123), success_interval(*args, seed=123))

    def test_invalid_counts_do_not_produce_plausible_intervals(self):
        for successes, totals in (([2], [1]), ([-1], [2]), ([0.5], [1]), ([1], [float("nan")])):
            with self.assertRaises(ValueError):
                success_interval(np.array(successes), np.array(totals), seed=42)


class StudyTests(unittest.TestCase):
    def test_reproducible_study_captures_inputs_and_all_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            rows = run_study(first, seasons=2, seed=42, ignitions=5)
            self.assertEqual(rows, run_study(second, seasons=2, seed=42, ignitions=5))
            self.assertEqual(len(rows), 36)
            for row in rows:
                self.assertAlmostEqual(row["within_15min_share"] + row["rejected_share"]
                                       + row["served_late_share"], 1)
                with np.load(first / f"{row['scenario']}.npz", allow_pickle=False) as capture:
                    self.assertEqual(len(capture["response_s"]), row["real_alerts"])
            with np.load(first / "alerts.npz", allow_pickle=False) as capture:
                self.assertEqual(len(capture["offsets"]), 3)
                self.assertEqual(capture["offsets"][-1], len(capture["times"]))
            with self.assertRaises(FileExistsError):
                run_study(first, seasons=2, seed=42, ignitions=5)


if __name__ == "__main__":
    unittest.main()
