import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import resilience
from research import MissionConfig, dispatch_physical
from sweep import CONFIG, base_grid


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads(resilience.PROTOCOL_PATH.read_text())
        self.draws = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])

    def test_baseline_dispatch(self):
        case = resilience.case_grid(self.protocol)[0]
        bases = resilience.geometry(case, CONFIG)
        original = base_grid(case["nominal_spacing_km"], CONFIG["domain_km2"])
        np.testing.assert_array_equal(bases, original)
        args = (np.array([0.0, 100.0]), np.array([[1.0, 1.0], [30.0, 30.0]]))
        mission = MissionConfig(airspeed_mps=18, wind_mps=(8, 0))
        actual = dispatch_physical(*args, bases, 1, 60, CONFIG, mission)
        expected = dispatch_physical(*args, original, 1, 60, CONFIG, mission)
        np.testing.assert_array_equal(actual["response_s"], expected["response_s"])

    def test_one_site_removed(self):
        for case in resilience.case_grid(self.protocol):
            original = base_grid(case["nominal_spacing_km"], CONFIG["domain_km2"])
            before = original.copy()
            actual = resilience.geometry(case, CONFIG)
            if case["offline_base"] >= 0:
                expected = np.delete(original, case["offline_base"], axis=0)
                self.assertEqual(len(actual), case["n_bases"] - 1)
                np.testing.assert_array_equal(actual, expected)
            np.testing.assert_array_equal(original, before)

    def test_training_selection_and_ties(self):
        cases = [dict(n_bases=9, wind_east_mps=8.0, offline_base=i,
                      case_id=f"c{i}") for i in range(3)]
        selected = resilience.select_sites(cases, np.array([[8], [3], [3]]))
        self.assertEqual(selected[0]["offline_base"], 1)
        self.assertEqual(selected[0]["training_timely"], 3)

    def test_pooled_interval(self):
        estimate, low, high = resilience.percent_interval([1, 9], [1, 99], self.draws)
        self.assertAlmostEqual(estimate, 10.0)
        self.assertAlmostEqual(low, 9.1590909091)
        self.assertAlmostEqual(high, 93.25)

    def test_paired_loss(self):
        estimate, low, high = resilience.percent_interval([-1, -9], [1, 99], self.draws)
        self.assertAlmostEqual(estimate, -10.0)
        self.assertAlmostEqual(low, -93.25)
        self.assertAlmostEqual(high, -9.1590909091)

    def test_loss_difference(self):
        delta = np.array([0, 0]) - [1, 9] - np.array([0, 0]) + [0, 5]
        estimate, _, _ = resilience.percent_interval(delta, [1, 99], self.draws)
        self.assertAlmostEqual(estimate, -5.0)

    def test_undefined_and_output_refusal(self):
        self.assertEqual(resilience.percent_interval([0, 0], [0, 0], self.draws),
                         (None, None, None))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "occupied"
            output.mkdir()
            sentinel = output / "sentinel"
            sentinel.write_bytes(b"unchanged")
            try:
                resilience.run_resilience(output, Path(directory) / "missing-protocol.json")
            except OSError as error:
                self.assertIsInstance(error, FileExistsError)
            else:
                self.fail("Existing output was not refused")
            self.assertEqual(sentinel.read_bytes(), b"unchanged")
            self.assertEqual({path.name for path in output.iterdir()}, {"sentinel"})

    def test_small_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = dict(self.protocol, training_seasons=2, heldout_seasons=2,
                            ignitions_per_season=3.0)
            source = root / "protocol.json"
            source.write_text(json.dumps(protocol))
            output = root / "capture"
            resilience.run_resilience(output, source)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["training_cases"], 72)
            self.assertEqual(manifest["heldout_cases"], 8)
            self.assertEqual(manifest["contrasts"], 6)
            for name, digest in manifest["artifact_sha256"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            with np.load(output / "heldout_responses.npz", allow_pickle=False) as data:
                self.assertEqual(len(data["case_ids"]), 8)
                self.assertEqual(data["responses_s"].shape[0], 8)
            selection = (output / "selection.csv").read_bytes()
            self.assertEqual(hashlib.sha256(selection).hexdigest(),
                             manifest["selection_sha256"])


if __name__ == "__main__":
    unittest.main()
