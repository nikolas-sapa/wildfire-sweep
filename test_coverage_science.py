import copy
import math
import unittest

import numpy as np

from coverage_engine import evaluate_grid, evaluate_points
from coverage_scenarios import make_scenarios
from research import MissionConfig, dispatch_physical
from simulator_engine import MODEL_CONFIG, PROTOCOL, SIDE_KM, layout_bases


class CoverageScienceTests(unittest.TestCase):
    def test_registry_has_exact_declared_matrix(self):
        cases = make_scenarios()
        self.assertEqual(len(cases), 388)
        self.assertEqual(len({case["case_id"] for case in cases}), 388)
        self.assertEqual(sum(case["wind_speed_mps"] == 0 for case in cases), 2)
        self.assertEqual(sum(case["wind_speed_mps"] == 13 for case in cases), 2)
        self.assertEqual(sum(len(case["offline_bases"]) == 2 for case in cases), 32)
        for case in cases:
            if case["wind_speed_mps"] == 12:
                self.assertLessEqual(math.hypot(*case["wind_mps"]), 12)
        for count in (9, 25):
            for heading in range(0, 360, 45):
                singles = [
                    case for case in cases
                    if case["n_bases"] == count and case["heading_deg"] == heading
                    and case["profile"] == "reference"
                    and case["wind_speed_mps"] == 12
                    and len(case["offline_bases"]) == 1
                ]
                self.assertEqual(
                    sorted(case["offline_bases"][0] for case in singles), list(range(count)))

    def test_120_points_match_authoritative_idle_dispatch(self):
        registry = make_scenarios()
        fractions = np.array([
            [0, 0], [1, 0], [0, 1], [1, 1], [.5, .5],
            [.1, .8], [.8, .1], [.25, .75], [.62, .56], [.9, .9],
        ])
        points = fractions * SIDE_KM
        checked = 0
        for count in (9, 25):
            choices = [
                next(c for c in registry if c["n_bases"] == count
                     and c["wind_speed_mps"] == speed and c["profile"] == profile
                     and c["heading_deg"] == heading
                     and len(c["offline_bases"]) == outage_count)
                for speed, profile, heading, outage_count in (
                    (12, "reference", 0, 0), (12, "reference", 45, 1),
                    (0, "reference", None, 0), (12, "short_endurance", 0, 0),
                    (12, "combined", 90, 0), (13, "reference", 0, 0))
            ]
            for case in choices:
                actual = evaluate_points(case, points)
                bases = [b for b in layout_bases(count)
                         if b["id"] not in case["offline_bases"]]
                coordinates = np.array([[b["x_km"], b["y_km"]] for b in bases])
                mission = MissionConfig(
                    airspeed_mps=case["airspeed_mps"], wind_mps=tuple(case["wind_mps"]),
                    endurance_min=case["endurance_min"],
                    reserve_fraction=case["reserve_fraction"],
                    max_wind_mps=PROTOCOL["max_wind_mps"])
                for index, point in enumerate(points):
                    expected = dispatch_physical(
                        np.array([0.0]), point[None, :], coordinates, 1,
                        case["launch_latency_s"], MODEL_CONFIG, mission)
                    response = float(expected["response_s"][0])
                    self.assertEqual(math.isfinite(response),
                                     math.isfinite(float(actual["response_s"][index])))
                    if math.isfinite(response):
                        self.assertAlmostEqual(float(actual["response_s"][index]), response,
                                               delta=1e-9)
                        one_base_responses = [
                            float(dispatch_physical(
                                np.array([0.0]), point[None, :],
                                np.array([[base["x_km"], base["y_km"]]]), 1,
                                case["launch_latency_s"], MODEL_CONFIG, mission
                            )["response_s"][0])
                            for base in bases]
                        selected = bases[int(np.argmin(one_base_responses))]["id"]
                        self.assertEqual(int(actual["selected_base_id"][index]), selected)
                        code = 2 if response <= 900 else 1
                    else:
                        self.assertEqual(int(actual["selected_base_id"][index]), -1)
                        code = 3 if expected["status"][0] == "weather_rejected" else 0
                    self.assertEqual(int(actual["outcome_code"][index]), code)
                    checked += 1
        self.assertEqual(checked, 120)

    def test_grid_centers_order_and_summary_are_authoritative(self):
        case = make_scenarios()[0]
        result = evaluate_grid(case, 8)
        centers = (np.arange(8) + .5) * SIDE_KM / 8
        np.testing.assert_array_equal(result["x_km"], centers)
        np.testing.assert_array_equal(result["y_km"], centers)
        x, y = np.meshgrid(centers, centers)
        direct = evaluate_points(case, np.column_stack([x.ravel(), y.ravel()]))
        for name in ("response_s", "selected_base_id", "outcome_code"):
            np.testing.assert_array_equal(result[name].ravel(), direct[name])
        counts = result["summary"]
        self.assertEqual(counts["total_cells"], 64)
        self.assertEqual(sum(counts[name] for name in (
            "timely_cells", "late_cells", "unreachable_cells", "weather_closed_cells")), 64)
        self.assertEqual(counts["timely_area_fraction"],
                         np.count_nonzero(result["outcome_code"] == 2) / 64)
        self.assertEqual(counts["reachable_area_fraction"],
                         np.count_nonzero(np.isfinite(result["response_s"])) / 64)

    def test_every_registered_case_matches_one_independent_dispatch(self):
        point = np.array([[.62, .56]]) * SIDE_KM
        for case in make_scenarios():
            bases = [b for b in layout_bases(case["n_bases"])
                     if b["id"] not in case["offline_bases"]]
            mission = MissionConfig(
                airspeed_mps=case["airspeed_mps"], wind_mps=tuple(case["wind_mps"]),
                endurance_min=case["endurance_min"],
                reserve_fraction=case["reserve_fraction"],
                max_wind_mps=PROTOCOL["max_wind_mps"])
            expected = dispatch_physical(
                np.array([0.0]), point,
                np.array([[b["x_km"], b["y_km"]] for b in bases]), 1,
                case["launch_latency_s"], MODEL_CONFIG, mission)
            actual = evaluate_points(case, point)
            response = float(expected["response_s"][0])
            with self.subTest(case=case["case_id"]):
                if math.isfinite(response):
                    self.assertAlmostEqual(float(actual["response_s"][0]), response,
                                           delta=1e-9)
                else:
                    self.assertTrue(np.isposinf(actual["response_s"][0]))

    def test_deadline_and_battery_boundaries_match_existing_rules(self):
        case = next(c for c in make_scenarios()
                    if c["n_bases"] == 9 and c["wind_speed_mps"] == 0)
        case = copy.deepcopy(case)
        case["offline_bases"] = [site for site in range(9) if site != 4]
        base = layout_bases(9)[4]
        origin = np.array([base["x_km"], base["y_km"]])
        deadline_km = (900 - 60) * 18 / 1000
        budget_km = ((46 * 60 * .75 - MODEL_CONFIG["dwell_s"]) / 2) * 18 / 1000
        points = origin + np.array([
            [deadline_km, 0], [deadline_km + 1e-5, 0],
            [budget_km, 0], [budget_km + 1e-5, 0],
        ])
        result = evaluate_points(case, points)
        np.testing.assert_array_equal(result["outcome_code"], [2, 1, 1, 0])
        self.assertAlmostEqual(float(result["response_s"][0]), 900, delta=1e-9)
        self.assertTrue(np.isposinf(result["response_s"][3]))

    def test_weather_closure_and_all_offline_are_unserved(self):
        for case in (c for c in make_scenarios() if c["wind_speed_mps"] == 13):
            result = evaluate_grid(case, 4)
            self.assertTrue(np.all(result["outcome_code"] == 3))
            self.assertTrue(np.isposinf(result["response_s"]).all())
            self.assertTrue(np.all(result["selected_base_id"] == -1))
            self.assertEqual(result["summary"]["timely_area_fraction"], 0)
        case = copy.deepcopy(make_scenarios()[0])
        case["offline_bases"] = list(range(case["n_bases"]))
        result = evaluate_grid(case, 4)
        self.assertTrue(np.all(result["outcome_code"] == 0))
        self.assertTrue(np.isposinf(result["response_s"]).all())

    def test_grid_and_scenario_inputs_fail_closed(self):
        case = make_scenarios()[0]
        for value in (0, -1, True, 2.5, 10000):
            with self.assertRaises(ValueError):
                evaluate_grid(case, value)
        for point in ([[math.nan, 0]], [[math.inf, 0]], [[-1, 0]], [[SIDE_KM + 1, 0]]):
            with self.assertRaises(ValueError):
                evaluate_points(case, point)
        for key, value in (("n_bases", True), ("reserve_fraction", math.nan),
                           ("offline_bases", [0, 0]), ("offline_bases", [99]),
                           ("launch_latency_s", True)):
            bad = {**case, key: value}
            with self.assertRaises(ValueError):
                evaluate_grid(bad, 4)

    def test_registry_and_engine_do_not_mutate_callers(self):
        first = make_scenarios()
        original = copy.deepcopy(first[0])
        evaluate_grid(first[0], 4)
        self.assertEqual(first[0], original)
        first[0]["offline_bases"].append(0)
        first[0]["wind_mps"][0] = 0
        self.assertEqual(make_scenarios()[0], original)


if __name__ == "__main__":
    unittest.main()
