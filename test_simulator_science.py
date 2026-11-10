import csv
import importlib.util
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import simulator_engine as engine
from simulator_data import DEFAULT_CAPTURE, ExplorerData


class MissionScienceTests(unittest.TestCase):
    def test_at_base_and_analytical_roundtrip(self):
        base = engine.layout_bases(9)[0]
        point = [base["x_km"], base["y_km"]]
        result = engine.run_mission({"point_km": point, "wind_mps": [0, 0]})
        self.assertEqual(result["response_s"], 60)
        self.assertEqual(result["selected_base_id"], 0)
        self.assertEqual(result["candidates"][0]["airborne_s"], 120)
        result = engine.run_mission({
            "point_km": [point[0] + 10, point[1]], "wind_mps": [6, 0]})
        candidate = result["candidates"][0]
        self.assertAlmostEqual(candidate["outbound_s"], 10000 / 24, places=6)
        self.assertAlmostEqual(candidate["return_s"], 10000 / 12, places=6)
        self.assertAlmostEqual(candidate["airborne_s"], 1370, places=6)

    def test_rejections_and_strict_json(self):
        for payload, status in [
                ({"wind_mps": [13, 0]}, "weather_rejected"),
                ({"reserve_fraction": .9, "endurance_min": 1}, "battery_rejected"),
                ({"airspeed_mps": 1, "wind_mps": [12, 0]}, "flight_rejected")]:
            result = engine.run_mission(payload)
            self.assertEqual(result["status"], status)
            self.assertIsNone(result["response_s"])
            self.assertIsNone(result["selected_base_id"])
            self.assertFalse(result["within_15min"])
            json.dumps(result, allow_nan=False)

    def test_all_original_sites_removable_and_no_mutation(self):
        for count in (9, 25):
            for offline in range(count):
                payload = {"n_bases": count, "offline_base": offline}
                original = dict(payload)
                result = engine.run_mission(payload)
                self.assertEqual(payload, original)
                self.assertEqual([b["id"] for b in result["bases"]], list(range(count)))
                self.assertEqual([b["id"] for b in result["bases"] if not b["available"]],
                                 [offline])
                self.assertNotEqual(result["selected_base_id"], offline)

    def test_inputs_rejected(self):
        for payload in [None, [], {"extra": 1}, {"n_bases": True}, {"n_bases": 10},
                        {"offline_base": -1}, {"offline_base": 9},
                        {"point_km": [-1, 0]}, {"point_km": [100, 0]},
                        {"wind_mps": [0]}, {"wind_mps": [True, 0]},
                        {"reserve_fraction": float("nan")}, {"airspeed_mps": float("inf")},
                        {"airspeed_mps": 10 ** 400},
                        {"airspeed_mps": "18"}, {"launch_latency_s": True}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                engine.run_mission(payload)

    def test_determinism_and_caller_isolation(self):
        first = engine.run_mission({})
        self.assertEqual(first, engine.run_mission({}))
        first["inputs"]["wind_mps"][0] = -99
        first["bases"][0]["available"] = False
        self.assertEqual(engine.run_mission({})["inputs"]["wind_mps"], [12.0, 0.0])
        metadata = engine.model_metadata()
        metadata["defaults"]["wind_mps"][0] = -99
        self.assertEqual(engine.model_metadata()["defaults"]["wind_mps"], [12.0, 0.0])

    def test_bad_return_explanation_fails(self):
        real_flight_times = engine.flight_times

        def broken(*args):
            outbound, inbound = real_flight_times(*args)
            return outbound, inbound * 100

        with patch.object(engine, "flight_times", broken), self.assertRaisesRegex(
                ValueError, "disagrees"):
            engine.run_mission({})

    def test_source_mutation_fails(self):
        original = Path.read_bytes

        def changed(path):
            data = original(path)
            return data + b"\n" if path.name == "simulator_protocol.json" else data

        with patch.object(Path, "read_bytes", changed), self.assertRaisesRegex(
                ValueError, "sources changed"):
            engine.run_mission({})

    def test_actual_copied_source_mutation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in engine.SOURCE_NAMES:
                shutil.copyfile(engine.ROOT / name, root / name)
            spec = importlib.util.spec_from_file_location("isolated_engine", root / "simulator_engine.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with (root / "simulator_protocol.json").open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(ValueError, "sources changed"):
                module.run_mission({})


class ReplayScienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = ExplorerData()

    def test_canonical_tables_exact(self):
        catalog = self.data.catalog()
        for name in ("summary", "contrasts"):
            with (DEFAULT_CAPTURE / f"{name}.csv").open(newline="") as handle:
                expected = list(csv.DictReader(handle))
            actual = catalog["study"][name]
            self.assertEqual(len(actual), len(expected))
            for row, captured in zip(actual, expected):
                for key, value in captured.items():
                    expected_value = (value if isinstance(row[key], str) else
                                      None if value == "" else float(value))
                    self.assertEqual(row[key], expected_value)
        self.assertEqual(catalog["study"]["heldout_seasons"], 200)
        self.assertEqual(catalog["study"]["heldout_real_alerts"], 61206)

    def test_first_last_every_case_exact_captured_arrays_and_counts(self):
        with np.load(DEFAULT_CAPTURE / "heldout_alerts.npz", allow_pickle=False) as alerts:
            with np.load(DEFAULT_CAPTURE / "heldout_responses.npz", allow_pickle=False) as responses:
                with (DEFAULT_CAPTURE / "heldout_counts.csv").open(newline="") as handle:
                    counts = {(r["case_id"], int(r["season"])): r for r in csv.DictReader(handle)}
                for row, case in enumerate(responses["case_ids"]):
                    for season in (0, 199):
                        view = self.data.replay(str(case), season)
                        start, stop = alerts["offsets"][season:season + 2]
                        self.assertEqual(len(view["alerts"]), stop - start)
                        for local, item in enumerate(view["alerts"]):
                            index = int(start) + local
                            self.assertEqual(item["index"], local)
                            self.assertEqual(item["alert_s"], alerts["times"][index])
                            self.assertEqual([item["x_km"], item["y_km"]],
                                             alerts["points"][index].tolist())
                            self.assertEqual(item["is_real"], bool(alerts["is_real"][index]))
                            response = float(responses["responses_s"][row, index])
                            self.assertEqual(item["response_s"], response if math.isfinite(response) else None)
                            self.assertEqual(item["within_15min"], response <= 900)
                            self.assertEqual(item["status"], "within_15min" if response <= 900 else
                                             "late" if math.isfinite(response) else "unreachable")
                        for key, value in counts[str(case), season].items():
                            self.assertEqual(view["counts"][key], value if key == "case_id" else int(value))
                        json.dumps(view, allow_nan=False)

    def test_no_simulation_and_caller_isolation(self):
        case = self.data.catalog()["study"]["cases"][0]["case_id"]
        with patch("research.dispatch_physical", side_effect=AssertionError("no dispatch")), \
                patch("sweep.generate_season", side_effect=AssertionError("no generator")), \
                patch.object(engine, "dispatch_physical", side_effect=AssertionError("no dispatch")), \
                patch.object(engine, "run_mission", side_effect=AssertionError("no sandbox")):
            data = ExplorerData()
            expected = data.replay(case, 0)
            changed = data.replay(case, 0)
            changed["alerts"][0]["x_km"] = -999
            changed["counts"]["real_alerts"] = -1
            self.assertEqual(data.replay(case, 0), expected)
            catalog = data.catalog()
            catalog["study"]["summary"].clear()
            self.assertEqual(len(data.catalog()["study"]["summary"]), 8)

    def test_bad_queries(self):
        case = self.data.catalog()["study"]["cases"][0]["case_id"]
        for name, season in [("missing", 0), (case, -1), (case, 200),
                             (case, True), (case, 0.0), ([], 0)]:
            with self.subTest(name=name, season=season), self.assertRaises(ValueError):
                self.data.replay(name, season)

    def test_snapshot_arrays_are_read_only(self):
        for array in [*self.data._alerts.values(), *self.data._responses.values()]:
            self.assertFalse(array.flags.writeable)
            with self.assertRaises(ValueError):
                array.flat[0] = array.flat[0]

    def test_tampered_capture_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "capture"
            shutil.copytree(DEFAULT_CAPTURE, target)
            with (target / "summary.csv").open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                ExplorerData(target)


if __name__ == "__main__":
    unittest.main()
